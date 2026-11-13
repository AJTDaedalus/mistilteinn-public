"""Math-fallback P0 — the scaling stat a talent row's tail names.

`DESIGN_team_math_fallback.md` §3 P0, `TASKS_team_math_fallback.md` task 1. The parser used to
read only the `{paramN}` tokens and drop the words after them, so every hit was implicitly ATK
and `# ATK+# Elemental Mastery` became two ATK hits that both landed. Every row below is
verbatim from the seeded catalogue (nanoka 7.0.51, level 1) — labels kept, params replaced
by small stand-ins — and `RESEARCH_math_fallback_inventory.md` §2.3 has the survey they were
picked from.

`test_every_tail_in_the_catalogue_is_classified` carries one row per distinct tail shape in
the catalogue, so a tail this file has not seen is a tail the survey did not contain.
"""

# ruff: noqa: RUF001 — `×` is U+00D7, the character the game's own data uses.

from __future__ import annotations

import pytest

from app.formula.genshin.damage import ScalingStat, ScalingTerm
from app.services.talent_scaling import (
    TalentScalingError,
    classify_talent_row,
    parse_talent_row,
)

ATK, HP, DEF, EM = (
    ScalingStat.ATK, ScalingStat.HP, ScalingStat.DEF, ScalingStat.ELEMENTAL_MASTERY,
)


def _one(entry: str, param: list[float]):
    [hit] = parse_talent_row([entry], param)
    return hit


def test_a_row_with_no_stat_word_scales_off_atk() -> None:
    hit = _one("Cutting DMG|{param1:P}", [1.123])

    assert hit.scaling_stat is ATK
    assert hit.extra_terms == ()


@pytest.mark.parametrize(("entry", "stat"), [
    ("Skill DMG|{param1:F2P} Max HP", HP),
    ("Ousia Bubble DMG|{param1:F1P} Max HP", HP),
    ("Skill DMG|{param1:P} DEF", DEF),
    ("Gradient Detonation Stellar-Conduct DMG|{param1:F1P} Elemental Mastery", EM),
])
def test_a_trailing_stat_word_is_the_hits_scaling_stat(entry: str, stat: ScalingStat) -> None:
    hit = _one(entry, [0.1462])

    assert hit.scaling_stat is stat
    assert hit.multiplier == pytest.approx(0.1462)
    assert hit.extra_terms == ()


def test_a_mixed_stat_row_is_one_hit_with_two_terms() -> None:
    """Nahida's Tri-Karma Purification: **one** instance of damage, `ATK x a + EM x b`.

    gcsim models it as one attack whose EM half is `FlatDmg = em * triKarmaEM`
    (`internal/characters/nahida/skill.go:219-220`). The old parse made it two hits that both
    land, each scaled by the caller's single stat — so it was counted twice and the EM half
    read off ATK.
    """
    parsed = parse_talent_row(
        ["Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery"],
        [0, 0, 1.032, 2.064],
    )

    assert len(parsed) == 1
    [hit] = parsed
    assert hit.scaling_stat is ATK
    assert hit.multiplier == pytest.approx(1.032)
    assert hit.extra_terms == (ScalingTerm(EM, 2.064),)
    assert hit.hits == 1
    assert not hit.exclusive


@pytest.mark.parametrize(("entry", "first", "second"), [
    ("Tamoto DMG|{param1:P} ATK+{param2:P} DEF", ATK, DEF),
    ("Field DMG|{param1:F1P} ATK+{param2:F2P} Max HP", ATK, HP),
    ("Hold DMG|{param1:P} Elemental Mastery+{param2:P} DEF", EM, DEF),
])
def test_every_mixed_pair_in_the_catalogue_is_one_hit(
    entry: str, first: ScalingStat, second: ScalingStat,
) -> None:
    [hit] = parse_talent_row([entry], [0.5, 0.7])

    assert hit.scaling_stat is first
    assert hit.multiplier == pytest.approx(0.5)
    assert hit.extra_terms == (ScalingTerm(second, 0.7),)


def test_a_parenthesised_mixed_hit_takes_the_repeat_outside_it() -> None:
    """Alhaitham's `2-Mirror Projection Attack DMG|({a} ATK+{b} Elemental Mastery)×2` is one
    two-term hit landing twice — not four hits, and not one hit with no repeat."""
    [hit] = parse_talent_row(
        [(
            "2-Mirror Projection Attack DMG|({param1:F1P} ATK+{param2:F1P} "
            "Elemental Mastery)×2"
        )],
        [0.672, 1.344],
    )

    assert hit.hits == 2
    assert hit.scaling_stat is ATK
    assert hit.extra_terms == (ScalingTerm(EM, 1.344),)


