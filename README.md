# Fantasy Matchup Projector

A personal, non-commercial command-line tool for my own Yahoo Fantasy Basketball
head-to-head leagues. For the current week's matchup it projects the final value of
every scoring category for me and my opponent, and shows which categories I'm likely
to win, lose, or that are toss-ups.

It uses **read-only** access to the Yahoo Fantasy Sports API (league settings,
matchup, rosters, player stats and status). Nothing is written back to Yahoo, and
data stays on my own machine.

## How it works

1. Reads the league's scoring categories (not hardcoded; FG%/FT% projected from makes and attempts).
2. Pulls the current week's matchup: both rosters, stats so far, and active lineup slots.
3. Counts each player's remaining games this week from the NBA schedule.
4. Projects the rest of the week (per-game average × games remaining; configurable window).
5. Adds the projections to current stats and compares category by category.

Output is structured JSON, rendered as a table:

```
category | me | opponent | projected winner | margin %
...
Projected 5-3-1
```

## Usage

```
python project.py --league <league_id> --window last14
```

## Status

Work in progress. Yahoo auth is set up; the projection modules are being built
step by step.

## Setup

1. Create a Yahoo developer app with Fantasy Sports read permission and redirect URI `https://localhost:8080`.
2. `cp .env.example .env` and fill in the client ID and secret.
3. `python -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. `.venv/bin/python project.py --check-auth`

Credentials (`.env`) and tokens (`oauth2.json`) are gitignored and never committed.
