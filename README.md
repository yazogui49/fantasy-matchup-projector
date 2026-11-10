# Fantasy Matchup Projector

A non-commercial tool for Yahoo Fantasy Basketball head-to-head leagues. For the current week's matchup it projects the final value of
every scoring category for me and my opponent, and shows which categories I'm likely
to win, lose, or that are toss-ups.

Rosters come from a league's **public** Yahoo pages (read-only, no login; Yahoo's API is
only open to US/Canada developers); stats and schedules come from ESPN. Nothing is
written back to Yahoo.

## How it works

1. Paste a public Yahoo league link and pick your team: your roster and that week's
   opponent load by themselves. Save several leagues and switch between them. Or pick both
   rosters by hand (searchable list of every NBA player, from ESPN).
2. Stats so far this week come from real box scores; the rest of the week is
   per-game average × games remaining (choose: this season, last 30 days, last season, ...).
3. At most 10 players count per day (positions ignored until Yahoo eligibility is in), and FG%/FT%
   are projected from makes and attempts, never averaged percentages.
4. Category-by-category comparison; anything within 5% is a toss-up.
5. Per-player games override for injuries/rest, and a next-week view.
6. Vs league: where your roster ranks against a simulated 12-team league, this week or
   over the rest of the season; What if shows the same for trades and pickups.

Yahoo data still to bring in (positions, real lineups, official totals, the real league)
is listed in [YAHOO_TODO.md](YAHOO_TODO.md).

## Run it

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py              # web app
.venv/bin/python project.py --matchup matchups/sample.txt --window last30   # command line
```

Your leagues, rosters and settings are kept in the page URL, so bookmark it to keep them.
Data comes from ESPN's public endpoints and is cached in `cache/`.

## Code

- `projector/schedule.py`: NBA schedule, games remaining in the fantasy week
- `projector/players.py`: player directory and name search
- `projector/stats.py`: game logs, averages per window, week-to-date totals
- `projector/projection.py`: projection, slot limits, category comparison (JSON result)
- `projector/yahoo_web.py`: rosters and matchups from public Yahoo league pages
- `projector/benchmark.py`: simulated league drafts and ranking (Vs league tab)
- `projector/output.py`: text table; `app.py`: Streamlit UI
- `projector/auth.py`: Yahoo OAuth (for when API access is approved)
