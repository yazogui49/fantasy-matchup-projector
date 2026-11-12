"""Streamlit UI: pick both rosters, choose a stats window, see the projected matchup.
Run with: .venv/bin/streamlit run app.py"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

from projector import yahoo_web
from projector.benchmark import benchmark, player_averages, real_league
from projector.config import ROOT
from projector.league import PRESETS
from projector.output import fmt
from projector.players import load_players
from projector.projection import YAHOO_WINDOWS, project_matchup
from projector.schedule import fantasy_week, nba_today, remaining_games

LEGACY_ROSTERS_FILE = ROOT / "data" / "rosters.json"
WINDOW_LABELS = {
    "season": "This season",
    "last30": "Last 30 days",
    "lastseason": "Last season",
    "last14": "Last 14 days",
    "last7": "Last 7 days",
    "yahoo": "Yahoo projections",
}
WINNER_COLORS = {"me": "#1a7f37", "opponent": "#cf222e", "toss-up": "#9a6700"}

# Cached results are keyed on this too: st.cache_data only notices edits to the cached
# function itself, so after a deploy that changes projector/ it would serve old results.
CODE_VERSION = hashlib.md5(b"".join(
    f.read_bytes() for f in sorted((ROOT / "projector").glob("*.py")))).hexdigest()

st.set_page_config(page_title="Matchup Projector", page_icon="🏀", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Loading NBA players…")
def players_by_id() -> dict[str, dict]:
    return {p["id"]: p for p in load_players()}


@st.cache_data(ttl=1800, show_spinner=False)
def team_games_left(as_of: date | None) -> dict[str, int]:
    return {team: len(dates) for team, dates in remaining_games(as_of).items()}


@st.cache_data(ttl=1800, show_spinner="Crunching the matchup…")
def run_projection(me: tuple[str, ...], opp: tuple[str, ...], preset: str, window: str,
                   as_of: date | None, games: tuple[tuple[str, int], ...],
                   sat: tuple[tuple[str, str, tuple[str, ...]], ...], code: str,
                   yahoo: tuple[str, ...] = ()) -> dict:
    """`yahoo`: (league id, team ids...) to read Yahoo's projections from."""
    directory = players_by_id()
    overrides = dict(games)
    projected = {}
    if yahoo and window in YAHOO_WINDOWS:
        today = as_of or nba_today()
        sunday = fantasy_week(today)[1]
        days = tuple((today + timedelta(days=i)).isoformat() for i in range((sunday - today).days + 1))
        projected = yahoo_projections(yahoo[0], yahoo[1:], days)

    def roster(ids):
        return [{**directory[i], "games_override": overrides.get(i), "projection": projected.get(i)}
                for i in ids]

    sat_by_side: dict[str, dict[str, list[str]]] = {}
    for side, day, ids in sat:
        sat_by_side.setdefault(side, {})[day] = list(ids)
    return project_matchup(roster(me), roster(opp), PRESETS[preset], window=window,
                           today=as_of, sat=sat_by_side)


@st.cache_data(ttl=1800, show_spinner="Reading the Yahoo league…")
def yahoo_league(lid: str) -> dict:
    return yahoo_web.league(lid)


@st.cache_data(ttl=1800, show_spinner="Loading Yahoo's projections…")
def yahoo_projections(lid: str, teams: tuple[str, ...], days: tuple[str, ...]) -> dict[str, dict]:
    """ESPN id -> {date: Yahoo's projected stats for that day's game}, for these teams'
    players over the given days (one Yahoo page per team per day)."""
    directory = players_by_id()
    projected: dict[str, dict] = {}
    for tid in teams:
        for day in days:
            players = yahoo_web.day_projections(lid, tid, day)
            for pid, p in zip(yahoo_web.find(players, directory), players):
                if pid:
                    projected.setdefault(pid, {})[day] = p["per_game"]
    return projected


@st.cache_data(ttl=1800, show_spinner="Loading rosters from Yahoo…")
def yahoo_matchup(lid: str, tid: str, week: int | None) -> dict:
    """Both rosters as ESPN ids, plus the opponent's team id and anyone not found."""
    directory = players_by_id()
    opp = yahoo_web.opponent(lid, tid, week) if week else None
    me, missing = yahoo_web.match(yahoo_web.roster(lid, tid), directory)
    them, missing_opp = yahoo_web.match(yahoo_web.roster(lid, opp), directory) if opp else ([], [])
    return {"me": me, "opponent": them, "opponent_team": opp, "missing": missing + missing_opp}


