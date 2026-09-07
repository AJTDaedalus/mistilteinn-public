"""What it costs to take a character or weapon from where it is to where you want it.

Four bills, kept separate because the owner asked to see them separately: character levels,
character ascension, talents, and the weapon. Each is priced in materials and mora; resin is
`resin.py`'s job and is layered on afterwards.

## Ascending without levelling

Level and ascension phase are **independent targets**, which is the whole point of the
"stay at 80/90" case. The only rules are the game's: a level may not exceed the cap its phase
unlocks (`AvatarPromoteExcelConfigData.unlockMaxLevel`, the 20/40/50/60/70/80/90 ladder), and
neither target may run backwards. Asking for phase 6 at level 80 is legal and costs the
ascension bill with no EXP at all.

## EXP is a pool, and its denominations do not craft into each other

Hero's Wit, Adventurer's Experience and Wanderer's Advice all feed the same EXP bar, and so do
the three Enhancement Ores — but **no recipe converts one into another**, which is checked
rather than assumed: `CombineExcelConfigData` holds no recipe touching any of the six, and
each is its own craft root. So stock is counted as *total EXP held*, not per denomination, and
the shortfall is expressed in books largest-first. Every other material in the planner is
counted per item, because every other material really is per item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.services.planner.economy import Economy, ExpItem

#: The highest talent level materials exist for. 11-15 come free from C3 and C5 and have no
#: bill at all — the planner says so rather than rendering an empty list.
MAX_TALENT_LEVEL = 10


class PlanError(ValueError):
    """A requested plan is not a state the game has."""


@dataclass(frozen=True)
class Progress:
    """Where something is now, or where it is going."""

    level: int
    ascension: int


@dataclass
class ExpBill:
    """The EXP half of levelling, in points and then in books."""

    exp_required: int = 0
    exp_owned: int = 0
    #: `[(material id, count)]`, largest denomination first, covering the shortfall. The last
    #: entry is rounded **up**: you cannot feed a fraction of a book, and rounding down would
    #: leave the plan a level short.
    books: list[tuple[int, int]] = field(default_factory=list)
    #: Mora charged for feeding that EXP, or `None` while the divisor is uncurated. `None`
    #: is not zero and the UI must not render it as free.
    mora: int | None = None

    @property
    def exp_short(self) -> int:
        """EXP still to find after what is already held."""
        return max(0, self.exp_required - self.exp_owned)


def validate(progress: Progress, caps: Mapping[int, int], *, what: str) -> None:
    """Reject a level/phase pair the game cannot produce."""
    if progress.ascension not in caps:
        msg = f"{what} ascension {progress.ascension} is outside 0-{max(caps)}"
        raise PlanError(msg)
    cap = caps[progress.ascension]
    if not 1 <= progress.level <= cap:
        msg = (
            f"{what} level {progress.level} is outside 1-{cap}, which is what ascension "
            f"phase {progress.ascension} unlocks"
        )
        raise PlanError(msg)


def validate_move(current: Progress, target: Progress, caps: Mapping[int, int], what: str) -> None:
    """Reject a plan that runs backwards, and both endpoints while we are here."""
    validate(current, caps, what=f"current {what}")
    validate(target, caps, what=f"target {what}")
    if target.level < current.level or target.ascension < current.ascension:
        msg = (
            f"{what} target {target.level}/{target.ascension} is behind the current "
            f"{current.level}/{current.ascension}; the planner does not un-level things"
        )
        raise PlanError(msg)


def character_exp_between(curve: Sequence[int], start: int, end: int) -> int:
    """EXP to go from character level `start` to `end`.

    `level_exp` is **per level, not cumulative**: entry `i` is the cost of `i+1` to `i+2`. The
    first 89 sum to 8,362,650, the published total to level 90, which is the check that
    settled the indexing.
    """
    if end <= start:
        return 0
    return sum(curve[start - 1 : end - 1])


def weapon_exp_between(curve: Mapping[str, int], start: int, end: int) -> int:
    """EXP to go from weapon level `start` to `end`.

    `xp_requirements` is keyed by the level being *left*, so this reads keys `start..end-1`.
    """
    return sum(int(curve.get(str(level), 0)) for level in range(start, end))


def books_for(exp: int, items: Sequence[ExpItem]) -> list[tuple[int, int]]:
    """Cover `exp` with the fewest books, largest denomination first.

    The remainder is covered by rounding the **smallest** denomination up, because a partial
    book does not exist and the leftover EXP is simply wasted — which is what happens in game.
    """
    if exp <= 0:
        return []
    ordered = sorted(items, key=lambda item: item.exp, reverse=True)
    out: list[tuple[int, int]] = []
    remaining = exp
    for index, item in enumerate(ordered):
        if remaining <= 0:
            break
        is_last = index == len(ordered) - 1
        count = -(-remaining // item.exp) if is_last else remaining // item.exp
        if count:
            out.append((item.id, count))
            remaining -= count * item.exp
    return out


def exp_bill(
    economy: Economy,
    required: int,
    owned_counts: Mapping[int, int],
    target: str,
) -> ExpBill:
    """Turn an EXP requirement into books, after crediting the stock already held.

    Stock is credited as **total EXP**, summed across denominations, because they are
    interchangeable as fuel even though they cannot be crafted into one another.
    """
    items = (
        economy.character_exp_items if target == "character" else economy.weapon_exp_items
    )
    owned_exp = sum(owned_counts.get(item.id, 0) * item.exp for item in items)
    bill = ExpBill(exp_required=required, exp_owned=owned_exp)
    bill.books = books_for(bill.exp_short, items)
    rate = economy.mora_per_exp(target)
    bill.mora = None if rate is None else round(required * rate)
    return bill


def ascension_bill(
    costs: Mapping[int, tuple[int, Sequence[Mapping[str, int]]]],
    current: int,
    target: int,
    *,
    what: str = "this",
) -> tuple[dict[int, int], int]:
    """`({material id: count}, mora)` for the phases strictly after `current` up to `target`.

    Phase `n`'s row is the cost of *reaching* phase `n`, so a character already at phase 2
    going to 4 pays rows 3 and 4.

    **A phase with no cost row raises.** It used to be skipped, which priced it at zero — and
    that is reachable, not theoretical: `weapon_level_caps` is the 5-star ladder for every
    weapon, but a 1-star weapon publishes only four phases, so planning one to 90/6 charged
    nothing for phases 5 and 6 and billed ore for levels it cannot reach. A skipped check is
    never a pass, and neither is a skipped bill.
    """
    items: dict[int, int] = {}
    mora = 0
    for phase in range(current + 1, target + 1):
        row = costs.get(phase)
        if row is None:
            # **An empty table is a different fault from a missing phase, and saying so is the
            # whole point of this branch.** Both used to produce "X has no ascension phase 1",
            # which reads as a fact about X — and it was reported that way: *"Albedo has no
            # ascension phase 1"*, about a character that publishes all six. What had actually
            # happened is that the planner's cost tables were created by a migration and never
            # seeded, so *every* character answered this and the sentence named whichever one
            # the user happened to pick.
            #
            # The rest of the app cannot show the difference either: a plan for an unseeded
            # database and a plan for a genuinely short ladder both come back as one 422.
            msg = (
                f"No ascension costs are seeded at all, so {what} cannot be priced. "
                f"The catalogue needs re-seeding: `python -m scripts.seed_db --version <pin>`."
            ) if not costs else (
                f"{what} has no ascension phase {phase} — it publishes "
                f"{sorted(costs)}. Pick a target within that."
            )
            raise PlanError(msg)
        phase_mora, entries = row
        mora += phase_mora
        for entry in entries:
            material_id = int(entry["id"])
            items[material_id] = items.get(material_id, 0) + int(entry["count"])
    return items, mora


def talent_bill(
    costs: Mapping[int, tuple[int, Sequence[Mapping[str, int]]]],
    current: int,
    target: int,
) -> tuple[dict[int, int], int]:
    """`({material id: count}, mora)` for taking one talent from `current` to `target`.

    Row `n` is the cost of `n` -> `n+1`, so levels `current..target-1` are charged. A target
    above 10 charges nothing beyond 10, because constellations supply those levels free.
    """
    target = min(target, MAX_TALENT_LEVEL)
    items: dict[int, int] = {}
    mora = 0
    for level in range(current, target):
        row = costs.get(level)
        if row is None:
            continue
        level_mora, entries = row
        mora += level_mora
        for entry in entries:
            material_id = int(entry["id"])
            items[material_id] = items.get(material_id, 0) + int(entry["count"])
    return items, mora
