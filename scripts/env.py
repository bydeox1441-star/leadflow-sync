"""Shared helpers: read .env and build the environment for n8n commands."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
N8N_BIN = RUNTIME / "node_modules" / ".bin" / "n8n"
# Secrets live in n8n's encrypted credential store, never in the n8n process environment.
SECRET_KEYS = {"HUBSPOT_TOKEN", "ANTHROPIC_API_KEY"}


def read_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def n8n_env(config: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_KEYS}
    env.update({k: v for k, v in config.items() if k not in SECRET_KEYS})
    env.update({
        "N8N_USER_FOLDER": str(RUNTIME / "data"),
        "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",  # workflow reads URLs and flags via $env
        "N8N_DIAGNOSTICS_ENABLED": "false",
        "N8N_PERSONALIZATION_ENABLED": "false",
        "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
        "N8N_SECURE_COOKIE": "false",
        "N8N_LISTEN_ADDRESS": "127.0.0.1",
        "GENERIC_TIMEZONE": "UTC",
    })
    return env
