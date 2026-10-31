"""League settings: scoring categories and roster slots."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Category:
    """A scoring category. Count categories sum `stat`; percentage categories are
    total `made` / total `attempted`, never an average of per-game percentages."""
    name: str
    stat: str | None = None
    made: str | None = None
    attempted: str | None = None
    higher_is_better: bool = True

    @property
    def is_pct(self) -> bool:
        return self.made is not None

    def value(self, totals: dict[str, float]) -> float:
        if self.is_pct:
            att = totals.get(self.attempted, 0)
            return totals.get(self.made, 0) / att if att else 0.0
        return totals.get(self.stat, 0)


# Which player positions can fill each slot (Yahoo-style slot names).
SLOT_ELIGIBILITY = {
    "PG": {"PG"}, "SG": {"SG"}, "G": {"PG", "SG"},
    "SF": {"SF"}, "PF": {"PF"}, "F": {"SF", "PF"},
    "C": {"C"}, "UTIL": {"PG", "SG", "SF", "PF", "C"},
}


@dataclass
class LeagueSettings:
    name: str
    categories: list[Category]
    starting_slots: list[str]
    bench: int = 0
    il: int = 0
    week_start: str = "monday"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


NINE_CAT = [
    Category("FG%", made="fgm", attempted="fga"),
    Category("FT%", made="ftm", attempted="fta"),
    Category("3PM", stat="fg3m"),
    Category("PTS", stat="pts"),
    Category("REB", stat="reb"),
    Category("AST", stat="ast"),
    Category("STL", stat="stl"),
    Category("BLK", stat="blk"),
    Category("TO", stat="tov", higher_is_better=False),
]

PRESETS = {
    "standard-9cat": LeagueSettings(
        name="Standard 9-cat",
        categories=NINE_CAT,
        starting_slots=["PG", "SG", "G", "G", "SF", "PF", "F", "F", "C", "C"],
        bench=2,
        il=2,
    ),
}
