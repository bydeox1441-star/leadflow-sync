"""Contract tests for the sandbox (HubSpot / Slack / log stand-ins).

Run: python -m unittest discover tests
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
import server  # noqa: E402

AUTH = {"Authorization": f"Bearer {server.TOKEN}"}


class SandboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        server.STATE.reset()

    def req(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(r) as resp:
                raw = resp.read().decode()
                return resp.status, json.loads(raw) if raw.startswith("{") else raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, json.loads(raw) if raw.startswith("{") else raw

    def search(self, email):
        return self.req("POST", "/crm/v3/objects/contacts/search",
                        {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}]}, AUTH)

    def test_create_search_update(self):
        status, created = self.req("POST", "/crm/v3/objects/contacts",
                                   {"properties": {"email": "A@B.example", "firstname": "Ann"}}, AUTH)
        self.assertEqual(status, 201)
        self.assertEqual(created["properties"]["email"], "a@b.example")
        status, found = self.search("a@b.example")
        self.assertEqual((status, found["total"], found["results"][0]["id"]), (200, 1, created["id"]))
        status, updated = self.req("PATCH", f"/crm/v3/objects/contacts/{created['id']}",
                                   {"properties": {"leadflow_type": "pricing"}}, AUTH)
        self.assertEqual((status, updated["properties"]["leadflow_type"]), (200, "pricing"))

    def test_hubspot_errors(self):
        self.assertEqual(self.search("x@y.example")[0], 200)
        self.assertEqual(self.req("POST", "/crm/v3/objects/contacts", {"properties": {"email": "a@b.example"}})[0], 401)
        self.req("POST", "/crm/v3/objects/contacts", {"properties": {"email": "a@b.example"}}, AUTH)
        status, body = self.req("POST", "/crm/v3/objects/contacts", {"properties": {"email": "a@b.example"}}, AUTH)
        self.assertEqual((status, body["category"]), (409, "CONFLICT"))
        status, body = self.req("POST", "/crm/v3/objects/contacts", {"properties": {"email": "c@d.example", "nope": 1}}, AUTH)
        self.assertEqual(status, 400)
        self.assertIn("PROPERTY_DOESNT_EXIST", body["message"])
        self.assertEqual(self.req("PATCH", "/crm/v3/objects/contacts/9999", {"properties": {}}, AUTH)[0], 404)

    def test_fault_injection_counts_down(self):
        self.req("POST", "/_faults", {"target": "crm", "mode": "fail", "count": 2, "status": 503})
        self.assertEqual(self.search("a@b.example")[0], 503)
        self.assertEqual(self.search("a@b.example")[0], 503)
        self.assertEqual(self.search("a@b.example")[0], 200)
        self.req("POST", "/_faults", {"target": "crm", "mode": "ratelimit", "count": 1})
        self.assertEqual(self.search("a@b.example")[0], 429)

    def test_slack_and_log(self):
        self.assertEqual(self.req("POST", "/slack/leads", {"text": "hello"}), (200, "ok"))
        self.assertEqual(self.req("POST", "/slack/alerts", {}), (400, "no_text"))
        status, body = self.req("POST", "/log/rows", {"email": "a@b.example", "status": "created", "extra": "x"})
        self.assertEqual((status, body["row"]), (200, 1))
        rows = self.req("GET", "/log/rows")[1]["rows"]
        self.assertEqual(rows[0]["status"], "created")
        self.assertNotIn("extra", rows[0])
        self.assertTrue(rows[0]["timestamp"])


if __name__ == "__main__":
    unittest.main()
