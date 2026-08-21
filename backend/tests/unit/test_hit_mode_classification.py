"""Characterization of every in-scope move's declared `hit_mode`.

Companion to `test_buildup_divisors.py`: that module pins what a move's gauge *is*, this
one pins what the move *is*. They move together, because changing `hit_mode` changes what
the authored `buildup` has to mean (`DESIGN_sequential_variant.md` §5.3).

**Every case starts out asserting the current, probably-wrong classification**, tagged
with the Phase 3/4 task that will re-derive it. Three outcomes are legal per move
(DESIGN §5.1), and the task's own verification decides which — the survey's shape letter
is a hypothesis, not an assignment:

1. **shape C** (charge levels / stances / contexts) → `variant` + `variants[]`;
2. **shape D** (one activation, several damage instances) → the move entry is **deleted**
   from the override file, because `atomic` is the default;
3. **shape A/B** (it really is a press chain, just not `len(rows)` long) → stays
   `sequential`, `hits` corrected to the verified press count, the row-partition question
   deferred to the #89 follow-up.

Outcome 2 is why `CHARACTERIZED` distinguishes `None` from `"sequential"`: `None` means
"no override entry at all", which is what an `atomic` move looks like on disk.

Loads the **real** `skill_overrides/` JSON — a synthetic override would prove nothing
(#77, `MODIFIER_AUTHORING.md:380-387`). Note this is what the *files* declare; what the
DB ends up holding after a re-seed is a separate question with its own trap (DESIGN §5.2:
`apply_skill_overrides` can never reset a row to `atomic`, so a re-classification to
`atomic` needs a full `seed_db`). Task 6 is the case that demonstrates it.
"""

from __future__ import annotations

import pytest

from app.data.loaders.skill_overrides import load_skill_overrides

# (agent file stem, move key, declared hit_mode or None if no entry, owning task)
#
# CORRECTED — verified, receipted in docs/LOG_sequential_variant.md, now locked.
# `None` means "no override entry", which is exactly what an `atomic` verdict looks like
# on disk.
CORRECTED: list[tuple[str, str, str | None, str]] = [
    ("seth", "Basic Attack: Lightning Strike - Electrified", None, "Task 6"),
    # Stays sequential; only `hits` changed. Verified and locked all the same.
    ("yixuan", "EX Special Attack: Ink Manifestation", "sequential", "Task 7"),
    ("alice", "Basic Attack: Starshine Waltz", "variant", "Task 8"),
    # Escalated, then resolved to `atomic` at Planner tier — one input, not a 2-press
    # chain, so the override entry was deleted. `None` here is outcome 2, and it only
    # reaches the DB through a full re-seed (DESIGN §5.2).
    ("hugo", "Basic Attack: Dark Abyss Concerto", None, "Task 11"),
]

# CHARACTERIZED — still the pre-verification declaration.
CHARACTERIZED: list[tuple[str, str, str | None, str]] = [
    # Phase 3 — moves that also carry a live divisor bug (#101).
    ("alice", "Basic Attack: Celestial Overture", "sequential", "Task 9"),
    ("grace", "Basic Attack: High-Pressure Spike", "sequential", "Task 10"),
    ("promeia", "Basic Attack: Sweeping Edge", "sequential", "Task 15"),
    ("soldier_0_anby", "Basic Attack: Penetrating Shock", "sequential", "Task 16"),
    # Phase 4 — shape C/D candidates with no `moves/agents/` spec, so no divisor to fix.
    # The deliverable is the verdict and its receipt. Billy verified as a two-axis hybrid
    # and was escalated; the escalation was ACCEPTED, so `sequential` here is the verified
    # outcome, not a pending one. L5 signal 6 (`seq_leading_qualifier`) now fires on the
    # stance pair, so it carries a real waiver — `seq_leading_qualifier|billy.json|0`,
    # retiring on #89. Task 26a.
    ("billy", "Basic Attack: Full Firepower", "sequential", "Task 19"),
]


@pytest.fixture(scope="module")
def overrides() -> dict:
    """The real shipped JSON, not a fixture — see the module docstring."""
    return load_skill_overrides()


def _declared_mode(overrides: dict, stem: str, move: str) -> str | None:
    agent = overrides.get(stem)
    if agent is None:
        return None
    entry = agent.moves.get(move)
    if entry is None:
        return None
    mode = entry.hit_mode
    return getattr(mode, "value", mode)


ALL_CASES = CORRECTED + CHARACTERIZED


@pytest.mark.parametrize(
    ("stem", "move", "mode", "task"),
    ALL_CASES,
    ids=[f"{s}-{t.replace(' ', '')}" for s, _, _, t in ALL_CASES],
)
def test_declared_hit_mode(
    overrides: dict, stem: str, move: str, mode: str | None, task: str
) -> None:
    """Declared mode: verified for `CORRECTED` cases, pre-verification for the rest."""
    assert _declared_mode(overrides, stem, move) == mode, f"{task} may change this"


@pytest.mark.parametrize(
    ("stem", "move", "task"),
    [(s, m, t) for s, m, mode, t in ALL_CASES if mode == "variant"],
    ids=[f"{s}-{t.replace(' ', '')}" for s, _, mode, t in ALL_CASES if mode == "variant"],
)
def test_variant_moves_declare_variants(overrides: dict, stem: str, move: str, task: str) -> None:
    """A `variant` declaration without `variants[]` labels nothing and filters nothing.

    Empty today (no in-scope move is `variant` yet); it fills in as Phase 3/4 lands and is
    the guard that a re-classification is not half-done.
    """
    agent = overrides[stem]
    entry = agent.moves[move]
    assert entry.variants, f"{task}: variant mode requires variants[]"
    labels = [v.label for v in entry.variants]
    assert len(labels) == len(set(labels)), f"{task}: duplicate variant labels"
    assert all(labels), f"{task}: every variant needs a non-empty label"


def test_every_characterized_agent_file_exists(overrides: dict) -> None:
    """Catches a rename or a deleted file turning a real assertion into a vacuous one.

    Without this, `_declared_mode` returning `None` for a missing *file* is
    indistinguishable from a deliberate `atomic` re-classification.
    """
    missing = sorted({stem for stem, _, _, _ in ALL_CASES if stem not in overrides})
    assert missing == [], f"no skill_overrides file for: {missing}"
