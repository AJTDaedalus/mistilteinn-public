"""Why a build scores what it scores — assembled, never re-derived.

DESIGN §4:

> A build's explanation is assembled from its own contribution log (which the kernel emits,
> exactly as `explain.py` does today), the retrieved simulated runs, and set/talent text from
> Postgres — and **every number in the answer cites the run or contribution it came from**.

That last clause is the whole design. An explanation that computes anything of its own is a
second implementation of the damage chain, which DESIGN §1 A6 forbids and which would be free
to disagree with the first. So nothing here multiplies, scales, or derives. It **groups,
joins and orders** numbers that already exist, and every one of them arrives carrying its
provenance.

## What "cites" means concretely

Three sources, and a number may come from exactly one:

- a **contribution** — recorded by `ContributionLog.add` on the same pass that registered it
  into the DAG, so the graph and the account cannot drift;
- a **simulated run** — retrieved by `sim_retrieval`, and carrying its own measured
  divergence, because §3's rule reaches here too: a *retrieved* number must say what it was
  retrieved from and how far that neighbour was;
- the **catalogue** — a set affix's own published text out of Postgres, which is description
  rather than arithmetic and is never the source of a value.

Anything that cannot be tied to one of those is reported in `uncited` rather than rendered
anyway. A confident sentence with nothing behind it is the failure mode this repo has spent
every chunk avoiding, and an explanation is the one place it would be least visible.

## The sum that is not your ATK

`StatAccount.sum_of_parts` is the **arithmetic sum of the recorded contributions**, not the
DAG's answer, and it is named that way so nobody reads it as a total. They agree for an
additive pool and deliberately do not for `base * (1 + pct) + flat` — the point
`ContributionLog.explain` already makes. The damage chain explains its own structure; this
lists the inputs to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.formula.genshin.tags import SRC_ARTIFACT_SET

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from app.formula.genshin.explain import Contribution
    from app.services.sim_retrieval import Retrieval

#: Quantities listed before the rest, in this order, because an account that opens with
#: `character_level` buries the thing the reader came for. Everything not named here follows,
#: alphabetically, so the ordering is total rather than "these first and then whatever".
_HEADLINE_ORDER: tuple[str, ...] = (
    "atk", "atk_pct", "flat_atk", "base_atk",
    "crit_rate", "crit_dmg",
    "elemental_mastery", "energy_recharge",
    "dmg_bonus",
)


@dataclass(frozen=True, slots=True)
class StatAccount:
    """One quantity and every contribution recorded against it."""

    quantity: str
    parts: tuple[Contribution, ...]

    @property
    def sum_of_parts(self) -> float:
        """The **arithmetic sum of the parts**, which is not necessarily the stat.

        Named for what it is. An additive pool agrees with the DAG; `base * (1 + pct) + flat`
        does not, and a field called `total` would invite a reader to believe otherwise.
        """
        return sum(part.value for part in self.parts)

    @property
    def sources(self) -> tuple[str, ...]:
        """Which kinds of thing fed this quantity, in first-seen order."""
        seen: dict[str, None] = {}
        for part in self.parts:
            seen.setdefault(part.source, None)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class SetEffectNote:
    """A set bonus that applied, in the catalogue's own words.

    `description` is published text, not a sentence composed here. Writing the effect from
    memory is what this repo forbids everywhere else, and an explanation is exactly where a
    fluent paraphrase would be least likely to be checked.
    """

    #: The note the contribution carried — e.g. `"Blizzard Strayer 4pc"`.
    note: str
    #: `None` when the catalogue has no text for it. Not an empty string: "the catalogue is
    #: silent" and "the catalogue says nothing applies" are different claims.
    description: str | None
    contributions: tuple[Contribution, ...]


@dataclass(frozen=True, slots=True)
class SimulationNote:
    """What the retrieved run contributes, and how far it was from this build."""

    matched_bucket: int
    requested_bucket: int
    bucket_distance: int
    is_exact_bucket: bool
    dps_mean: float | None
    #: Present whenever the corpus held an immediate neighbour to measure against. See
    #: `sim_retrieval`: this is *"the fastest the answer is moving nearby"*, a lower bound on
    #: the uncertainty and not a ceiling on it.
    divergence_pct: float | None
    noise_floor: float | None
    exceeds_noise: bool | None

    @property
    def caveat(self) -> str:
        """One sentence a reader must not be able to miss.

        Stated even for a distance-zero match, because an exact *key* is not an exact
        *answer* — `docs/RESEARCH_er_bucketing.md` measured the steepest bucket at 13.3 %
        wide, and a build sits somewhere inside its bucket rather than at the point that was
        simulated.
        """
        where = (
            f"bucket {self.matched_bucket}"
            if self.is_exact_bucket
            else f"bucket {self.matched_bucket}, {self.bucket_distance} away from "
            f"{self.requested_bucket}"
        )
        if self.divergence_pct is None:
            return (
                f"Simulated at {where}. The corpus holds no neighbouring bucket, so how much "
                f"that approximation is worth here has not been measured."
            )
        return (
            f"Simulated at {where}. The nearest cached bucket differs by "
            f"{self.divergence_pct:+.1f}%, which is a lower bound on the approximation — the "
            f"build sits somewhere inside its bucket, not at the point that was simulated."
        )


@dataclass(frozen=True, slots=True)
class Uncited:
    """Something the explanation could not attribute, reported rather than dropped."""

    what: str
    why: str


@dataclass(frozen=True, slots=True)
class BuildExplanation:
    """One build's account of itself."""

    stats: tuple[StatAccount, ...]
    set_effects: tuple[SetEffectNote, ...]
    simulation: SimulationNote | None
    uncited: tuple[Uncited, ...]

    def account_for(self, quantity: str) -> StatAccount | None:
        """One quantity's account, or None if nothing was recorded against it."""
        return next((s for s in self.stats if s.quantity == quantity), None)


