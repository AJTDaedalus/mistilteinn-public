"""M.1 — turning a talent's published rows into hits.

`DESIGN_multipliers.md` §2, counted from `tests/fixtures/nanoka_gi/detail/character_*.json`
rather than recalled: 498 non-empty rows, four format codes, five tails. The params are
already fractions — `1.123` is 112.3% — so nothing here converts them.

**The separator carries meaning.** `A+B` is two parts of one attack and sums; `A/B` is two
alternatives and must not. A low plunge plus a high plunge is a multiplier for a hit nobody
can perform, which is a plausible number for an impossible action.
"""

# ruff: noqa: RUF001 — the `×` below is U+00D7, which is the character the game's own data
# uses. Replacing it with an ASCII `x` to satisfy the ambiguity check would make these
# fixtures no longer be what the payload says, which is the one thing they are for.

from __future__ import annotations

import re

import pytest

from app.services.talent_scaling import (
    TalentScalingError,
    energy_cost,
    parse_talent_row,
)

# Ayaka's normal attack and burst, verbatim from `character_10000002.json`.
AYAKA_NORMAL_DESC = [
    "1-Hit DMG|{param1:F1P}",
    "2-Hit DMG|{param2:F1P}",
    "3-Hit DMG|{param3:F1P}",
    "4-Hit DMG|{param4:F1P}×3",
    "5-Hit DMG|{param7:F1P}",
    "Charged Attack DMG|{param8:F1P}×3",
    "Charged Attack Stamina Cost|{param9:F1}",
]
AYAKA_NORMAL_PARAM = [
    0.457253, 0.486846, 0.626218, 0.226464, 0, 0, 0.781817, 0.55126, 20,
]

AYAKA_BURST_DESC = [
    "Cutting DMG|{param1:P}",
    "Bloom DMG|{param2:P}",
    "Duration|{param3:F1}s",
    "CD|{param4:F1}s",
    "Energy Cost|{param5:I}",
    "", "", "",
]
AYAKA_BURST_PARAM = [1.123, 1.6845, 5, 20, 80, 0, 0, 0]


def _by_label(desc, param):
    return {hit.label: hit for hit in parse_talent_row(desc, param)}


# ── the ordinary case ────────────────────────────────────────────────────────


def test_a_simple_damage_row_yields_its_multiplier() -> None:
    """`Cutting DMG|{param1:P}` against `param[0] == 1.123`. Already a fraction."""
    hits = _by_label(AYAKA_BURST_DESC, AYAKA_BURST_PARAM)

    assert hits["Cutting DMG"].multiplier == pytest.approx(1.123)
    assert hits["Cutting DMG"].hits == 1


def test_params_are_indexed_from_one() -> None:
    """`{param2:P}` is `param[1]`. An off-by-one here is a wrong multiplier that looks
    entirely reasonable — the worst shape of bug this parser can have."""
    hits = _by_label(AYAKA_BURST_DESC, AYAKA_BURST_PARAM)

    assert hits["Bloom DMG"].multiplier == pytest.approx(1.6845)


def test_the_two_percentage_formats_are_the_same_number() -> None:
    """`P` and `F1P` differ only in display precision. Treating `F1P` as needing a divide
    would quietly make every normal attack a hundredth of its real value."""
    p_only = _by_label(["Skill DMG|{param1:P}"], [2.392])
    f1p = _by_label(["Skill DMG|{param1:F1P}"], [2.392])

    assert p_only["Skill DMG"].multiplier == f1p["Skill DMG"].multiplier == pytest.approx(2.392)


# ── the three shapes ─────────────────────────────────────────────────────────


def test_a_repeated_hit_keeps_its_count_separate() -> None:
    """OQ-M2. `×3` is one hit landing three times, **not** a tripled multiplier.

    The damage chain applies crit and DEF terms per hit. Pre-multiplying would apply them
    once to a tripled number, which is a different and smaller answer.
    """
    hits = _by_label(AYAKA_NORMAL_DESC, AYAKA_NORMAL_PARAM)

    assert hits["4-Hit DMG"].multiplier == pytest.approx(0.226464)
    assert hits["4-Hit DMG"].hits == 3


def test_a_summed_row_adds_its_parts() -> None:
    """`A+B` is two parts of one attack."""
    hits = _by_label(["Charged Attack DMG|{param6:F1P}+{param7:P}"], [0, 0, 0, 0, 0, 1.5, 2.0])

    assert hits["Charged Attack DMG"].multiplier == pytest.approx(3.5)
    assert hits["Charged Attack DMG"].hits == 1


def test_alternatives_are_two_hits_and_are_never_summed() -> None:
    """OQ-M1, and the mistake worth guarding hardest.

    A low plunge and a high plunge are different actions. Summing them gives a multiplier for
    a hit nobody can perform; collapsing to one loses the other.
    """
    parsed = parse_talent_row(["Low/High Plunge DMG|{param10:P}/{param11:P}"],
                              [0] * 9 + [1.0, 2.0])

    assert len(parsed) == 2
    assert [hit.multiplier for hit in parsed] == pytest.approx([1.0, 2.0])
    assert {hit.multiplier for hit in parsed} != {3.0}


