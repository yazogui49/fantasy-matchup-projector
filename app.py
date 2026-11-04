"""Streamlit UI: pick both rosters, choose a stats window, see the projected matchup.
Run with: .venv/bin/streamlit run app.py"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

from projector.benchmark import benchmark
from projector.config import ROOT
from projector.league import PRESETS
from projector.output import fmt
from projector.players import load_players
from projector.projection import project_matchup
from projector.schedule import fantasy_week, nba_today, remaining_games

LEGACY_ROSTERS_FILE = ROOT / "data" / "rosters.json"
WINDOW_LABELS = {
    "season": "This season",
    "last30": "Last 30 days",
    "lastseason": "Last season",
    "last14": "Last 14 days",
    "last7": "Last 7 days",
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
                   sat: tuple[tuple[str, str, tuple[str, ...]], ...], code: str) -> dict:
    directory = players_by_id()
    overrides = dict(games)

    def roster(ids):
        return [{**directory[i], "games_override": overrides.get(i)} for i in ids]

    sat_by_side: dict[str, dict[str, list[str]]] = {}
    for side, day, ids in sat:
        sat_by_side.setdefault(side, {})[day] = list(ids)
    return project_matchup(roster(me), roster(opp), PRESETS[preset], window=window,
                           today=as_of, sat=sat_by_side)


@st.cache_data(ttl=3600, show_spinner="Simulating a league…")
def run_benchmark(me: tuple[str, ...], preset: str, week_start: str, code: str) -> dict:
    directory = players_by_id()
    return benchmark([directory[i] for i in me], directory, PRESETS[preset],
                     date.fromisoformat(week_start))


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
    if "me" in q or "opp" in q:
        return {"me": q.get("me", "").split(","), "opponent": q.get("opp", "").split(","),
                "window": q.get("w", "season"), "games": decode_games(q.get("g", "")),
                "sat": decode_sat(q.get("s", ""))}
    try:  # one-time carry-over of rosters saved by earlier local versions
        return json.loads(LEGACY_ROSTERS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(state: dict) -> None:
    this_monday = fantasy_week(nba_today())[0].isoformat()
    games = {w: g for w, g in state["games"].items() if w >= this_monday}
    sat = {side: {d: ids for d, ids in days.items() if d >= this_monday}
           for side, days in st.session_state.get("sat", {}).items()}
    params = {"me": ",".join(state["me"]), "opp": ",".join(state["opponent"]),
              "w": state["window"], "g": encode_games(games), "s": encode_sat(sat)}
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

with st.sidebar:
    st.header("Settings")
    preset = st.selectbox("League settings", list(PRESETS), format_func=lambda k: PRESETS[k].name)
    week = st.radio("Week", ["this", "next"], horizontal=True,
                    format_func={"this": "This week", "next": "Next week"}.get)
    window = st.radio("Project using", list(WINDOW_LABELS), key="window",
                      format_func=WINDOW_LABELS.get)
    with st.expander("Testing"):
        pretend = st.checkbox("Pretend it's another day")
        as_of = st.date_input("Date", value=nba_today()) if pretend else None

if week == "next":
    as_of = fantasy_week(nba_today())[1] + timedelta(days=1)  # next Monday morning
week_start = fantasy_week(as_of or nba_today())[0].isoformat()

st.title("🏀 Matchup Projector")
settings = PRESETS[preset]
roster_size = len(settings.starting_slots) + settings.bench + settings.il

left, right = st.columns(2)
for col, key, title in ((left, "me", "My team"), (right, "opponent", "Opponent")):
    with col:
        st.multiselect(title, list(directory), key=key, format_func=label,
                       max_selections=roster_size, placeholder="Type a name…")
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
                        CODE_VERSION)
summary = result["summary"]
WINNER_TEXT = {"me": "Me", "opponent": "Opponent", "toss-up": "Toss-up"}


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
           f" · using {WINDOW_LABELS[window].lower()} stats")

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
               "the player's real games in the chosen window. 40–60% counts as a toss-up.")

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
            "Open": d["open_slots"], "Sitting": ", ".join(d["benched"]),
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
    st.caption("Try a roster move and see the matchup with it. Your real roster isn't changed.")
    on_rosters = set(me_ids) | set(opp_ids)
    w1, w2 = st.columns(2)
    with w1:
        drops = st.multiselect("Drop", me_ids, format_func=label, key="wi_drop")
    with w2:
        adds = st.multiselect("Add", [i for i in directory if i not in on_rosters],
                              format_func=label, key="wi_add", placeholder="Type a name…")
    if not drops and not adds:
        st.info("Pick a player to add and/or one to drop.")
    else:
        new_me = [i for i in me_ids if i not in drops] + adds
        if len(new_me) > roster_size:
            st.warning(f"That's {len(new_me)} players, over your {roster_size}-man roster.")
        alt = run_projection(tuple(new_me), tuple(opp_ids), preset, window, as_of, games_key,
                             sat_key, CODE_VERSION)
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
        st.caption("Added players play all their team's remaining games unless they're Out.")

with tab_league:
    st.caption("Your team against a typical 12-team league instead of just your opponent: "
               "50 simulated drafts of the best players, everyone's week projected the same way "
               "(this season's averages × games this week, at most 10 a day). "
               "Your real league comes in once Yahoo access is approved.")
    bench_res = run_benchmark(tuple(me_ids), preset, week_start, CODE_VERSION)
    b1, b2, b3 = st.columns(3)
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
        "Typical team": fmt(c["typical"], c["is_pct"]),
        "Better than": f"{c['beats_pct']:.0%} of teams",
        "": level,
    } for c, level in zip(bench_res["categories"], levels)]).style.apply(
        lambda col: [f"color: {WINNER_COLORS[{'Strong': 'me', 'Weak': 'opponent'}.get(v, 'toss-up')]};"
                     " font-weight: 600" for v in col], subset=[""]),
        hide_index=True, width="stretch")
    st.caption(f"Games this week: you {bench_res['games']['me']}, typical team "
               f"{bench_res['games']['typical']:g}. Out players count as 0; the Plays overrides "
               "aren't applied here.")

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
            "Stats from": f"{WINDOW_LABELS.get(p['avg_source'], 'none')} ({p['avg_games']}g)",
            **stat_cells(p),
        } for p in result["teams"][side]["players"]]), hide_index=True, width="stretch")
    st.caption("Sat = games on days when more than 10 of the team's players played; the ones "
               "with the fewest minutes are assumed to sit, so those games don't count.")
