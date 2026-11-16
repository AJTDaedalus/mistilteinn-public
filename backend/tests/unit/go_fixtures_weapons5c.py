"""Math-fallback P3, task 12 (fifth batch, continued): commonly used 4-star weapons.

The method and helpers are `go_fixtures_weapons5.py`'s: GO's formula worked by hand with our
seeded refinement values written out, the source from the resolver for a stated wielder, every
condition stated.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapon_compare as cmp
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base
from tests.unit.go_fixtures_weapons5 import (
    AMBER,
    AYAKA,
    KAEYA,
    KOKOMI,
    RAZOR,
    STAND_IN,
    XIANG,
    own,
    vape,
)


def _proc(name: str, go: str, gcsim_note: str, weapon: str, nanoka_id: str,
          slug: str) -> dict[str, Any]:
    """One instance of each of a Frost Burial weapon's two procs on Xiangling (R1: 80% and
    200% of total ATK, Physical)."""
    plain = cmp._proc_figure(*XIANG, count=1, multiplier=0.8)
    cryo = cmp._proc_figure(*XIANG, count=1, multiplier=2.0)
    return w._fx(
        name, "two proc rows: one Everfrost Icicle of each kind (80% and 200% ATK, Physical)"
        + STAND_IN, [w.FORMULA, f"{w.WEAPONS}{go}", cmp.PROC, gcsim_note],
        w._wielder("Xiangling", weapon, 1, w.SUBJECT), w2.XTEAM, *XIANG, "pyro",
        [cmp._proc_row(f"weapon:{slug}", "icicle", 1, base.PYRONADO, "Everfrost Icicle"),
         cmp._proc_row(f"weapon:{slug}", "icicle_cryo", 1, base.PYRONADO,
                       "Everfrost Icicle (Cryo)")],
        cmp.source(nanoka_id, 1, "Xiangling", XIANG[0], subject=True), {},
        lambda c: plain(c) + cryo(c))


def four_star_fixtures_a() -> list[dict[str, Any]]:
    """Each weapon on its main effect."""
    sword, bow, claymore, xteam = w2.SWORD, w2.BOW, w2.CLAYMORE, w2.XTEAM
    hydro = w2.CATALYST_HYDRO
    kaeya_atk = base._total(base._stats(*KAEYA), "atk")
    out = [
        own("mailed_flower_r1_on_razor", "a self ATK% and EM after a skill hit or reaction",
            "Claymore/MailedFlower/index.tsx:8-30", "Razor", "Mailed Flower", "12418", 1,
            claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:mailed_flower/passive": 1}, {"atk_pct": 0.12, "em": 48.0}),
        own("toukabou_shigure_r1_on_ayaka", "a self DMG against the Cursed Parasol's opponent",
            "Sword/ToukabouShigure/index.tsx:8-27", "Kamisato Ayaka", "Toukabou Shigure",
            "11422", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:toukabou_shigure/parasol": 1}, {"dmg": 0.16}),
        vape("ballad_of_the_fjords_r1_on_xiangling_vape",
             "a self EM with three elements in the party (stated on), into an amplifying "
             "reaction", "Polearm/BalladOfTheFjords/index.tsx:14-27", "Ballad of the Fjords",
             "13424", 1, {"weapon:ballad_of_the_fjords/three": 1}, {"em": 120.0}),
    ]
    for name, slug, nid, go in (("Prospector's Drill", "prospectors_drill", "13427",
                                 "Polearm/ProspectorsDrill/index.tsx:16-50"),
                                ("Range Gauge", "range_gauge", "15427",
                                 "Bow/RangeGauge/index.tsx:16-50")):
        out.append(own(f"{slug}_r1_on_xiangling",
                       "a self ATK% and Elemental DMG per Symbol consumed, three (stated)"
                       + ("" if slug == "prospectors_drill" else STAND_IN), go, "Xiangling",
                       name, nid, 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
                       {f"weapon:{slug}/symbols": 3}, {"atk_pct": 3 * 0.03, "dmg": 3 * 0.07}))
    for name, slug, nid, go in (("The Dockhand's Assistant", "the_dockhands_assistant", "11427",
                                 "Sword/TheDockhandsAssistant/index.tsx:16-38"),
                                ("Portable Power Saw", "portable_power_saw", "12427",
                                 "Claymore/PortablePowerSaw/index.tsx:16-38")):
        out.append(vape(f"{slug}_r1_on_xiangling_vape",
                        "a self EM per Symbol consumed, three (stated), into an amplifying "
                        "reaction" + STAND_IN, go, name, nid, 1, {f"weapon:{slug}/symbols": 3},
                        {"em": 3 * 40.0}))
    out += [
        own("tidal_shadow_r1_on_razor", "a self ATK% after being healed (stated on)",
            "Claymore/TidalShadow/index.tsx:8-23", "Razor", "Tidal Shadow", "12425", 1, claymore,
            RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1, {"weapon:tidal_shadow/healed": 1},
            {"atk_pct": 0.24}),
        own("sturdy_bone_r1_on_kaeya",
            "a self Normal Attack flat DMG from the wielder's own ATK after a Sprint, per "
            "candidate", "Sword/SturdyBone/index.tsx:8-35", "Kaeya", "Sturdy Bone", "11430", 1,
            sword, KAEYA, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1,
            {"weapon:sturdy_bone/sprint": 1}, {"flat": 0.16 * kaeya_atk}),
        own("blackcliff_agate_r1_on_kokomi", "a self ATK% per opponent defeated, three (stated)",
            "Catalyst/BlackcliffAgate/index.tsx:15-35", "Sangonomiya Kokomi",
            "Blackcliff Agate", "14408", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:blackcliff_agate/kills": 3}, {"atk_pct": 3 * 0.12}),
        own("blackcliff_pole_r5_on_xiangling", "the same at R5",
            "Polearm/BlackcliffPole/index.tsx:15-35", "Xiangling", "Blackcliff Pole", "13404", 5,
            xteam, XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:blackcliff_pole/kills": 3},
            {"atk_pct": 3 * 0.24}),
        own("blackcliff_slasher_r1_on_razor", "a self ATK% per opponent defeated, three",
            "Claymore/BlackcliffSlasher/index.tsx:15-35", "Razor", "Blackcliff Slasher", "12408",
            1, claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:blackcliff_slasher/kills": 3}, {"atk_pct": 3 * 0.12}),
        own("blackcliff_warbow_r1_on_amber", "a self ATK% per opponent defeated, three",
            "Bow/BlackcliffWarbow/index.tsx:15-35", "Amber", "Blackcliff Warbow", "15408", 1,
            bow, AMBER, "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:blackcliff_warbow/kills": 3},
            {"atk_pct": 3 * 0.12}),
        own("royal_bow_r1_on_amber", "a self CRIT Rate per Focus stack, five",
            "Bow/RoyalBow/index.tsx:15-33", "Amber", "Royal Bow", "15404", 1, bow, AMBER, "pyro",
            w2.WAVE, b8.AMBER_WAVE, {"weapon:royal_bow/focus": 5}, {"cr": 5 * 0.08}),
        own("royal_greatsword_r1_on_razor", "a self CRIT Rate per Focus stack, five",
            "Claymore/RoyalGreatsword/index.tsx:15-33", "Razor", "Royal Greatsword", "12404", 1,
            claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:royal_greatsword/focus": 5}, {"cr": 5 * 0.08}),
        own("royal_grimoire_r5_on_kokomi", "the same at R5, three stacks (five would pass "
            "100% CRIT Rate)",
            "Catalyst/RoyalGrimoire/index.tsx:15-33", "Sangonomiya Kokomi", "Royal Grimoire",
            "14404", 5, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:royal_grimoire/focus": 3}, {"cr": 3 * 0.16}),
        own("royal_longsword_r1_on_ayaka", "a self CRIT Rate per Focus stack, five",
            "Sword/RoyalLongsword/index.tsx:15-33", "Kamisato Ayaka", "Royal Longsword", "11404",
            1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA, {"weapon:royal_longsword/focus": 5},
            {"cr": 5 * 0.08}),
        own("royal_spear_r1_on_xiangling", "a self CRIT Rate per Focus stack, five",
            "Polearm/RoyalSpear/index.tsx:15-33", "Xiangling", "Royal Spear", "13408", 1, xteam,
            XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:royal_spear/focus": 5},
            {"cr": 5 * 0.08}),
        own("lithic_blade_r1_on_razor", "a self ATK% and CRIT Rate per Liyue member, four "
            "(stated)", "Claymore/LithicBlade/index.tsx:8-27", "Razor", "Lithic Blade", "12410",
            1, claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:lithic_blade/liyue": 4}, {"atk_pct": 4 * 0.07, "cr": 4 * 0.03}),
        own("lithic_spear_r1_on_xiangling", "a self ATK% and CRIT Rate per Liyue member, four "
            "(stated)", "Polearm/LithicSpear/index.tsx:8-27", "Xiangling", "Lithic Spear",
            "13406", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:lithic_spear/liyue": 4}, {"atk_pct": 4 * 0.07, "cr": 4 * 0.03}),
        own("mitternachts_waltz_r1_on_amber_na",
            "a self Normal Attack DMG after a skill hit (both stated on)",
            "Bow/MitternachtsWaltz/index.tsx:8-32", "Amber", "Mitternachts Waltz", "15412", 1,
            bow, AMBER, "physical", w2.AMBER_NA, w.AMBER_NA_1,
            {"weapon:mitternachts_waltz/skill": 1, "weapon:mitternachts_waltz/normal": 1},
            {"dmg": 0.2}),
        own("hamayumi_r1_full_on_amber_aimed",
            "a self Charged Attack DMG, doubled at full Energy (stated on)",
            "Bow/Hamayumi/index.tsx:9-38", "Amber", "Hamayumi", "15414", 1, bow, AMBER, "pyro",
            w2.AIMED, w.AMBER_AIMED, {"weapon:hamayumi/full": 1}, {"dmg": 2 * 0.12}),
    ]
    out += [
        _proc("dragonspine_spear_r1_proc_row_on_xiangling",
              "Polearm/DragonspineSpear/index.tsx:16-52",
              "gcsim: internal/weapons/spear/dragonspine/dragonspine.go:34-68",
              "Dragonspine Spear", "13409", "dragonspine_spear"),
        _proc("frostbearer_r1_proc_row_on_xiangling", "Catalyst/Frostbearer/index.tsx:17-54",
              "gcsim: internal/weapons/catalyst/frostbearer/frostbearer.go:34-71",
              "Frostbearer", "14412", "frostbearer"),
        _proc("snow_tombed_starsilver_r1_proc_row_on_xiangling",
              "Claymore/SnowTombedStarsilver/index.tsx:16-53",
              "gcsim: internal/weapons/claymore/starsilver/starsilver.go:33-67",
              "Snow-Tombed Starsilver", "12411", "snow_tombed_starsilver"),
    ]
    return out
