"""Characterization of the #101 buildup divisors, one case per in-scope spec.

**Every case here starts out asserting the WRONG value.** That is the point: these are
characterization tests recording what the JSON says *today*, each tagged with the Phase 3
task that will flip it. A task is not done until its case in this file has been changed
and the change is red-before / green-after.

Why the divisor matters (`DESIGN_sequential_variant.md` §5.3, the authoring contract):

| `hit_mode` | rows per resolved step | divisor | authored `buildup` must be |
|---|---|---|---|
| `sequential` (single-tap) | 1 | `move_spec.hits` | whole-**cycle** total; `hits` = press count |
| `atomic` | all N | `len(step.attacks)` | the whole-**activation** total |
| `variant` | the chosen variant's | `len(step.attacks)` | the **per-variant** total |

`anomaly_simulator.py:1516-1520` implements the first row: for a single-tap slice of a
`sequential` move it sets `buildup_hits = move_spec.hits` and applies `buildup //
buildup_hits` per press. So when `hits` is the DB **row** count rather than the **press**
count — which is the whole of #101 — every press applies too little gauge, and a full
cycle of N presses applies only N/rows of the move's real total.

The modules load the **real** JSON through `load_agent_moves()`. A synthetic spec would
prove nothing: it is exactly the #77 failure mode where the harness validated a fixture
rather than the shipped data (`MODIFIER_AUTHORING.md:380-387`).

Scope note: this module asserts what the *spec files* say. The end-to-end anchor — a real
seeded DB, a real combo, the activation's total gauge equal to the DB row sum — is Task 17
(`tests/integration/test_buildup_divisors_e2e.py`, DESIGN §6 layer 5). Neither substitutes
for the other: this one is fast and total, that one proves the number survives the whole
pipeline.
"""

from __future__ import annotations

import pytest

from app.data.loaders.moves import load_agent_moves

# (agent file stem, move key, authored buildup, authored hits, owning task)
#
# `buildup=None` means the spec authors none and runs the DB-row-sum fallback.
# `hits` is what the divisor uses; the "real presses" column of
# `docs/RESEARCH_101_buildup_divisors.md` §2 is what verification is expected to make it,
# but each Phase 3 task re-derives that itself and may overturn it.
#
# CORRECTED — verified, receipted in docs/LOG_sequential_variant.md, and now locked.
# A change to one of these is a regression, not progress.
CORRECTED: list[tuple[str, str, int | None, int, str]] = [
    ("seth", "Basic Attack: Lightning Strike - Electrified", None, 1, "Task 6"),
    ("yixuan", "EX Special Attack: Ink Manifestation", 85819, 3, "Task 7"),
    # buildup deleted: three mutually exclusive charge levels, one per variant, so the
    # DB-row fallback is the only per-variant-correct source (DESIGN §5.3 mechanism 1).
    ("alice", "Basic Attack: Starshine Waltz", None, 1, "Task 8"),
    # 45735 summed all six rows and double-counted press 5. 30135 is the base five-press
    # cycle; the enhanced cycle (36015) is not representable alongside it.
    ("alice", "Basic Attack: Celestial Overture", 30135, 5, "Task 9"),
    ("grace", "Basic Attack: High-Pressure Spike", 6460, 4, "Task 10"),
    ("promeia", "Basic Attack: Sweeping Edge", 62215, 5, "Task 15"),
    ("soldier_0_anby", "Basic Attack: Penetrating Shock", None, 5, "Task 16"),
    # 20968 counted both shot forms; 13198 is the un-charged four-press cycle.
    ("hugo", "Basic Attack: Dark Abyss Quartet", 13198, 4, "Task 12"),
    # Escalated, then resolved to `atomic` at Planner tier: one input, not a chain, so
    # 28003 summed two mutually exclusive shot forms. 16079 is the un-charged activation.
    ("hugo", "Basic Attack: Dark Abyss Concerto", 16079, 2, "Task 11"),
    # Divisor-only: Lucy's ALT row carries zero gauge, so the 4-press total is the row sum.
    ("lucy", "Basic Attack: Lady's Bat", 32026, 4, "Task 13"),
    # Caesar's ALT row does carry gauge (7432), so the total moved with the divisor.
    ("caesar", "Basic Attack: Rampaging Slash", 63870, 6, "Task 14"),
]

# CHARACTERIZED — still wrong. Each entry names the task that will flip it into CORRECTED.
# Empty since Task 11a: all 11 in-scope divisors are corrected, which is Task 17's #101
# closure gate. An entry appearing here again means a divisor regressed or a new one was
# found; it does not mean this branch left one open.
CHARACTERIZED: list[tuple[str, str, int | None, int, str]] = []

# Aria is deliberately absent. `aria.json` is the one spec with
# `requires_charge_level > 0`, which binds `hits` to the abloom final-hit gate
# (`anomaly_simulator.py:2591-2593`) — changing it changes more than a divisor.
# DESIGN §2.2.1 / §5.3.1 excludes it from this branch; DECISIONS 2026-07-29.
EXCLUDED_FROM_SCOPE = ("aria", "Basic Attack: Perfect Pitch")


