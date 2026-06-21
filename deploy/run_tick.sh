#!/usr/bin/env bash
# Ballast — one live tick on a Linux host (invoked hourly by the systemd timer).
# Mirrors scripts/run_tick.sh but for a root-user Ubuntu droplet.
set -euo pipefail

cd /root/ballast
export PATH="/root/.npm-global/bin:/root/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TWAK_NONINTERACTIVE=1 NO_PROMPT=1

set -a; source /root/ballast/.env; set +a

echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) tick ====="
/root/ballast/.venv/bin/python -m scripts.compete --live
