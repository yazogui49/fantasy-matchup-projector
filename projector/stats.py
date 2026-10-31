"""Player game logs from ESPN, per-game averages over a window, and week-to-date totals."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .cache import get_json
from .schedule import NBA_TZ, nba_today

GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{}/gamelog"
STATS = ["min", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "reb", "ast", "stl", "blk", "tov", "pts"]
# Averaging windows: days back from today, None for the whole current season,
# or "lastseason" for all of last season's games.
WINDOWS = {"season": None, "last30": 30, "last14": 14, "last7": 7, "lastseason": "lastseason"}

# ESPN column name -> our stat key(s); "made-attempted" columns split into two.
_COLUMNS = {
    "minutes": ["min"],
    "fieldGoalsMade-fieldGoalsAttempted": ["fgm", "fga"],
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ["fg3m", "fg3a"],
    "freeThrowsMade-freeThrowsAttempted": ["ftm", "fta"],
    "totalRebounds": ["reb"],
    "assists": ["ast"],
    "steals": ["stl"],
    "blocks": ["blk"],
    "turnovers": ["tov"],
    "points": ["pts"],
}


def game_log(player_id: str, season: int | None = None) -> list[dict]:
    """Regular-season games the player appeared in, oldest first.
    `season` is the year the season ends (2026 = 2025-26); None = current season."""
    url = GAMELOG.format(player_id) + (f"?season={season}" if season else "")
    data = get_json(url, ttl=None if season else 3 * 3600)
    columns = data.get("names", [])
    events = data.get("events", {})

    games = []
    for season_type in data.get("seasonTypes", []):
        if "Regular Season" not in season_type.get("displayName", ""):
            continue
        for cat in season_type.get("categories", []):
            if cat.get("type") != "event":
                continue
            for row in cat.get("events", []):
                stats = {}
                for col, raw in zip(columns, row["stats"]):
                    keys = _COLUMNS.get(col)
                    if keys:
                        for key, val in zip(keys, raw.split("-")):
                            stats[key] = float(val)
                if not stats.get("min"):
                    continue  # listed but didn't play
                info = events.get(row["eventId"], {})
                played = datetime.fromisoformat(info["gameDate"].replace("Z", "+00:00"))
                games.append({
                    "date": played.astimezone(NBA_TZ).date().isoformat(),
                    "team": info.get("team", {}).get("abbreviation"),
                    "stats": stats,
                })
    return sorted(games, key=lambda g: g["date"])


def played_by(games: list[dict], today: date) -> list[dict]:
    """Games completed as of `today`: through today for the real date, but only
    before it for a simulated past date (matching schedule.remaining_games)."""
    if today >= nba_today():
        return [g for g in games if g["date"] <= today.isoformat()]
    return [g for g in games if g["date"] < today.isoformat()]


def _sum(games: list[dict]) -> dict[str, float]:
    return {s: sum(g["stats"].get(s, 0) for g in games) for s in STATS}


def averages(player_id: str, window: str = "season", today: date | None = None) -> dict:
    """Per-game averages over the window. An empty window falls back to the full
    season, then last season (for "lastseason": to this season, e.g. rookies).
    Reports which source it used."""
    today = today or nba_today()
    last_season = today.year - 1 if today.month < 8 else today.year  # ESPN labels seasons by end year
    last_season_games = lambda: game_log(player_id, season=last_season)
    games = played_by(game_log(player_id), today)
    if window == "lastseason":
        sources = [("lastseason", last_season_games), ("season", games)]  # rookies
    else:
        days = WINDOWS[window]
        sources = [(window, [g for g in games if days is None
                             or g["date"] > (today - timedelta(days=days)).isoformat()])]
        if window != "season":
            sources.append(("season", games))
        sources.append(("lastseason", last_season_games))

    for source, pool in sources:
        pool = pool() if callable(pool) else pool
        if pool:
            totals = _sum(pool)
            return {"source": source, "games": len(pool),
                    "per_game": {s: v / len(pool) for s, v in totals.items()}}
    return {"source": None, "games": 0, "per_game": {s: 0.0 for s in STATS}}


def week_totals(player_id: str, monday: date, today: date | None = None) -> dict:
    """Stats from completed games this fantasy week, through today."""
    today = today or nba_today()
    week = [g for g in played_by(game_log(player_id), today) if g["date"] >= monday.isoformat()]
    return {"games": len(week), "totals": _sum(week)}


if __name__ == "__main__":
    import argparse

    from .players import search
    from .schedule import fantasy_week

    p = argparse.ArgumentParser(description="A player's averages and this week's totals")
    p.add_argument("name")
    p.add_argument("--window", choices=WINDOWS, default="season")
    p.add_argument("--date", type=date.fromisoformat, help="pretend today is YYYY-MM-DD")
    args = p.parse_args()

    matches = search(args.name, limit=1)
    if not matches:
        raise SystemExit(f"No player found for '{args.name}'")
    player = matches[0]
    today = args.date or nba_today()
    cols = ["min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta"]

    print(f"{player['name']} ({player['team']})\n")
    print("  date        " + " ".join(f"{c:>5}" for c in cols))
    for g in played_by(game_log(player["id"]), today):
        print(f"  {g['date']}  " + " ".join(f"{g['stats'].get(c, 0):>5.0f}" for c in cols))

    avg = averages(player["id"], args.window, today)
    print(f"\n  avg ({avg['source']}, {avg['games']} games)")
    print("              " + " ".join(f"{avg['per_game'][c]:>5.1f}" for c in cols))

    monday, _ = fantasy_week(today)
    wk = week_totals(player["id"], monday, today)
    print(f"\n  this week so far ({wk['games']} games since {monday})")
    print("              " + " ".join(f"{wk['totals'][c]:>5.0f}" for c in cols))
