"""Project a weekly H2H matchup: stats so far + per-game average x games remaining,
with daily starting-slot limits, then compare category by category."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .league import SLOT_ELIGIBILITY, LeagueSettings
from .schedule import fantasy_week, nba_today, remaining_games
from .stats import STATS, averages, game_log, played_by

TOSS_UP_PCT = 5.0


def _starters(candidates: list[dict], slots: list[str]) -> set[str]:
    """Ids of the candidates who get a starting slot. Candidates come in priority
    order; each is placed if any slot assignment fits them (bipartite matching),
    so a lower-priority player only starts when a higher one can't use the slot."""
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


def _project_team(roster: list[dict], settings: LeagueSettings, window: str,
                  today: date, monday: date, sunday: date,
                  remaining: dict[str, list[str]]) -> dict:
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
            "avg": averages(p["id"], window, stats_date),
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

    day = monday
    while day <= sunday:
        d = day.isoformat()
        playing = [p for p in priority if d in p["played"] or d in p["upcoming"]]
        starting = _starters(playing, settings.starting_slots)
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
        day += timedelta(days=1)

    current = {s: sum(p["current"][s] for p in players) for s in STATS}
    rest = {s: sum(p["projected_rest"][s] for p in players) for s in STATS}
    return {
        "current": current,
        "final": {s: current[s] + rest[s] for s in STATS},
        "players": [{
            "id": p["id"], "name": p["name"], "team": p["team"],
            "positions": p["positions"], "injury": p.get("injury"),
            "avg_source": p["avg"]["source"], "avg_games": p["avg"]["games"],
            "games_played": p["games_played"], "games_remaining": p["games_remaining"],
            "games_benched": p["games_benched"], "team_games_left": p["team_games_left"],
            "games_assumed": len(p["upcoming"]),
            "current": p["current"], "projected_rest": p["projected_rest"],
        } for p in players],
    }


def compare(settings: LeagueSettings, mine: dict, theirs: dict,
            toss_up_pct: float = TOSS_UP_PCT) -> list[dict]:
    rows = []
    for cat in settings.categories:
        a, b = cat.value(mine), cat.value(theirs)
        margin = abs(a - b) / max(abs(a), abs(b)) * 100 if max(abs(a), abs(b)) else 0.0
        if margin <= toss_up_pct:
            winner = "toss-up"
        else:
            winner = "me" if (a > b) == cat.higher_is_better else "opponent"
        rows.append({"category": cat.name, "is_pct": cat.is_pct, "me": a, "opponent": b,
                     "winner": winner, "margin_pct": round(margin, 1)})
    return rows


def project_matchup(me: list[dict], opponent: list[dict], settings: LeagueSettings,
                    window: str = "season", today: date | None = None) -> dict:
    """Full projection as a JSON-serializable dict; every view renders from this."""
    today = today or nba_today()
    monday, sunday = fantasy_week(today)
    remaining = remaining_games(today)
    teams = {side: _project_team(roster, settings, window, today, monday, sunday, remaining)
             for side, roster in (("me", me), ("opponent", opponent))}
    categories = compare(settings, teams["me"]["final"], teams["opponent"]["final"])
    current = compare(settings, teams["me"]["current"], teams["opponent"]["current"])
    wins = sum(r["winner"] == "me" for r in categories)
    losses = sum(r["winner"] == "opponent" for r in categories)
    ties = len(categories) - wins - losses
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "league": settings.name,
        "window": window,
        "as_of": today.isoformat(),
        "week": {"start": monday.isoformat(), "end": sunday.isoformat()},
        "categories": categories,
        "current_categories": current,
        "summary": {"wins": wins, "losses": losses, "toss_ups": ties,
                    "text": f"Projected {wins}-{losses}-{ties}"},
        "teams": teams,
    }
