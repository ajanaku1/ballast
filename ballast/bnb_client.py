"""BNB AI Agent SDK wrapper — ERC-8004 identity + x402 payment signing.

Wraps `bnbagent` (the BNB AI Agent SDK) behind the narrow surface Ballast needs:

  - a self-custody EVM wallet (encrypted keystore via the SDK; key from env/keychain,
    never committed),
  - ERC-8004 identity registration + on-chain metadata anchoring (used to anchor the
    decision journal's rolling hash on-chain — a verifiable track record without
    needing a separate blob store),
  - an x402 payment signer with the SDK's built-in per-call + session budget caps,
    keyed by the BSC payment-token address.

Local operations (wallet signing, agent-URI generation, typed-data x402 signatures)
work with no RPC. Chain writes (register, set_metadata) are gated: mainnet requires
`confirmed=True` so an autonomous run can never register or spend unprompted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # the SDK is optional at import time so the agent still runs in paper mode
    from bnbagent import ERC8004Agent, EVMWalletProvider, X402Signer, networks
    from bnbagent import NetworkConfig
    from bnbagent.erc8004 import get_erc8004_config
    _SDK = True
except Exception:  # noqa: BLE001
    _SDK = False

# The SDK ships dead default testnet RPCs; use live public nodes unless overridden.
_DEFAULT_RPC = {
    "bsc-testnet": "https://bsc-testnet-rpc.publicnode.com",
    "bsc-mainnet": "https://bsc-rpc.publicnode.com",
}


class SdkUnavailableError(RuntimeError):
    """Raised when a BNB-SDK action is requested but `bnbagent` isn't installed."""


class MainnetGated(RuntimeError):
    """Raised when a mainnet chain write is attempted without explicit confirmation."""


# x402 payment token (USDC-equivalent) per BSC chain id, from the SDK.
_PAYMENT_TOKEN = {56: "0xcE24439F2D9C6a2289F741120FE202248B666666",
                  97: "0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565"}


@dataclass
class BnbConfig:
    network: str = "bsc-testnet"  # bsc-testnet | bsc-mainnet
    spend_cap_usdc: float = 5.0   # session budget; SDK enforces in token base units
    max_per_call_usdc: float = 1.0
    rpc_url: str | None = None    # override the SDK's default (often dead) RPC


class BnbAgentClient:
    """Thin, testable wrapper over the BNB AI Agent SDK."""

    def __init__(self, wallet, cfg: BnbConfig | None = None) -> None:
        if not _SDK:
            raise SdkUnavailableError("bnbagent SDK not installed")
        self.cfg = cfg or BnbConfig()
        self.wallet = wallet
        self._chain_id = 56 if self.cfg.network == "bsc-mainnet" else 97
        self._agent = ERC8004Agent(wallet_provider=wallet,
                                   network=self._network_with_live_rpc())
        token = _PAYMENT_TOKEN[self._chain_id]
        self.x402 = X402Signer(
            wallet,
            max_value_per_call={token: _to_base_units(self.cfg.max_per_call_usdc)},
            session_budget={token: _to_base_units(self.cfg.spend_cap_usdc)},
        )

    def _network_with_live_rpc(self):
        """Return a NetworkConfig that keeps the SDK's contract addresses but swaps
        in a working RPC (the SDK's default testnet seed nodes are often down)."""
        rpc = self.cfg.rpc_url or _DEFAULT_RPC.get(self.cfg.network)
        base = get_erc8004_config(self.cfg.network)
        if not rpc or base.get("rpc_url") == rpc:
            return self.cfg.network
        return NetworkConfig(
            name=base["name"], chain_id=base["chain_id"], rpc_url=rpc,
            paymaster_url=base.get("paymaster_url"),
            use_paymaster=bool(base.get("paymaster", False)),
            registry_contract=base.get("registry_contract", ""),
        )

    @property
    def address(self) -> str:
        return self.wallet.get_wallet_info()["address"]

    @property
    def is_mainnet(self) -> bool:
        return self._chain_id == 56

    def generate_uri(self, name: str, description: str,
                     endpoints: list | None = None) -> str:
        return self._agent.generate_agent_uri(name=name, description=description,
                                              endpoints=endpoints or [default_endpoint()])

    def register(self, agent_uri: str, metadata: list | None = None,
                 *, confirmed: bool = False) -> dict:
        self._guard_mainnet(confirmed)
        return self._agent.register_agent(agent_uri, metadata=metadata)

    def anchor_journal_hash(self, agent_id: int, rolling_hash: str,
                            *, confirmed: bool = False) -> dict:
        """Write the journal's latest hash to the agent's on-chain ERC-8004
        metadata — tamper-evidence anchored to the agent's verifiable identity."""
        self._guard_mainnet(confirmed)
        return self._agent.set_metadata(agent_id, "journal_hash", rolling_hash)

    def sign_x402_payment(self, domain: dict, types: dict, message: dict,
                          expected_to: str) -> dict:
        """Sign an x402 (EIP-3009) payment; SDK enforces the budget caps. Local."""
        return self.x402.sign_payment(domain=domain, types=types, message=message,
                                      expected_to=expected_to)

    def _guard_mainnet(self, confirmed: bool) -> None:
        if self.is_mainnet and not confirmed:
            raise MainnetGated("mainnet chain write requires confirmed=True")


def _to_base_units(usdc: float, decimals: int = 6) -> int:
    return int(round(usdc * 10 ** decimals))


def default_endpoint():
    """The agent's self-describing ERC-8004 endpoint (the strategy skill spec)."""
    from bnbagent import AgentEndpoint

    return AgentEndpoint(
        name="ballast-strategy",
        endpoint="https://github.com/bnb-chain/bnbagent-sdk",  # repo/skill ref
        version="1.0.0",
        capabilities=["spot-trading", "funding-shadow", "x402", "erc8004"],
    )


def make_wallet(password: str, private_key: str | None = None, persist: bool = True):
    """Construct the SDK's self-custody wallet. `private_key` comes from env/keychain
    and is NEVER persisted to the repo. With persist=False it stays in memory only."""
    if not _SDK:
        raise SdkUnavailableError("bnbagent SDK not installed")
    return EVMWalletProvider(password=password, private_key=private_key, persist=persist)


def from_env() -> BnbAgentClient | None:
    """Build a client from env if a wallet secret is available; else None (paper).
    Reads BNB_WALLET_KEY / BNB_WALLET_PASSWORD — both gitignored, never committed."""
    if not _SDK:
        return None
    key = os.getenv("BNB_WALLET_KEY")
    password = os.getenv("BNB_WALLET_PASSWORD", "ballast")
    network = os.getenv("TWAK_NETWORK", "bsc-testnet")
    if not key:
        return None
    wallet = make_wallet(password=password, private_key=key, persist=False)
    return BnbAgentClient(wallet, BnbConfig(network=network))
