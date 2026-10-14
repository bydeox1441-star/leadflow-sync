"""Build workflow/leadflow-sync.json, the n8n workflow, from readable pieces.

The JavaScript for each Code node lives in workflow/code/*.js so it can be
read and diffed normally; this script assembles nodes, connections, retry
settings and layout into the JSON that n8n imports.

Usage: python workflow/build_workflow.py
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE / "code"
WORKFLOW_ID = "LeadFlowSync0001"
HUBSPOT_CRED = {"httpHeaderAuth": {"id": "leadflowHubspot", "name": "HubSpot private app (LeadFlow)"}}
ANTHROPIC_CRED = {"httpHeaderAuth": {"id": "leadflowAnthropic", "name": "Anthropic API (LeadFlow)"}}

nodes: list[dict] = []
connections: dict[str, dict] = {}


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"leadflow/{name}"))


def add(name: str, type_: str, version: float, x: int, y: int, parameters: dict, **extra) -> str:
    nodes.append({"id": _id(name), "name": name, "type": type_, "typeVersion": version,
                  "position": [x, y], "parameters": parameters, **extra})
    return name


def code(name: str, file: str, x: int, y: int) -> str:
    js = (CODE / file).read_text()
    return add(name, "n8n-nodes-base.code", 2, x, y,
               {"mode": "runOnceForEachItem", "language": "javaScript", "jsCode": js})


def http(name: str, x: int, y: int, method: str, url: str, body: str | None = None, *, credentials=None,
         headers: list[tuple[str, str]] | None = None, tries: int = 3, wait_ms: int = 1000,
         on_error: str = "continueErrorOutput") -> str:
    params: dict = {"method": method, "url": url, "options": {"timeout": 15000}}
    if credentials:
        params.update({"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"})
    if headers:
        params.update({"sendHeaders": True,
                       "headerParameters": {"parameters": [{"name": k, "value": v} for k, v in headers]}})
    if body is not None:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    extra = {"retryOnFail": tries > 1, "maxTries": tries, "waitBetweenTries": wait_ms, "onError": on_error}
    if credentials:
        extra["credentials"] = credentials
    return add(name, "n8n-nodes-base.httpRequest", 4.2, x, y, params, **extra)


def condition(name: str, x: int, y: int, left: str, op_type: str, operation: str, right=None) -> str:
    cond = {"id": _id(name + "/cond"), "leftValue": left, "operator": {"type": op_type, "operation": operation}}
    if right is None:
        cond["operator"]["singleValue"] = True
        cond["rightValue"] = ""
    else:
        cond["rightValue"] = right
    return add(name, "n8n-nodes-base.if", 2.2, x, y, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                       "conditions": [cond], "combinator": "and"},
        "options": {},
    })


def link(src: str, dst: str, output: int = 0) -> None:
    outputs = connections.setdefault(src, {"main": []})["main"]
    while len(outputs) <= output:
        outputs.append([])
    outputs[output].append({"node": dst, "type": "main", "index": 0})


def note(name: str, x: int, y: int, w: int, h: int, text: str, color: int = 7) -> None:
    add(name, "n8n-nodes-base.stickyNote", 1, x, y, {"content": text, "width": w, "height": h, "color": color})


def build() -> dict:
    # ---- intake: validate, then look the email up in the CRM ------------------
    webhook = add("Lead form webhook", "n8n-nodes-base.webhook", 2, 0, 300,
                  {"httpMethod": "POST", "path": "leadflow", "responseMode": "onReceived", "options": {}},
                  webhookId=_id("webhook"))
    validate = code("Validate input", "validate.js", 220, 300)
    accepted = condition("Accepted?", 440, 300, "={{ $json.decision }}", "string", "equals", "accept")
    search = http("Find contact in CRM", 660, 280, "POST", "={{ $env.CRM_BASE_URL }}/crm/v3/objects/contacts/search",
                  "={{ JSON.stringify({ filterGroups: [{ filters: [{ propertyName: 'email', operator: 'EQ', value: $json.email }] }], "
                  "properties: ['email', 'leadflow_last_sync'], limit: 1 }) }}",
                  credentials=HUBSPOT_CRED)
    recent = code("Check recent sync", "recent_sync.js", 880, 280)
    is_dup = condition("Recently synced?", 1100, 280, "={{ $json.recently_synced }}", "boolean", "true")
    log_skip = http("Log skipped lead", 1320, 600, "POST", "={{ $env.LOG_URL }}",
                    "={{ JSON.stringify($json.log_row) }}", on_error="continueRegularOutput")

    # ---- classification ---------------------------------------------------
    ai_on = condition("AI step enabled?", 1320, 300, "={{ $env.LEADFLOW_AI }}", "string", "equals", "on")
    ai_req = code("Build AI request", "ai_request.js", 1540, 140)
    claude = http("Classify with Claude", 1760, 140, "POST", "https://api.anthropic.com/v1/messages",
                  "={{ JSON.stringify($json.ai_request) }}", credentials=ANTHROPIC_CRED,
                  headers=[("anthropic-version", "2023-06-01"), ("anthropic-beta", "server-side-fallback-2026-07-01")],
                  tries=2, wait_ms=2000)
    ai_check = code("Check AI answer", "ai_check.js", 1980, 140)
    ai_ok = condition("AI answer valid?", 2200, 140, "={{ $json.ai_ok }}", "boolean", "true")
    rules = code("Classify with rules", "rules.js", 1980, 420)

    # ---- CRM write ----------------------------------------------------------
    prepare = code("Prepare CRM record", "prepare.js", 2420, 300)
    exists = condition("Contact exists?", 2640, 300, "={{ $json.existing_id }}", "string", "notEmpty")
    update = http("Update contact", 2860, 200, "PATCH", "={{ $env.CRM_BASE_URL }}/crm/v3/objects/contacts/{{ $json.existing_id }}",
                  "={{ JSON.stringify({ properties: $json.update_properties }) }}", credentials=HUBSPOT_CRED)
    create = http("Create contact", 2860, 400, "POST", "={{ $env.CRM_BASE_URL }}/crm/v3/objects/contacts",
                  "={{ JSON.stringify({ properties: $json.create_properties }) }}", credentials=HUBSPOT_CRED)

    # ---- notify + log -------------------------------------------------------
    notify_build = code("Build notification", "notification.js", 3080, 300)
    slack = http("Notify sales on Slack", 3300, 300, "POST", "={{ $env.SLACK_LEADS_WEBHOOK_URL }}",
                 "={{ JSON.stringify({ text: $json.slack_text }) }}")
    log_ok = http("Log success", 3520, 300, "POST", "={{ $env.LOG_URL }}",
                  "={{ JSON.stringify($('Build notification').item.json.log_row) }}", on_error="continueRegularOutput")

    # ---- failure path -------------------------------------------------------
    describe = code("Describe failure", "failure.js", 3300, 660)
    log_fail = http("Log failure", 3520, 660, "POST", "={{ $env.LOG_URL }}",
                    "={{ JSON.stringify($json.log_row) }}", on_error="continueRegularOutput")
    alert = http("Alert team on Slack", 3740, 660, "POST", "={{ $env.SLACK_ALERTS_WEBHOOK_URL }}",
                 "={{ JSON.stringify({ text: $('Describe failure').item.json.alert_text }) }}",
                 on_error="continueRegularOutput")

    for a, b in [(webhook, validate), (validate, accepted), (search, recent), (recent, is_dup),
                 (ai_req, claude), (claude, ai_check), (ai_check, ai_ok), (rules, prepare), (prepare, exists),
                 (update, notify_build), (create, notify_build), (notify_build, slack), (slack, log_ok),
                 (describe, log_fail), (log_fail, alert)]:
        link(a, b)
    link(accepted, search, 0)
    link(accepted, log_skip, 1)     # rejected input
    link(is_dup, log_skip, 0)       # re-sent within 10 minutes
    link(is_dup, ai_on, 1)
    link(ai_on, ai_req, 0)
    link(ai_on, rules, 1)
    link(claude, rules, 1)          # API error after retries -> rules
    link(ai_ok, prepare, 0)
    link(ai_ok, rules, 1)           # malformed answer -> rules
    link(exists, update, 0)
    link(exists, create, 1)
    for failing in (search, update, create, slack):
        link(failing, describe, 1)  # error output after retries

    note("About", -40, -80, 640, 280,
         "## LeadFlow Sync (demo)\nForm lead → validate → CRM lookup & de-dupe → classify (Claude or rules) → "
         "HubSpot create/update → Slack → run log.\n\nEvery HTTP step retries (3 tries, 1 s apart). "
         "Failures that survive the retries are logged and alerted in #leadflow-alerts.\n\n"
         "URLs and flags come from environment variables, tokens from n8n credentials: "
         "nothing secret is stored in this workflow.", 5)
    note("Failure path", 3260, 560, 680, 260,
         "### Failure path\nCRM or Slack errors that survive the retries end up here: the lead is logged "
         "with the failing step and an alert is posted.", 3)

    return {
        "id": WORKFLOW_ID,
        "name": "LeadFlow Sync",
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "all", "saveDataErrorExecution": "all"},
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": True},
        "tags": [],
    }


if __name__ == "__main__":
    out = HERE / "leadflow-sync.json"
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"Wrote {out} ({len(nodes)} nodes)")