@st.cache_data(ttl=1800, show_spinner="Reading every team in your Yahoo league…")
def yahoo_league_teams(lid: str, period: str) -> dict[str, dict]:
    """Team id -> {'name', 'ids', 'projected': {id: Yahoo's per-game projection}}, for
    every team in the league (one Yahoo page each)."""
    directory = players_by_id()
    teams = {}
    for tid, name in yahoo_league(lid)["teams"].items():
        players = yahoo_web.projections(lid, tid, period)
        ids = yahoo_web.find(players, directory)
        teams[tid] = {"name": name, "ids": [i for i in ids if i],
                      "projected": {i: p["per_game"] for i, p in zip(ids, players)
                                    if i and p["per_game"]}}
    return teams


@st.cache_data(ttl=3600, show_spinner="Comparing with your league…")
def run_real_league(me: tuple[str, ...], preset: str, week_start: str, window: str,
                    horizon: str, lid: str, tid: str, code: str) -> dict:
    """`me` against the other teams of Yahoo league `lid`, standing in for team `tid`."""
    directory = players_by_id()
    # Yahoo projects the next 7 days or the rest of the season, not a Monday-Sunday week.
    teams = yahoo_league_teams(lid, "rest" if horizon == "season" else "next7")
    yahoo = window in YAHOO_WINDOWS
    ids = list(dict.fromkeys(list(me) + [i for t in teams.values() for i in t["ids"]]))
    per_game = player_averages(ids, "season" if yahoo else window, nba_today())
    if yahoo:  # Yahoo has no minutes or 3-point attempts: those stay as this season's
        for t in teams.values():
            for pid, projected in t["projected"].items():
                per_game[pid] = {**per_game.get(pid, {}), **projected}
    return real_league([directory[i] for i in me],
                       {k: {"name": t["name"], "ids": t["ids"]} for k, t in teams.items()},
                       tid, directory, PRESETS[preset], date.fromisoformat(week_start),
                       per_game, horizon)


HORIZONS = {"season": "Rest of season", "week": "This week"}


@st.cache_data(ttl=3600, show_spinner="Simulating a league…")
def run_benchmark(me: tuple[str, ...], preset: str, week_start: str, window: str,
                  horizon: str, code: str) -> dict:
    directory = players_by_id()
    return benchmark([directory[i] for i in me], directory, PRESETS[preset],
                     date.fromisoformat(week_start), window, horizon)


# Each person's state lives in the page URL (bookmarkable, shareable, per-browser), so
# people using one hosted app never see or overwrite each other's rosters.
# Games overrides are per fantasy week: "2026-11-02~1966.3~4277961.0_2026-11-09~...".
def encode_games(games: dict[str, dict[str, int]]) -> str:
    return "_".join(week + "".join(f"~{pid}.{n}" for pid, n in sorted(g.items()))
                    for week, g in sorted(games.items()) if g)


def decode_games(text: str) -> dict[str, dict[str, int]]:
    games: dict[str, dict[str, int]] = {}
    for chunk in filter(None, text.split("_")):
        week, *pairs = chunk.split("~")
        try:
            games[week] = {pid: int(n) for pid, n in (pair.split(".") for pair in pairs)}
        except ValueError:
            continue  # hand-edited or truncated URL: drop that week
    return games


# Who sat on past crowded days, when the app's guess was wrong: "m~2026-11-02~123.456_o~...".
SIDE_CODES = {"me": "m", "opponent": "o"}


def encode_sat(sat: dict[str, dict[str, list[str]]]) -> str:
    return "_".join(f"{SIDE_CODES[side]}~{day}~{'.'.join(ids)}"
                    for side, days in sorted(sat.items()) for day, ids in sorted(days.items()))


def decode_sat(text: str) -> dict[str, dict[str, list[str]]]:
    sides = {code: side for side, code in SIDE_CODES.items()}
    sat: dict[str, dict[str, list[str]]] = {}
    for chunk in filter(None, text.split("_")):
        parts = chunk.split("~")
        if len(parts) == 3 and parts[0] in sides:
            sat.setdefault(sides[parts[0]], {})[parts[1]] = [i for i in parts[2].split(".") if i]
    return sat


def load_saved() -> dict:
    q = st.query_params
    # Yahoo leagues as "league.team", e.g. y=3170.11,210575.9 and l = the one shown.
    leagues = [k for k in q.get("y", "").split(",") if re.fullmatch(r"\d+\.\d+", k)]
    yahoo = {"leagues": leagues, "league": q.get("l") if q.get("l") in leagues else ""}
    if q.keys() & {"me", "opp", "y", "w"}:
        return {"me": q.get("me", "").split(","), "opponent": q.get("opp", "").split(","),
                "window": q.get("w", "season"), "games": decode_games(q.get("g", "")),
                "sat": decode_sat(q.get("s", "")), **yahoo}
    try:  # one-time carry-over of rosters saved by earlier local versions
        return {**json.loads(LEGACY_ROSTERS_FILE.read_text()), **yahoo}
    except (FileNotFoundError, json.JSONDecodeError):
        return yahoo