# ── what is not damage ───────────────────────────────────────────────────────


def test_rows_that_are_not_damage_are_not_hits() -> None:
    """`CD`, `Duration` and `Energy Cost` are all in the same list as the multipliers. A
    parser that took every `P`-formatted row would also take `Blazing Threshold`."""
    labels = {hit.label for hit in parse_talent_row(AYAKA_BURST_DESC, AYAKA_BURST_PARAM)}

    assert labels == {"Cutting DMG", "Bloom DMG"}


def test_a_percentage_that_is_not_damage_is_excluded() -> None:
    """The reason the test is on the **label** and not the format."""
    assert parse_talent_row(["Blazing Threshold|{param1:P}"], [0.5]) == []


def test_padding_is_ignored() -> None:
    """Every row list is padded with empty strings to a fixed width."""
    assert parse_talent_row(["", "", ""], [1.0]) == []


# ── refusals ─────────────────────────────────────────────────────────────────


def test_a_param_index_past_the_end_is_refused_not_defaulted() -> None:
    """A zero there is a **real multiplier for a hit that does no damage**, which is exactly
    the sort of plausible wrong answer this repo refuses. `param` lists are padded with real
    zeroes, so a default cannot be told apart from a value."""
    with pytest.raises(TalentScalingError, match="param9"):
        parse_talent_row(["Skill DMG|{param9:P}"], [1.0, 2.0])


def test_a_damage_row_with_no_param_is_refused() -> None:
    """A `DMG` label the parser cannot resolve is a gap in the parser, not an absent hit."""
    with pytest.raises(TalentScalingError):
        parse_talent_row(["Skill DMG|something else"], [1.0])


def test_a_desc_shorter_than_its_params_is_fine() -> None:
    """Guards the guard: the two lists are not required to be the same length, and treating
    that as an error would refuse most real rows."""
    assert len(parse_talent_row(["Skill DMG|{param1:P}"], [1.0, 0, 0, 0, 0])) == 1


# ── the energy cost, nullable since Chunk D ──────────────────────────────────


def test_the_energy_cost_is_read_from_the_same_row_list() -> None:
    """`Character.burst_energy_cost` has been nullable since Chunk D precisely because this
    had never been parsed out."""
    assert energy_cost(AYAKA_BURST_DESC, AYAKA_BURST_PARAM) == 80


def test_a_talent_with_no_energy_cost_says_none_rather_than_zero() -> None:
    """A normal attack has no burst cost. Zero would claim it is free to cast."""
    assert energy_cost(AYAKA_NORMAL_DESC, AYAKA_NORMAL_PARAM) is None


# ── against every row in the committed fixtures ──────────────────────────────


def test_every_published_row_parses() -> None:
    """The test the hand-written cases above cannot be: **all 498 of them.**

    A parser exercised only on rows someone chose is a parser tested against its own author's
    imagination. This runs it over every talent, every level, in the committed payloads — and
    a `TalentScalingError` from any of them fails, because a row this cannot read is a gap in
    the parser rather than a talent with no hits.
    """
    import glob
    import json

    rows = hits = 0
    for path in glob.glob("tests/fixtures/nanoka_gi/detail/character_*.json"):
        payload = json.loads(open(path).read())  # noqa: SIM115
        for skill in payload.get("skills", []):
            for level, row in (skill.get("promote") or {}).items():
                rows += 1
                parsed = parse_talent_row(row.get("desc"), row.get("param"))
                hits += len(parsed)
                for hit in parsed:
                    assert hit.multiplier >= 0, f"{path} {skill['name']} L{level}: {hit}"
                    assert hit.hits >= 1

    # Measured: the two committed characters carry **91** promote rows between them, yielding
    # **345** hits. The floors are under those rather than equal to them, so adding a fixture
    # does not fail this — but a fixture directory that failed to load, or a parser that
    # stopped matching, drops straight through them.
    assert rows >= 80, f"only {rows} rows reached — the fixtures did not load"
    assert hits >= 300, f"only {hits} hits found — the parser matched almost nothing"


def test_the_fixtures_really_contain_the_shapes_this_claims_to_handle() -> None:
    """Guards the guard above.

    `test_every_published_row_parses` would pass just as happily if the payloads had stopped
    containing `×N` or `A/B` rows — it only asserts that nothing raised. This asserts the
    hard shapes are actually in there, so the sweep is exercising them.
    """
    import glob
    import json

    seen = {"repeat": 0, "sum": 0, "alternatives": 0}
    for path in glob.glob("tests/fixtures/nanoka_gi/detail/character_*.json"):
        payload = json.loads(open(path).read())  # noqa: SIM115
        for skill in payload.get("skills", []):
            for row in (skill.get("promote") or {}).values():
                for entry in row.get("desc") or []:
                    spec = entry.partition("|")[2] if entry else ""
                    if "×" in spec:
                        seen["repeat"] += 1
                    stripped = re.sub(r"\{param\d+:[A-Za-z0-9]+\}", "", spec)
                    if "+" in stripped:
                        seen["sum"] += 1
                    if "/" in stripped and "DMG" in entry:
                        seen["alternatives"] += 1

    assert all(count > 0 for count in seen.values()), seen
