"""Project a weekly H2H matchup: stats so far + per-game average x games remaining,
with daily starting-slot limits, then compare category by category."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np

from .league import SLOT_ELIGIBILITY, LeagueSettings
from .schedule import fantasy_week, nba_today, remaining_games, week_games
from .stats import STATS, averages, game_log, played_by

SIMULATIONS = 2000
TOSS_UP = (0.40, 0.60)  # win chance inside this band = toss-up
# ESPN positions don't match Yahoo eligibility (e.g. Yahoo adds SG to some forwards),
# so until Yahoo data is in, only the number of slots limits each day's starters.
USE_POSITIONS = False
# Windows that use Yahoo's per-game projections (given on each player as "projection").
YAHOO_WINDOWS = {"yahoo7"}


def _starters(candidates: list[dict], slots: list[str]) -> set[str]:
    """Ids of the candidates who get a starting slot. Candidates come in priority
    order; each is placed if any slot assignment fits them (bipartite matching),
    so a lower-priority player only starts when a higher one can't use the slot."""
    if not USE_POSITIONS:
        return {p["id"] for p in candidates[:len(slots)]}
    holder: dict[int, dict] = {}

    def place(player: dict, tried: set[int]) -> bool:
        for i, slot in enumerate(slots):
            if i in tried or not SLOT_ELIGIBILITY[slot] & set(player["positions"]):
                continue
            tried.add(i)
            if i not in holder or place(holder[i], tried):
                holder[i] = player
                return True
        return False

    for player in candidates:
        place(player, set())
    return {p["id"] for p in holder.values()}


def _averages(p: dict, window: str, stats_date: date) -> dict:
    """Per-game stats for the window. Yahoo windows: Yahoo's projection, with this
    season's real games scaled to match it, so the win chances keep each player's real
    game-to-game swings. Players without one (not on a team in the league) use this season."""
    if window not in YAHOO_WINDOWS:
        return averages(p["id"], window, stats_date)
    base = averages(p["id"], "season", stats_date)
    if not p.get("projection"):
        return base
    # Yahoo doesn't project minutes or 3-point attempts: those stay as this season's.
    per_game = {s: p["projection"].get(s, base["per_game"][s]) for s in STATS}
    scale = {s: per_game[s] / base["per_game"][s] if base["per_game"][s] else 1.0 for s in STATS}
    return {"source": window, "games": base["games"], "per_game": per_game,
            "pool": [{s: g.get(s, 0.0) * scale[s] for s in STATS} for g in base["pool"]]}


def _project_team(roster: list[dict], settings: LeagueSettings, window: str,
                  today: date, monday: date, sunday: date,
                  remaining: dict[str, list[str]], sat: dict[str, list[str]] | None = None,
                  schedule: dict[str, list[str]] | None = None) -> dict:
    """`sat`: date -> the exact ids benched that day, as set by the user; benched
    players never count. Days not in `sat`: if more play than there are slots, the
    ones with the fewest minutes sit."""
    sat = sat or {}
    # A future `today` (projecting next week) still averages the games played up to now.
    stats_date = min(today, nba_today())
    players = []
    for p in roster:
        team_games = remaining.get(p["team"], [])
        # games_override: how many of the team's remaining games he plays. When fewer
        # than all, assume the last ones (the usual case: returning from injury).
        n = p.get("games_override")
        if n is None:
            n = 0 if p.get("injury") == "Out" else len(team_games)
        players.append({
            **p,
            "avg": _averages(p, window, stats_date),
            "played": {g["date"]: g["stats"] for g in played_by(game_log(p["id"]), today)
                       if g["date"] >= monday.isoformat()},
            "team_games_left": len(team_games),
            "upcoming": team_games[len(team_games) - min(n, len(team_games)):] if n > 0 else [],
            "current": dict.fromkeys(STATS, 0.0),
            "projected_rest": dict.fromkeys(STATS, 0.0),
            "games_played": 0, "games_remaining": 0, "games_benched": 0,
        })
    # Who starts when more players have games than there are slots: most minutes first.
    priority = sorted(players, key=lambda p: p["avg"]["per_game"]["min"], reverse=True)

    daily = []
    day = monday
    while day <= sunday:
        d = day.isoformat()
        playing = [p for p in priority if d in p["played"] or d in p["upcoming"]]
        benched = set(sat.get(d, []))
        starting = _starters([p for p in playing if p["id"] not in benched], settings.starting_slots)
        for p in playing:
            if p["id"] not in starting:
                p["games_benched"] += 1
            elif d in p["played"]:
                p["games_played"] += 1
                for s in STATS:
                    p["current"][s] += p["played"][d].get(s, 0)
            else:
                p["games_remaining"] += 1
                for s in STATS:
                    p["projected_rest"][s] += p["avg"]["per_game"][s]
        daily.append({
            "date": d,
            "past": d < today.isoformat(),
            "with_games": len(playing),
            "scheduled": sum(d in (schedule or {}).get(p["team"], []) for p in players),
            # Players whose team had/has a game, including ones who sat out injured.
            "scheduled_ids": [p["id"] for p in priority if d in (schedule or {}).get(p["team"], [])],
            "user_set": d in sat,
            # Everyone sitting: the user's bench (even players who didn't play), plus anyone
            # who played but didn't fit in the slots.
            "sitting": [p["name"] for p in priority
                        if (p["id"] in benched and d in (schedule or {}).get(p["team"], []))
                        or (p in playing and p["id"] not in starting)],
            "starting": len(starting),
            "benched": [p["name"] for p in playing if p["id"] not in starting],
            "playing_ids": [p["id"] for p in playing],
            "benched_ids": [p["id"] for p in playing if p["id"] not in starting],
            "open_slots": len(settings.starting_slots) - len(starting),
        })
        day += timedelta(days=1)

    current = {s: sum(p["current"][s] for p in players) for s in STATS}
    rest = {s: sum(p["projected_rest"][s] for p in players) for s in STATS}
    return {
        "current": current,
        "final": {s: current[s] + rest[s] for s in STATS},
        "daily": daily,
        "players": [{
            "id": p["id"], "name": p["name"], "team": p["team"],
            "positions": p["positions"], "injury": p.get("injury"),
            "avg_source": p["avg"]["source"], "avg_games": p["avg"]["games"],
            "games_played": p["games_played"], "games_remaining": p["games_remaining"],
            "games_benched": p["games_benched"], "team_games_left": p["team_games_left"],
            "games_assumed": len(p["upcoming"]),
            "current": p["current"], "projected_rest": p["projected_rest"],
        } for p in players],
        # Not part of the JSON result: each starter's remaining games and the real
        # games to resample them from, for simulate().
        "_sim": [(p["games_remaining"], p["avg"]["pool"]) for p in players],
    }


