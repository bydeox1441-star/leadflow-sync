"""Start the local n8n with the LeadFlow configuration (secrets excluded from its environment).

Usage: python scripts/start_n8n.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import N8N_BIN, ROOT, n8n_env, read_env  # noqa: E402

if __name__ == "__main__":
    env = n8n_env(read_env(ROOT / ".env"))
    os.execve(str(N8N_BIN), [str(N8N_BIN), "start"], env)
