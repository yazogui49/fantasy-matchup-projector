from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from projector.league import PRESETS
from projector.output import render_players, render_table
from projector.players import load_players, resolve
from projector.projection import project_matchup
from projector.stats import WINDOWS


def load_matchup_file(path: Path) -> dict[str, list[str]]:
    """Parse a text file with [me] and [opponent] sections, one player name per line."""
    sides: dict[str, list[str]] = {"me": [], "opponent": []}
    section = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            if section not in sides:
                raise SystemExit(f"{path}: unknown section [{section}]; use [me] and [opponent]")
        elif section is None:
            raise SystemExit(f"{path}: put names under a [me] or [opponent] heading")
        else:
            sides[section].append(line)
    return sides


def main() -> None:
    p = argparse.ArgumentParser(description="H2H fantasy basketball matchup projector")
    p.add_argument("--matchup", type=Path, help="text file with [me] and [opponent] rosters")
    p.add_argument("--window", choices=WINDOWS, default="season", help="stats used to project")
    p.add_argument("--preset", choices=PRESETS, default="standard-9cat", help="league settings")
    p.add_argument("--date", type=date.fromisoformat, help="pretend today is YYYY-MM-DD")
    p.add_argument("--players", action="store_true", help="also show the per-player breakdown")
    p.add_argument("--json", action="store_true", help="print the raw JSON result instead")
    p.add_argument("--check-auth", action="store_true",
                   help="Authenticate with Yahoo and list your NBA league ids")
    args = p.parse_args()

    if args.check_auth:
        from projector.auth import get_session, list_leagues
        sc = get_session()
        print("Authenticated. Your NBA league ids:")
        for lid in list_leagues(sc):
            print(" ", lid)
        return
    if not args.matchup:
        p.print_help()
        return

    directory = load_players()
    names = load_matchup_file(args.matchup)
    try:
        rosters = {side: [resolve(n, directory) for n in ns] for side, ns in names.items()}
    except ValueError as e:
        raise SystemExit(str(e))
    for side, ns in names.items():
        for typed, player in zip(ns, rosters[side]):
            if typed.lower() != player["name"].lower():
                print(f"  note: '{typed}' matched {player['name']} ({player['team']})")

    result = project_matchup(rosters["me"], rosters["opponent"], PRESETS[args.preset],
                             window=args.window, today=args.date)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(render_table(result))
    if args.players:
        print(render_players(result))


if __name__ == "__main__":
    main()
