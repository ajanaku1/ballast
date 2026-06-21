"""The competition's BEP-20 trading universe.

Trades outside this fixed list don't count. The real ~149-token list is published
by the competition and loaded from `universe.txt` (one symbol per line) when
present; the bundled default is a small stand-in of liquid BSC names so the agent
and backtest run before the official list is dropped in.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_UNIVERSE: tuple[str, ...] = (
    "BNB", "CAKE", "XVS", "ALPACA", "BSW", "BURGER", "AUTO", "BAND",
    "LINK", "ADA", "DOT", "AVAX", "MATIC", "UNI", "AAVE", "INJ",
    "TWT", "SXP", "ALICE", "TLM",
)


def load_universe(path: str | Path = "universe.txt") -> list[str]:
    p = Path(path)
    if p.exists():
        return [s.strip().upper() for s in p.read_text().splitlines() if s.strip()]
    return list(DEFAULT_UNIVERSE)
