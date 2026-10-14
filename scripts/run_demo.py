"""Send the 30 synthetic leads through the running workflow and verify every outcome.

Needs the sandbox (sandbox/server.py) and n8n (scripts/start_n8n.py) running.
Faults are injected through the sandbox before the leads that expect them:
  lead 21  CRM down for 3 calls      -> retried 3 times, logged as failed, alert
  lead 22  CRM fails once            -> retried, succeeds
  lead 25  Slack down for 3 calls    -> contact saved, logged as notify_failed, alert

Usage: python scripts/run_demo.py [--delay 0.5]
Writes output/run_report.md; exits with status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call(method: str, url: str, payload=None, headers: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode()
        return json.loads(body) if body.startswith(("{", "[")) else body


def wait_for_rows(sandbox: str, count: int, timeout: float = 45) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = call("GET", f"{sandbox}/log/rows")["rows"]
        if len(rows) >= count:
            return rows
        time.sleep(0.25)
    raise TimeoutError(f"no log row for lead #{count} after {timeout:.0f}s; is n8n running and the workflow published?")


def wait_for_published_version(timeout: float = 120) -> None:
    """n8n applies CLI publications asynchronously (publication outbox) after it starts.
    Until then webhooks are still served by the previously published version, so wait."""
    db = ROOT / "runtime" / "data" / ".n8n" / "database.sqlite"
    if not db.exists():
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            row = con.execute(
                "SELECT w.activeVersionId, p.publishedVersionId FROM workflow_entity w "
                "LEFT JOIN workflow_published_version p ON p.workflowId = w.id WHERE w.id = 'LeadFlowSync0001'"
            ).fetchone()
        if row and row[0] and row[0] == row[1]:
            return
        time.sleep(1)
    raise TimeoutError("n8n has not applied the latest published workflow version; is n8n running?")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook", default="http://127.0.0.1:5678/webhook/leadflow")
    ap.add_argument("--sandbox", default="http://127.0.0.1:8787")
    ap.add_argument("--delay", type=float, default=0.5, help="pause between leads (seconds), nice for recordings")
    args = ap.parse_args()

    data = json.loads((ROOT / "data" / "leads.json").read_text())
    leads = data["leads"]
    run_id = datetime.now().strftime("demo-%Y%m%d-%H%M%S")
    wait_for_published_version()
    call("POST", f"{args.sandbox}/_reset", {})
    call("POST", f"{args.sandbox}/_seed", {"contacts": data["seed_contacts"]})

    started = time.time()
    for n, lead in enumerate(leads, start=1):
        if scenario := lead.get("scenario"):
            call("POST", f"{args.sandbox}/_faults", scenario)
        call("POST", args.webhook, lead["form"])
        rows = wait_for_rows(args.sandbox, n)
        call("POST", f"{args.sandbox}/_faults", {"mode": "clear"})
        print(f"[{n:02d}/{len(leads)}] {lead['form']['name'] or '(no name)':<18} -> {rows[-1]['status']}")
        time.sleep(args.delay)
    elapsed = time.time() - started

    time.sleep(1.0)  # let the last alerts land
    state = call("GET", f"{args.sandbox}/_state")
    rows = state["log"]
    checks: list[tuple[str, bool, str]] = []
    per_lead = []
    for lead, row in zip(leads, rows):
        exp = lead["expected"]
        same_lead = row["email"] == lead["form"]["email"].strip().lower()
        ok_status = same_lead and row["status"] == exp["status"]
        ok_class = all(row.get(k) == exp[k] for k in ("lead_type", "urgency") if k in exp)
        per_lead.append((lead, row, ok_status, ok_class))
    checks.append(("every lead produced exactly one log row", len(rows) == len(leads), f"{len(rows)} rows"))
    checks.append(("final status matches the expected outcome",
                   all(p[2] for p in per_lead), f"{sum(p[2] for p in per_lead)}/{len(leads)}"))

    expected_alerts = [l for l in leads if l["expected"].get("alert")]
    alerted = [a for a in state["alerts"]
               if any(l["form"]["email"].lower() in a["text"] for l in expected_alerts)]
    checks.append(("an alert for every lead that failed after retries",
                   len(state["alerts"]) == len(expected_alerts) == len(alerted),
                   f"{len(state['alerts'])} alerts, {len(expected_alerts)} expected"))

    statuses = Counter(r["status"] for r in rows)
    in_crm = statuses["created"] + statuses["notify_failed"]
    checks.append(("CRM holds the 3 seeded contacts plus every new lead (no duplicates)",
                   len(state["contacts"]) == len(data["seed_contacts"]) + in_crm, f"{len(state['contacts'])} contacts"))
    retries = sum(1 for c in state["calls"] if c["status"] >= 500)
    recovered = next((r for l, r, *_ in per_lead if l["id"] == 22), {})
    checks.append(("transient CRM error recovered by retry (lead 22)", recovered.get("status") == "created",
                   recovered.get("status", "missing")))
    slack_ok = len(state["slack"]) == statuses["created"] + statuses["updated"]
    checks.append(("one Slack message per synced lead", slack_ok, f"{len(state['slack'])} messages"))

    classified = [p for p in per_lead if "lead_type" in p[0]["expected"]]
    class_ok = sum(p[3] for p in classified)
    classifiers = Counter(r.get("classifier", "") for r in rows if r.get("classifier"))

    lines = [
        "# LeadFlow Sync: demo run report",
        "",
        f"Run `{run_id}` · {len(leads)} synthetic leads · {elapsed:.1f} s · classifier: "
        + ", ".join(f"{k} ({v})" for k, v in classifiers.items()),
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
        *[f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |" for name, ok, detail in checks],
        "",
        "## Outcomes",
        "",
        "| Status | Leads |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(statuses.items())],
        "",
        f"Server errors absorbed by retries or reported: {retries} (injected faults).",
        f"Classification matching the expected type and urgency: {class_ok}/{len(classified)} "
        "(the keyword rules were written against this data set, so this is a consistency check, not a benchmark).",
        "",
        "## Per lead",
        "",
        "| # | Lead | Expected | Got | Type / urgency | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for lead, row, ok_status, ok_class in per_lead:
        exp = lead["expected"]
        tu = f"{row.get('lead_type') or '-'} / {row.get('urgency') or '-'}"
        detail = row.get("error") or row.get("summary") or ""
        lines.append(f"| {lead['id']} | {lead['form']['name'] or '-'} | {exp['status']} | "
                     f"{row['status']}{'' if ok_status else ' ✗'} | {tu}{'' if ok_class else ' ✗'} | {detail[:90]} |")
    report = "\n".join(lines) + "\n"
    out = ROOT / "output" / "run_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)
    print("\n" + "\n".join(f"{'PASS' if ok else 'FAIL'}  {name} ({detail})" for name, ok, detail in checks))
    print(f"\nReport: {out}")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