def test_a_stat_word_after_alternatives_applies_to_each() -> None:
    """Nilou's `{a}/{b} Max HP`: both alternatives are HP. Read positionally, the first
    would have had no word and fallen back to ATK."""
    parsed = parse_talent_row(
        ["Sword Dance/Whirling Steps 1-Hit DMG|{param1:F2P}/{param2:F2P} Max HP"],
        [0.0455, 0.0506],
    )

    assert [h.scaling_stat for h in parsed] == [HP, HP]
    assert all(h.exclusive for h in parsed)


def test_a_stat_word_after_parts_of_one_stat_keeps_them_separate_hits() -> None:
    """`{a}+{b} DEF` — two parts that both land, both off DEF. One stat across the parts is the
    existing `+` meaning (two hits); only *different* stats make one hit with two terms."""
    parsed = parse_talent_row(
        ["Lunar Phase Shift 3-Hit DMG|{param1:F1P}+{param2:F1P} DEF"], [0.3, 0.4],
    )

    assert [h.multiplier for h in parsed] == pytest.approx([0.3, 0.4])
    assert [h.scaling_stat for h in parsed] == [DEF, DEF]
    assert not any(h.exclusive for h in parsed)
    assert all(h.extra_terms == () for h in parsed)


def test_each_alternative_may_carry_its_own_word() -> None:
    parsed = parse_talent_row(
        ["Low/High Plunge DMG|{param1:F1P} DEF/{param2:F1P} DEF"], [1.2, 1.5],
    )

    assert [h.scaling_stat for h in parsed] == [DEF, DEF]
    assert all(h.exclusive for h in parsed)


@pytest.mark.parametrize(("entry", "stat", "count"), [
    # A space before the repeat — Yelan's Exquisite Throw. The old pattern wanted the `×`
    # directly after the brace and read this as one hit.
    ("Exquisite Throw DMG|{param1:F2P} Max HP ×3", HP, 3),
    ("Slash DMG|{param1:F1P} ×5", ATK, 5),
    ("Lumi Pound-Pound Pummeler DMG|{param1:F1P} DEF ×2", DEF, 2),
    # Xiangling's 4-Hit is written with an ASCII asterisk; gcsim gives it four hitmarks
    # (`internal/characters/xiangling/attack.go`).
    ("4-Hit DMG|{param1:F1P}*4", ATK, 4),
])
def test_a_repeat_after_a_stat_word_or_a_space_is_still_a_repeat(
    entry: str, stat: ScalingStat, count: int,
) -> None:
    hit = _one(entry, [0.5])

    assert hit.scaling_stat is stat
    assert hit.hits == count


@pytest.mark.parametrize("entry", [
    "Fatal Blossom DMG|{param1:F1P} each",
    "Icy Paw DMG|{param1:F1P} per Paw",
    "Ice Javelin DMG|{param1:F1P}/Strike",
])
def test_a_per_instance_unit_is_one_atk_hit(entry: str) -> None:
    """`each`, `per Paw` and `/Strike` say the multiplier is per damage instance, which is
    what a hit already is. `/Strike` is not a second alternative: nothing follows it."""
    hit = _one(entry, [0.5])

    assert hit.scaling_stat is ATK
    assert hit.hits == 1
    assert not hit.exclusive


def test_element_words_are_two_atk_hits() -> None:
    """Freminet's `{a} Cryo + {b} Physical`: two parts in two elements, both off ATK. The
    element words are not stats, and the channel stays the caller's (`talent_hits`)."""
    parsed = parse_talent_row(
        ["Level 1 Shattering Pressure DMG|{param1:F1P} Cryo + {param2:F1P} Physical"],
        [0.2, 0.8],
    )

    assert [h.multiplier for h in parsed] == pytest.approx([0.2, 0.8])
    assert [h.scaling_stat for h in parsed] == [ATK, ATK]
    assert not any(h.exclusive for h in parsed)


