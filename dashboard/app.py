"""Read-only Ballast dashboard (demo-only, never part of the trade loop).

Reads the agent's hash-chained decision journal and renders the latest tick in
the 'Keel' (nautical) direction. Two routes:

  /            the dashboard page (Keel direction, server-rendered)
  /api/state   the same data as JSON (so the page can poll/refresh)

It only ever reads files the agent writes; it holds no keys and places no trades.

Run:  python -m dashboard.app   (then open http://127.0.0.1:8088)
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, render_template, send_file

from ballast.config import Config
from ballast.journal import Journal

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))


def _journal_path() -> Path:
    return ROOT / "journal.jsonl"


@app.route("/logo.png")
def logo():
    return send_file(ROOT / "docs" / "images" / "logo.png")


@app.route("/favicon.png")
def favicon():
    return send_file(ROOT / "docs" / "images" / "favicon.png")


def load_view(preset: str = "conservative") -> dict:
    """Assemble the dashboard view-model from the latest journal entry."""
    cfg = Config.from_env()
    entries = _read_entries(_journal_path())
    chain_ok = Journal(_journal_path()).verify_chain()
    if not entries:
        return _empty_view(cfg, chain_ok)

    curve = [e["equity"] for e in entries if e.get("equity")]
    last = entries[-1]
    equity = last.get("equity", 0.0)
    start = curve[0] if curve else equity
    positions = _positions(last, equity)

    return {
        "agent": cfg_agent(),
        "preset": cfg.preset.value,
        "mode": cfg.mode.value,
        "regime": last.get("regime", "—"),
        "fear_greed": last.get("fear_greed", 0),
        "gross": last.get("gross_exposure", 0.0),
        "equity": equity,
        "start_equity": start,
        "total_return": (equity / start - 1.0) if start else 0.0,
        "open_drawdown": last.get("drawdown", 0.0),
        "max_drawdown": _max_dd(curve),
        "breaker": cfg.limits.breaker_drawdown,
        "positions": positions,
        "signals": _top(last.get("signals", {})),
        "curve": _spark(curve),
        "log": _log(entries[-6:]),
        "chain_ok": chain_ok,
        "n_ticks": len(entries),
    }


def cfg_agent() -> str:
    import os

    addr = os.getenv("BALLAST_AGENT_ADDRESS") or "0x0000…unset"
    return addr if len(addr) < 14 else f"{addr[:6]}…{addr[-4:]}"


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(json.loads(line)["entry"])
    return out


def _positions(entry: dict, equity: float) -> list[dict]:
    weights = entry.get("target_weights", {})
    rows = [
        {"symbol": s, "weight": w, "value": round(w * equity, 2)}
        for s, w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    ]
    deployed = sum(w for w in weights.values())
    if deployed < 1.0:
        rows.append({"symbol": "USDT", "weight": round(1 - deployed, 4),
                     "value": round((1 - deployed) * equity, 2), "cash": True})
    return rows


def _top(signals: dict) -> list[dict]:
    return [{"symbol": s, "score": v}
            for s, v in sorted(signals.items(), key=lambda kv: kv[1], reverse=True)]


def _max_dd(curve: list[float]) -> float:
    peak, mdd = 0.0, 0.0
    for eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, (peak - eq) / peak)
    return mdd


def _spark(curve: list[float], w: int = 400, h: int = 120) -> str:
    if len(curve) < 2:
        return ""
    lo, hi = min(curve), max(curve)
    rng = (hi - lo) or 1.0
    step = w / (len(curve) - 1)
    pts = [f"{i * step:.1f},{h - (v - lo) / rng * (h - 10) - 5:.1f}"
           for i, v in enumerate(curve)]
    return " ".join(pts)


def _log(entries: list[dict]) -> list[dict]:
    out = []
    for e in reversed(entries):
        regime = e.get("regime", "—")
        n = len(e.get("trades", []))
        msg = (f"{regime.upper()} · {n} swap(s) · gross {e.get('gross_exposure', 0):.0%}"
               if regime != "risk_off" else "Risk-Off · rotated to stable")
        if e.get("notes"):
            msg = e["notes"]
        out.append({"ts": e.get("timestamp", 0), "msg": msg, "regime": regime})
    return out


def _empty_view(cfg: Config, chain_ok: bool) -> dict:
    return {
        "agent": cfg_agent(), "preset": cfg.preset.value, "mode": cfg.mode.value,
        "regime": "—", "fear_greed": 0, "gross": 0.0, "equity": 0.0,
        "start_equity": 0.0, "total_return": 0.0, "open_drawdown": 0.0,
        "max_drawdown": 0.0, "breaker": cfg.limits.breaker_drawdown,
        "positions": [], "signals": [], "curve": "", "log": [],
        "chain_ok": chain_ok, "n_ticks": 0,
    }


@app.route("/")
def index():
    return render_template("keel.html", v=load_view())


@app.route("/api/state")
def api_state():
    return jsonify(load_view())


def main() -> int:
    app.run(host="127.0.0.1", port=8088, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
