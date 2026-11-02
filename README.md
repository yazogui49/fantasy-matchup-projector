# Fantasy Matchup Projector

A personal, non-commercial command-line tool for my own Yahoo Fantasy Basketball
head-to-head leagues. For the current week's matchup it projects the final value of
every scoring category for me and my opponent, and shows which categories I'm likely
to win, lose, or that are toss-ups.

It uses **read-only** access to the Yahoo Fantasy Sports API (league settings,
matchup, rosters, player stats and status). Nothing is written back to Yahoo, and
data stays on my own machine.

## How it works

1. Pick both rosters (searchable list of every NBA player, from ESPN).
2. Stats so far this week come from real box scores; the rest of the week is
   per-game average × games remaining (choose: this season, last 30 days, last season, ...).
3. At most 10 players count per day (positions ignored until Yahoo eligibility is in), and FG%/FT%
   are projected from makes and attempts, never averaged percentages.
4. Category-by-category comparison; anything within 5% is a toss-up.
5. Per-player games override for injuries/rest, and a next-week view.
6. Vs league: where your roster ranks against a simulated 12-team league.

Yahoo integration (real rosters, lineups and totals) is waiting on Yahoo Fantasy API approval;
everything set aside for it is listed in [YAHOO_TODO.md](YAHOO_TODO.md).

## Run it

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py              # web app
.venv/bin/python project.py --matchup matchups/sample.txt --window last30   # command line
```

Your rosters and settings are kept in the page URL, so bookmark it to keep them.
Data comes from ESPN's public endpoints and is cached in `cache/`.

## Code

- `projector/schedule.py`: NBA schedule, games remaining in the fantasy week
- `projector/players.py`: player directory and name search
- `projector/stats.py`: game logs, averages per window, week-to-date totals
- `projector/projection.py`: projection, slot limits, category comparison (JSON result)
- `projector/benchmark.py`: simulated league drafts and ranking (Vs league tab)
- `projector/output.py`: text table; `app.py`: Streamlit UI
- `projector/auth.py`: Yahoo OAuth (for when API access is approved)