@pytest.mark.parametrize(("entry", "reason"), [
    ("Soul Companion DMG|{param1:F1P} Normal Attack DMG", "Normal Attack DMG"),
    ("Kuugo: Toufukai DMG|{param1:F1P} Charged Attack DMG", "Charged Attack DMG"),
    ("Arcane Projection DMG|{param1:F1P} Corresponding Character's ATK", "another"),
    ("2-Hit Hold DMG|{param1:F1P} Elemental Mastery Per Verdant Dew", "Verdant Dew"),
    ("Steady State Core Detonation DMG|{param1:F1P} Elemental Mastery/Beacon", "Beacon"),
])
def test_a_tail_that_is_not_a_stat_is_refused_by_name(entry: str, reason: str) -> None:
    """A multiple of another attack's damage, another character's ATK, or a per-stack value.

    None of these is `multiplier x own stat`, and each used to be scored as ATK. Refused rows
    are not hits — so no page offers them — and `classify_talent_row` names each one.
    """
    assert parse_talent_row([entry], [0.5]) == []

    result = classify_talent_row([entry], [0.5])
    assert result.hits == []
    [refused] = result.refused
    assert refused.label == entry.partition("|")[0]
    assert reason in refused.reason
    assert not refused.unrecognised


def test_an_unknown_tail_word_is_refused_not_read_as_atk() -> None:
    """The next patch's new word arrives as a named refusal, not as a silent ATK hit."""
    result = classify_talent_row(["Skill DMG|{param1:P} Stamina"], [0.5])

    assert result.hits == []
    [refused] = result.refused
    assert "'Stamina'" in refused.reason
    assert refused.unrecognised


def test_a_refused_row_does_not_take_its_neighbours_with_it() -> None:
    """One unreadable tail refuses that row, not the talent: the other hits are still real."""
    result = classify_talent_row(
        ["Skill DMG|{param1:P} Stamina", "Bloom DMG|{param2:P} Max HP"], [0.5, 0.6],
    )

    assert [h.label for h in result.hits] == ["Bloom DMG"]
    assert len(result.refused) == 1


def test_a_bare_param_after_the_last_stat_word_is_refused() -> None:
    """`{a} Max HP+{b}` would leave `b` with no word to inherit. ATK is a guess there."""
    with pytest.raises(TalentScalingError, match="no stat word"):
        parse_talent_row(["Skill DMG|{param1:P} Max HP+{param2:P}"], [0.5, 0.6])


def test_parts_that_share_a_stat_with_a_third_are_refused() -> None:
    """`ATK + ATK + EM` is neither "parts that all land" nor "one hit, one term per stat"."""
    with pytest.raises(TalentScalingError, match="composition"):
        parse_talent_row(
            ["Skill DMG|{param1:P} ATK+{param2:P} ATK+{param3:P} Elemental Mastery"],
            [0.1, 0.2, 0.3],
        )


def test_an_interval_is_not_a_hit() -> None:
    """`Spiritbreath Thorn DMG Interval|{param10:F1}s` is seconds. It used to parse as a
    hit worth 1.5x ATK."""
    assert parse_talent_row(["Spiritbreath Thorn DMG Interval|{param1:F1}s"], [1.5]) == []
    assert parse_talent_row(
        ["Spiritbreath Thorn/Surging Blade DMG Interval|{param1:I}s/{param2:I}s"], [1, 2],
    ) == []


# ── the whole survey ─────────────────────────────────────────────────────────