def simulate(team: dict, rng: np.random.Generator, n: int = SIMULATIONS) -> np.ndarray:
    """n possible end-of-week totals (n x len(STATS)): stats so far plus, for each
    remaining start, one of the player's real games from the window, drawn at random."""
    totals = np.tile(np.array([team["current"][s] for s in STATS]), (n, 1))
    for starts, pool in team["_sim"]:
        if starts and pool:
            games = np.array([[g.get(s, 0.0) for s in STATS] for g in pool])
            totals += games[rng.integers(0, len(games), size=(n, starts))].sum(axis=1)
    return totals


def _category_values(cat, totals: np.ndarray) -> np.ndarray:
    col = {s: i for i, s in enumerate(STATS)}
    if cat.is_pct:
        made, att = totals[:, col[cat.made]], totals[:, col[cat.attempted]]
        return np.divide(made, att, out=np.zeros_like(made), where=att > 0)
    return totals[:, col[cat.stat]]


def compare(settings: LeagueSettings, mine: dict, theirs: dict,
            sims: tuple[np.ndarray, np.ndarray] | None = None) -> list[dict]:
    """Category rows. With simulations, the winner comes from the win chance
    (toss-up inside TOSS_UP); without, from which projected total is better."""
    rows = []
    for cat in settings.categories:
        a, b = cat.value(mine), cat.value(theirs)
        margin = abs(a - b) / max(abs(a), abs(b)) * 100 if max(abs(a), abs(b)) else 0.0
        row = {"category": cat.name, "is_pct": cat.is_pct, "me": a, "opponent": b,
               "margin_pct": round(margin, 1)}
        if sims is not None:
            va, vb = _category_values(cat, sims[0]), _category_values(cat, sims[1])
            better = va > vb if cat.higher_is_better else va < vb
            prob = float(np.mean(better) + 0.5 * np.mean(va == vb))
            row["win_prob"] = round(prob, 3)
            row["winner"] = ("toss-up" if TOSS_UP[0] <= prob <= TOSS_UP[1]
                             else "me" if prob > TOSS_UP[1] else "opponent")
        else:
            row["winner"] = ("toss-up" if a == b
                             else "me" if (a > b) == cat.higher_is_better else "opponent")
        rows.append(row)
    return rows


def project_matchup(me: list[dict], opponent: list[dict], settings: LeagueSettings,
                    window: str = "season", today: date | None = None,
                    sat: dict[str, dict[str, list[str]]] | None = None) -> dict:
    """Full projection as a JSON-serializable dict; every view renders from this."""
    today = today or nba_today()
    monday, sunday = fantasy_week(today)
    remaining = remaining_games(today)
    schedule = week_games(today)
    sat = sat or {}
    teams = {side: _project_team(roster, settings, window, today, monday, sunday, remaining,
                                 sat.get(side), schedule)
             for side, roster in (("me", me), ("opponent", opponent))}
    rng = np.random.default_rng(0)  # fixed seed: same inputs give the same chances
    sims = (simulate(teams["me"], rng), simulate(teams["opponent"], rng))
    for team in teams.values():
        del team["_sim"]

    categories = compare(settings, teams["me"]["final"], teams["opponent"]["final"], sims)
    current = compare(settings, teams["me"]["current"], teams["opponent"]["current"])
    wins = sum(r["winner"] == "me" for r in categories)
    losses = sum(r["winner"] == "opponent" for r in categories)
    ties = len(categories) - wins - losses
    expected = sum(r["win_prob"] for r in categories)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "league": settings.name,
        "window": window,
        "as_of": today.isoformat(),
        "week": {"start": monday.isoformat(), "end": sunday.isoformat()},
        "categories": categories,
        "current_categories": current,
        "summary": {"wins": wins, "losses": losses, "toss_ups": ties,
                    "expected_wins": round(expected, 1),
                    "text": f"Projected {wins}-{losses}-{ties}"},
        "teams": teams,
    }
