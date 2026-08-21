"""Task 14 (C2) — mindscape gate fields, and the variant rows they enable.

Some mindscapes do not *add* a buff — they **upgrade one that already exists**. Astra's
M2 raises her core team-ATK buff's cap from 1200 to 1600 and its ATK ratio from 35% to
41.65% (×1.19); Caesar's M2 raises his core team-ATK buff to 150% of its original value.
Modelling those as an independent additive row is wrong in both directions: it stacks
with the buff it was supposed to replace, and its "value" (Caesar's +500) appears in no
source, which is precisely what L1 flagged.

`min_mindscape` / `max_mindscape` let the same buff be authored as **two gated rows**,
each carrying its own literal, independently citable value, with exactly one ever active.
Chosen over a `modifies: <id>` patch graph — see D-KV2.

Ground truth (ZO @ 0c9bde8f, read this session):

  AstraYao.ts:171-186  core_atk = min(
                           sum(core.max_atk, cmpGE(mc, 2, m2.max_increase)),   → 1200 | 1600
                           prod(own.initial.atk,
                                percent(subscript(char.core, core.atk_)),      → 0.35 @ max core
                                sum(percent(1), cmpGE(mc, 2, percent(m2.atk_)))))  → ×1 | ×1.19
                       ⇒ M0/M1: cap 1200, ratio 3500.  M2+: cap 1600, ratio 4165.

  Caesar.ts:101-114    core_atk = prod(subscript(char.core, core.atk),         → 1000 @ max core
                                       cmpGE(mc, 2, m2.atk_increase_, 1))      → ×1 | ×1.5
                       ⇒ M0/M1: 1000 flat ATK.  M2+: 1500.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import Modifier, ModifierSource, mindscape_allows

MODIFIERS_DIR = Path(__file__).parents[2] / "app" / "data" / "modifiers"

ASTRA = "1311"
CAESAR = "1071"


def _mod(label: str, source: ModifierSource, **gates) -> Modifier:
    return Modifier(stat="flat_atk", value=1, source=source, source_label=label, **gates)


def _active(hakushin_id: str, mc: int) -> list[Modifier]:
    return [m for m in load_agent_modifiers(hakushin_id) if mindscape_allows(m, mc)]


def _core_atk_row(hakushin_id: str, mc: int) -> Modifier:
    rows = [
        m
        for m in _active(hakushin_id, mc)
        if m.stat == "flat_atk" and m.source == ModifierSource.CORE_SKILL
    ]
    assert len(rows) == 1, f"expected exactly one active core ATK row at M{mc}, got {rows}"
    return rows[0]


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


class TestMindscapeAllows:
    @pytest.mark.parametrize(("mc", "expected"), [(0, False), (1, False), (2, True), (6, True)])
    def test_label_gate_still_applies(self, mc: int, expected: bool) -> None:
        """The existing rule: an `M<n>:` row needs mindscape >= n. Unchanged."""
        mod = _mod("M2: Something", ModifierSource.MINDSCAPE)
        assert mindscape_allows(mod, mc) is expected

    @pytest.mark.parametrize(("mc", "expected"), [(0, True), (1, True), (2, False), (6, False)])
    def test_max_mindscape_gate(self, mc: int, expected: bool) -> None:
        mod = _mod("Core: Base variant", ModifierSource.CORE_SKILL, max_mindscape=1)
        assert mindscape_allows(mod, mc) is expected

    @pytest.mark.parametrize(("mc", "expected"), [(0, False), (1, False), (2, True), (6, True)])
    def test_min_mindscape_gate(self, mc: int, expected: bool) -> None:
        mod = _mod("Core: Upgraded variant", ModifierSource.CORE_SKILL, min_mindscape=2)
        assert mindscape_allows(mod, mc) is expected

    def test_ungated_rows_are_always_allowed(self) -> None:
        mod = _mod("Core: Plain", ModifierSource.CORE_SKILL)
        assert all(mindscape_allows(mod, mc) for mc in range(7))

    def test_gates_are_exclusive_by_construction(self) -> None:
        """A [0..1] row and a [2..] row never both fire — that is the whole point."""
        base = _mod("Core: X", ModifierSource.CORE_SKILL, max_mindscape=1)
        upgraded = _mod("Core: X", ModifierSource.CORE_SKILL, min_mindscape=2)
        for mc in range(7):
            assert mindscape_allows(base, mc) != mindscape_allows(upgraded, mc)


# ---------------------------------------------------------------------------
# Astra Yao — M2 restored (it was dropped in Phase A; see D-KV3)
# ---------------------------------------------------------------------------


class TestAstraCoreVariants:
    @pytest.mark.parametrize("mc", [0, 1])
    def test_below_m2_is_the_base_variant(self, mc: int) -> None:
        row = _core_atk_row(ASTRA, mc)
        assert row.value == 1200  # cap
        assert row.atk_scale_ratio == 3500  # 35% of her initial ATK

    @pytest.mark.parametrize("mc", [2, 4, 6])
    def test_m2_and_above_is_the_upgraded_variant(self, mc: int) -> None:
        row = _core_atk_row(ASTRA, mc)
        assert row.value == 1600  # 1200 + m2.max_increase (400)
        assert row.atk_scale_ratio == 4165  # 0.35 x 1.19

    def test_m2_owners_are_no_longer_under_buffed(self) -> None:
        """Phase A deleted the wrong M2 row and could not express the right one (D-KV3)."""
        assert _core_atk_row(ASTRA, 2).value > _core_atk_row(ASTRA, 1).value


# ---------------------------------------------------------------------------
# Caesar — the additive +500 row replaced by a x1.5 variant
# ---------------------------------------------------------------------------


class TestCaesarCoreVariants:
    @pytest.mark.parametrize(("mc", "expected"), [(0, 1000), (1, 1000), (2, 1500), (6, 1500)])
    def test_core_atk_is_multiplied_not_added_to(self, mc: int, expected: int) -> None:
        assert _core_atk_row(CAESAR, mc).value == expected

    def test_the_phantom_500_row_is_gone(self) -> None:
        """+500 appears in no source — it was 1500 minus 1000, reverse-engineered.

        Task 17 Batch 9 added a legitimate M2 row (Energy Generation Rate,
        audited) alongside the core ATK variants, so this no longer checks
        for "no M2-labeled row at all" — it checks for the specific phantom
        value/shape the original bug produced (a bare `+500` flat_atk row
        with no override_reason, distinct from the real variant pair's
        1000/1500 values).
        """
        raw = json.loads((MODIFIERS_DIR / "agents" / "caesar.json").read_text())
        assert not [
            m
            for m in raw["modifiers"]
            if m["stat"] == "flat_atk" and m["value"] == 500
        ]


# ---------------------------------------------------------------------------
# Corpus invariant
# ---------------------------------------------------------------------------


def test_no_kit_has_overlapping_variant_rows() -> None:
    """Two rows sharing a source_label must be mutually exclusive across every state.

    A same-label pair is the variant pattern; if both can fire the buff is applied twice,
    which is the very bug this schema exists to prevent.

    The state space is mindscape level **and** Potential rank (#90). A base/unlocked pair
    shares a label and both halves are unrestricted by mindscape, so it is the Potential
    tag that separates them — this test is one of the "callers must apply the gate
    wherever they filter" sites named in `potential_allows`, and without the second axis
    it reports a false positive on every such pair.
    """
    for path in sorted(MODIFIERS_DIR.rglob("*.json")):
        mods = json.loads(path.read_text()).get("modifiers", [])
        by_label: dict[str, list[dict]] = {}
        for mod in mods:
            by_label.setdefault(mod["source_label"], []).append(mod)

        for label, rows in by_label.items():
            if len(rows) < 2:
                continue
            for mc in range(7):
                for rank in (0, 5):
                    live = [
                        r
                        for r in rows
                        if r.get("min_mindscape", 0) <= mc
                        and (r.get("max_mindscape") is None or mc <= r["max_mindscape"])
                        and _potential_live(r.get("potential"), rank)
                    ]
                    assert len(live) <= 1, (
                        f"{path.name}: {label!r} has {len(live)} rows live at "
                        f"M{mc}/potential_rank {rank}"
                    )


def _potential_live(tag: str | None, potential_rank: int) -> bool:
    """Mirror of `modifiers.potential_allows`, over the raw JSON value."""
    if tag is None:
        return True
    return (potential_rank >= 1) if tag == "unlocked" else (potential_rank == 0)
