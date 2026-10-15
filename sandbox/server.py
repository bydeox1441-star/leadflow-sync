"""LeadFlow sandbox: local stand-ins for HubSpot, Slack and the run log.

Lets the n8n workflow run end to end without third-party accounts. The
endpoints follow the real contracts closely enough that switching to the real
services is a matter of changing base URLs and credentials:

  HubSpot CRM v3 (subset)
    POST  /crm/v3/objects/contacts/search   filterGroups -> email EQ
    POST  /crm/v3/objects/contacts          201, or 409 CONFLICT if the email exists
    PATCH /crm/v3/objects/contacts/{id}     200, or 404
    Requires "Authorization: Bearer <token>"; unknown properties -> 400 like HubSpot.
  Slack incoming webhooks
    POST  /slack/leads   and   POST /slack/alerts   -> "ok" (400 "no_text" without text)
  Run log (same contract as the Google Apps Script endpoint in sheets/)
    POST  /log/rows  -> {"ok": true, "row": n}

Control endpoints (demo only): GET /  (live dashboard), GET /_state,
POST /_reset, POST /_seed, POST /_faults.

Usage: python sandbox/server.py [--port 8787]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ.get("SANDBOX_HUBSPOT_TOKEN", "sandbox-token")
DASHBOARD = Path(__file__).with_name("dashboard.html")

CONTACT_PROPERTIES = {
    "email", "firstname", "lastname", "company", "phone", "website", "message", "lifecyclestage",
    "leadflow_type", "leadflow_urgency", "leadflow_summary", "leadflow_source", "leadflow_classifier",
    "leadflow_last_sync",
}
LOG_COLUMNS = ["timestamp", "execution_id", "email", "name", "company", "status", "lead_type", "urgency",
               "classifier", "crm_id", "failed_step", "error", "summary"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.contacts: dict[str, dict] = {}
        self.next_id = 1001
        self.slack: list[dict] = []
        self.alerts: list[dict] = []
        self.log: list[dict] = []
        self.calls: list[dict] = []
        # target -> {"mode": "fail"|"down"|"ratelimit", "count": int, "status": int}
        self.faults: dict[str, dict] = {}

    def take_fault(self, target: str) -> dict | None:
        fault = self.faults.get(target)
        if not fault:
            return None
        if fault["mode"] == "down":
            return fault
        fault["count"] -= 1
        if fault["count"] <= 0:
            del self.faults[target]
        return fault

    def snapshot(self) -> dict:
        return {
            "contacts": sorted(self.contacts.values(), key=lambda c: int(c["id"])),
            "slack": self.slack, "alerts": self.alerts, "log": self.log,
            "calls": self.calls[-80:], "faults": self.faults,
        }


STATE = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "LeadFlowSandbox/1.0"

    # ------------------------------------------------------------ helpers
    def log_message(self, fmt, *args):  # quieter console
        pass

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _send(self, status: int, payload, content_type: str = "application/json", headers: dict | None = None):
        data = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        data = data.encode() if isinstance(data, str) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _record(self, target: str, status: int, note: str = "") -> None:
        STATE.calls.append({"t": now(), "target": target, "method": self.command, "path": self.path,
                            "status": status, "note": note})

    def _fault_response(self, target: str) -> bool:
        """Apply an injected fault. Returns True if a failure response was sent."""
        fault = STATE.take_fault(target)
        if not fault:
            return False
        if fault["mode"] == "ratelimit":
            self._record(target, 429, "injected rate limit")
            self._send(429, {"status": "error", "category": "RATE_LIMITS", "message": "You have reached your secondly limit."},
                       headers={"Retry-After": "1"})
        else:
            status = fault.get("status", 503)
            self._record(target, status, "injected fault")
            self._send(status, {"status": "error", "message": "Service unavailable (sandbox fault injection)"})
        return True

    def _hubspot_auth_ok(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._record("crm", 401, "bad token")
        self._send(401, {"status": "error", "category": "INVALID_AUTHENTICATION",
                         "message": "Authentication credentials not found."})
        return False

    @staticmethod
    def _contact_by_email(email: str) -> dict | None:
        return next((c for c in STATE.contacts.values() if c["properties"].get("email") == email.lower()), None)

    def _bad_properties(self, props: dict) -> bool:
        unknown = sorted(set(props) - CONTACT_PROPERTIES)
        if unknown:
            self._record("crm", 400, f"unknown property {unknown[0]}")
            self._send(400, {"status": "error", "category": "VALIDATION_ERROR",
                             "message": f"Property values were not valid: PROPERTY_DOESNT_EXIST {unknown}"})
            return True
        return False

    # -------------------------------------------------------------- routes
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):  # the dashboard accepts ?mask=1
            return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/_state":
            with STATE.lock:
                return self._send(200, STATE.snapshot())
        if self.path == "/log/rows":
            with STATE.lock:
                return self._send(200, {"columns": LOG_COLUMNS, "rows": STATE.log})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()
        if body is None:
            return self._send(400, {"status": "error", "message": "Invalid JSON body"})
        with STATE.lock:
            path = self.path.split("?")[0]
            if path == "/crm/v3/objects/contacts/search":
                return self._crm_search(body)
            if path == "/crm/v3/objects/contacts":
                return self._crm_create(body)
            if path in ("/slack/leads", "/slack/alerts"):
                return self._slack(path.rsplit("/", 1)[1], body)
            if path == "/log/rows":
                return self._log(body)
            if path == "/_reset":
                STATE.reset()
                return self._send(200, {"ok": True})
            if path == "/_seed":
                for c in body.get("contacts", []):
                    self._store_contact(c, created=c.get("createdAt"))
                return self._send(200, {"ok": True, "contacts": len(STATE.contacts)})
            if path == "/_faults":
                target = body.get("target")
                if body.get("mode") == "clear":
                    STATE.faults.pop(target, None) if target else STATE.faults.clear()
                else:
                    STATE.faults[target] = {"mode": body.get("mode", "fail"), "count": int(body.get("count", 1)),
                                            "status": int(body.get("status", 503))}
                return self._send(200, {"ok": True, "faults": STATE.faults})
        self._send(404, {"error": "not found"})

    def do_PATCH(self):
        body = self._body()
        if body is None:
            return self._send(400, {"status": "error", "message": "Invalid JSON body"})
        with STATE.lock:
            m = re.fullmatch(r"/crm/v3/objects/contacts/(\d+)", self.path.split("?")[0])
            if not m:
                return self._send(404, {"error": "not found"})
            if not self._hubspot_auth_ok() or self._fault_response("crm"):
                return
            contact = STATE.contacts.get(m.group(1))
            if not contact:
                self._record("crm", 404, "contact not found")
                return self._send(404, {"status": "error", "category": "OBJECT_NOT_FOUND",
                                        "message": f"resource not found: {m.group(1)}"})
            props = body.get("properties", {})
            if self._bad_properties(props):
                return
            contact["properties"].update({k: v for k, v in props.items() if k != "email"})
            contact["updatedAt"] = contact["properties"]["lastmodifieddate"] = now()
            self._record("crm", 200, f"updated {contact['id']}")
            self._send(200, contact)

    # ------------------------------------------------------------ handlers
    def _store_contact(self, props: dict, created: str | None = None) -> dict:
        cid = str(STATE.next_id)
        STATE.next_id += 1
        ts = created or now()
        properties = {k: v for k, v in props.items() if k in CONTACT_PROPERTIES}
        properties["email"] = properties.get("email", "").lower()
        properties.update({"hs_object_id": cid, "createdate": ts, "lastmodifieddate": ts})
        contact = {"id": cid, "properties": properties, "createdAt": ts, "updatedAt": ts, "archived": False}
        STATE.contacts[cid] = contact
        return contact

    def _crm_search(self, body: dict):
        if not self._hubspot_auth_ok() or self._fault_response("crm"):
            return
        try:
            f = body["filterGroups"][0]["filters"][0]
            assert f["propertyName"] == "email" and f["operator"] == "EQ"
        except (KeyError, IndexError, AssertionError):
            self._record("crm", 400, "unsupported search")
            return self._send(400, {"status": "error", "category": "VALIDATION_ERROR",
                                    "message": "Sandbox supports email EQ searches only"})
        found = self._contact_by_email(str(f["value"]))
        self._record("crm", 200, "found" if found else "no match")
        self._send(200, {"total": 1 if found else 0, "results": [found] if found else []})

    def _crm_create(self, body: dict):
        if not self._hubspot_auth_ok() or self._fault_response("crm"):
            return
        props = body.get("properties", {})
        if self._bad_properties(props):
            return
        existing = self._contact_by_email(props.get("email", ""))
        if existing:
            self._record("crm", 409, "conflict")
            return self._send(409, {"status": "error", "category": "CONFLICT",
                                    "message": f"Contact already exists. Existing ID: {existing['id']}"})
        contact = self._store_contact(props)
        self._record("crm", 201, f"created {contact['id']}")
        self._send(201, contact)

    def _slack(self, channel: str, body: dict):
        target = "slack" if channel == "leads" else "alerts"
        if self._fault_response(target):
            return
        if not body.get("text"):
            self._record(target, 400, "no_text")
            return self._send(400, "no_text", "text/plain")
        (STATE.slack if channel == "leads" else STATE.alerts).append({"t": now(), **body})
        self._record(target, 200)
        self._send(200, "ok", "text/plain")

    def _log(self, body: dict):
        if self._fault_response("log"):
            return
        row = {c: body.get(c, "") for c in LOG_COLUMNS}
        row["timestamp"] = row["timestamp"] or now()
        STATE.log.append(row)
        self._record("log", 200, row.get("status", ""))
        self._send(200, {"ok": True, "row": len(STATE.log)})


def main() -> None:
    ap = argparse.ArgumentParser(description="LeadFlow sandbox services")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SANDBOX_PORT", 8787)))
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"LeadFlow sandbox on http://127.0.0.1:{args.port}  (dashboard at /)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
