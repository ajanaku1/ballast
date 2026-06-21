"""Launch the Ballast agent.

  python -m scripts.run --ticks 3           # paper mode, 3 ticks, then exit
  python -m scripts.run                      # continuous (Ctrl-C to stop)

Live trading requires the twak CLI + a funded wallet and is gated behind the
mainnet checkpoint; this entrypoint defaults to paper mode.
"""

from __future__ import annotations

import argparse
import json
import logging

from dotenv import load_dotenv

from ballast.config import Config
from ballast.loop import build_agent


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ballast autonomous spot agent")
    parser.add_argument("--ticks", type=int, default=None, help="run N ticks then exit")
    parser.add_argument("--cash", type=float, default=10_000.0, help="starting equity")
    parser.add_argument("--interval", type=int, default=None, help="override tick seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config.from_env()
    if args.interval:
        cfg = cfg.replace(tick_interval_s=args.interval)

    agent = build_agent(cfg, start_cash=args.cash)
    print(f"Ballast [{cfg.preset.value} / {cfg.mode.value}] — universe {len(agent.universe)} "
          f"tokens, breaker {cfg.limits.breaker_drawdown:.0%}\n")

    if args.ticks:
        for _ in range(args.ticks):
            rec = agent.tick()
            print(json.dumps({
                "ts": rec.timestamp, "regime": rec.regime, "fng": rec.fear_greed,
                "gross": round(rec.gross_exposure, 3), "equity": rec.equity,
                "dd": rec.drawdown, "trades": len(rec.trades), "note": rec.notes,
            }))
        print(f"\njournal chain valid: {agent.journal.verify_chain()}")
    else:
        agent.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