def save(state: dict) -> None:
    this_monday = fantasy_week(nba_today())[0].isoformat()
    games = {w: g for w, g in state["games"].items() if w >= this_monday}
    sat = {side: {d: ids for d, ids in days.items() if d >= this_monday}
           for side, days in st.session_state.get("sat", {}).items()}
    params = {"me": ",".join(state["me"]), "opp": ",".join(state["opponent"]),
              "w": state["window"], "g": encode_games(games), "s": encode_sat(sat),
              "y": ",".join(st.session_state["leagues"]), "l": st.session_state["league"]}
    params = {k: v for k, v in params.items() if v}
    if dict(st.query_params) != params:
        st.query_params.from_dict(params)


try:
    directory = players_by_id()
except requests.RequestException as e:
    st.error(f"Couldn't load NBA players from ESPN, so the app can't run right now. ({e})")
    st.stop()


def label(pid: str) -> str:
    p = directory[pid]
    injury = f" · {p['injury']}" if p["injury"] else ""
    return f"{p['name']} ({p['team']}, {'/'.join(p['positions'])}){injury}"


# Restore saved state for anything this session doesn't have yet (each key separately,
# so sessions opened before a new setting existed still pick it up).
saved = load_saved()
for side in ("me", "opponent"):
    if side not in st.session_state:
        st.session_state[side] = [i for i in saved.get(side, []) if i in directory]
if "window" not in st.session_state:
    w = saved.get("window", "season")
    st.session_state["window"] = w if w in WINDOW_LABELS else "season"
if "games" not in st.session_state:
    st.session_state["games"] = saved.get("games", {})
if "sat" not in st.session_state:
    st.session_state["sat"] = saved.get("sat", {})
for key in ("leagues", "league"):
    if key not in st.session_state:
        st.session_state[key] = saved[key]

with st.sidebar:
    st.header("Settings")
    preset = st.selectbox("League settings", list(PRESETS), format_func=lambda k: PRESETS[k].name)
    week = st.radio("Week", ["this", "next"], horizontal=True,
                    format_func={"this": "This week", "next": "Next week"}.get)
    # Yahoo's projections need a Yahoo league to read them from.
    windows = [w for w in WINDOW_LABELS if st.session_state["league"] or w not in YAHOO_WINDOWS]
    if st.session_state["window"] not in windows:
        st.session_state["window"] = "season"
    window = st.radio("Project using", windows, key="window", format_func=WINDOW_LABELS.get)
    with st.expander("Testing"):
        pretend = st.checkbox("Pretend it's another day")
        as_of = st.date_input("Date", value=nba_today()) if pretend else None

if week == "next":
    as_of = fantasy_week(nba_today())[1] + timedelta(days=1)  # next Monday morning
week_start = fantasy_week(as_of or nba_today())[0].isoformat()

st.title("🏀 Matchup Projector")
settings = PRESETS[preset]
roster_size = len(settings.starting_slots) + settings.bench + settings.il



def league_label(key: str) -> str:
    if not key:
        return "No Yahoo league (type players in)"
    lid, tid = key.split(".")
    try:
        info = yahoo_league(lid)
    except yahoo_web.YahooError:
        return f"League {lid} · team {tid}"
    return f"{info['name']} · {info['teams'].get(tid, f'team {tid}')}"


def add_league(lid: str, tid: str) -> None:
    key = f"{lid}.{tid}"
    if key not in st.session_state["leagues"]:
        st.session_state["leagues"].append(key)
    st.session_state["league"] = key
    st.session_state["yahoo_link"] = ""


def change_team(lid: str, widget: str) -> None:
    """Swap the shown league's team for the one picked (keeping its place in the list)."""
    old, new = st.session_state["league"], f"{lid}.{st.session_state[widget]}"
    leagues = st.session_state["leagues"]
    if new in leagues:  # that team is already saved: just switch to it
        leagues.remove(old)
    else:
        leagues[leagues.index(old)] = new
    st.session_state["league"] = new


def remove_league() -> None:
    st.session_state["leagues"].remove(st.session_state["league"])
    st.session_state["league"] = next(iter(st.session_state["leagues"]), "")


def reload_yahoo() -> None:
    yahoo_league.clear()
    yahoo_matchup.clear()
    st.session_state.pop("loaded_for", None)


# Yahoo leagues: each person adds their own (saved in their URL) and switches between them.
leagues = st.session_state["leagues"]
if leagues:
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    c1.selectbox("League", leagues + [""], key="league", format_func=league_label)
    c2.button("Reload from Yahoo", on_click=reload_yahoo, width="stretch")
