"""Math-fallback P3, task 12 (third batch): GO fixtures for the commonly used 4-star weapons.

The method is `go_fixtures_weapons.py`'s, unchanged. A target-state condition (an opponent's
aura), a shield, a kill or an off-field wielder is situational and off by default; each fixture
here states it on, so the figure checks the effect it gates.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base

#: Kokomi's seeded burst row at level 10: a Max HP scaling hit.
KOKOMI_BURST = ("Skill DMG|{param1:F1P} Max HP", [0.187488])
KOKOMI_BURST_ROW = base._row("burst", "Skill DMG", "burst", 1, KOKOMI_BURST, None)

mine = w2.mine


def four_star_fixtures() -> list[dict[str, Any]]:
    """One fixture per weapon on its main effect."""
    lisa = (w2.LISA_BASE, w2.LISA_ARTIFACTS)
    xian = (w2.XB, w2.XA)
    kaeya = (w2.KB, w2.KA)
    razor = (w2.RB, w2.RA)
    amber = (w.AMBER_BASE, w.AMBER_ARTIFACTS)
    kokomi = (w2.KOB, w2.KOA)
    out = [
        mine("the_widsith_r1_aria_on_lisa", "a self choice: Aria's Elemental DMG",
             "Catalyst/TheWidsith/index.tsx:9-46", "Lisa", "The Widsith", "14402", 1,
             w2.CATALYST_ELECTRO, lisa, "electro", w2.LISA_ROW, w2.LISA_HOLD,
             {"weapon:the_widsith/song": "aria"}, {"dmg": 0.48}),
        mine("the_widsith_r5_recitative_on_lisa", "a self choice: Recitative's ATK% at R5",
             "Catalyst/TheWidsith/index.tsx:9-46", "Lisa", "The Widsith", "14402", 5,
             w2.CATALYST_ELECTRO, lisa, "electro", w2.LISA_ROW, w2.LISA_HOLD,
             {"weapon:the_widsith/song": "recitative"}, {"atk_pct": 1.2}),
        mine("iron_sting_r1_on_kaeya", "a self all-DMG per stack, two stacks",
             "Sword/IronSting/index.tsx:16-34", "Kaeya", "Iron Sting", "11407", 1, w2.SWORD,
             kaeya, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1, {"weapon:iron_sting/stacks": 2},
             {"dmg": 2 * 0.06}),
        mine("alley_hunter_r5_on_amber_burst", "a self all-DMG per stack, ten stacks, at R5",
             "Bow/AlleyHunter/index.tsx:15-34", "Amber", "Alley Hunter", "15410", 5, w2.BOW,
             amber, "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:alley_hunter/stacks": 10},
             {"dmg": 10 * 0.04}),
        mine("mappa_mare_r1_on_kokomi", "a self Elemental DMG per stack, two stacks",
             "Catalyst/MappaMare/index.tsx:16-35", "Sangonomiya Kokomi", "Mappa Mare", "14407",
             1, w2.CATALYST_HYDRO, kokomi, "hydro", w2.KOKOMI_NA, w2.b6.KOKOMI_NA_1,
             {"weapon:mappa_mare/stacks": 2}, {"dmg": 2 * 0.08}),
        mine("prototype_rancour_r5_on_kaeya", "a self ATK% and DEF% per stack, four stacks",
             "Sword/PrototypeRancour/index.tsx:15-39", "Kaeya", "Prototype Rancour", "11406", 5,
             w2.SWORD, kaeya, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1,
             {"weapon:prototype_rancour/stacks": 4}, {"atk_pct": 4 * 0.08, "def_pct": 4 * 0.08}),
        mine("the_bell_r1_on_razor_shielded", "a self all-DMG while shielded (stated on)",
             "Claymore/TheBell/index.tsx:15-48", "Razor", "The Bell", "12402", 1, w2.CLAYMORE,
             razor, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1, {"weapon:the_bell/shield": 1},
             {"dmg": 0.12}),
        mine("serpent_spine_r1_on_razor", "a self all-DMG per stack, five stacks",
             "Claymore/SerpentSpine/index.tsx:15-35", "Razor", "Serpent Spine", "12409", 1,
             w2.CLAYMORE, razor, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
             {"weapon:serpent_spine/stacks": 5}, {"dmg": 5 * 0.06}),
        mine("rainslasher_r1_on_razor", "a self DMG against an aura the estimate does not "
             "track, stated on", "Claymore/Rainslasher/index.tsx:8-21", "Razor", "Rainslasher",
             "12405", 1, w2.CLAYMORE, razor, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
             {"weapon:rainslasher/aura": 1}, {"dmg": 0.2}),
        mine("dragons_bane_r5_on_xiangling", "a self DMG against an aura, stated on, at R5",
             "Polearm/DragonsBane/index.tsx:8-21", "Xiangling", "Dragon's Bane", "13401", 5,
             w2.XTEAM, xian, "pyro", w.NADO, base.PYRONADO, {"weapon:dragons_bane/aura": 1},
             {"dmg": 0.36}),
        mine("lions_roar_r1_on_kaeya", "a self DMG against an aura, stated on",
             "Sword/LionsRoar/index.tsx:8-22", "Kaeya", "Lion's Roar", "11405", 1, w2.SWORD,
             kaeya, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1, {"weapon:lions_roar/aura": 1},
             {"dmg": 0.2}),
        mine("deathmatch_r1_one_opponent_on_xiangling",
             "a self choice by opponent count: one opponent's ATK%",
             "Polearm/Deathmatch/index.tsx:14-40", "Xiangling", "Deathmatch", "13405", 1,
             w2.XTEAM, xian, "pyro", w.NADO, base.PYRONADO,
             {"weapon:deathmatch/opponents": "one_or_none"}, {"atk_pct": 0.24}),
        mine("deathmatch_r5_two_opponents_on_xiangling",
             "a self choice by opponent count: two opponents' ATK% and DEF%, at R5",
             "Polearm/Deathmatch/index.tsx:14-40", "Xiangling", "Deathmatch", "13405", 5,
             w2.XTEAM, xian, "pyro", w.NADO, base.PYRONADO,
             {"weapon:deathmatch/opponents": "more_than_one"},
             {"atk_pct": 0.32, "def_pct": 0.32}),
        mine("blackcliff_longsword_r1_on_kaeya", "a self ATK% per kill, three stated",
             "Sword/BlackcliffLongsword/index.tsx:15-33", "Kaeya", "Blackcliff Longsword",
             "11408", 1, w2.SWORD, kaeya, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1,
             {"weapon:blackcliff_longsword/kills": 3}, {"atk_pct": 3 * 0.12}),
    ]
    jade = mine("sacrificial_jade_r1_on_kokomi_burst",
                "a self HP% and EM off-field (stated on), on a Max HP scaling hit",
                "Catalyst/SacrificialJade/index.tsx:8-31", "Sangonomiya Kokomi",
                "Sacrificial Jade", "14424", 1, w2.CATALYST_HYDRO, kokomi, "hydro",
                KOKOMI_BURST_ROW, KOKOMI_BURST, {"weapon:sacrificial_jade/off_field": 1},
                {"hp_pct": 0.32, "em": 40.0})
    jade["expected"] = w._figure(w2.KOB, w2.KOA, KOKOMI_BURST, "hydro",
                                 {"hp_pct": 0.32, "em": 40.0}, scaling="hp")(
        base.OUR_EM_COEFFICIENT)
    jade["go_value"] = jade["expected"]
    out.append(jade)

    collei = {"element": "pyro", "weapon_type": "WEAPON_POLE",
              "member_elements": ["pyro", "hydro", "dendro", "anemo"]}
    out.append(w._fx(
        "sapwood_blade_r1_on_xiangling_vape",
        "a teammate's weapon: EM to the active character from the Leaf (active), into an "
        "amplifying reaction",
        [w.FORMULA_AMP, f"{w.WEAPONS}Sword/SapwoodBlade/index.tsx:15-37"],
        w._wielder("Collei", "Sapwood Blade", 1, {}), collei, w2.XB, w2.XA, "pyro",
        [w.NADO_VAPE], w.weapon_source("11417", 1, "Collei", {}, subject=False),
        {"weapon:sapwood_blade/leaf": 1},
        w._figure(w2.XB, w2.XA, base.PYRONADO, "pyro", {"em": 60.0}, amplifying=True),
        w.AMP_DIVERGENCE))
    return out
