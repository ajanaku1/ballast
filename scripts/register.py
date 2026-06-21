"""One-time on-chain setup — ERC-8004 identity + competition registration.

Both are mainnet actions and are GATED: this script refuses to broadcast unless
run with --confirm AND the required tooling (twak / bnbagent) is present. It
prints exactly what it would do otherwise, so it is safe to run as a dry preview.

  python -m scripts.register                # preview (no chain action)
  python -m scripts.register --confirm      # broadcast (requires twak + funded wallet)
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from ballast import identity
from ballast.twak_client import TwakClient


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ballast on-chain registration (gated)")
    parser.add_argument("--confirm", action="store_true",
                        help="actually broadcast mainnet txns (requires twak + funds)")
    args = parser.parse_args()

    twak = TwakClient()
    ident = identity.load_identity()
    print("Ballast registration")
    print(f"  competition contract : {identity.COMPETE_CONTRACT}")
    print(f"  twak available       : {twak.available}")
    print(f"  already registered   : {ident.registered}")

    if not args.confirm:
        print("\nPREVIEW only — re-run with --confirm to broadcast (mainnet checkpoint).")
        return 0

    try:
        ident.erc8004_tx = identity.register_erc8004(confirmed=True)
        ident.registration_tx = identity.register_competition(twak, confirmed=True)
        ident.registered = True
        identity.save_identity(ident)
        print(f"\nRegistered. erc8004={ident.erc8004_tx} compete={ident.registration_tx}")
        return 0
    except (identity.RegistrationGated, NotImplementedError) as exc:
        print(f"\nBLOCKED: {exc}")
        print("Install/auth twak + bnbagent and wire the broadcast calls at the checkpoint.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