if st.session_state["league"]:
    with st.expander("Change team or remove this league"):
        lid, tid = st.session_state["league"].split(".")
        try:
            info = yahoo_league(lid)
        except yahoo_web.YahooError as e:
            st.error(str(e))
        else:
            teams = list(info["teams"])
            widget = f"my_team_{lid}"
            st.session_state[widget] = tid  # follow the league picked above
            st.selectbox(f"My team in {info['name']}", teams, key=widget,
                         format_func=info["teams"].get, on_change=change_team, args=(lid, widget))
        st.button("Remove this league", on_click=remove_league)
with st.expander("Add a Yahoo league" if leagues else "Load your team from Yahoo",
                 expanded=not leagues):
    st.caption("Paste your league's (or your team's) link from Yahoo Fantasy Basketball. Your "
               "roster and this week's opponent then load by themselves. Works for leagues "
               "set to publicly viewable; for others, type the players in below.")
    link = st.text_input("League link", key="yahoo_link",
                         placeholder="https://basketball.fantasysports.yahoo.com/nba/3170/11")
    if link:
        try:
            lid, tid = yahoo_web.parse_link(link)
            info = yahoo_league(lid)
        except yahoo_web.YahooError as e:
            st.error(str(e))
        else:
            teams = list(info["teams"])
            team = st.selectbox(f"Your team in {info['name']}", teams, key=f"yahoo_team_{lid}",
                                index=teams.index(tid) if tid in teams else None,
                                format_func=info["teams"].get, placeholder="Pick your team")
            st.button("Add league", type="primary", on_click=add_league, args=(lid, team),
                      disabled=team is None)

titles = {"me": "My team", "opponent": "Opponent"}
yahoo_teams: tuple[str, ...] = ()  # (league, my team, opponent) for Yahoo's projections
league_name = ""
if st.session_state["league"]:
    lid, tid = st.session_state["league"].split(".")
    try:
        info = yahoo_league(lid)
        yahoo_week = info["week"] and info["week"] + (week == "next")
        loaded = yahoo_matchup(lid, tid, yahoo_week)
    except yahoo_web.YahooError as e:
        st.error(f"{e} Showing the rosters as they were.")
    else:
        # Fill the pickers when the league or week changes (or after Reload); edits made
        # by hand stay until then.
        if st.session_state.get("loaded_for") != (lid, tid, yahoo_week):
            st.session_state["me"], st.session_state["opponent"] = loaded["me"], loaded["opponent"]
            st.session_state["loaded_for"] = (lid, tid, yahoo_week)
        yahoo_teams = (lid, tid) + ((loaded["opponent_team"],) if loaded["opponent_team"] else ())
        league_name = info["name"]
        titles["me"] += f" · {info['teams'].get(tid, '')}"
        if loaded["opponent_team"]:
            titles["opponent"] += f" · {info['teams'].get(loaded['opponent_team'], '')}"
        else:
            st.info(f"No opponent on Yahoo for week {yahoo_week}. Type one in below.")
        if loaded["missing"]:
            st.warning(f"Not found on ESPN, so left out: {', '.join(loaded['missing'])}")

left, right = st.columns(2)
for col, key in ((left, "me"), (right, "opponent")):
    with col:
        st.multiselect(titles[key], list(directory), key=key, format_func=label,
                       max_selections=max(roster_size, len(st.session_state[key])),
                       placeholder="Type a name…")
        # The chips get cut off when the box is narrow (phones), so list everyone here too.
        if st.session_state[key]:
            with st.expander(f"Show all {len(st.session_state[key])} players"):
                st.markdown("\n".join(f"- {label(pid)}" for pid in st.session_state[key]))

me_ids, opp_ids = st.session_state["me"], st.session_state["opponent"]
if not me_ids or not opp_ids:
    save({"me": me_ids, "opponent": opp_ids, "window": window, "games": st.session_state["games"]})
    st.info("Add players to both teams to see the projection.")
    st.stop()

# Games each player plays: saved per fantasy week, so last week's choices don't leak in.
left_by_team = team_games_left(as_of)
week_games = st.session_state["games"].setdefault(week_start, {})
rows = []
for side, ids in (("Me", me_ids), ("Opponent", opp_ids)):
    for pid in ids:
        p = directory[pid]
        available = left_by_team.get(p["team"], 0)
        default = 0 if p["injury"] == "Out" else available
        rows.append({"id": pid, "Team": side, "Player": p["name"], "NBA": p["team"],
                     "Status": p["injury"] or "", "Games left": available,
                     "Plays": min(week_games.get(pid, default), available), "_default": default})
games_df = pd.DataFrame(rows)

