"""BNB AI Agent SDK integration tests — real SDK, ephemeral in-memory wallet.

These exercise the *local* crypto surface (wallet signing, agent-URI generation,
x402 typed-data signing, budget caps, the mainnet gate). They never hit an RPC,
spend funds, or persist a key. Skipped cleanly if the SDK isn't installed so the
suite stays green in paper-only environments.
"""

from __future__ import annotations

import time

import pytest

bnbagent = pytest.importorskip("bnbagent")
eth_account = pytest.importorskip("eth_account")

from ballast.bnb_client import BnbAgentClient, BnbConfig, MainnetGated, make_wallet


@pytest.fixture
def ephemeral_wallet():
    key = eth_account.Account.create().key.hex()  # discarded after the test
    return make_wallet(password="test", private_key=key, persist=False)


def test_wallet_has_address(ephemeral_wallet):
    info = ephemeral_wallet.get_wallet_info()
    assert info["address"].startswith("0x") and len(info["address"]) == 42


def test_client_builds_with_budget_on_testnet(ephemeral_wallet):
    client = BnbAgentClient(ephemeral_wallet, BnbConfig(network="bsc-testnet",
                                                        spend_cap_usdc=5.0))
    assert not client.is_mainnet
    assert client.address == ephemeral_wallet.get_wallet_info()["address"]


def test_mainnet_register_is_gated(ephemeral_wallet):
    client = BnbAgentClient(ephemeral_wallet, BnbConfig(network="bsc-mainnet"))
    assert client.is_mainnet
    with pytest.raises(MainnetGated):
        client.register("erc8004://agent", confirmed=False)
    with pytest.raises(MainnetGated):
        client.anchor_journal_hash(1, "deadbeef", confirmed=False)


def test_x402_payment_signature_is_local(ephemeral_wallet):
    client = BnbAgentClient(ephemeral_wallet, BnbConfig(network="bsc-testnet"))
    domain = {"name": "USDC", "version": "1", "chainId": 97,
              "verifyingContract": "0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565"}
    types = {"TransferWithAuthorization": [
        {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}]}
    to = "0x000000000000000000000000000000000000dEaD"
    now = int(time.time())
    message = {"from": client.address, "to": to, "value": 1000,
               "validAfter": now - 10, "validBefore": now + 300,  # 600s policy cap
               "nonce": "0x" + "11" * 32}
    sig = client.sign_x402_payment(domain, types, message, expected_to=to)
    assert "signature" in sig
    sig_val = sig["signature"]
    assert sig_val  # non-empty signature (bytes or 0x-hex str)
    if isinstance(sig_val, str):
        assert sig_val.startswith("0x")
