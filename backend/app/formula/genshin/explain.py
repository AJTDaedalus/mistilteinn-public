"""Attribution: what contributed to a number, and from where.

DESIGN §1 A6 requires that a damage figure be able to say *why* it is what it is. This is
the mechanism, and it is deliberately **not** a tag category.

## Why not a tag

Pando's `NodeRegistry.gather(query)` returns entries whose registration tag is a **subset of
the read context** — categories in a registration are *requirements*, not labels. Registering
ATK% as `{q: atk_pct, src: artifact}` therefore does not attribute it; it hides it, because a
read of `{q: atk_pct}` no longer matches. (That is the right behaviour for scope gating,
which is what the mechanism is for: `{q: dmg_bonus, scope: charged}` should only apply to
charged attacks.)

So attribution rides alongside the registry rather than inside the tag. `ContributionLog`
registers into the DAG *and* records provenance in one call, which means the two cannot drift:
there is no way to add a contribution to the graph without saying where it came from.

## What this is not

It is not a debug flag or a logging hook. The log is built on the same pass that builds the
graph, always, because an explanation you have to re-run the calculation to get is an
explanation nobody has when they need it — and because a second, "explaining" code path is
precisely the duplicated logic A6 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.formula.builder import const
from app.formula.genshin.tags import ALL_SOURCES, Q, stat_tag

if TYPE_CHECKING:
    from app.formula.tags import Tag
    from app.pando.calculator import NodeRegistry


@dataclass(frozen=True, slots=True)
class Contribution:
    """One value, and the account of where it came from.

    `note` is free text for the specific thing — `"Deepwood Memories 4pc"`, `"circlet main
    stat"`, `"ascension phase 6"` — because "artifact" alone does not tell a user which of
    five pieces to change.
    """

    quantity: str
    value: float
    source: str
    note: str = ""
    #: The tag it registered under, kept so a scope-gated contribution can be told from an
    #: unconditional one when reading the log back.
    tag: Tag | None = None

    def __str__(self) -> str:
        where = f"{self.source}: {self.note}" if self.note else self.source
        return f"{self.quantity} {self.value:+g} ({where})"


@dataclass
class ContributionLog:
    """Registers contributions into a DAG and records what each one was.

    One call site, two effects, on purpose: `add` is the only way this project puts a stat
    into the graph, so the graph and its explanation are built from the same statement and
    cannot disagree.
    """

    registry: NodeRegistry
    contributions: list[Contribution] = field(default_factory=list)

    def add(
        self,
        quantity: str,
        value: float,
        source: str,
        note: str = "",
        *,
        tag: Tag | None = None,
    ) -> None:
        """Register `value` under `quantity` (or `tag`) and record where it came from.

        A zero contributes nothing and is skipped — but it is skipped *silently and
        deliberately*, because a build that lists "ATK% +0 (artifact)" forty times is an
        explanation nobody reads.
        """
        if source not in ALL_SOURCES:
            msg = f"{source!r} is not a known contribution source. The list is {ALL_SOURCES}."
            raise ValueError(msg)
        if value == 0:
            return
        registration = tag if tag is not None else stat_tag(quantity)
        declared = registration.get(Q)
        if declared != quantity:
            # Otherwise the contribution registers into one pool while the account reports
            # another, and *both* the DAG total and the printed explanation look plausible
            # — the precise drift this class exists to make impossible.
            msg = (
                f"tag {registration} registers under {declared!r} but the contribution "
                f"says {quantity!r}. The graph and the account would disagree."
            )
            raise ValueError(msg)
        self.registry.register(registration, const(value))
        self.contributions.append(
            Contribution(
                quantity=quantity, value=value, source=source, note=note, tag=registration,
            ),
        )

    def for_quantity(self, quantity: str) -> list[Contribution]:
        """Everything recorded against one quantity, in registration order."""
        return [c for c in self.contributions if c.quantity == quantity]

    def explain(self, quantity: str) -> str:
        """A human-readable account of one stat: every contribution, and their sum.

        The sum here is the *arithmetic* of the recorded contributions, not the DAG's answer.
        They agree for an additive pool and deliberately do not for `base * (1 + pct) + flat`
        — which is why the damage chain (F.5) explains its own structure rather than leaving
        a reader to infer it from a list of numbers.
        """
        rows = self.for_quantity(quantity)
        if not rows:
            return f"{quantity}: nothing registered"
        lines = [f"  {row}" for row in rows]
        total = sum(row.value for row in rows)
        return "\n".join([f"{quantity}:", *lines, f"  = {total:g} (sum of contributions)"])