# One "games" editor under each team's picker.
editor_key = "games_" + hashlib.md5(f"{week_start}|{me_ids}|{opp_ids}".encode()).hexdigest()[:10]
for col, side in ((left, "Me"), (right, "Opponent")):
    side_rows = [r for r in rows if r["Team"] == side]
    with col, st.expander("Games each player plays (injuries, rest)"):
        st.caption("Change **Plays** to assume a player sits some or all of his team's remaining "
                   "games, or to bring an Out player back. Fewer than all = his last games of the week.")
        edited = st.data_editor(
            games_df[games_df["Team"] == side].drop(columns=["id", "_default", "Team"]),
            key=f"{editor_key}_{side}", hide_index=True, width="stretch",
            disabled=["Player", "NBA", "Status", "Games left"],
            column_config={"Plays": st.column_config.NumberColumn(min_value=0, step=1, format="%d")},
        )
        clamped = []
        for row, plays in zip(side_rows, edited["Plays"]):
            n = max(0, min(int(plays if pd.notna(plays) else row["_default"]), row["Games left"]))
            if n != plays:
                clamped.append(row["Player"])
            if n == row["_default"]:
                week_games.pop(row["id"], None)
            else:
                week_games[row["id"]] = n
        if clamped:
            st.warning(f"Capped at their team's games left: {', '.join(clamped)}")

save({"me": me_ids, "opponent": opp_ids, "window": window, "games": st.session_state["games"]})

games_key = tuple(sorted(week_games.items()))
sat_key = tuple((side, d, tuple(ids)) for side, days in sorted(st.session_state["sat"].items())
                for d, ids in sorted(days.items()))
result = run_projection(tuple(me_ids), tuple(opp_ids), preset, window, as_of, games_key, sat_key,
                        CODE_VERSION, yahoo_teams)
summary = result["summary"]
WINNER_TEXT = {"me": "Me", "opponent": "Opponent", "toss-up": "Toss-up"}
# Yahoo only projects the players on this league's teams, so league comparisons (which
# draft from every NBA player) use this season's stats instead.
bench_window = "season" if window in YAHOO_WINDOWS else window
HORIZON_SPANS = {"week": "this week", "season": "for the rest of the season"}


def vs_league(roster_ids: list[str], horizon: str) -> tuple[dict, bool]:
    """(result, is it the real league?): the loaded Yahoo league's real teams, or a
    simulated league when there's none (or Yahoo can't be read)."""
    if yahoo_teams:
        try:
            return run_real_league(tuple(roster_ids), preset, week_start, window, horizon,
                                   yahoo_teams[0], yahoo_teams[1], CODE_VERSION), True
        except yahoo_web.YahooError as e:
            st.warning(f"Couldn't read your league from Yahoo, so this uses a simulated one. ({e})")
    return run_benchmark(tuple(roster_ids), preset, week_start, bench_window, horizon,
                         CODE_VERSION), False


def league_source(real: bool, horizon: str) -> str:
    """How every team in the comparison is projected, for captions."""
    if real and window in YAHOO_WINDOWS:
        return ("Yahoo's rest-of-season projections" if horizon == "season" else
                "Yahoo's per-game projections for the next 7 days")
    note = ("" if real or window not in YAHOO_WINDOWS else
            "; Yahoo's projections only cover players in your league, so a simulated one uses "
            "this season's stats")
    return f"{WINDOW_LABELS[bench_window].lower()} averages{note}"


def styled_winner(df: pd.DataFrame, winners: list[str], column: str):
    return df.style.apply(
        lambda col: [f"color: {WINNER_COLORS[w]}; font-weight: 600" for w in winners],
        subset=[column])


def remaining_starts(res: dict, side: str = "me") -> int:
    return sum(d["starting"] for d in res["teams"][side]["daily"] if not d["past"])


def total_starts(res: dict, side: str = "me") -> int:
    return sum(d["starting"] for d in res["teams"][side]["daily"])


st.subheader(f"{summary['text']} · expected {summary['expected_wins']} categories")
when = "nothing played yet, all games projected" if week == "next" else f"as of {result['as_of']}"
st.caption(f"Week {result['week']['start']} to {result['week']['end']} · {when}"
           f" · using {WINDOW_LABELS[window].lower()}"
           + ("" if window in YAHOO_WINDOWS else " stats"))

tab_matchup, tab_days, tab_whatif, tab_league, tab_players = st.tabs(
    ["Matchup", "Days", "What if", "Vs league", "Players"])

