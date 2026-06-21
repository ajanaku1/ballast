"""One-time setup: ERC-8004 on-chain identity + competition registration.

Both are mainnet actions and stay behind the live checkpoint — the functions
build and describe the action but refuse to broadcast until explicitly cleared,
so an autonomous run can never accidentally register or spend on-chain.

`load_identity` / `save_identity` keep the public agent address (safe to store)
so the journal and dashboard can reference it without any private material.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

COMPETE_CONTRACT = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"


@dataclass
class Identity:
    agent_address: str | None = None
    erc8004_tx: str | None = None
    registration_tx: str | None = None
    registered: bool = False


class RegistrationGated(RuntimeError):
    """Raised if registration is attempted before the mainnet checkpoint is cleared."""


def load_identity(path: str | Path = "identity.json") -> Identity:
    p = Path(path)
    if not p.exists():
        return Identity()
    return Identity(**json.loads(p.read_text()))


def save_identity(identity: Identity, path: str | Path = "identity.json") -> None:
    Path(path).write_text(json.dumps(asdict(identity), indent=2))


def register_erc8004(bnb=None, *, confirmed: bool = False,
                     name: str = "Ballast",
                     description: str = "Self-custody spot agent (funding-shadow strategy)") -> dict:
    """Register the agent's ERC-8004 identity via the BNB AI Agent SDK.

    `bnb` is a `ballast.bnb_client.BnbAgentClient`. Testnet writes proceed; mainnet
    writes require confirmed=True (enforced inside the client too). Returns the
    SDK's registration receipt (includes agent id + tx)."""
    if bnb is None:
        from .bnb_client import from_env
        bnb = from_env()
    if bnb is None:
        raise RegistrationGated("no BNB wallet configured (set BNB_WALLET_KEY) — gated")
    if bnb.is_mainnet and not confirmed:
        raise RegistrationGated("ERC-8004 mainnet registration; pass confirmed=True")
    uri = bnb.generate_uri(name=name, description=description, endpoints=[])
    return bnb.register(uri, confirmed=confirmed)


def register_competition(twak=None, contract: str = COMPETE_CONTRACT,
                         *, confirmed: bool = False) -> str:
    """`twak compete register` to the competition contract. Gated."""
    if not confirmed:
        raise RegistrationGated("competition registration is a mainnet action; pass confirmed=True")
    if twak is None or not getattr(twak, "available", False):
        raise RegistrationGated("twak CLI not available for registration")
    raise NotImplementedError("Wire twak.register_competition() at the mainnet checkpoint.")
