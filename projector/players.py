"""Directory of current NBA players from ESPN team rosters, with name search."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .cache import get_json

TEAMS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"
ROSTER_TTL = 3 * 3600  # injuries and trades change during the day

# ESPN only lists G/F/C; expand to the positions those players can fill.
ESPN_POSITIONS = {"G": ["PG", "SG"], "F": ["SF", "PF"], "C": ["C"]}


def _normalize(name: str) -> str:
    """'Nikola Jokić' -> 'nikola jokic'; drops punctuation like 'Jr.' periods."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", ascii_name.lower()).strip()


def load_players() -> list[dict]:
    teams = get_json(TEAMS, ttl=86400)["sports"][0]["leagues"][0]["teams"]
    players = []
    for t in teams:
        team = t["team"]
        roster = get_json(ROSTER.format(team["id"]), ttl=ROSTER_TTL)
        for a in roster["athletes"]:
            espn_pos = a["position"]["abbreviation"]
            injuries = a.get("injuries") or []
            players.append({
                "id": a["id"],
                "name": a["displayName"],
                "team": team["abbreviation"],
                "positions": ESPN_POSITIONS.get(espn_pos, []),
                "injury": injuries[0]["status"] if injuries else None,
            })
    return players


def search(query: str, players: list[dict] | None = None, limit: int = 5) -> list[dict]:
    """Best name matches for `query`: substring hits first, then closest spellings."""
    players = players if players is not None else load_players()
    q = _normalize(query)

    def score(p: dict) -> float:
        name = _normalize(p["name"])
        if q in name:
            return 2.0 if name.startswith(q) or f" {q}" in name else 1.5
        last = name.split(" ")[-1]
        return max(SequenceMatcher(None, q, name).ratio(), SequenceMatcher(None, q, last).ratio())

    ranked = sorted(players, key=score, reverse=True)
    return [p for p in ranked[:limit] if score(p) >= 0.6]


def resolve(name: str, players: list[dict]) -> dict:
    """The single best match for a typed name; raises if nothing is close."""
    matches = search(name, players, limit=1)
    if not matches:
        raise ValueError(f"No NBA player found matching '{name}'")
    return matches[0]


if __name__ == "__main__":
    import sys

    everyone = load_players()
    print(f"{len(everyone)} players loaded\n")
    for query in sys.argv[1:] or ["brunson", "jokic", "shai", "wemby"]:
        print(f"'{query}':")
        for p in search(query, everyone):
            injury = f"  [{p['injury']}]" if p["injury"] else ""
            print(f"   {p['name']:<28} {p['team']:<5} {'/'.join(p['positions']):<6} id={p['id']}{injury}")
        print()
