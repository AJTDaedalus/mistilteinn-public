"""Math-fallback P3, task 12: GO fixtures for weapon passives.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is the kit sheets': each figure is worked by hand from Genshin Optimizer's
formula (`formula.ts:434-453`) and its WR weapon sheet at `2c13fc40`, with **our** numbers —
talent rows verbatim from the seeded catalogue (nanoka 7.2.51), the weapon's refinement values
as our seeded `weapon_refinements.param_list` publishes them (written out here by hand, never
read through the resolver), stated builds. The weapon source is what `weapon_passives.resolve`
gives for a stated **wielder**: the optimized character (whose own buffs from a stat their
artifacts move become per-candidate conversions), or a teammate whose pass-1 stats are written
out. So the committed source is checked against the resolver here, and applied by the browser in
`formula:verify`, where a planted 1% error in any weapon effect must fail.

Every fixture states every condition its sources read (`_states_every_condition`). A fixture
with an amplifying reaction carries the recorded 2.78 vs 25/9 divergence; every other fixture
agrees with GO exactly.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_weapon_passives.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from app.formula.genshin import weapon_passives
from app.schemas.formula import FormulaBonusRead
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
FORMULA_AMP = "libs/gi/wr/src/formula.ts:257,357,434-484,505-514"
WEAPONS = "libs/gi/sheets/src/Weapons/"
AMP_DIVERGENCE = "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9"

# ── Rows and stated builds ─────────────────────────────────────────────────────────────────

#: Amber's seeded Normal Attack rows at level 10 (a bow user for the bow passives).
AMBER_NA_1 = ("1-Hit DMG|{param1:F1P}", [0.714])
AMBER_AIMED = ("Fully-Charged Aimed Shot|{param7:P}",
               [0.714, 0.714, 0.918, 0.935, 1.173, 0.867, 2.232])
#: Amber as the optimized character at 90: base ATK character + weapon, the rest artifacts.
AMBER_BASE = base._base_stats(base_atk=733.0, atk_pct=0.24, base_hp=9461.0, base_def=601.0)
AMBER_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                   "physical_dmg_bonus": 0.0, "crit_rate": 0.3, "crit_dmg": 0.6}

XIANGLING = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
XIANGLING_TEAM = ["pyro", "hydro", "anemo", "cryo"]
NADO = base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None)
NADO_VAPE = base._row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, base.PYRONADO,
                      "reverse_vaporize")


def weapon_source(nanoka_id: str, refinement: int, wielder: str, stats: dict[str, float], *,
                  subject: bool, receiver_element: str | None = None,
                  team_elements: list[str] | None = None) -> dict[str, Any]:
    """The weapon passive as `/formula/kit-buffs` would send it, for a stated wielder."""
    passive = weapon_passives.passive_for(nanoka_id)
    assert passive is not None, nanoka_id
    resolved = weapon_passives.resolve(
        passive,
        weapon_passives.Wielder(wielder, refinement, list(passive.pins[refinement]),
                                base._stated_registry(stats)),
        wielder_is_subject=subject, receiver_element=receiver_element,
        team_elements=team_elements,
    )
    return {"id": resolved.source_id, "label": resolved.label, "citation": resolved.citation,
            "bonus": FormulaBonusRead.of(resolved.bonus).model_dump()}


def _go(stats: dict[str, float], *, row: tuple[str, list[float]], scaling: str = "atk",
        channel: str, amplifying: bool, coefficient: float, x: dict[str, float]) -> float:
    """GO `hit.dmg` (`formula.ts:434-453`) with a weapon passive's terms written in.

    `x` names what the passive adds, each where GO's sheet writes it: `hp_pct`/`atk_pct`/
    `def_pct` into `premod`; `flat_atk` and `atk_from_hp` (× `premod.hp`) into `total.atk`;
    `em`; `dmg`, `cr`, `cd`; `flat` and `flat_from_def` (× `premod.def`) into `dmgInc`; `res`
    the target's resistance change.
    """
    g = x.get
    hp = (stats["base_hp"] * (1 + stats.get("hp_pct", 0.0) + g("hp_pct", 0.0))
          + stats.get("flat_hp", 0.0))
    def_ = (stats["base_def"] * (1 + stats.get("def_pct", 0.0) + g("def_pct", 0.0))
            + stats.get("flat_def", 0.0))
    atk = (stats["base_atk"] * (1 + stats.get("atk_pct", 0.0) + g("atk_pct", 0.0))
           + stats.get("flat_atk", 0.0) + g("flat_atk", 0.0) + g("atk_from_hp", 0.0) * hp)
    em = stats.get("elemental_mastery", 0.0) + g("em", 0.0)
    value = {"atk": atk, "hp": hp, "def": def_, "elemental_mastery": em}[scaling]
    return b4._go_hit(
        base_damage=base._multiplier(row) * value,
        flat=g("flat", 0.0) + g("flat_from_def", 0.0) * def_,
        dmg_bonus=stats.get(f"{channel}_dmg_bonus", 0.0) + g("dmg", 0.0),
        crit_rate=stats["crit_rate"] + g("cr", 0.0), crit_dmg=stats["crit_dmg"] + g("cd", 0.0),
        res=0.1 + g("res", 0.0),
        amp=b4._amp(em, coefficient, reaction_bonus=g("reaction_bonus", 0.0)) if amplifying
        else 1.0,
    )


def _figure(base_stats: dict[str, float], artifacts: dict[str, float],
            row: tuple[str, list[float]], channel: str, x: dict[str, float], *,
            amplifying: bool = False, scaling: str = "atk") -> Any:
    stats = base._stats(base_stats, artifacts)
    return lambda coefficient: _go(stats, row=row, scaling=scaling, channel=channel,
                                   amplifying=amplifying, coefficient=coefficient, x=x)


def _wielder(name: str, weapon: str, refinement: int, stats: Any) -> dict[str, Any]:
    return {"name": name, "weapon": weapon, "refinement": refinement, "stats": stats}


SUBJECT = "the optimized character"


def _fx(name: str, covers: str, go: list[str], wielder: dict[str, Any], team: dict[str, Any],
        base_stats: dict[str, float], artifacts: dict[str, float], channel: str,
        rows: list[dict[str, Any]], source: dict[str, Any], conditionals: dict[str, Any],
        figure: Any, divergence: str = "none: no reaction") -> dict[str, Any]:
    out = base._buffer(name, covers, go, wielder, team, base_stats, artifacts, channel, rows[0],
                       source, conditionals, figure, divergence)
    out["rows"] = rows
    return out


def weapon_fixtures() -> list[dict[str, Any]]:
    """Task 12: one fixture per modelled weapon on its main effect, R1 and R5 for some."""
    out: list[dict[str, Any]] = []
    xb, xa = base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS
    ab, aa = base.AYAKA_BASE, base.AYAKA_ARTIFACTS

    # ── Staff of Homa: HP%, ATK from Max HP, and the low-HP part ───────────────────────────
    for r, hp_pct, atk, low, low_on in ((1, 0.2, 0.008, 0.01, 0), (5, 0.4, 0.016, 0.018, 1)):
        out.append(_fx(
            f"staff_of_homa_r{r}_on_xiangling",
            "a self HP% and ATK from the wielder's own Max HP, per candidate (flat_atk_from_hp)"
            + (", with the below-50%-HP part stated on" if low_on else ""),
            [FORMULA, f"{WEAPONS}Polearm/StaffOfHoma/index.tsx:17-52"],
            _wielder("Xiangling", "Staff of Homa", r, SUBJECT),
            {**XIANGLING, "member_elements": XIANGLING_TEAM}, xb, xa, "pyro", [NADO],
            weapon_source("13501", r, "Xiangling", xb, subject=True),
            {"weapon:staff_of_homa/low_hp": low_on},
            _figure(xb, xa, base.PYRONADO, "pyro",
                    {"hp_pct": hp_pct, "atk_from_hp": atk + (low if low_on else 0.0)})))

    # ── Primordial Jade Cutter ─────────────────────────────────────────────────────────────
    for r, hp_pct, atk in ((1, 0.2, 0.012), (5, 0.4, 0.024)):
        out.append(_fx(
            f"primordial_jade_cutter_r{r}_on_ayaka",
            "a self HP% and ATK from the wielder's own Max HP, per candidate",
            [FORMULA, f"{WEAPONS}Sword/PrimordialJadeCutter/index.tsx:10-35"],
            _wielder("Kamisato Ayaka", "Primordial Jade Cutter", r, SUBJECT),
            {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["cryo", "hydro"]},
            ab, aa, "cryo", [base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None)],
            weapon_source("11505", r, "Kamisato Ayaka", ab, subject=True), {},
            _figure(ab, aa, base.HYOUKA, "cryo", {"hp_pct": hp_pct, "atk_from_hp": atk})))

    # ── Redhorn Stonethresher on a Physical Normal Attack ──────────────────────────────────
    rb, ra = b8.RAZOR_BASE, b8.RAZOR_ARTIFACTS
    out.append(_fx(
        "redhorn_stonethresher_r1_on_razor",
        "a self DEF% and Normal Attack flat damage from the wielder's own DEF, per candidate "
        "(flat_damage_from_def, move-scoped)",
        [FORMULA, f"{WEAPONS}Claymore/RedhornStonethresher/index.tsx:10-44"],
        _wielder("Razor", "Redhorn Stonethresher", 1, SUBJECT),
        {"element": "electro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["electro", "pyro"]},
        rb, ra, "physical", [base._row("na1", "1-Hit DMG", "normal", 1, b8.RAZOR_NA_1, None)],
        weapon_source("12510", 1, "Razor", rb, subject=True), {},
        _figure(rb, ra, b8.RAZOR_NA_1, "physical", {"def_pct": 0.28, "flat_from_def": 0.4})))

    # ── Tag-gated DMG and CRIT ──────────────────────────────────────────────────────────────
    out.append(_fx(
        "the_stringless_r1_on_amber_burst",
        "a self Elemental Skill and Burst DMG bonus",
        [FORMULA, f"{WEAPONS}Bow/TheStringless/index.tsx:10-19"],
        _wielder("Amber", "The Stringless", 1, SUBJECT),
        {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": ["pyro", "cryo"]},
        AMBER_BASE, AMBER_ARTIFACTS, "pyro",
        [base._row("wave", "Fiery Rain DMG Per Wave", "burst", 1, b8.AMBER_WAVE, None)],
        weapon_source("15402", 1, "Amber", AMBER_BASE, subject=True), {},
        _figure(AMBER_BASE, AMBER_ARTIFACTS, b8.AMBER_WAVE, "pyro", {"dmg": 0.24})))

    out.append(_fx(
        "festering_desire_r5_on_ayaka",
        "a self Elemental Skill DMG bonus and Elemental Skill CRIT Rate",
        [FORMULA, f"{WEAPONS}Sword/FesteringDesire/index.tsx:10-24"],
        _wielder("Kamisato Ayaka", "Festering Desire", 5, SUBJECT),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        ab, aa, "cryo", [base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None)],
        weapon_source("11413", 5, "Kamisato Ayaka", ab, subject=True), {},
        _figure(ab, aa, base.HYOUKA, "cryo", {"dmg": 0.32, "cr": 0.12})))

    out.append(_fx(
        "the_catch_r5_on_xiangling",
        "a self Elemental Burst DMG bonus and Elemental Burst CRIT Rate",
        [FORMULA, f"{WEAPONS}Polearm/TheCatch/index.tsx:10-20"],
        _wielder("Xiangling", "\"The Catch\"", 5, SUBJECT),
        {**XIANGLING, "member_elements": XIANGLING_TEAM}, xb, xa, "pyro", [NADO],
        weapon_source("13415", 5, "Xiangling", xb, subject=True), {},
        _figure(xb, xa, base.PYRONADO, "pyro", {"dmg": 0.32, "cr": 0.12})))

    fb, fa = b8.FLINS_BASE, b8.FLINS_ARTIFACTS
    out.append(_fx(
        "white_tassel_r1_on_flins",
        "a self Normal Attack DMG bonus",
        [FORMULA, f"{WEAPONS}Polearm/WhiteTassel/index.tsx:9-15"],
        _wielder("Flins", "White Tassel", 1, SUBJECT),
        {"element": "electro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["electro", "hydro"]},
        fb, fa, "electro", [base._row("na1", "1-Hit DMG", "normal", 1, b8.FLINS_NA_1, None)],
        weapon_source("13301", 1, "Flins", fb, subject=True), {},
        _figure(fb, fa, b8.FLINS_NA_1, "electro", {"dmg": 0.24})))

    # Rust: +80% on the Normal Attack, the published 10% taken off the aimed shot.
    rust_na = _figure(AMBER_BASE, AMBER_ARTIFACTS, AMBER_NA_1, "physical", {"dmg": 0.8})
    rust_ca = _figure(AMBER_BASE, AMBER_ARTIFACTS, AMBER_AIMED, "pyro", {"dmg": -0.1})
    rust = _fx(
        "rust_r5_on_amber",
        "a self Normal Attack DMG bonus, and a Charged Attack DMG decrease the list publishes "
        "positive (negated); two rows of two channels",
        [FORMULA, f"{WEAPONS}Bow/Rust/index.tsx:10-20"],
        _wielder("Amber", "Rust", 5, SUBJECT),
        {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": ["pyro", "cryo"]},
        AMBER_BASE, AMBER_ARTIFACTS, "pyro",
        [{**base._row("na1", "1-Hit DMG", "normal", 1, AMBER_NA_1, None), "channel": "physical"},
         base._row("aimed", "Fully-Charged Aimed Shot", "charged", 1, AMBER_AIMED, None)],
        weapon_source("15405", 5, "Amber", AMBER_BASE, subject=True), {},
        lambda c: rust_na(c) + rust_ca(c))
    out.append(rust)

    # ── Mistsplitter Reforged: all-element DMG, and the Emblem on the wielder's own element ─
    for r, passive, emblem, stacks in ((1, 0.12, 0.28, 3), (5, 0.24, 0.32, 2)):
        out.append(_fx(
            f"mistsplitter_reforged_r{r}_on_ayaka",
            f"a self Elemental DMG bonus for every element, and the Emblem at {stacks} stacks on "
            "the wielder's own element (own_element)",
            [FORMULA, f"{WEAPONS}Sword/MistsplitterReforged/index.tsx:17-62"],
            _wielder("Kamisato Ayaka", "Mistsplitter Reforged", r, SUBJECT),
            {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["cryo", "hydro"]},
            ab, aa, "cryo", [base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None)],
            weapon_source("11509", r, "Kamisato Ayaka", ab, subject=True,
                          receiver_element="cryo"),
            {"weapon:mistsplitter_reforged/emblem": stacks},
            _figure(ab, aa, base.HYOUKA, "cryo", {"dmg": passive + emblem})))

    # ── Team buffs from a teammate's weapon ────────────────────────────────────────────────
    team = {**XIANGLING, "member_elements": XIANGLING_TEAM}
    out.append(_fx(
        "thrilling_tales_r5_on_xiangling",
        "a teammate's weapon: ATK% to the character switched in (others)",
        [FORMULA, f"{WEAPONS}Catalyst/ThrillingTalesOfDragonSlayers/index.tsx:16-43"],
        _wielder("Kamisato Ayato", "Thrilling Tales of Dragon Slayers", 5, {}),
        team, xb, xa, "pyro", [NADO],
        weapon_source("14302", 5, "Kamisato Ayato", {}, subject=False),
        {"weapon:thrilling_tales_of_dragon_slayers/heritage": 1},
        _figure(xb, xa, base.PYRONADO, "pyro", {"atk_pct": 0.48})))

    out.append(_fx(
        "elegy_for_the_end_r1_on_xiangling_vape",
        "a teammate's weapon: party EM and ATK% after the Farewell Song, into an amplifying "
        "reaction; the wielder's own EM does not reach",
        [FORMULA_AMP, f"{WEAPONS}Bow/ElegyForTheEnd/index.tsx:8-43"],
        _wielder("Venti", "Elegy for the End", 1, {}),
        team, xb, xa, "pyro", [NADO_VAPE],
        weapon_source("15503", 1, "Venti", {}, subject=False),
        {"weapon:elegy_for_the_end/farewell": 1},
        _figure(xb, xa, base.PYRONADO, "pyro", {"em": 100.0, "atk_pct": 0.2},
                amplifying=True), AMP_DIVERGENCE))

    kb, ka = b8.KAEYA_BASE, b8.PHYSICAL_ARTIFACTS
    out.append(_fx(
        "freedom_sworn_r1_on_kaeya",
        "a teammate's weapon: party ATK% and Normal/Charged/Plunging DMG during the Song of "
        "Resistance; the wielder's own DMG% does not reach",
        [FORMULA, f"{WEAPONS}Sword/FreedomSworn/index.tsx:9-59"],
        _wielder("Kaedehara Kazuha", "Freedom-Sworn", 1, {}),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "anemo"]},
        kb, ka, "physical", [base._row("na1", "1-Hit DMG", "normal", 1, b8.KAEYA_NA_1, None)],
        weapon_source("11503", 1, "Kaedehara Kazuha", {}, subject=False),
        {"weapon:freedom_sworn/song": 1},
        _figure(kb, ka, b8.KAEYA_NA_1, "physical", {"atk_pct": 0.2, "dmg": 0.16})))

    nilou = {"base_hp": 15185.0, "hp_pct": 0.466, "flat_hp": 4780.0}
    # GO `input.total.hp` carries the weapon's own 20% HP (`premod.hp_`).
    nilou_hp = 15185.0 * (1 + 0.466 + 0.2) + 4780.0
    out.append(_fx(
        "key_of_khaj_nisut_r1_on_xiangling_vape",
        "a teammate's weapon: party EM from the wielder's Max HP at three stacks, that HP "
        "carrying the weapon's own HP%; into an amplifying reaction",
        [FORMULA_AMP, f"{WEAPONS}Sword/KeyOfKhajNisut/index.tsx:17-84"],
        _wielder("Nilou", "Key of Khaj-Nisut", 1, nilou),
        team, xb, xa, "pyro", [NADO_VAPE],
        weapon_source("11511", 1, "Nilou", nilou, subject=False),
        {"weapon:key_of_khaj_nisut/stacks": 3},
        _figure(xb, xa, base.PYRONADO, "pyro", {"em": 0.002 * nilou_hp}, amplifying=True),
        AMP_DIVERGENCE))

    out.append(_fx(
        "wolfs_gravestone_r1_on_xiangling",
        "a teammate's weapon: party ATK% against an opponent below 30% HP (stated on); the "
        "wielder's own ATK% does not reach",
        [FORMULA, f"{WEAPONS}Claymore/WolfsGravestone/index.tsx:8-33"],
        _wielder("Diluc", "Wolf's Gravestone", 1, {}),
        team, xb, xa, "pyro", [NADO],
        weapon_source("12502", 1, "Diluc", {}, subject=False),
        {"weapon:wolfs_gravestone/low_hp_enemy": 1},
        _figure(xb, xa, base.PYRONADO, "pyro", {"atk_pct": 0.4})))

    out.append(_fx(
        "song_of_broken_pines_r1_on_razor",
        "a teammate's weapon: party ATK% during the Banner-Hymn",
        [FORMULA, f"{WEAPONS}Claymore/SongOfBrokenPines/index.tsx:8-42"],
        _wielder("Eula", "Song of Broken Pines", 1, {}),
        {"element": "electro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["electro", "cryo"]},
        rb, ra, "physical", [base._row("na1", "1-Hit DMG", "normal", 1, b8.RAZOR_NA_1, None)],
        weapon_source("12503", 1, "Eula", {}, subject=False),
        {"weapon:song_of_broken_pines/banner": 1},
        _figure(rb, ra, b8.RAZOR_NA_1, "physical", {"atk_pct": 0.2})))
    # The later batches, kept in their own modules as the kit batches are.
    from tests.unit.go_fixtures_weapons2 import five_star_fixtures
    from tests.unit.go_fixtures_weapons3 import four_star_fixtures
    out.extend(five_star_fixtures())
    out.extend(four_star_fixtures())
    return out

