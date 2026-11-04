"""Where a roster stands against a typical league, not just this week's opponent.

Until Yahoo gives us the real league, simulate one: rank players by 9-cat value,
snake-draft them into 12 teams (with some noise, since real drafts aren't by the
book), and compare everyone's full week on the same footing: per-game averages from
the chosen window x games that week, at most `slots` players counted per day."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np

from .cache import get_json
from .league import LeagueSettings
from .schedule import nba_today, week_games
from .stats import STATS, averages

SEASON_STATS = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/"
                "statistics/byathlete?region=us&lang=en&contentorigin=espn&isqualified=false&limit=1000")
# ESPN per-game column -> our stat key.
_COLUMNS = {
    "avgMinutes": "min", "avgFieldGoalsMade": "fgm", "avgFieldGoalsAttempted": "fga",
    "avgThreePointFieldGoalsMade": "fg3m", "avgThreePointFieldGoalsAttempted": "fg3a",
    "avgFreeThrowsMade": "ftm", "avgFreeThrowsAttempted": "fta", "avgRebounds": "reb",
    "avgAssists": "ast", "avgSteals": "stl", "avgBlocks": "blk", "avgTurnovers": "tov",
    "avgPoints": "pts",
}
LEAGUES = 50
TEAMS = 12
DRAFT_NOISE = 0.5  # spread of each drafter's opinion, in units of value's std dev
MIN_GAMES = 2      # ignore players with fewer games when building the draft pool
POOL_FACTOR = 2    # recent windows: fetch game logs for this many x the drafted players


def season_averages(season: int | None = None) -> dict[str, dict]:
    """Player id -> {'games': n, 'per_game': {stat: avg}} for everyone who's played.
    `season` = end year of a past regular season (2026 = 2025-26); None = this season."""
    url = SEASON_STATS + (f"&season={season}&seasontype=2" if season else "")
    data = get_json(url, ttl=None if season else 3 * 3600)
    names = {c["name"]: c["names"] for c in data["categories"]}
    out = {}
    for a in data["athletes"]:
        per_game, games = {}, 0
        for cat in a["categories"]:
            for col, value in zip(names[cat["name"]], cat["values"]):
                if col in _COLUMNS:
                    per_game[_COLUMNS[col]] = float(value)
                elif col == "gamesPlayed":
                    games = int(value)
        out[a["athlete"]["id"]] = {"games": games, "per_game": per_game}
    return out


def _values(pool: list[dict], settings: LeagueSettings) -> np.ndarray:
    """Draft value: summed z-scores per category. Percentages count by impact
    (makes above league rate x volume), so a 60% shooter on 2 shots barely matters."""
    per_game = [p["per_game"] for p in pool]
    total = np.zeros(len(pool))
    for cat in settings.categories:
        if cat.is_pct:
            made = np.array([g.get(cat.made, 0) for g in per_game])
            att = np.array([g.get(cat.attempted, 0) for g in per_game])
            rate = made.sum() / att.sum() if att.sum() else 0
            col = made - rate * att
        else:
            col = np.array([g.get(cat.stat, 0) for g in per_game])
        z = (col - col.mean()) / (col.std() or 1)
        total += z if cat.higher_is_better else -z
    return total


def _week_totals(players: list[dict], schedule: dict[str, list[str]], slots: int) -> dict[str, float]:
    """A roster's week: each day, up to `slots` players with a game count (most minutes first)."""
    by_day: dict[str, list[dict]] = {}
    for p in players:
        for d in schedule.get(p["team"], []):
            by_day.setdefault(d, []).append(p)
    totals = dict.fromkeys(STATS, 0.0)
    for playing in by_day.values():
        playing.sort(key=lambda p: p["per_game"].get("min", 0), reverse=True)
        for p in playing[:slots]:
            for s in STATS:
                totals[s] += p["per_game"].get(s, 0)
    totals["games"] = sum(min(len(v), slots) for v in by_day.values())
    return totals


def _cat_matrix(teams: list[dict], settings: LeagueSettings) -> np.ndarray:
    """teams x categories, flipped so higher is always better."""
    return np.array([[c.value(t) if c.higher_is_better else -c.value(t)
                      for c in settings.categories] for t in teams])