with tab_matchup:
    c1, c2, c3 = st.columns(3)
    c1.metric("Winning", summary["wins"])
    c2.metric("Losing", summary["losses"])
    c3.metric("Toss-ups", summary["toss_ups"])
    g1, g2 = st.columns(2)
    for col, side, title in ((g1, "me", "My games"), (g2, "opponent", "Opponent games")):
        left = remaining_starts(result, side)
        col.metric(title, total_starts(result, side),
                   None if week == "next" else f"{left} left", delta_color="off")
        with col.expander("Show players"):
            players = sorted(result["teams"][side]["players"],
                             key=lambda p: -(p["games_played"] + p["games_remaining"]))
            st.dataframe(pd.DataFrame([{
                "Player": p["name"],
                **({"Games": p["games_remaining"]} if week == "next" else
                   {"Played": p["games_played"], "Left": p["games_remaining"]}),
                "Sat": p["games_benched"],
            } for p in players]), hide_index=True, width="stretch")
    st.caption(f"Games = every player's games added up, but at most "
               f"{len(settings.starting_slots)} count on any one day.")

    now = {r["category"]: r for r in result["current_categories"]}
    table = pd.DataFrame([{
        "Category": r["category"],
        "Me": fmt(r["me"], r["is_pct"]),
        "Opponent": fmt(r["opponent"], r["is_pct"]),
        "Win chance": f"{r['win_prob']:.0%}",
        "Projected winner": WINNER_TEXT[r["winner"]],
        "Margin %": f"{r['margin_pct']:.1f}",
        "So far (me–opp)": f"{fmt(now[r['category']]['me'], r['is_pct'])} – "
                           f"{fmt(now[r['category']]['opponent'], r['is_pct'])}",
    } for r in result["categories"]])
    if week == "next":
        table = table.drop(columns="So far (me–opp)")
    st.dataframe(styled_winner(table, [r["winner"] for r in result["categories"]], "Projected winner"),
                 hide_index=True, width="stretch")
    st.caption("Win chance: the rest of the week replayed 2,000 times, drawing each game from "
               "the player's real games in the chosen window (for Yahoo's projections: this season's "
               "games, scaled to Yahoo's projection for each day's game). 40–60% counts as a "
               "toss-up.")

with tab_days:
    n_slots = len(settings.starting_slots)
    st.caption(f"**Had a game** = his team played. **Playing** = actually played (past days) or "
               f"expected to (Out players and Plays overrides excluded). **Counted** = at most "
               f"{n_slots} a day; the rest sit (pick who sits under each table). **Open** = unused "
               "slots, where a pickup adds games.")

    def remember_sat(side: str, day: str, key: str) -> None:
        st.session_state["sat"].setdefault(side, {})[day] = st.session_state[key]

    for side, title in (("me", "My team"), ("opponent", "Opponent")):
        daily = result["teams"][side]["daily"]
        st.markdown(f"**{title}** · {total_starts(result, side)} games counted this week")
        days_df = pd.DataFrame([{
            "Day": date.fromisoformat(d["date"]).strftime("%a %b %-d") + (" ✓" if d["past"] else ""),
            "Had a game": d["scheduled"], "Playing": d["with_games"], "Counted": d["starting"],
            "Open": d["open_slots"], "Sitting": ", ".join(d["sitting"]),
        } for d in daily])
        st.dataframe(days_df.style.apply(
            lambda col: ["background-color: rgba(26,127,55,.15)" if v > 0 else "" for v in col],
            subset=["Open"]), hide_index=True, width="stretch")

        # Who sits, any day: the app's guess (fewest minutes, only when more than 10
        # play) until the user sets the day, then exactly what they picked.
        game_days = [d for d in daily if d["scheduled"]]
        if game_days:
            with st.expander(f"Choose who sits each day ({title.lower()})"):
                st.caption("Benched players' stats don't count, even if they played. Days you "
                           "haven't touched use the app's guess.")
                for d in game_days:
                    key = f"sat_{side}_{d['date']}"
                    chosen = st.session_state["sat"].get(side, {}).get(d["date"])
                    st.session_state[key] = ([i for i in chosen if i in d["scheduled_ids"]]
                                             if chosen is not None else d["benched_ids"])
                    st.multiselect(
                        f"{date.fromisoformat(d['date']).strftime('%a %b %-d')} · "
                        f"{d['scheduled']} had a game · "
                        + ("set by you" if d["user_set"] else "app's guess"),
                        d["scheduled_ids"], key=key, format_func=lambda i: directory[i]["name"],
                        placeholder="Nobody sits",
                        on_change=remember_sat, args=(side, d["date"], key))
    st.caption("✓ = already played.")
    if any(st.session_state["sat"].values()):  # any day set by the user
        if st.button("Back to the app's guesses of who sits"):
            st.session_state["sat"] = {}
            st.rerun()

