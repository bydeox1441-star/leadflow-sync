"""Create the custom leadflow_* contact properties in a real HubSpot account (run once).

Needs a private app token with crm.schemas.contacts.write in HUBSPOT_TOKEN (.env).
Existing properties are left untouched (HubSpot answers 409).
Usage: python scripts/hubspot_properties.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import ROOT, read_env  # noqa: E402

PROPERTIES = [
    ("leadflow_type", "LeadFlow: lead type", "string", "text"),
    ("leadflow_urgency", "LeadFlow: urgency", "string", "text"),
    ("leadflow_summary", "LeadFlow: summary", "string", "textarea"),
    ("leadflow_source", "LeadFlow: form source", "string", "text"),
    ("leadflow_classifier", "LeadFlow: classifier", "string", "text"),
    ("leadflow_last_sync", "LeadFlow: last sync", "datetime", "date"),
]


def main() -> None:
    env = read_env(ROOT / ".env")
    base, token = env["CRM_BASE_URL"].rstrip("/"), env["HUBSPOT_TOKEN"]
    if "hubapi.com" not in base:
        sys.exit("CRM_BASE_URL does not point to HubSpot (https://api.hubapi.com); nothing to do for the sandbox.")
    for name, label, type_, field in PROPERTIES:
        body = json.dumps({"name": name, "label": label, "type": type_, "fieldType": field,
                           "groupName": "contactinformation"}).encode()
        req = urllib.request.Request(f"{base}/crm/v3/properties/contacts", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"created  {name} ({resp.status})")
        except urllib.error.HTTPError as e:
            print(f"{'exists ' if e.code == 409 else 'ERROR  '} {name} ({e.code})")


if __name__ == "__main__":
    main()