def _h2h(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Matchup score of each row of `a` vs each row of `b`: 1 win, 0.5 tie, 0 loss."""
    wins = (a[:, None, :] > b[None, :, :]).sum(-1)
    losses = (a[:, None, :] < b[None, :, :]).sum(-1)
    return np.where(wins > losses, 1.0, np.where(wins == losses, 0.5, 0.0))


def _window_averages(window: str, roster: list[dict], directory: dict[str, dict],
                     settings: LeagueSettings, roster_size: int, today: date) -> dict[str, dict]:
    """Per-player averages for `window`. Whole seasons come from one all-player request;
    recent windows from game logs, for the players a draft could reach (ranked by this
    season) plus the roster."""
    this_season = season_averages()
    if window == "season":
        return this_season
    if window == "lastseason":
        last = season_averages(today.year - 1 if today.month < 8 else today.year)
        return {**this_season, **last}  # rookies keep this season's numbers
    eligible = [pid for pid, a in this_season.items() if a["games"] >= MIN_GAMES
                and pid in directory and directory[pid]["injury"] != "Out"]
    value = _values([this_season[pid] for pid in eligible], settings)
    reach = [eligible[i] for i in np.argsort(-value)[:TEAMS * roster_size * POOL_FACTOR]]
    ids = list(dict.fromkeys(reach + [p["id"] for p in roster]))
    with ThreadPoolExecutor(8) as ex:
        results = ex.map(lambda pid: averages(pid, window, today), ids)
    return {pid: {"games": r["games"], "per_game": r["per_game"]} for pid, r in zip(ids, results)}


def benchmark(roster: list[dict], directory: dict[str, dict], settings: LeagueSettings,
              day: date, window: str = "season", seed: int = 0) -> dict:
    """Compare `roster` (player dicts with id/team/injury) with simulated league teams
    for the fantasy week containing `day`. JSON-serializable result."""
    schedule = week_games(day)
    slots = len(settings.starting_slots)
    roster_size = slots + settings.bench
    stats_day = nba_today()  # averages use every game played so far, whichever week
    avgs = _window_averages(window, roster, directory, settings, roster_size, stats_day)

    def player(pid: str) -> dict:
        info = directory.get(pid, {})
        return {"id": pid, "team": info.get("team"),
                "per_game": avgs.get(pid, {}).get("per_game", {})}

    # Draft pool: current players who've played, minus anyone Out (they'd sit on IL).
    pool = [player(pid) for pid, a in avgs.items()
            if a["games"] >= MIN_GAMES and pid in directory and directory[pid]["injury"] != "Out"]
    value = _values(pool, settings)

    rng = np.random.default_rng(seed)
    league_teams = []  # LEAGUES x TEAMS week totals
    for _ in range(LEAGUES):
        order = np.argsort(-(value + rng.normal(0, DRAFT_NOISE * value.std(), len(value))))
        picks = order[:TEAMS * roster_size]
        teams: list[list[dict]] = [[] for _ in range(TEAMS)]
        for i, idx in enumerate(picks):
            rnd, pos = divmod(i, TEAMS)
            teams[pos if rnd % 2 == 0 else TEAMS - 1 - pos].append(pool[idx])
        league_teams.append([_week_totals(t, schedule, slots) for t in teams])

    mine_players = [player(p["id"]) for p in roster if p.get("injury") != "Out"]
    mine = _week_totals(mine_players, schedule, slots)
    me = _cat_matrix([mine], settings)[0]
    all_teams = [t for league in league_teams for t in league]
    others = _cat_matrix(all_teams, settings)

    categories = []
    for j, cat in enumerate(settings.categories):
        beat = float(np.mean(me[j] > others[:, j]) + 0.5 * np.mean(me[j] == others[:, j]))
        typical = float(np.median([cat.value(t) for t in all_teams]))
        categories.append({"category": cat.name, "is_pct": cat.is_pct, "me": cat.value(mine),
                           "typical": typical, "beats_pct": round(beat, 3)})

    # Rank: put me in each simulated league in place of one team (rotating which),
    # then order the 12 by their record against the other 11.
    ranks = []
    for i, league in enumerate(league_teams):
        teams = league[:i % TEAMS] + [mine] + league[i % TEAMS + 1:]
        m = _cat_matrix(teams, settings)
        score = _h2h(m, m).sum(1) - 0.5  # drop the tie with itself
        ranks.append(1 + int(np.sum(score > score[i % TEAMS])))

    matchups = _h2h(me[None, :], others)[0]
    return {
        "teams_simulated": len(all_teams),
        "categories": categories,
        "expected_cats": round(sum(c["beats_pct"] for c in categories), 1),
        "matchup_win_pct": round(float(matchups.mean()), 3),
        "rank": round(float(np.mean(ranks)), 1),
        "rank_best": int(min(ranks)), "rank_worst": int(max(ranks)),
        "league_size": TEAMS,
        "games": {"me": mine["games"], "typical": float(np.median([t["games"] for t in all_teams]))},
    }
