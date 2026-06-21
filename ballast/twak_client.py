"""Trust Wallet Agent Kit (TWAK) execution client — wired to the `twak` CLI.

TWAK is the sole execution layer: spot swaps on BSC with autonomous on-device
signing (self-custody, OS keychain). This wrapper shells out to the installed
`twak` binary and degrades by mode:

  - paper:   simulate fills at the provided price, no chain, no twak needed.
  - dry_run: `twak swap … --quote-only` — a real on-chain quote, never broadcast.
  - live:    `twak swap … --password` — signs + broadcasts (gated; needs creds + funds).

TWAK needs API credentials (TWAK_ACCESS_ID / TWAK_HMAC_SECRET, via `twak setup`)
and the wallet password (TWAK_WALLET_PASSWORD / keychain). The binary is located
on PATH or in the npm-global bin; if absent in a non-paper request we fail loud.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Mode

_NPM_GLOBAL_BIN = Path.home() / ".npm-global" / "bin" / "twak"
_BSC = "bsc"
# Native gas token is referenced by symbol; ERC-20s must be resolved to addresses.
_NATIVE = {"BNB"}
_TOKEN_CACHE = Path("token_map.json")


@dataclass
class SwapResult:
    ok: bool
    tx_hash: str | None
    sell_symbol: str
    buy_symbol: str
    usd_amount: float
    fill_price: float
    note: str = ""


class TwakUnavailableError(RuntimeError):
    """Raised when a live/dry-run twak action is requested but twak is missing."""


class TwakError(RuntimeError):
    """Raised when the twak CLI returns an error (e.g. missing API credentials)."""


def _find_twak() -> str | None:
    return shutil.which("twak") or (str(_NPM_GLOBAL_BIN) if _NPM_GLOBAL_BIN.exists() else None)


class TwakClient:
    def __init__(self, mode: Mode = Mode.PAPER, chain: str = _BSC,
                 slippage_pct: float = 1.0, timeout_s: int = 90) -> None:
        self.mode = mode
        self.chain = chain
        self.slippage_pct = slippage_pct
        self.timeout_s = timeout_s
        self.twak_path = _find_twak()

    @property
    def available(self) -> bool:
        return self.twak_path is not None

    # --- token resolution (twak swaps need contract addresses, not symbols) ---
    def resolve_token(self, symbol: str) -> str | None:
        """Resolve a BEP-20 symbol to its BSC contract address via `twak search`,
        cached to disk. Native BNB returns the symbol itself."""
        if symbol in _NATIVE or symbol.startswith("0x"):
            return symbol
        cache = self._load_token_cache()
        if symbol in cache:
            return cache[symbol]
        addr = self._search_bsc_address(symbol)
        if addr:
            cache[symbol] = addr
            _TOKEN_CACHE.write_text(json.dumps(cache, indent=2))
        return addr

    def _load_token_cache(self) -> dict:
        if _TOKEN_CACHE.exists():
            try:
                return json.loads(_TOKEN_CACHE.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _search_bsc_address(self, symbol: str) -> str | None:
        data = self._run(["search", symbol, "--json"])
        results = data.get("result") if isinstance(data.get("result"), list) else data
        if isinstance(results, dict):
            results = results.get("results", [])
        for r in results or []:
            if r.get("chain") == _BSC and r.get("symbol", "").upper() == symbol.upper():
                return r.get("address")
        return None

    # --- execution ---
    def swap(self, sell: str, buy: str, usd: float, price: float,
             reason: str = "") -> SwapResult:
        if self.mode is Mode.PAPER:
            return SwapResult(True, None, sell, buy, usd, price, "paper-fill")
        if not self.available:
            raise TwakUnavailableError(
                "twak CLI not found; install Trust Wallet Agent Kit before live/dry-run."
            )
        sell_id = self.resolve_token(sell) or sell
        buy_id = self.resolve_token(buy) or buy
        args = ["swap", sell_id, buy_id, "--usd", f"{usd:.2f}", "--chain", self.chain,
                "--slippage", str(self.slippage_pct), "--json"]
        if self.mode is Mode.DRY_RUN:
            args.append("--quote-only")
            data = self._run(args)
            return SwapResult(True, None, sell, buy, usd,
                              _quote_price(data, price), "dry-run quote (not broadcast)")
        # live: password comes from TWAK_WALLET_PASSWORD / keychain.
        data = self._run(args + self._password_args())
        tx = _tx_hash(data)
        return SwapResult(
            ok=bool(tx),
            tx_hash=tx,
            sell_symbol=sell, buy_symbol=buy, usd_amount=usd,
            fill_price=_quote_price(data, price), note="live swap",
        )

    def register_competition(self, *, confirmed: bool = False) -> SwapResult:
        """`twak compete register` — one-time on-chain registration (mainnet, gated)."""
        if not confirmed:
            raise TwakError("competition registration is a mainnet action; pass confirmed=True")
        if not self.available:
            raise TwakUnavailableError("twak CLI not found for registration")
        data = self._run(["compete", "register", "--json"] + self._password_args())
        return SwapResult(
            ok=bool(_tx_hash(data) or data.get("registered")),
            tx_hash=_tx_hash(data), sell_symbol="-", buy_symbol="-",
            usd_amount=0.0, fill_price=0.0, note=f"compete register: {data}",
        )

    def competition_status(self) -> dict:
        """Read-only registration status (needs API creds, not the wallet)."""
        if not self.available:
            raise TwakUnavailableError("twak CLI not found")
        return self._run(["compete", "status", "--json"])

    # --- internals ---
    def _password_args(self) -> list[str]:
        # Prefer keychain/env; only pass --password if explicitly provided.
        pw = os.getenv("TWAK_WALLET_PASSWORD")
        return ["--password", pw] if pw else []

    def _run(self, args: list[str]) -> dict:
        proc = subprocess.run(
            [self.twak_path, *args, "--no-analytics"],
            capture_output=True, text=True, timeout=self.timeout_s,
            env={**os.environ, "TWAK_NONINTERACTIVE": "1", "NO_PROMPT": "1"},
        )
        out = (proc.stdout or "").strip()
        data = _parse_json(out)
        if data.get("error") or data.get("errorCode"):
            raise TwakError(data.get("error", out))
        if proc.returncode != 0 and not data:
            raise TwakError(proc.stderr.strip() or f"twak exited {proc.returncode}")
        return data


def _parse_json(out: str) -> dict:
    """twak prints a banner before JSON; extract the JSON object/array."""
    for start in (out.find("{"), out.find("[")):
        if start != -1:
            try:
                parsed = json.loads(out[start:])
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except json.JSONDecodeError:
                continue
    return {}


def _tx_hash(data: dict) -> str | None:
    """twak reports the broadcast tx under `hash` (also tolerate `txHash`/`tx`)."""
    for k in ("hash", "txHash", "tx"):
        v = data.get(k)
        if v:
            return v
    return None


def _quote_price(data: dict, fallback: float) -> float:
    for k in ("price", "fillPrice", "executionPrice", "rate"):
        if k in data and data[k]:
            try:
                return float(data[k])
            except (TypeError, ValueError):
                pass
    return fallback
