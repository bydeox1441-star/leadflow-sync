"""Create .env if needed, then import credentials and the workflow into the local n8n and publish it.

Run once, and again after changing credentials or the workflow (n8n must be stopped).
Usage: python scripts/setup.py
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import N8N_BIN, ROOT, RUNTIME, n8n_env, read_env  # noqa: E402

WORKFLOW_ID = "LeadFlowSync0001"


def ensure_env() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        text = (ROOT / ".env.example").read_text()
        text = text.replace("N8N_ENCRYPTION_KEY=\n", f"N8N_ENCRYPTION_KEY={secrets.token_hex(24)}\n")
        env_file.write_text(text)
        env_file.chmod(0o600)
        print("Created .env from .env.example")
    return read_env(env_file)


def n8n(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run([str(N8N_BIN), *args], env=env, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip().splitlines()
    print(f"$ n8n {' '.join(args)}\n  " + "\n  ".join(output[-3:]))
    if result.returncode != 0:
        sys.exit(f"n8n {args[0]} failed")


def main() -> None:
    if not N8N_BIN.exists():
        sys.exit("n8n is not installed: cd runtime && npm install")
    config = ensure_env()
    env = n8n_env(config)

    credentials = [
        {"id": "leadflowHubspot", "name": "HubSpot private app (LeadFlow)", "type": "httpHeaderAuth",
         "data": {"name": "Authorization", "value": f"Bearer {config.get('HUBSPOT_TOKEN', '')}"}},
        {"id": "leadflowAnthropic", "name": "Anthropic API (LeadFlow)", "type": "httpHeaderAuth",
         "data": {"name": "x-api-key", "value": config.get("ANTHROPIC_API_KEY") or "not-configured"}},
    ]
    tmp = RUNTIME / "credentials.import.json"
    tmp.write_text(json.dumps(credentials))
    tmp.chmod(0o600)
    try:
        n8n(["import:credentials", f"--input={tmp}"], env)
    finally:
        tmp.unlink()  # n8n now holds them encrypted with N8N_ENCRYPTION_KEY

    subprocess.run([sys.executable, str(ROOT / "workflow" / "build_workflow.py")], check=True)
    n8n(["import:workflow", f"--input={ROOT / 'workflow' / 'leadflow-sync.json'}"], env)
    n8n(["publish:workflow", f"--id={WORKFLOW_ID}"], env)
    print("Done. Start n8n with: python scripts/start_n8n.py")


if __name__ == "__main__":
    main()