def _ordered(quantity: str) -> tuple[int, str]:
    """Sort key: headline quantities in their stated order, then everything else by name."""
    try:
        return (_HEADLINE_ORDER.index(quantity), "")
    except ValueError:
        return (len(_HEADLINE_ORDER), quantity)


def explain(
    contributions: Sequence[Contribution],
    *,
    set_descriptions: Mapping[str, str] | None = None,
    retrieval: Retrieval | None = None,
) -> BuildExplanation:
    """Assemble a build's explanation from what is already known about it.

    `set_descriptions` maps a set contribution's `note` to the catalogue's published text.
    A note with no entry is not an error — it is an `Uncited` line, because the alternative
    is a set effect shown with an invented description or with none and no comment.

    `retrieval` is what `sim_retrieval.retrieve` returned, or None when the build was scored
    without one.
    """
    descriptions = dict(set_descriptions or {})

    by_quantity: dict[str, list[Contribution]] = {}
    for part in contributions:
        by_quantity.setdefault(part.quantity, []).append(part)

    stats = tuple(
        StatAccount(quantity=quantity, parts=tuple(parts))
        for quantity, parts in sorted(by_quantity.items(), key=lambda kv: _ordered(kv[0]))
    )

    uncited: list[Uncited] = []
    set_parts: dict[str, list[Contribution]] = {}
    for part in contributions:
        if part.source != SRC_ARTIFACT_SET:
            continue
        if not part.note:
            # A set bonus with no note cannot be shown to a user at all: "artifact_set +0.15"
            # names neither which set nor which threshold, and there are five pieces to change.
            uncited.append(
                Uncited(
                    what=f"{part.quantity} {part.value:+g} from a set bonus",
                    why="the contribution carries no note, so which set and how many pieces "
                    "is not recoverable from it",
                )
            )
            continue
        set_parts.setdefault(part.note, []).append(part)

    set_effects = []
    for note, parts in sorted(set_parts.items()):
        description = descriptions.get(note)
        if description is None:
            uncited.append(
                Uncited(
                    what=note,
                    why="the catalogue has no published text for this set bonus, so its "
                    "effect is shown as numbers without the words that explain them",
                )
            )
        set_effects.append(
            SetEffectNote(note=note, description=description, contributions=tuple(parts))
        )

    return BuildExplanation(
        stats=stats,
        set_effects=tuple(set_effects),
        simulation=_simulation_note(retrieval),
        uncited=tuple(uncited),
    )