with tab_whatif:
    st.caption("Try a pickup or a trade and see this week's matchup and your rest-of-season "
               "standing with it. Your real roster isn't changed.")
    w1, w2 = st.columns(2)
    with w1:
        drops = st.multiselect("Give / drop", me_ids, format_func=label, key="wi_drop")
    with w2:
        adds = st.multiselect("Get / add", [i for i in directory if i not in me_ids],
                              format_func=label, key="wi_add", placeholder="Type a name…")
    if not drops and not adds:
        st.info("Pick players to get and/or give. For a trade, pick both sides.")
    else:
        new_me = [i for i in me_ids if i not in drops] + adds
        if len(new_me) > roster_size:
            st.warning(f"That's {len(new_me)} players, over your {roster_size}-man roster.")
        # Getting players from this week's opponent = a trade with them: they get mine.
        from_opp = [i for i in adds if i in opp_ids]
        new_opp = ([i for i in opp_ids if i not in from_opp] + list(drops)) if from_opp else opp_ids
        alt = run_projection(tuple(new_me), tuple(new_opp), preset, window, as_of, games_key,
                             sat_key, CODE_VERSION, yahoo_teams)
        a_sum = alt["summary"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Result", a_sum["text"].replace("Projected ", ""),
                  f"was {summary['text'].replace('Projected ', '')}", delta_color="off")
        m2.metric("Expected categories", a_sum["expected_wins"],
                  round(a_sum["expected_wins"] - summary["expected_wins"], 1))
        m3.metric("Starts left this week", remaining_starts(alt),
                  remaining_starts(alt) - remaining_starts(result))

        rows = []
        for before, after in zip(result["categories"], alt["categories"]):
            rows.append({
                "Category": after["category"],
                "Me now": fmt(before["me"], before["is_pct"]),
                "Me with move": fmt(after["me"], after["is_pct"]),
                "Opponent": fmt(after["opponent"], after["is_pct"]),
                "Win chance": f"{before['win_prob']:.0%} → {after['win_prob']:.0%}",
                "Change": f"{(after['win_prob'] - before['win_prob']) * 100:+.0f} pts",
                "Projected winner": WINNER_TEXT[after["winner"]],
            })
        st.dataframe(styled_winner(pd.DataFrame(rows), [r["winner"] for r in alt["categories"]],
                                   "Projected winner"), hide_index=True, width="stretch")
        st.caption("Added players play all their team's remaining games unless they're Out."
                   + (" Trade with your opponent: they get the players you give."
                      if from_opp else ""))

        horizon = st.radio("Over", list(HORIZONS), format_func=HORIZONS.get, horizontal=True,
                           key="wi_horizon")
        b_now, real = vs_league(me_ids, horizon)
        b_alt, _ = vs_league(new_me, horizon)
        st.markdown(f"**Against {league_name}**" if real else "**Against a typical league**")
        approx = "" if real else "~"
        l1, l2, l3 = st.columns(3)
        l1.metric(f"Rank of {b_alt['league_size']}", f"{approx}{b_alt['rank']:g}",
                  f"was {approx}{b_now['rank']:g}", delta_color="off")
        l2.metric("Matchups you'd win", f"{b_alt['matchup_win_pct']:.0%}",
                  f"{(b_alt['matchup_win_pct'] - b_now['matchup_win_pct']) * 100:+.0f} pts")
        l3.metric("Categories per matchup" if real else "Categories vs a typical team",
                  b_alt["expected_cats"],
                  round(b_alt["expected_cats"] - b_now["expected_cats"], 1))
        st.dataframe(pd.DataFrame([{
            "Category": a["category"],
            "Now": fmt(n["me"], n["is_pct"]),
            "With move": fmt(a["me"], a["is_pct"]),
            "Total change": f"{a['me'] - n['me']:+.3f}" if n["is_pct"] else f"{a['me'] - n['me']:+.0f}",
            "Better than (teams)": f"{n['beats_pct']:.0%} → {a['beats_pct']:.0%}",
        } for n, a in zip(b_now["categories"], b_alt["categories"])]),
            hide_index=True, width="stretch")
        st.caption(f"Now / With move = your team's projected totals {HORIZON_SPANS[horizon]} "
                   f"({league_source(real, horizon)} × games, at most 10 a day). Better than = "
                   + ("share of the other teams in your league" if real else
                      "share of the simulated league's teams")
                   + " you'd beat in that category."
                   + (" Injured players count at their averages, as if healthy."
                      if horizon == "season" else ""))

