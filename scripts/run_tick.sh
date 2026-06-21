#!/bin/bash
# Ballast — one scheduled live tick. Invoked hourly by launchd.
# Sets up the environment the agent needs (twak on PATH, .env secrets, keychain)
# and runs a single competition tick, appending to the log.
set -euo pipefail

PROJECT="/Users/mac/Vibecoding/Ballast"
cd "$PROJECT"

export PATH="$HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TWAK_NONINTERACTIVE=1 NO_PROMPT=1

# Load .env (secrets stay out of the plist). Rename TW_* aliases handled in .env.
set -a; source "$PROJECT/.env"; set +a

echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) tick ====="
"$PROJECT/.venv/bin/python" -m scripts.compete --live
