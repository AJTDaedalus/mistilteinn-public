"""Math-fallback P3, task 12 (second batch): GO fixtures for the most-used 5-star weapons.

The method is `go_fixtures_weapons.py`'s, unchanged: GO's formula worked by hand with our seeded
refinement values written out, the weapon source from the resolver for a stated wielder. Most of
these are the wielder's own buffs, so the wielder is the optimized character and every stack
count each one reads is stated.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapons as w
from tests.unit import test_go_formula_fixtures as base

#: Lisa's seeded skill row at level 10, a catalyst user's Elemental Skill.
LISA_HOLD = ("Non-Conductive Hold DMG|{param1:P}", [5.76])
LISA_BASE = base._base_stats(base_atk=774.0, base_hp=9570.0, base_def=573.0,
                             elemental_mastery=96.0)
LISA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}

XB, XA = base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS
AB, AA = base.AYAKA_BASE, base.AYAKA_ARTIFACTS
KB, KA = b8.KAEYA_BASE, b8.PHYSICAL_ARTIFACTS
RB, RA = b8.RAZOR_BASE, b8.RAZOR_ARTIFACTS
KOB, KOA = b6.KOKOMI_BASE, b6.KOKOMI_ARTIFACTS
XTEAM = {**w.XIANGLING, "member_elements": w.XIANGLING_TEAM}
SWORD = {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]}
BOW = {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": ["pyro", "cryo"]}
CLAYMORE = {"element": "electro", "weapon_type": "WEAPON_CLAYMORE",
            "member_elements": ["electro", "pyro"]}
CATALYST_HYDRO = {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
                  "member_elements": ["hydro", "pyro"]}
CATALYST_ELECTRO = {"element": "electro", "weapon_type": "WEAPON_CATALYST",
                    "member_elements": ["electro", "pyro"]}

PRESS = base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None)
KAEYA_NA = base._row("na1", "1-Hit DMG", "normal", 1, b8.KAEYA_NA_1, None)
RAZOR_NA = base._row("na1", "1-Hit DMG", "normal", 1, b8.RAZOR_NA_1, None)
WAVE = base._row("wave", "Fiery Rain DMG Per Wave", "burst", 1, b8.AMBER_WAVE, None)
AIMED = base._row("aimed", "Fully-Charged Aimed Shot", "charged", 1, w.AMBER_AIMED, None)
AMBER_NA = {**base._row("na1", "1-Hit DMG", "normal", 1, w.AMBER_NA_1, None),
            "channel": "physical"}
KOKOMI_NA = base._row("na1", "1-Hit DMG", "normal", 1, b6.KOKOMI_NA_1, None)
LISA_ROW = base._row("hold", "Non-Conductive Hold DMG", "skill", 1, LISA_HOLD, None)


def mine(name: str, covers: str, go: str, who: str, weapon: str, nanoka_id: str, r: int,
         team: dict[str, Any], stats: tuple[dict[str, float], dict[str, float]], channel: str,
         row: dict[str, Any], talent: tuple[str, list[float]], conditionals: dict[str, Any],
         x: dict[str, float]) -> dict[str, Any]:
    """A fixture whose wielder is the optimized character."""
    return w._fx(
        name, covers, [w.FORMULA, f"{w.WEAPONS}{go}"], w._wielder(who, weapon, r, w.SUBJECT),
        team, stats[0], stats[1], channel, [row],
        w.weapon_source(nanoka_id, r, who, stats[0], subject=True,
                        receiver_element=team["element"]),
        conditionals, w._figure(stats[0], stats[1], talent, channel, x))


def five_star_fixtures() -> list[dict[str, Any]]:
    """One fixture per weapon on its main effect; R1 and R5 for a few."""
    out = [
        mine("aquila_favonia_r1_on_kaeya", "a self ATK%; the Falcon's proc named, not applied",
             "Sword/AquilaFavonia/index.tsx:17-57", "Kaeya", "Aquila Favonia", "11501", 1,
             SWORD, (KB, KA), "physical", KAEYA_NA, b8.KAEYA_NA_1, {}, {"atk_pct": 0.2}),
        mine("skyward_blade_r1_on_ayaka",
             "a self CRIT Rate; Skypiercing Might named, not applied",
             "Sword/SkywardBlade/index.tsx:18-57", "Kamisato Ayaka", "Skyward Blade", "11502",
             1, SWORD, (AB, AA), "cryo", PRESS, base.HYOUKA, {}, {"cr": 0.04}),
        mine("skyward_harp_r1_on_amber", "a self CRIT DMG; the AoE proc named, not applied",
             "Bow/SkywardHarp/index.tsx:17-40", "Amber", "Skyward Harp", "15501", 1, BOW,
             (w.AMBER_BASE, w.AMBER_ARTIFACTS), "pyro", WAVE, b8.AMBER_WAVE, {}, {"cd": 0.2}),
        mine("skyward_pride_r1_on_razor", "a self all-DMG bonus reaching a Physical hit",
             "Claymore/SkywardPride/index.tsx:16-46", "Razor", "Skyward Pride", "12501", 1,
             CLAYMORE, (RB, RA), "physical", RAZOR_NA, b8.RAZOR_NA_1, {}, {"dmg": 0.08}),
        mine("skyward_spine_r5_on_xiangling", "a self CRIT Rate at R5",
             "Polearm/SkywardSpine/index.tsx:17-48", "Xiangling", "Skyward Spine", "13502", 5,
             XTEAM, (XB, XA), "pyro", w.NADO, base.PYRONADO, {}, {"cr": 0.16}),
        mine("skyward_atlas_r1_on_kokomi", "a self Elemental DMG bonus for every element",
             "Catalyst/SkywardAtlas/index.tsx:17-52", "Sangonomiya Kokomi", "Skyward Atlas",
             "14501", 1, CATALYST_HYDRO, (KOB, KOA), "hydro", KOKOMI_NA, b6.KOKOMI_NA_1, {},
             {"dmg": 0.12}),
    ]
    for r, auto, step, n in ((1, 0.12, 0.08, 5), (5, 0.24, 0.16, 2)):
        out.append(mine(
            f"amos_bow_r{r}_on_amber_aimed",
            f"a self Normal and Charged Attack DMG and {n} steps of arrow flight (per stack)",
            "Bow/AmosBow/index.tsx:16-52", "Amber", "Amos' Bow", "15502", r, BOW,
            (w.AMBER_BASE, w.AMBER_ARTIFACTS), "pyro", AIMED, w.AMBER_AIMED,
            {"weapon:amos_bow/arrow": n}, {"dmg": auto + n * step}))
    for r, ele, atk, n in ((1, 0.12, 0.48, 4), (5, 0.24, 0.6, 3)):
        out.append(mine(
            f"polar_star_r{r}_on_amber_burst",
            f"a self Elemental Burst DMG and Ashen Nightstar's ATK% at {n} stacks (a table)",
            "Bow/PolarStar/index.tsx:9-38", "Amber", "Polar Star", "15507", r, BOW,
            (w.AMBER_BASE, w.AMBER_ARTIFACTS), "pyro", WAVE, b8.AMBER_WAVE,
            {"weapon:polar_star/ashen": n}, {"dmg": ele, "atk_pct": atk}))
    out += [
        mine("thundering_pulse_r1_on_amber_na",
             "a self ATK% and the Thunder Emblem's Normal Attack DMG at 3 stacks",
             "Bow/ThunderingPulse/index.tsx:9-34", "Amber", "Thundering Pulse", "15509", 1, BOW,
             (w.AMBER_BASE, w.AMBER_ARTIFACTS), "physical", AMBER_NA, w.AMBER_NA_1,
             {"weapon:thundering_pulse/emblem": 3}, {"atk_pct": 0.2, "dmg": 0.4}),
        mine("lost_prayer_r5_on_kokomi", "a self Elemental DMG per stack, four stacks",
             "Catalyst/LostPrayerToTheSacredWinds/index.tsx:17-44", "Sangonomiya Kokomi",
             "Lost Prayer to the Sacred Winds", "14502", 5, CATALYST_HYDRO, (KOB, KOA), "hydro",
             KOKOMI_NA, b6.KOKOMI_NA_1, {"weapon:lost_prayer_to_the_sacred_winds/stacks": 4},
             {"dmg": 4 * 0.16}),
        mine("kaguras_verity_r1_on_lisa",
             "a self Elemental Skill DMG per stack and Elemental DMG at three stacks; "
             "Stellar-Conduct named, not applied",
             "Catalyst/KagurasVerity/index.tsx:10-52", "Lisa", "Kagura's Verity", "14509", 1,
             CATALYST_ELECTRO, (LISA_BASE, LISA_ARTIFACTS), "electro", LISA_ROW, LISA_HOLD,
             {"weapon:kaguras_verity/dance": 3}, {"dmg": 3 * 0.12 + 0.12}),
    ]
    for r, ele, atk, off in ((1, 0.12, 0.032, 0), (5, 0.24, 0.064, 1)):
        out.append(mine(
            f"calamity_queller_r{r}_on_xiangling",
            "a self Elemental DMG and Consummation's ATK% at six stacks"
            + (", doubled off-field (stated on)" if off else ""),
            "Polearm/CalamityQueller/index.tsx:19-54", "Xiangling", "Calamity Queller",
            "13507", r, XTEAM, (XB, XA), "pyro", w.NADO, base.PYRONADO,
            {"weapon:calamity_queller/stacks": 6, "weapon:calamity_queller/off_field": off},
            {"dmg": ele, "atk_pct": 6 * atk * (2 if off else 1)}))
    out += [
        mine("primordial_jade_winged_spear_r1_on_xiangling",
             "a self ATK% per stack and DMG at seven stacks",
             "Polearm/PrimordialJadeWingedSpear/index.tsx:16-38", "Xiangling",
             "Primordial Jade Winged-Spear", "13505", 1, XTEAM, (XB, XA), "pyro", w.NADO,
             base.PYRONADO, {"weapon:primordial_jade_winged_spear/stacks": 7},
             {"atk_pct": 7 * 0.032, "dmg": 0.12}),
        mine("vortex_vanquisher_r1_on_xiangling_shielded",
             "a self ATK% per stack, doubled under a shield (stated on)",
             "Polearm/VortexVanquisher/index.tsx:17-42", "Xiangling", "Vortex Vanquisher",
             "13504", 1, XTEAM, (XB, XA), "pyro", w.NADO, base.PYRONADO,
             {"weapon:vortex_vanquisher/stacks": 5, "weapon:vortex_vanquisher/shield": 1},
             {"atk_pct": 2 * 5 * 0.04}),
        mine("summit_shaper_r5_on_ayaka", "a self ATK% per stack, unshielded, at R5",
             "Sword/SummitShaper/index.tsx:17-40", "Kamisato Ayaka", "Summit Shaper", "11504",
             5, SWORD, (AB, AA), "cryo", PRESS, base.HYOUKA,
             {"weapon:summit_shaper/stacks": 5, "weapon:summit_shaper/shield": 0},
             {"atk_pct": 5 * 0.08}),
        mine("haran_geppaku_futsu_r1_on_kaeya",
             "a self Normal Attack DMG per Wavespike; its Elemental DMG does not reach a "
             "Physical hit", "Sword/HaranGeppakuFutsu/index.tsx:16-42", "Kaeya",
             "Haran Geppaku Futsu", "11510", 1, SWORD, (KB, KA), "physical", KAEYA_NA,
             b8.KAEYA_NA_1, {"weapon:haran_geppaku_futsu/wavespike": 2}, {"dmg": 2 * 0.2}),
    ]
    out.append(_engulfing())
    return out


def _engulfing() -> dict[str, Any]:
    """Engulfing Lightning: its Energy Recharge feeds Emblem's burst bonus and its own ATK% from
    ER, per candidate since the owner's approval of 2026-11-14 (`DECISIONS.md` §45). It was
    withheld by name on the wielder in #389, GO's figure carrying it and ours not; now both
    agree."""
    emblem = base._set_source(15020, 4, [0.25, 0.75, 0, 0, 0, 0, 0, 0], [])
    er_total = 1.0 + 0.2 + 0.3
    emblem_dmg = min(0.25 * er_total, 0.75)
    gos = w._figure(XB, XA, base.PYRONADO, "pyro",
                    {"dmg": emblem_dmg, "atk_pct": min(0.28 * (er_total - 1), 0.8)})
    fixture = w._fx(
        "engulfing_lightning_r1_on_xiangling_emblem",
        "a self Energy Recharge after the burst (stated on), read by Emblem's burst bonus and "
        "by the wielder's own ATK% from Energy Recharge, per candidate",
        [w.FORMULA, f"{w.WEAPONS}Polearm/EngulfingLightning/index.tsx:16-52",
         "libs/gi/sheets/src/Artifacts/EmblemOfSeveredFate/index.tsx:13-24"],
        w._wielder("Xiangling", "Engulfing Lightning", 1, w.SUBJECT), XTEAM, XB, XA, "pyro",
        [w.NADO], w.weapon_source("13509", 1, "Xiangling", XB, subject=True),
        {"weapon:engulfing_lightning/dream": 1},
        gos)
    fixture["sources"].append(emblem)
    fixture["set_pools"] = [{"energy_recharge": 0.2}]
    return fixture
