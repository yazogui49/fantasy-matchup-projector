"""Rosters and matchups from Yahoo's public league pages (no login, no API).

Yahoo only gives its Fantasy API to developers in the US and Canada, but a league its
commissioner made publicly viewable can be read like any web page. Private leagues
redirect to a login page and can't be read this way. Yahoo answers HTTP 999 when hit
too fast, so requests are spaced out (callers should cache results, as the app does)."""
from __future__ import annotations

import html
import re
import threading
import time

import requests

from .players import _normalize

BASE = "https://basketball.fantasysports.yahoo.com/nba/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 0.5  # seconds between requests to Yahoo
# Yahoo team abbreviation -> ESPN's, where they differ.
TEAM_CODES = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH",
              "WAS": "WSH", "PHO": "PHX"}

_lock = threading.Lock()
_last_request = 0.0


class YahooError(RuntimeError):
    pass


def _page(path: str) -> str:
    global _last_request
    url = BASE + path
    with _lock:
        time.sleep(max(0.0, _last_request + DELAY - time.time()))
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            raise YahooError(f"Couldn't reach Yahoo ({e})") from e
        finally:
            _last_request = time.time()
    if resp.status_code == 999:
        raise YahooError("Yahoo asked us to slow down. Try again in a few minutes.")
    if resp.status_code != 200:
        raise YahooError(f"Yahoo returned HTTP {resp.status_code} for {url}")
    return resp.text


def parse_link(text: str) -> tuple[str, str | None]:
    """'https://basketball.fantasysports.yahoo.com/nba/3170/11' -> ('3170', '11').
    Also takes '3170/11' or a bare league id. Team is None when the link has none."""
    m = re.search(r"/nba/(\d+)(?:/(\d+))?", text) or re.fullmatch(r"\s*(\d+)(?:\s*/\s*(\d+))?\s*", text)
    if not m:
        raise YahooError("That doesn't look like a Yahoo Fantasy Basketball league link.")
    return m.group(1), m.group(2)


def league(lid: str) -> dict:
    """{'id', 'name', 'week' (current matchup week, None before the schedule exists),
    'teams': {team id: team name}}."""
    page = _page(lid)
    teams: dict[str, str] = {}
    for tid, name in re.findall(rf'href="[^"]*/nba/{lid}/(\d+)"[^>]*>([^<]+)<', page):
        teams.setdefault(tid, html.unescape(name.strip()))
    if not teams:
        raise YahooError("Couldn't read that league. It's probably private: only leagues set "
                         "to publicly viewable can be read without the Yahoo API.")
    weeks = [int(w) for w in re.findall(r"matchup\?week=(\d+)&(?:amp;)?mid1=", page)]
    title = re.search(r"<title>([^<|]+)", page)
    return {"id": lid, "name": html.unescape(title.group(1).strip()) if title else f"League {lid}",
            "week": max(set(weeks), key=weeks.count) if weeks else None,
            "teams": dict(sorted(teams.items(), key=lambda kv: int(kv[0])))}


def opponent(lid: str, tid: str, week: int) -> str | None:
    """Team id that `tid` plays in `week`, or None (bye, or past the schedule)."""
    page = _page(f"{lid}/matchup?week={week}&mid1={tid}")
    others = {t for t in re.findall(rf'/nba/{lid}/(\d+)"', page) if t != tid}
    return others.pop() if len(others) == 1 else None


def roster(lid: str, tid: str) -> list[dict]:
    """Today's roster: [{'name', 'team' (ESPN code), 'positions', 'slot'}].
    `slot` is the lineup spot (PG ... C, BN, IL); `positions` is Yahoo's eligibility."""
    players = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", _page(f"{lid}/{tid}"), re.S):
        name = re.search(r'title="([^"]+)" data-yga', row)
        team_pos = re.search(r'<span class="Fz-xxs">([^<]+)</span>', row)
        if not name or not team_pos:
            continue
        team, _, positions = html.unescape(team_pos.group(1)).partition(" - ")
        slot = re.search(r'data-pos="([^"]*)"', row)
        players.append({
            "name": html.unescape(name.group(1)),
            "team": TEAM_CODES.get(team.strip(), team.strip()),
            "positions": [p for p in positions.strip().split(",") if p],
            "slot": slot.group(1) if slot else None,
        })
    return players


def match(players: list[dict], directory: dict[str, dict]) -> tuple[list[str], list[str]]:
    """ESPN ids for Yahoo players, by name (team breaks ties, and catches spellings like
    'Nicolas'/'Nic'). Returns (ids, names of players not found)."""
    by_name: dict[str, list[str]] = {}
    for pid, p in directory.items():
        by_name.setdefault(_normalize(p["name"]), []).append(pid)
    ids, missing = [], []
    for p in players:
        name = _normalize(p["name"])
        found = by_name.get(name, [])
        if len(found) != 1:
            same_team = [pid for pid in found or directory if directory[pid]["team"] == p["team"]]
            # Same team, same last name: almost surely the same player spelt differently.
            found = [pid for pid in same_team if _normalize(directory[pid]["name"]) == name
                     or _normalize(directory[pid]["name"]).split()[-1:] == name.split()[-1:]]
        if len(found) == 1:
            ids.append(found[0])
        else:
            missing.append(p["name"])
    return ids, missing


if __name__ == "__main__":
    import sys

    from .players import load_players

    lid, tid = parse_link(sys.argv[1] if len(sys.argv) > 1 else "3170/11")
    info = league(lid)
    print(f"{info['name']} (week {info['week']}): {len(info['teams'])} teams")
    for t, n in info["teams"].items():
        print(f"  {t:>3} {n}")
    tid = tid or next(iter(info["teams"]))
    opp = opponent(lid, tid, info["week"])
    directory = {p["id"]: p for p in load_players()}
    for side, team in (("Me", tid), ("Opponent", opp)):
        players = roster(lid, team)
        ids, missing = match(players, directory)
        print(f"\n{side}: {info['teams'][team]}: {len(ids)}/{len(players)} matched"
              + (f", not found: {', '.join(missing)}" if missing else ""))
        for p in players:
            print(f"  {p['slot'] or '':<3} {p['name']:<26} {p['team']:<5} {','.join(p['positions'])}")