def _simulation_note(retrieval: Retrieval | None) -> SimulationNote | None:
    if retrieval is None:
        return None
    divergence = retrieval.divergence
    return SimulationNote(
        matched_bucket=retrieval.matched_bucket,
        requested_bucket=retrieval.requested_bucket,
        bucket_distance=retrieval.bucket_distance,
        is_exact_bucket=retrieval.is_exact_bucket,
        dps_mean=retrieval.run.dps_mean,
        divergence_pct=None if divergence is None else divergence.dps_delta_pct,
        noise_floor=None if divergence is None else divergence.noise_floor,
        exceeds_noise=None if divergence is None else divergence.exceeds_noise,
    )


@dataclass(frozen=True, slots=True)
class StatDifference:
    """One quantity that differs between two builds, and by how much."""

    quantity: str
    left: float
    right: float
    #: Contributions present on the right and not the left, and vice versa. These are what a
    #: user acts on — "you gained Blizzard Strayer 4pc" is actionable where "+8% crit" is not.
    gained: tuple[Contribution, ...]
    lost: tuple[Contribution, ...]

    @property
    def delta(self) -> float:
        """Right minus left, in the quantity's own units."""
        return self.right - self.left


@dataclass(frozen=True, slots=True)
class BuildComparison:
    """Why one build differs from another, largest difference first."""

    differences: tuple[StatDifference, ...]
    #: Quantities recorded identically in both. Reported so "what changed" has a denominator:
    #: two builds differing in one stat out of twenty is a different claim from two builds
    #: differing in one out of two.
    unchanged: tuple[str, ...]


def compare(left: Sequence[Contribution], right: Sequence[Contribution]) -> BuildComparison:
    """What differs between two builds' contribution logs.

    "Why is this better" is a diff of two accounts, not a new calculation — so this compares
    what was recorded and never re-scores anything.

    Ordered by the **relative** size of the difference rather than the absolute one: a
    quantity is only comparable with itself, and sorting `flat_atk +311` above `crit_dmg
    +0.20` would rank builds by which stats happen to be big numbers.
    """
    left_by = _sum_by_quantity(left)
    right_by = _sum_by_quantity(right)
    left_parts = _parts_by_quantity(left)
    right_parts = _parts_by_quantity(right)

    differences: list[StatDifference] = []
    unchanged: list[str] = []
    for quantity in sorted(set(left_by) | set(right_by), key=_ordered):
        a, b = left_by.get(quantity, 0.0), right_by.get(quantity, 0.0)
        if a == b and _keys(left_parts.get(quantity, ())) == _keys(right_parts.get(quantity, ())):
            unchanged.append(quantity)
            continue
        before = {_key(p): p for p in left_parts.get(quantity, ())}
        after = {_key(p): p for p in right_parts.get(quantity, ())}
        differences.append(
            StatDifference(
                quantity=quantity,
                left=a,
                right=b,
                gained=tuple(p for k, p in after.items() if k not in before),
                lost=tuple(p for k, p in before.items() if k not in after),
            )
        )

    differences.sort(key=_magnitude, reverse=True)
    return BuildComparison(differences=tuple(differences), unchanged=tuple(unchanged))


def _magnitude(difference: StatDifference) -> float:
    """Relative change, so quantities in different units can be ranked against each other.

    A denominator of zero means the quantity appeared from nothing, which is as large a change
    as there is — `inf` rather than a guard that would silently sort it last.
    """
    base = abs(difference.left)
    if base == 0.0:
        return float("inf") if difference.delta != 0.0 else 0.0
    return abs(difference.delta) / base


def _key(contribution: Contribution) -> tuple[str, str, str, float]:
    """What makes two contributions the same contribution, for diffing purposes."""
    return (
        contribution.quantity,
        contribution.source,
        contribution.note,
        contribution.value,
    )


def _keys(parts: Iterable[Contribution]) -> frozenset[tuple[str, str, str, float]]:
    return frozenset(_key(p) for p in parts)


def _sum_by_quantity(contributions: Iterable[Contribution]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for part in contributions:
        totals[part.quantity] = totals.get(part.quantity, 0.0) + part.value
    return totals


def _parts_by_quantity(
    contributions: Iterable[Contribution],
) -> dict[str, list[Contribution]]:
    parts: dict[str, list[Contribution]] = {}
    for part in contributions:
        parts.setdefault(part.quantity, []).append(part)
    return parts