#: One verbatim row per distinct level-1 DMG tail in the seeded catalogue, with what it must
#: classify as: a list of `(stat, extra stats, hits, exclusive)` per hit, or `"refused"`.
#: Generated by surveying `talent_scalings` (2026-11-13, nanoka 7.0.51), 1,767 DMG rows.
SURVEY: list[tuple[str, object]] = [
    ("1-Hit DMG|{param1:F1P}", [(ATK, (), 1, False)]),
    ("Low/High Plunge DMG|{param1:P}/{param2:P}", [(ATK, (), 1, True)] * 2),
    ("Charged Attack DMG|{param1:F1P}+{param2:F1P}", [(ATK, (), 1, False)] * 2),
    ("Skill DMG|{param1:F1P} Max HP", [(HP, (), 1, False)]),
    ("Skill DMG|{param1:P} DEF", [(DEF, (), 1, False)]),
    ("Tri-Karma Purification DMG|{param1:F1P} ATK+{param2:F1P} Elemental Mastery",
     [(ATK, (EM,), 1, False)]),
    ("4-Hit DMG|{param1:F1P}+{param2:F1P}+{param3:F1P}", [(ATK, (), 1, False)] * 3),
    ("Soul Companion DMG|{param1:F1P} Normal Attack DMG", "refused"),
    ("Phantasm Performance 1-Hit DMG (Shades)|{param1:F1P} Elemental Mastery",
     [(EM, (), 1, False)]),
    ("Total DMG|{param1:F1P}/{param2:F1P} Max HP", [(HP, (), 1, True)] * 2),
    ("Skill DMG|{param1:P} Elemental Mastery+{param2:P} DEF", [(EM, (DEF,), 1, False)]),
    ("Field DMG|{param1:F1P} ATK+{param2:F2P} Max HP", [(ATK, (HP,), 1, False)]),
    ("Level 1 Shattering Pressure DMG|{param1:F1P} Cryo + {param2:F1P} Physical",
     [(ATK, (), 1, False)] * 2),
    ("Tamoto DMG|{param1:P} ATK+{param2:P} DEF", [(ATK, (DEF,), 1, False)]),
    ("Ice Javelin DMG|{param1:F1P}/Strike", [(ATK, (), 1, False)]),
    ("Exquisite Throw DMG|{param1:F2P} Max HP ×3", [(HP, (), 3, False)]),
    ("Driftcloud Wave DMG|{param1:F1P}/{param2:F1P}/{param3:F1P}", [(ATK, (), 1, True)] * 3),
    ("Lunar Phase Shift 3-Hit DMG|{param1:F1P}+{param2:F1P} DEF", [(DEF, (), 1, False)] * 2),
    ("Bombardment DMG|{param1:F1P} ×3", [(ATK, (), 3, False)]),
    ("Windborne Sword Lv. 3 Spirit Blade DMG|{param1:F1P} ×4", [(ATK, (), 4, False)]),
    ("4-Hit DMG|{param1:F1P}*4", [(ATK, (), 4, False)]),
    ("Fatal Blossom DMG|{param1:F1P} each", [(ATK, (), 1, False)]),
    ("Icy Paw DMG|{param1:F1P} per Paw", [(ATK, (), 1, False)]),
    ("Kuugo: Toufukai DMG|{param1:F1P} Charged Attack DMG", "refused"),
    ("2-Mirror Projection Attack DMG|({param1:F1P} ATK+{param2:F1P} Elemental Mastery)×2",
     [(ATK, (EM,), 2, False)]),
    ("3-Mirror Projection Attack DMG|({param1:F1P} ATK+{param2:F1P} Elemental Mastery)×3",
     [(ATK, (EM,), 3, False)]),
    ("Spiritbreath Thorn DMG Interval|{param1:F1}s", []),
    ("Spiritbreath Thorn/Surging Blade DMG Interval|{param1:I}s/{param2:I}s", []),
    ("Low/High Plunge DMG|{param1:F1P} DEF/{param2:F1P} DEF", [(DEF, (), 1, True)] * 2),
    ("Slash DMG|{param1:F1P} ×5", [(ATK, (), 5, False)]),
    ("2-Hit Hold DMG|{param1:F1P} Elemental Mastery Per Verdant Dew", "refused"),
    ("Gravity Interference: Lunar-Bloom DMG|{param1:F2P} Max HP ×5", [(HP, (), 5, False)]),
    ("Lumi Pound-Pound Pummeler DMG|{param1:F1P} DEF ×2", [(DEF, (), 2, False)]),
    ("Arcane Projection DMG|{param1:F1P} Corresponding Character's ATK", "refused"),
    ("Steady State Core Detonation DMG|{param1:F1P} Elemental Mastery/Beacon", "refused"),
]


@pytest.mark.parametrize(("entry", "expected"), SURVEY, ids=[e for e, _ in SURVEY])
def test_every_tail_in_the_catalogue_is_classified(entry: str, expected: object) -> None:
    result = classify_talent_row([entry], [0.5, 0.6, 0.7])

    if expected == "refused":
        assert result.hits == []
        assert len(result.refused) == 1
        assert not result.refused[0].unrecognised, result.refused[0].reason
        return
    assert result.refused == []
    assert [
        (h.scaling_stat, tuple(t.stat for t in h.extra_terms), h.hits, h.exclusive)
        for h in result.hits
    ] == expected


def test_the_survey_has_one_row_per_tail_shape() -> None:
    """35 distinct shapes were surveyed; a duplicate here would be a shape counted twice."""
    import re

    shapes = {
        re.sub(r"\{param\d+:[A-Za-z0-9]+\}", "#", e.partition("|")[2]) for e, _ in SURVEY
    }
    assert len(shapes) == len(SURVEY) == 35
