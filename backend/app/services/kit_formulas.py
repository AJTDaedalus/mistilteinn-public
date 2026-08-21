"""Custom damage instances authored in a kit's ``formulas[]`` block.

A kit JSON's ``modifiers[]`` are *buffs* — they move a stat, and the snapshot
builder bakes them into ``BuildSnapshot.modifiers``. Its ``formulas[]`` are a
different animal: each one is an **extra damage instance** the agent emits when
a matching move executes (Ben's M2 fire hit on Special, Miyabi's frostburn break
on Basic, Burnice's afterburn). They are not buffs and no buff bucket can hold
them; before Task 21 (C3) nothing read the key at all, so all 21 of them were
authored, ZO-cited, and then silently dropped.

This module is the consumer. It owns:

* the **op grammar** for a formula's ``multiplier`` tree (``FORMULA_OPS``),
* the **resolution** of that tree to a literal basis-point multiplier, done once
  at snapshot-build time — mindscape and core level are both known there, which
  keeps the evaluator out of the optimizer's hot loop,
* the **shape validation** that `scripts/validate_kits.py` (L0) introspects, so a
  formula naming an op, read target, scope, or scaling stat the engine does not
  implement is a build failure rather than a silent zero.

Everything unknown raises. Returning 0 for an op we do not understand is the exact
failure mode this feature exists to kill.

**Naming.** The JSON key is ``scaling_stat``, but that name already means two other
things in this codebase (``Modifier.scaling_stat`` = the *bake basis* for a buff's
value; ``calculate_standard_damage(scaling_stat=…)`` = the resolved ATK *number*).
Here it means "the stat this damage instance scales off", so the dataclass field is
``damage_stat``. The JSON key is unchanged — the 21 authored entries and their ZO
citations already use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.enums import PotentialTag
from app.services.modifiers import AttackScope, potential_allows


def _potential_of(raw: dict[str, Any]) -> PotentialTag | None:
    """The Potential state a raw formula declares, or None for 'both'."""
    value = raw.get("potential")
    return PotentialTag(value) if value else None

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Grammar ──────────────────────────────────────────────────────────────────

# The state a formula may read. `core_level` is ZO's `char.core` (0–6), NOT
# fairy's `Build.core_skill_level` (0–5): ZO prepends a 0th core level to the
# 6-row coreStats table, so its per-core-level parameter tables (Miyabi's
# frostburn, Burnice's afterburn) carry 7 entries indexed 0–6. The ezod importer
# already records the offset the other way — `core_skill_level = clamp(core-1,0,5)`
# — so callers pass `core_skill_level + 1`. Getting this wrong reads one row low
# and understates the damage at every core tier.
FORMULA_READ_TARGETS: frozenset[str] = frozenset({"mindscape", "core_level"})

FORMULA_QUANTITIES: frozenset[str] = frozenset({"standard_dmg", "anom_buildup"})

# The stat a `standard_dmg` instance scales off. `atk` is the default when the
# JSON omits the key. `def` is Ben's M2; `anomaly_proficiency` is Alice's and
# Jane's M6 — those scale off AP, not ATK, and calculating them off ATK would be
# wrong by an order of magnitude in either direction depending on the build.
FORMULA_DAMAGE_STATS: frozenset[str] = frozenset({"atk", "def", "anomaly_proficiency"})

_SCOPES: dict[str, AttackScope] = {s.value: s for s in AttackScope}

MAX_MINDSCAPE = 6
MAX_CORE_LEVEL = 6  # ZO's `char.core` tops out at 6 — the 7th row of a core table
MIN_MINDSCAPE = 0
MIN_CORE_LEVEL = 1  # `core_skill_level` 0 (tier A) + 1 — the lowest ZO index a build reaches


class UnknownFormulaOpError(ValueError):
    """A formula names an op, read target, scope, quantity, or stat we do not implement.

    Always raised, never swallowed. A kit formula that cannot be evaluated is a
    curation or engine bug; degrading it to 0 damage reproduces the very defect
    (silently dead kit data) that the validation harness exists to detect.
    """


@dataclass(frozen=True)
class KitFormula:
    """One resolved custom damage instance, ready for the simulator to emit.

    ``multiplier`` is already evaluated against the build's mindscape and core
    level, so this is a plain value object: no op tree survives into the sim.
    """

    name: str
    quantity: str
    scope: AttackScope
    multiplier: int = 0  # basis points; `standard_dmg` only
    buildup: int = 0  # anomaly gauge; `anom_buildup` only
    element: str | None = None  # None → the emitting agent's own element
    damage_stat: str = "atk"
    # Which Potential state this instance belongs to (#90). Same three states and same
    # meaning as `Modifier.potential` and `Attack.potential`. A formula CAN be
    # Potential-gated -- Burnice's unlocked-only free Afterburn proc is one -- so
    # omitting the field here would have left `formulas[]` a silent hole in a rule that
    # otherwise claims every row states its state.
    potential: PotentialTag | None = None

    @property
    def is_inert(self) -> bool:
        """True when the formula resolves to nothing at this build's mindscape/core.

        An M6-gated instance on an M0 build resolves to multiplier 0. That is a
        correct evaluation, not a failure — the sim just has nothing to emit.
        """
        return self.multiplier == 0 and self.buildup == 0


# ── Evaluator ────────────────────────────────────────────────────────────────


def _eval_const(node: dict[str, Any], _state: dict[str, int]) -> int:
    return int(node["value"])


def _eval_read(node: dict[str, Any], state: dict[str, int]) -> int:
    q = node.get("q")
    if q not in FORMULA_READ_TARGETS:
        raise UnknownFormulaOpError(
            f"formula reads unknown state {q!r} (known: {', '.join(sorted(FORMULA_READ_TARGETS))})"
        )
    return state[q]


def _eval_cmp_ge(node: dict[str, Any], state: dict[str, int]) -> int:
    left = _eval(node["left"], state)
    right = _eval(node["right"], state)
    # No authored entry carries an `if_lt`, so "below the threshold" defaults to
    # 0 — an M6 instance on an M5 build contributes nothing.
    branch = "if_ge" if left >= right else "if_lt"
    return _eval(node.get(branch, 0), state)


def _eval_subscript(node: dict[str, Any], state: dict[str, int]) -> int:
    table = node["table"]
    index = _eval(node["index"], state)
    if not 0 <= index < len(table):
        raise UnknownFormulaOpError(
            f"formula subscript index {index} is outside its {len(table)}-entry table — "
            f"the table is authored for the wrong level range"
        )
    return int(table[index])


def _eval_sum(node: dict[str, Any], state: dict[str, int]) -> int:
    return sum(_eval(arg, state) for arg in node["args"])


# The op registry. `scripts/validate_kits.py` introspects this set, so an op used
# in a kit JSON but absent here fails L0 rather than blowing up at damage time.
FORMULA_OPS: dict[str, Callable[[dict[str, Any], dict[str, int]], int]] = {
    "const": _eval_const,
    "read": _eval_read,
    "cmp_ge": _eval_cmp_ge,
    "subscript": _eval_subscript,
    "sum": _eval_sum,
}


def _eval(node: Any, state: dict[str, int]) -> int:
    """Evaluate one node of a multiplier tree. Operands may be bare int literals."""
    if isinstance(node, bool):  # bool is an int subclass; never a valid operand
        raise UnknownFormulaOpError(f"formula operand {node!r} is a bool, not a multiplier")
    if isinstance(node, int):
        return node
    if not isinstance(node, dict):
        raise UnknownFormulaOpError(f"formula operand {node!r} is neither an int nor an op node")
    op = node.get("op")
    handler = FORMULA_OPS.get(op)  # type: ignore[arg-type]
    if handler is None:
        raise UnknownFormulaOpError(
            f"formula uses unknown op {op!r} (known: {', '.join(sorted(FORMULA_OPS))})"
        )
    return handler(node, state)


def evaluate_multiplier(node: Any, *, mindscape: int, core_level: int) -> int:
    """Resolve a formula's ``multiplier`` op-tree to a basis-point literal.

    ``core_level`` is ZO's 0–6 index (``Build.core_skill_level + 1``), not the 0–5
    tier stored on the build.
    """
    return _eval(node, {"mindscape": mindscape, "core_level": core_level})


def resolve_kit_formula(raw: dict[str, Any], *, mindscape: int, core_level: int) -> KitFormula:
    """Validate one raw ``formulas[]`` entry and resolve its multiplier.

    Raises ``UnknownFormulaOpError`` on anything the engine cannot execute.
    """
    name = raw.get("name", "")

    quantity = raw.get("quantity", "")
    if quantity not in FORMULA_QUANTITIES:
        raise UnknownFormulaOpError(
            f"formula {name!r} has unknown quantity {quantity!r} "
            f"(known: {', '.join(sorted(FORMULA_QUANTITIES))})"
        )

    raw_scope = raw.get("scope", "all")
    scope = _SCOPES.get(raw_scope)
    if scope is None:
        raise UnknownFormulaOpError(
            f"formula {name!r} has unknown scope {raw_scope!r} "
            f"(known: {', '.join(sorted(_SCOPES))})"
        )

    damage_stat = raw.get("scaling_stat") or "atk"
    if damage_stat not in FORMULA_DAMAGE_STATS:
        raise UnknownFormulaOpError(
            f"formula {name!r} scales off unknown stat {damage_stat!r} "
            f"(known: {', '.join(sorted(FORMULA_DAMAGE_STATS))})"
        )

    if quantity == "anom_buildup":
        # Buildup instances carry a flat gauge `value` and no multiplier tree.
        return KitFormula(
            name=name,
            quantity=quantity,
            scope=scope,
            buildup=int(raw.get("value", 0)),
            element=raw.get("element"),
            potential=_potential_of(raw),
        )

    if "multiplier" not in raw:
        raise UnknownFormulaOpError(
            f"formula {name!r} is a standard_dmg instance with no multiplier"
        )

    return KitFormula(
        name=name,
        quantity=quantity,
        scope=scope,
        multiplier=evaluate_multiplier(
            raw["multiplier"], mindscape=mindscape, core_level=core_level
        ),
        element=raw.get("element"),
        damage_stat=damage_stat,
        potential=_potential_of(raw),
    )


# The operand keys each op recurses into. Used only by the structural walk below;
# the evaluators above deliberately visit just the branch they take.
_OP_OPERANDS: dict[str, tuple[str, ...]] = {
    "const": (),
    "read": (),
    "cmp_ge": ("left", "right", "if_ge", "if_lt"),
    "subscript": ("index",),
    "sum": (),  # variadic — handled explicitly
}


def _walk(node: Any) -> None:
    """Structurally check every node of a multiplier tree, taking no branches.

    ``_eval`` only visits the subtree a ``cmp_ge`` actually selects, so evaluating
    at one mindscape can never prove the *other* branch is sound. L0 needs the
    whole tree checked, or a bad op in an untaken ``if_lt`` ships and only fails
    for the one user whose build reaches it.
    """
    if isinstance(node, bool):
        raise UnknownFormulaOpError(f"formula operand {node!r} is a bool, not a multiplier")
    if isinstance(node, int):
        return
    if not isinstance(node, dict):
        raise UnknownFormulaOpError(f"formula operand {node!r} is neither an int nor an op node")

    op = node.get("op")
    if op not in FORMULA_OPS:
        raise UnknownFormulaOpError(
            f"formula uses unknown op {op!r} (known: {', '.join(sorted(FORMULA_OPS))})"
        )
    if op == "read" and node.get("q") not in FORMULA_READ_TARGETS:
        raise UnknownFormulaOpError(
            f"formula reads unknown state {node.get('q')!r} "
            f"(known: {', '.join(sorted(FORMULA_READ_TARGETS))})"
        )
    if op == "sum":
        for arg in node["args"]:
            _walk(arg)
        return
    for key in _OP_OPERANDS[op]:
        if key in node:
            _walk(node[key])


def validate_kit_formula(raw: dict[str, Any]) -> None:
    """Assert a raw ``formulas[]`` entry is executable, whatever the build.

    The L0 harness's entry point. Two passes, because neither subsumes the other:

    * ``_walk`` checks the tree *structurally*, visiting both branches of every
      ``cmp_ge`` — evaluation only ever takes one, so a bad op in an untaken branch
      is invisible to any number of evaluations.
    * evaluation then runs the tree at **both ends of the build domain**. ``subscript``
      is the one op whose validity is value-dependent (its index comes from mindscape
      or core level), so a single sample point proves only that sample. A table
      authored for core levels 1-6 indexed by a 0-based read passes at the top and
      runs off the end at the bottom, or vice versa; checking both corners catches
      each. Everything between is bounded by them, since both read targets enter
      ``subscript`` monotonically.

    Raises ``UnknownFormulaOpError`` on anything unexecutable.
    """
    if raw.get("quantity") == "standard_dmg" and "multiplier" in raw:
        _walk(raw["multiplier"])
    resolve_kit_formula(raw, mindscape=MAX_MINDSCAPE, core_level=MAX_CORE_LEVEL)
    resolve_kit_formula(raw, mindscape=MIN_MINDSCAPE, core_level=MIN_CORE_LEVEL)


def resolve_kit_formulas(
    raw_formulas: list[dict[str, Any]],
    *,
    mindscape: int,
    core_level: int,
    potential_rank: int = 6,
) -> tuple[KitFormula, ...]:
    """Resolve every formula in a kit, dropping the ones inert at this build.

    Inert entries (an M6 instance on an M0 build) are dropped rather than carried
    as zeroes so the sim never emits a 0-damage event. Formulas outside the build's
    Potential state are dropped for the same reason (#90).

    ``potential_rank`` defaults to 6 (Level VI, fully unlocked) to match the DB
    column's own default and
    the rule the whole #90 migration follows: an unspecified rank means "as fairy behaved
    before #90".
    """
    resolved = (
        resolve_kit_formula(raw, mindscape=mindscape, core_level=core_level)
        for raw in raw_formulas
    )
    return tuple(
        f for f in resolved if not f.is_inert and potential_allows(f, potential_rank)
    )
