# Yahoo data still to bring in

The Yahoo Fantasy API was **denied on 2026-11-10** (Yahoo only approves developers in the
USA and Canada). Instead, the app reads **public leagues' web pages** with no login
(`projector/yahoo_web.py`), the way ifsl.online does. Private leagues still need the
players typed in.

Done:
- **Rosters load automatically**: paste a league link, pick your team, and your roster
  and that week's opponent load; switch between saved leagues at the top.
- **Yahoo's projections** as a "Project using" option: Yahoo's projection for each
  remaining day's game (so it knows the opponent); the app's schedule and overrides
  decide which games count.
- **Vs league with my real league**: the "Vs league" tab and What if compare against the
  league's actual teams (their current Yahoo rosters), with projected standings. With
  Yahoo projections on, every team uses Yahoo's rest-of-season numbers, or for "This
  week" each remaining day's own projection.
- **Real positions**: with a Yahoo league, players get Yahoo's eligibility and daily
  starters fill PG SG G G SF PF F F C C (`use_positions` in `projector/projection.py`).
- **Who actually started each day**: days played so far (and today) use Yahoo's real
  lineups; anyone not in an active slot sat (bench, IL, or not on the team yet). Any day
  can still be changed by hand.
- **IL slots**: players in IL slots start at 0 games this week (and don't count in the
  league comparison's week).

Possible from the public pages, not built yet:
1. **Official totals so far**: the matchup page has Yahoo's category totals for the week.
   This also counts players who've left the team since (e.g. dropped or traded mid-week),
   whose games the app currently misses because it only knows today's roster.
2. **League settings**: categories and roster slots from the league's settings page,
   instead of the `standard-9cat` preset.
3. **Free agents in What if**: only offer players not on any team in the league.
4. **Real schedule in Vs league standings**: the standings play everyone once; the
   league's actual remaining matchups are on Yahoo's schedule page.

Still needs the API (or a login):
- Private leagues.
