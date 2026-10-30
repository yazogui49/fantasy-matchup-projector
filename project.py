from __future__ import annotations

import argparse

from projector.auth import get_session, list_leagues


def main() -> None:
    p = argparse.ArgumentParser(description="Yahoo H2H matchup projector")
    p.add_argument("--check-auth", action="store_true",
                   help="Authenticate and list your NBA league ids")
    args = p.parse_args()

    if args.check_auth:
        sc = get_session()
        print("Authenticated. Your NBA league ids:")
        for lid in list_leagues(sc):
            print(" ", lid)
        return
    p.print_help()


if __name__ == "__main__":
    main()