@pytest.fixture(scope="module")
def moves() -> dict:
    """The real shipped JSON, not a fixture — see the module docstring."""
    return load_agent_moves()


def _spec(moves: dict, stem: str, move: str):
    agent = moves.get(stem)
    assert agent is not None, f"no move spec file for {stem!r}"
    spec = agent.moves.get(move)
    assert spec is not None, f"{stem}.json has no move {move!r}"
    return spec


ALL_CASES = CORRECTED + CHARACTERIZED


@pytest.mark.parametrize(
    ("stem", "move", "buildup", "hits", "task"),
    ALL_CASES,
    ids=[f"{s}-{t.replace(' ', '')}" for s, _, _, _, t in ALL_CASES],
)
def test_authored_buildup_and_hits(
    moves: dict, stem: str, move: str, buildup: int | None, hits: int, task: str
) -> None:
    """Authored values: corrected for `CORRECTED` cases, still-wrong for the rest."""
    spec = _spec(moves, stem, move)
    assert spec.buildup == buildup, f"{task} changes this"
    assert spec.hits == hits, f"{task} changes this"


@pytest.mark.parametrize(
    ("stem", "move", "buildup", "hits", "task"),
    [c for c in ALL_CASES if c[2] is not None],
    ids=[f"{s}-{t.replace(' ', '')}" for s, _, b, _, t in ALL_CASES if b is not None],
)
def test_per_press_buildup_today(
    moves: dict, stem: str, move: str, buildup: int | None, hits: int, task: str
) -> None:
    """The gauge one single-tap press applies today: `buildup // hits`.

    Derived from the spec exactly as `anomaly_simulator.py:1516-1520` derives it for a
    `_seq_slice` step. This is the number #101 is about, so it is asserted directly
    rather than left implicit in the two fields above.
    """
    spec = _spec(moves, stem, move)
    assert spec.buildup is not None
    assert spec.buildup // spec.hits == buildup // hits, f"{task} changes this"


def test_omitted_buildup_is_not_an_authored_zero(moves: dict) -> None:
    """Soldier 0 - Anby authors no `buildup` and must keep authoring none.

    `None` and `0` are different instructions: `None` falls back to the DB row sum
    (`:1523-1530`), an explicit `0` suppresses the move's gauge entirely. DESIGN §5.3
    makes dropping the authored `buildup` the *preferred* fix for a re-classified move,
    so this distinction is about to be load-bearing on more specs than this one.
    """
    spec = _spec(moves, "soldier_0_anby", "Basic Attack: Penetrating Shock")
    assert spec.buildup is None
    assert spec.hits >= 1, "hits must be set, not deleted — MoveBuildupSpec defaults it to 1"


def test_aria_is_out_of_scope_and_untouched(moves: dict) -> None:
    """A guard, not a characterization: this branch must not edit Aria.

    If a later task drops `requires_charge_level` here to make a divisor tidy, it has
    silently changed the abloom final-hit gate too. That is Scope 3.
    """
    stem, move = EXCLUDED_FROM_SCOPE
    spec = _spec(moves, stem, move)
    assert spec.requires_charge_level > 0, "Aria's charge gate is what excludes her"


def test_no_other_spec_acquires_requires_charge_level(moves: dict) -> None:
    """DESIGN §5.3.1's one hard prohibition, enforced across every shipped spec."""
    offenders = [
        f"{stem}/{name}"
        for stem, agent in moves.items()
        for name, spec in agent.moves.items()
        if getattr(spec, "requires_charge_level", 0) > 0 and (stem, name) != EXCLUDED_FROM_SCOPE
    ]
    assert offenders == [], (
        "requires_charge_level binds `hits` to the abloom final-hit gate; "
        "no spec but Aria's may carry it in this branch"
    )


def test_alices_ultimate_polarity_is_gated_to_mindscape_2(moves: dict) -> None:
    """Alice's `Ultimate: Starfall Finale` triggers Polarity Assault only from M2.

    nanoka's Mindscape 2 ("Sage at the Sword's Tip") is what grants it — *"When Ultimate:
    Starfall Finale's Finishing Move hits an enemy, it triggers Polarity Assault"* — and
    the Ultimate's own skill text mentions no such trigger. The flag was ungated, so an M0
    Alice was credited an M2 effect on every Ultimate.
    """
    spec = _spec(moves, "alice", "Ultimate: Starfall Finale")
    assert spec.polarity_disorder is True
    assert spec.polarity_requires_mindscape == 2


def test_polarity_gate_defaults_to_base_kit(moves: dict) -> None:
    """Every other `polarity_disorder` move is base kit and must stay ungated.

    Starshine Waltz's Polarity Assault *is* in the base skill description, so a blanket
    gate would have deleted a real effect.
    """
    gated = {
        (stem, name)
        for stem, agent in moves.items()
        for name, spec in agent.moves.items()
        if spec.polarity_disorder and spec.polarity_requires_mindscape
    }
    assert gated == {("alice", "Ultimate: Starfall Finale")}