with tab_league:
    league_horizon = st.radio("Over", list(HORIZONS), format_func=HORIZONS.get, horizontal=True,
                              key="league_horizon")
    span = HORIZON_SPANS[league_horizon]
    bench_res, real = vs_league(me_ids, league_horizon)
    how = (f"every team projected the same way ({league_source(real, league_horizon)} × games "
           f"{span}, at most 10 a day)")
    st.caption(f"Your team against the other teams in {league_name} instead of just your "
               f"opponent: their current Yahoo rosters, {how}." if real else
               "Your team against a typical 12-team league instead of just your opponent: "
               f"100 simulated drafts of the best players, {how}.")
    b1, b2, b3 = st.columns(3)
    if real:
        b1.metric(f"Rank of {bench_res['league_size']}", bench_res["rank"])
        b2.metric("Matchups you'd win", f"{bench_res['matchup_win_pct']:.0%}",
                  f"vs {bench_res['league_size'] - 1} teams", delta_color="off")
        b3.metric("Categories per matchup", bench_res["expected_cats"])
    else:
        b1.metric(f"Rank of {bench_res['league_size']}", f"~{bench_res['rank']:g}",
                  f"range {bench_res['rank_best']}–{bench_res['rank_worst']}", delta_color="off")
        b2.metric("Matchups you'd win", f"{bench_res['matchup_win_pct']:.0%}")
        b3.metric("Categories vs a typical team", bench_res["expected_cats"])

    def strength(beats: float) -> str:
        return "Strong" if beats >= 0.7 else "Weak" if beats <= 0.3 else "Average"

    levels = [strength(c["beats_pct"]) for c in bench_res["categories"]]
    st.dataframe(pd.DataFrame([{
        "Category": c["category"],
        "You": fmt(c["me"], c["is_pct"]),
        ("League median" if real else "Typical team"): fmt(c["typical"], c["is_pct"]),
        **({"Rank": f"{c['rank']} of {bench_res['league_size']}"} if real else
           {"Better than": f"{c['beats_pct']:.0%} of teams"}),
        "": level,
    } for c, level in zip(bench_res["categories"], levels)]).style.apply(
        lambda col: [f"color: {WINNER_COLORS[{'Strong': 'me', 'Weak': 'opponent'}.get(v, 'toss-up')]};"
                     " font-weight: 600" for v in col], subset=[""]),
        hide_index=True, width="stretch")
    st.caption(f"Games {span}: you {bench_res['games']['me']}, "
               + ("league median" if real else "typical team")
               + f" {bench_res['games']['typical']:g}. "
               + ("Out players count as 0" if league_horizon == "week" else
                  "Injured players count at their averages, as if healthy")
               + "; the Plays overrides aren't applied here.")

    if real:
        st.markdown("**Projected standings**")
        others = bench_res["league_size"] - 1
        st.dataframe(pd.DataFrame([{
            "": i,
            "Team": t["name"],
            f"Matchups won (of {others})": f"{t['matchups_won']:g}",
            "Categories per matchup": t["expected_cats"],
            "Games": t["games"],
        } for i, t in enumerate(bench_res["teams"], 1)]).style.apply(
            lambda row: ["font-weight: 700" if row["Team"] == "You" else ""] * len(row), axis=1),
            hide_index=True, width="stretch")
        st.caption(f"Every team against each of the other {others}, once, with the same "
                   "projection: not your real schedule. You = your roster as it is above.")

with tab_players:
    all_stats = st.toggle("Show all stats")
    if all_stats:
        view = st.radio("Stats", ["so far", "projected", "rest"], horizontal=True,
                        format_func={"so far": "So far", "projected": "Whole week (projected)",
                                     "rest": "Rest of week"}.get)

    def stat_cells(p: dict) -> dict:
        if not all_stats:
            return {"PTS so far": round(p["current"]["pts"]),
                    "PTS projected": round(p["current"]["pts"] + p["projected_rest"]["pts"])}
        t = {"so far": p["current"], "rest": p["projected_rest"],
             "projected": {s: p["current"][s] + p["projected_rest"][s] for s in p["current"]}}[view]
        cells = {}
        for cat in settings.categories:
            if cat.is_pct:
                cells[cat.name] = (f"{t[cat.made]:.0f}/{t[cat.attempted]:.0f} "
                                   f"({fmt(cat.value(t), True)})" if t[cat.attempted] else "–")
            else:
                cells[cat.name] = round(cat.value(t)) if view == "so far" else round(cat.value(t), 1)
        return cells

    for side, title in (("me", "My team"), ("opponent", "Opponent")):
        st.markdown(f"**{title}**")
        st.dataframe(pd.DataFrame([{
            "Player": p["name"],
            "Team": p["team"],
            "Status": p["injury"] or "",
            "Games counted": p["games_played"],
            "Plays (of left)": f"{p['games_assumed']} of {p['team_games_left']}",
            "Games to count": p["games_remaining"],
            "Sat (not counted)": p["games_benched"],
            "Stats from": ("Yahoo projection" if p["avg_source"] in YAHOO_WINDOWS else
                           f"{WINDOW_LABELS.get(p['avg_source'], 'none')} ({p['avg_games']}g)"),
            **stat_cells(p),
        } for p in result["teams"][side]["players"]]), hide_index=True, width="stretch")
    st.caption("Sat = games on days when more than 10 of the team's players played; the ones "
               "with the fewest minutes are assumed to sit, so those games don't count.")
