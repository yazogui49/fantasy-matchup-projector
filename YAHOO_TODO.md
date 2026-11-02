# Waiting on Yahoo API access

Things set aside until Yahoo approves the app (applied 2026-10-30). Check access with
`.venv/bin/python project.py --check-auth`.

1. **Rosters load automatically**: my team and this week's opponent, for both leagues,
   instead of typing them in.
2. **League settings from Yahoo**: categories, starting slots, bench/IL, instead of the
   `standard-9cat` preset.
3. **Real position eligibility**: ESPN only has G/F/C and doesn't match Yahoo (e.g. Jaquez
   is SG/SF/PF on Yahoo). Then turn `USE_POSITIONS` back on in `projector/projection.py`
   so daily starters follow PG SG G G SF PF F F C C.
4. **Who actually started each day**: past days currently assume the fewest-minutes
   players sat when more than 10 played. Yahoo has the real daily lineups.
5. **Official matchup totals so far**: use Yahoo's live category totals instead of
   rebuilding them from ESPN box scores.
6. **Yahoo's 7-day projections**: add as a "Project using" option (if the API exposes them).
7. **Vs league with my real league**: replace the simulated 12-team league in the
   "Vs league" tab with the actual teams.
8. **Free agents in What if**: only offer players who are actually available in my league.
