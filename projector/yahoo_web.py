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


def _text(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>|\s+", " ", cell)).strip()


def _number(text: str | None) -> float | None:
    try:
        return float((text or "").replace(",", ""))
    except ValueError:
        return None  # "-": no projection


def _player_rows(page: str) -> list[dict]:
    """Player rows of a team page: name, team (ESPN code), Yahoo positions, lineup slot,
    and the stat cells by column header."""
    tables = re.findall(r"<table.*?</table>", page, re.S)
    table = max(tables, key=lambda t: t.count("data-ys-playerid"), default="")
    heads: list[str] = []
    rows = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", table, re.S):
        name = re.search(r'title="([^"]+)" data-yga', tr)
        team_pos = re.search(r'<span class="Fz-xxs">([^<]+)</span>', tr)
        if not name or not team_pos:
            cells = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S)]
            if "Players" in cells:
                heads = cells
            continue
        team, _, positions = html.unescape(team_pos.group(1)).partition(" - ")
        slot = re.search(r'data-pos="([^"]*)"', tr)
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        rows.append({
            "name": html.unescape(name.group(1)),
            "team": TEAM_CODES.get(team.strip(), team.strip()),
            "positions": [p for p in positions.strip().split(",") if p],
            "slot": slot.group(1) if slot else None,
            # Some headers span two cells (e.g. "Action"), all before the stats: line
            # headers up with cells from the right.
            "cells": dict(zip(reversed(heads), reversed(cells))),
        })
    return rows


def roster(lid: str, tid: str) -> list[dict]:
    """Today's roster: [{'name', 'team' (ESPN code), 'positions', 'slot'}].
    `slot` is the lineup spot (PG ... C, BN, IL); `positions` is Yahoo's eligibility."""
    return [{k: r[k] for k in ("name", "team", "positions", "slot")}
            for r in _player_rows(_page(f"{lid}/{tid}"))]


# Yahoo projection column -> our stat key; "made/attempted" columns hold two.
_PROJECTED = {"FGM/A*": ("fgm", "fga"), "FTM/A*": ("ftm", "fta"), "3PTM": ("fg3m",),
              "PTS": ("pts",), "REB": ("reb",), "AST": ("ast",), "ST": ("stl",),
              "BLK": ("blk",), "TO": ("tov",)}
PROJECTION_PERIODS = {"next7": "PS7", "rest": "PSR"}


def projections(lid: str, tid: str, period: str = "next7") -> list[dict]:
    """Yahoo's projected per-game stats for a team's players: [{'name', 'team', 'per_game'}].
    Yahoo projects totals over the period (next 7 days, or the rest of the season) and
    the games he'll play in it; per game = one over the other. Players Yahoo projects to
    play no games are left out."""
    page = _page(f"{lid}/{tid}?stat1=P&stat2={PROJECTION_PERIODS[period]}")
    out = []
    for row in _player_rows(page):
        games = _number(row["cells"].get("GP*"))
        if not games:
            continue
        per_game = {}
        for head, keys in _PROJECTED.items():
            values = [_number(v) for v in row["cells"].get(head, "").split("/")]
            if len(values) == len(keys) and None not in values:
                per_game.update({k: v / games for k, v in zip(keys, values)})
        out.append({"name": row["name"], "team": row["team"], "per_game": per_game})
    return out


def find(players: list[dict], directory: dict[str, dict]) -> list[str | None]:
    """ESPN id for each Yahoo player (None if not found), by name: team breaks ties, and
    catches spellings like 'Nicolas'/'Nic'."""
    by_name: dict[str, list[str]] = {}
    for pid, p in directory.items():
        by_name.setdefault(_normalize(p["name"]), []).append(pid)
    ids = []
    for p in players:
        name = _normalize(p["name"])
        found = by_name.get(name, [])
        if len(found) != 1:
            same_team = [pid for pid in found or directory if directory[pid]["team"] == p["team"]]
            # Same team, same last name: almost surely the same player spelt differently.
            found = [pid for pid in same_team if _normalize(directory[pid]["name"]) == name
                     or _normalize(directory[pid]["name"]).split()[-1:] == name.split()[-1:]]
        ids.append(found[0] if len(found) == 1 else None)
    return ids


def match(players: list[dict], directory: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(ESPN ids of the players found, names of those not found)."""
    ids = find(players, directory)
    return ([i for i in ids if i],
            [p["name"] for p, i in zip(players, ids) if not i])


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
    print("\nYahoo per-game projections, next 7 days (my team):")
    for p in projections(lid, tid):
        g = p["per_game"]
        print(f"  {p['name']:<26} " + "  ".join(f"{k} {g[k]:.1f}" for k in ("pts", "reb", "ast", "stl", "blk", "fg3m") if k in g)
              + (f"  FG {g['fgm'] / g['fga']:.3f}" if g.get("fga") else ""))
