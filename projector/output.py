"""Render a projection result (the dict from projection.project_matchup) as text."""
from __future__ import annotations

WINNER_LABEL = {"me": "me", "opponent": "opponent", "toss-up": "TOSS-UP"}


def fmt(value: float, is_pct: bool) -> str:
    return f"{value:.3f}".lstrip("0") if is_pct else f"{value:.0f}"


def render_table(result: dict) -> str:
    header = ("category", "me", "opponent", "projected winner", "margin %", "win %")
    rows = [(r["category"], fmt(r["me"], r["is_pct"]), fmt(r["opponent"], r["is_pct"]),
             WINNER_LABEL[r["winner"]], f"{r['margin_pct']:.1f}", f"{r['win_prob']:.0%}")
            for r in result["categories"]]
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]

    def line(cells):
        return " | ".join(str(c).ljust(w) if i in (0, 3) else str(c).rjust(w)
                          for i, (c, w) in enumerate(zip(cells, widths)))

    out = [f"{result['league']} · week {result['week']['start']} to {result['week']['end']}"
           f" · as of {result['as_of']} · window: {result['window']}", "",
           line(header), "-+-".join("-" * w for w in widths)]
    out += [line(r) for r in rows]
    out += ["", f"{result['summary']['text']} (expected {result['summary']['expected_wins']} categories)"]
    return "\n".join(out)


def render_players(result: dict) -> str:
    out = []
    for side in ("me", "opponent"):
        out += ["", f"{side.upper()}",
                f"  {'player':<26} {'team':<5} {'avg from':<16} {'played':>6} {'left':>4} {'bench':>5}  note"]
        for p in result["teams"][side]["players"]:
            source = f"{p['avg_source']} ({p['avg_games']}g)" if p["avg_source"] else "no data"
            note = p["injury"] or ""
            out.append(f"  {p['name']:<26} {p['team']:<5} {source:<16} {p['games_played']:>6}"
                       f" {p['games_remaining']:>4} {p['games_benched']:>5}  {note}")
    return "\n".join(out)
