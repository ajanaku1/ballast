"""Stage 6: the decision journal — additive, fail-safe, tamper-evident.

Every tick's decision + rationale is recorded under the agent's ERC-8004 identity.
Two layers:

  1. A local append-only, hash-chained JSONL (always on). Each entry carries the
     hash of the previous, so any edit to history is detectable offline.
  2. BNB Greenfield (best-effort). The remote write is wired through the BNB AI
     Agent SDK; it is self-flagged breaking-change-prone, so it is wrapped such
     that *any* failure is swallowed and logged — journaling must never halt the
     trade loop. The first five stages run even if this layer is fully down.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path

from .models import TickRecord

log = logging.getLogger("ballast.journal")

GENESIS_HASH = "0" * 64


def _hash_entry(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev_hash}:{body}".encode()).hexdigest()


class Journal:
    """Hash-chained local journal with a best-effort Greenfield mirror."""

    def __init__(self, path: str | Path = "journal.jsonl",
                 greenfield=None, agent_address: str | None = None) -> None:
        self.path = Path(path)
        self.greenfield = greenfield  # optional client with .put(key, bytes)
        self.agent_address = agent_address

    def last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS_HASH
        last = GENESIS_HASH
        for line in self.path.read_text().splitlines():
            if line.strip():
                last = json.loads(line).get("hash", last)
        return last

    def record(self, entry: TickRecord) -> dict:
        """Append the entry locally (always) and mirror to Greenfield (best
        effort). Returns the written envelope. Never raises into the caller."""
        payload = asdict(entry)
        payload["agent"] = self.agent_address
        prev = self.last_hash()
        envelope = {"prev": prev, "hash": _hash_entry(prev, payload), "entry": payload}
        self._append_local(envelope)
        self._mirror_remote(envelope)
        return envelope

    def _append_local(self, envelope: dict) -> None:
        try:
            with self.path.open("a") as fh:
                fh.write(json.dumps(envelope) + "\n")
        except OSError as exc:  # disk full / permissions — log, do not crash loop
            log.error("local journal write failed: %s", exc)

    def _mirror_remote(self, envelope: dict) -> None:
        if self.greenfield is None:
            return
        try:
            key = f"tick/{envelope['entry']['timestamp']}.json"
            self.greenfield.put(key, json.dumps(envelope).encode())
        except Exception as exc:  # noqa: BLE001 — fail-safe by design
            log.warning("Greenfield mirror failed (continuing): %s", exc)

    def verify_chain(self) -> bool:
        """Re-derive the hash chain to detect tampering. Offline integrity check."""
        if not self.path.exists():
            return True
        prev = GENESIS_HASH
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            env = json.loads(line)
            if env.get("prev") != prev:
                return False
            if _hash_entry(prev, env["entry"]) != env["hash"]:
                return False
            prev = env["hash"]
        return True
