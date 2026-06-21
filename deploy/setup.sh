#!/usr/bin/env bash
# Ballast — one-shot installer for an Ubuntu 22.04 DigitalOcean droplet (run as root).
#
# Prereq: from your Mac you've already copied two secret files to /root on the box:
#   scp .env                root@DROPLET_IP:/root/ballast-env
#   scp ~/.twak/wallet.json root@DROPLET_IP:/root/twak-wallet.json
#
# Then on the droplet:
#   git clone https://github.com/ajanaku1/ballast.git
#   cd ballast && bash deploy/setup.sh
#
# Idempotent: safe to re-run.
set -euo pipefail

echo "==> system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git curl ca-certificates python3 python3-venv python3-pip

echo "==> Node.js (for twak)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

echo "==> uv (python package manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="/root/.local/bin:$PATH"

echo "==> python env + deps"
cd /root/ballast
uv venv --python 3.11 .venv
uv pip install -e .

echo "==> Trust Wallet Agent Kit (twak)"
if [ ! -x /root/.npm-global/bin/twak ]; then
  curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
fi
export PATH="/root/.npm-global/bin:$PATH"

echo "==> install secrets (must already be on the box)"
[ -f /root/ballast-env ] || { echo "MISSING /root/ballast-env (scp your .env there)"; exit 1; }
[ -f /root/twak-wallet.json ] || { echo "MISSING /root/twak-wallet.json (scp ~/.twak/wallet.json there)"; exit 1; }
install -m 600 /root/ballast-env /root/ballast/.env
mkdir -p /root/.twak
install -m 600 /root/twak-wallet.json /root/.twak/wallet.json

echo "==> sanity: wallet + registration status"
chmod +x deploy/run_tick.sh
set -a; source /root/ballast/.env; set +a
TWAK_NONINTERACTIVE=1 NO_PROMPT=1 /root/.npm-global/bin/twak compete status --json | grep -E "registered|participant" || true

echo "==> systemd timer (hourly tick)"
cp deploy/ballast.service /etc/systemd/system/ballast.service
cp deploy/ballast.timer   /etc/systemd/system/ballast.timer
systemctl daemon-reload
systemctl enable --now ballast.timer

echo "==> run one tick now to verify"
systemctl start ballast.service || true
sleep 5
tail -n 8 /root/ballast/ballast-agent.log 2>/dev/null || true

echo ""
echo "DONE. The agent now ticks hourly via systemd."
echo "  watch:   journalctl -u ballast.service -f   (or: tail -f /root/ballast/ballast-agent.log)"
echo "  status:  systemctl list-timers ballast.timer"
echo "  stop:    systemctl disable --now ballast.timer"
