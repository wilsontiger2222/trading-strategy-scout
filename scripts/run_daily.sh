#!/usr/bin/env bash
set -euo pipefail
cd /home/openclaw/.openclaw/workspace/trading-strategy-scout
if [ -x .venv/bin/python ]; then
  .venv/bin/python orchestrator.py
else
  python3 orchestrator.py
fi
