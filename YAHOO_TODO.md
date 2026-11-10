# Yahoo data still to bring in

The Yahoo Fantasy API was **denied on 2026-11-10** (Yahoo only approves developers in the
USA and Canada). Instead, the app reads **public leagues' web pages** with no login
(`projector/yahoo_web.py`), the way ifsl.online does. Private leagues still need the
players typed in.

Done:
- **Rosters load automatically**: paste a league link, pick your team, and your roster
  and that week's opponent load; switch between saved leagues at the top.

Possible from the public pages, not built yet:
1. **Real position eligibility**: team pages list Yahoo's positions (e.g. "LAC - PG,SG").
   Then turn `USE_POSITIONS` back on in `projector/projection.py` so daily starters follow
   PG SG G G SF PF F F C C.
2. **Who actually started each day**: `/{league}/{team}/team?date=YYYY-MM-DD` shows each
   day's lineup slots (BN / IL = didn't count), replacing the manual bench editor.
3. **IL slots**: players in IL slots don't count; start them at 0 games by default.
4. **Official totals so far**: the matchup page has Yahoo's category totals for the week.
5. **League settings**: categories and roster slots from the league's settings page,
   instead of the `standard-9cat` preset.
6. **Vs league with my real league**: every team's roster is public, so the "Vs league"
   tab can use the actual teams instead of simulated ones.
7. **Free agents in What if**: only offer players not on any team in the league.

Still needs the API (or a login):
- Private leagues.
- Yahoo's 7-day projections.
