#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Trading Strategy Scout — Setup ==="

# Create runtime directories
for dir in data data/daily_scans reports logs; do
    mkdir -p "$dir"
    echo "  Created $dir/"
done

# Install Python dependencies
if command -v pip3 &>/dev/null; then
    pip3 install -r requirements.txt
elif command -v pip &>/dev/null; then
    pip install -r requirements.txt
else
    echo "ERROR: pip not found. Install Python 3.10+ first."
    exit 1
fi

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env from .env.example — edit it with your tokens."
else
    echo "  .env already exists, skipping."
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit .env with your GITHUB_TOKEN, BOT_TOKEN, and CHAT_ID"
echo "  2. Run: python orchestrator.py"
