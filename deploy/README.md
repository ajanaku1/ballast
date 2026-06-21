# Deploy Ballast to an always-on host (DigitalOcean)

Run the agent 24/7 on a cheap Ubuntu droplet so it keeps trading when your laptop
is off. Free for the competition week on DigitalOcean's new-user credit.

> IMPORTANT: only ONE machine should run the agent at a time. Before (or right
> after) deploying here, stop the Mac job so two agents don't trade the same
> wallet at once:
> `launchctl unload ~/Library/LaunchAgents/com.ballast.agent.plist`

## 1. Create the droplet (in the browser, ~3 min)

1. Sign up at https://www.digitalocean.com (new accounts get $200 / 60-day credit).
2. **Create → Droplets.**
3. **Region:** Frankfurt or Amsterdam (better odds of Binance access; CoinGecko
   fallback works anywhere regardless).
4. **Image:** Ubuntu 24.04 (or 22.04) LTS.
5. **Size:** Basic → Regular → the **$6/mo** option (1 vCPU / 1 GB) is plenty.
6. **Authentication:** SSH key (recommended) or password.
7. Create. Note the droplet's **IP address**.

## 2. Send your two secret files to the box (from your Mac terminal)

These never go through git or chat. Replace `DROPLET_IP`:

```bash
scp ~/Vibecoding/Ballast/.env        root@DROPLET_IP:/root/ballast-env
scp ~/.twak/wallet.json              root@DROPLET_IP:/root/twak-wallet.json
```

This puts the **same wallet** `0x05e690…bd94` on the server, so it's already
registered — no re-registration needed.

## 3. Install + start (on the droplet)

SSH in and run the installer:

```bash
ssh root@DROPLET_IP

git clone https://github.com/ajanaku1/ballast.git
cd ballast
bash deploy/setup.sh
```

The script installs Python + Node + twak, wires the secrets into place, verifies
the wallet is registered, installs a **systemd timer**, and runs one tick.

## 4. Verify + operate

```bash
systemctl list-timers ballast.timer        # next scheduled tick
journalctl -u ballast.service -f           # live logs
tail -f /root/ballast/ballast-agent.log    # same, file form

systemctl disable --now ballast.timer      # STOP the agent
systemctl enable  --now ballast.timer      # restart it
```

## Notes

- **Don't run two agents.** Stop the Mac launchd job (above) once this is live.
- **Updates:** `cd /root/ballast && git pull` — the next tick uses the new code
  (each tick is a fresh process).
- **Security:** the wallet key lives on the droplet (`/root/ballast/.env`,
  chmod 600). It's a tiny gasless wallet protected by the breaker + spend caps;
  still, treat the droplet as sensitive and destroy it after the competition.
- **Cost:** destroy the droplet when done (`Destroy` in the DO panel) so it stops
  billing after the free credit.
