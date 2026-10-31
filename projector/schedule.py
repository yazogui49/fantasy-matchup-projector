"""NBA schedule from ESPN's public scoreboard, and games remaining in the fantasy week."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .cache import get_json

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
NBA_TZ = ZoneInfo("America/New_York")  # NBA game dates are Eastern dates


def nba_today() -> date:
    return datetime.now(NBA_TZ).date()


def fantasy_week(day: date) -> tuple[date, date]:
    """Monday..Sunday week containing `day`."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def games_on(day: date) -> list[dict]:
    """Games on an Eastern date. state is 'pre' (not started), 'in' (live) or 'post' (final)."""
    # Past days can't change; today's and future days can (status, postponements).
    ttl = None if day < nba_today() else 3600
    data = get_json(SCOREBOARD.format(day.strftime("%Y%m%d")), ttl=ttl)
    games = []
    for event in data.get("events", []):
        teams = {c["homeAway"]: c["team"]["abbreviation"]
                 for c in event["competitions"][0]["competitors"]}
        games.append({
            "id": event["id"],
            "date": day.isoformat(),
            "state": event["status"]["type"]["state"],
            "home": teams["home"],
            "away": teams["away"],
        })
    return games


def remaining_games(today: date | None = None) -> dict[str, list[str]]:
    """Team -> dates of its unfinished games from today through Sunday.
    Live games count as remaining: week totals come from final box scores only.
    Passing a past `today` counts every game from that date on, as of that morning."""
    real_today = nba_today()
    today = today or real_today
    _, sunday = fantasy_week(today)
    remaining: dict[str, list[str]] = defaultdict(list)
    day = today
    while day <= sunday:
        for g in games_on(day):
            if day != real_today or g["state"] != "post":
                remaining[g["home"]].append(g["date"])
                remaining[g["away"]].append(g["date"])
        day += timedelta(days=1)
    return dict(remaining)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Games remaining this fantasy week per NBA team")
    p.add_argument("--date", type=date.fromisoformat, help="pretend today is YYYY-MM-DD")
    args = p.parse_args()

    today = args.date or nba_today()
    monday, sunday = fantasy_week(today)
    rem = remaining_games(today)
    print(f"Week {monday} to {sunday}, counting from {today}\n")
    for team in sorted(rem, key=lambda t: (-len(rem[t]), t)):
        days = ", ".join(datetime.fromisoformat(d).strftime("%a") for d in rem[team])
        print(f"  {team:<5} {len(rem[team])}  ({days})")
    print(f"\n{len(rem)} teams with games left; teams not listed have 0.")
