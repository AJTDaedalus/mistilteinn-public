"""Math-fallback P3, task 12 (fifth batch, continued): more 4-star weapons.

The method and helpers are `go_fixtures_weapons5.py`'s. An Energy Recharge passive is checked
through Emblem of Severed Fate's burst bonus, which reads it (`EmblemOfSeveredFate/index.tsx:
13-24`, `min(0.25 × ER, 0.75)`), as Engulfing Lightning's fixture is.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapon_compare as cmp
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base
from tests.unit.go_fixtures_weapons5 import (
    AMBER,
    AYAKA,
    KACHINA,
    KACHINA_ROW,
    KACHINA_TEAM,
    KAEYA,
    KOKOMI,
    RAZOR,
    STAND_IN,
    XIANG,
    mate,
    own,
    vape,
)
from tests.unit.go_fixtures_weapons5b import PLUNGE

EMBLEM = "libs/gi/sheets/src/Artifacts/EmblemOfSeveredFate/index.tsx:13-24"


def _emblem(fixture: dict[str, Any]) -> dict[str, Any]:
    """Emblem of Severed Fate's 4-piece beside the weapon, its 2-piece's 20% ER in the pool."""
    fixture["sources"].append(base._set_source(15020, 4, [0.25, 0.75, 0, 0, 0, 0, 0, 0], []))
    fixture["set_pools"] = [{"energy_recharge": 0.2}]
    fixture["go"].append(EMBLEM)
    return fixture


def _proc(name: str, covers: str, go: str, gcsim: str, who: str, weapon: str, nanoka_id: str,
          slug: str, key: str, label: str, team: dict[str, Any],
          stats: tuple[dict[str, float], dict[str, float]], talent: tuple[str, list[float]],
          channel: str, count: float, multiplier: float) -> dict[str, Any]:
    return w._fx(
        name, covers, [w.FORMULA, f"{w.WEAPONS}{go}", cmp.PROC, f"gcsim: {gcsim}"],
        w._wielder(who, weapon, 1, w.SUBJECT), team, *stats, channel,
        [cmp._proc_row(f"weapon:{slug}", key, count, talent, label)],
        cmp.source(nanoka_id, 1, who, stats[0], subject=True, receiver_element=team["element"]),
        {}, cmp._proc_figure(*stats, count=count, multiplier=multiplier))


def _sea_lord() -> dict[str, Any]:
    """Luxurious Sea-Lord on Xiangling: its burst DMG on the Pyronado, and one tuna (100% of
    total ATK, Physical) as a proc row that the burst DMG does not reach."""
    burst = w._figure(*XIANG, base.PYRONADO, "pyro", {"dmg": 0.12})
    tuna = cmp._proc_figure(*XIANG, count=1, multiplier=1.0)
    return w._fx(
        "luxurious_sea_lord_r1_on_xiangling",
        "a self Elemental Burst DMG, and a proc row of one tuna (100% ATK, Physical) it does "
        "not reach" + STAND_IN,
        [w.FORMULA, f"{w.WEAPONS}Claymore/LuxuriousSeaLord/index.tsx:16-44", cmp.PROC,
         "gcsim: internal/weapons/claymore/sealord/sealord.go:46-73"],
        w._wielder("Xiangling", "Luxurious Sea-Lord", 1, w.SUBJECT), w2.XTEAM, *XIANG, "pyro",
        [w.NADO, cmp._proc_row("weapon:luxurious_sea_lord", "tuna", 1, base.PYRONADO, "Tuna")],
        cmp.source("12412", 1, "Xiangling", XIANG[0], subject=True), {},
        lambda c: burst(c) + tuna(c))


def four_star_fixtures_b() -> list[dict[str, Any]]:
    """Each weapon on its main effect."""
    sword, bow, claymore, xteam = w2.SWORD, w2.BOW, w2.CLAYMORE, w2.XTEAM
    hydro = w2.CATALYST_HYDRO
    kokomi_low_hp = (KOKOMI[0], {**KOKOMI[1], "hp_pct": 0.0})
    hp_kokomi = base._total(base._stats(*KOKOMI), "hp")
    hp_low = base._total(base._stats(*kokomi_low_hp), "hp")
    return [
        own("cinnabar_spindle_r1_on_kachina",
            "a self Elemental Skill flat DMG from the wielder's own DEF, per candidate" + STAND_IN,
            "Sword/CinnabarSpindle/index.tsx:9-37", "Kachina", "Cinnabar Spindle", "11415", 1,
            KACHINA_TEAM, KACHINA, "geo", KACHINA_ROW, base.KACHINA_INDEPENDENT,
            {"weapon:cinnabar_spindle/spotless": 1}, {"flat_from_def": 0.4}, scaling="def"),
        own("katsuragikiri_nagamasa_r1_on_ayaka", "a self Elemental Skill DMG" + STAND_IN,
            "Claymore/KatsuragikiriNagamasa/index.tsx:8-17", "Kamisato Ayaka",
            "Katsuragikiri Nagamasa", "12414", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {}, {"dmg": 0.06}),
        own("kitain_cross_spear_r5_on_ayaka", "a self Elemental Skill DMG at R5" + STAND_IN,
            "Polearm/KitainCrossSpear/index.tsx:8-16", "Kamisato Ayaka", "Kitain Cross Spear",
            "13414", 5, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA, {}, {"dmg": 0.12}),
        _emblem(own("oathsworn_eye_r1_emblem_on_xiangling",
                    "a self Energy Recharge after a skill, read by Emblem's burst bonus"
                    + STAND_IN, "Catalyst/OathswornEye/index.tsx:8-20", "Xiangling",
                    "Oathsworn Eye", "14415", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
                    {"weapon:oathsworn_eye/after_skill": 1},
                    {"dmg": min(0.25 * (1.0 + 0.2 + 0.24), 0.75)})),
        own("wine_and_song_r1_on_kokomi", "a self ATK% after a Sprint",
            "Catalyst/WineAndSong/index.tsx:8-23", "Sangonomiya Kokomi", "Wine and Song",
            "14410", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:wine_and_song/sprint": 1}, {"atk_pct": 0.2}),
        own("solar_pearl_r1_on_kokomi",
            "a self Normal Attack DMG after a skill or burst hit (both stated on)",
            "Catalyst/SolarPearl/index.tsx:8-25", "Sangonomiya Kokomi", "Solar Pearl", "14405",
            1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:solar_pearl/after_normal": 1, "weapon:solar_pearl/after_skill_burst": 1},
            {"dmg": 0.2}),
        own("prototype_crescent_r1_on_amber", "a self ATK% after a weak-point hit (stated on)",
            "Bow/PrototypeCrescent/index.tsx:8-20", "Amber", "Prototype Crescent", "15406", 1,
            bow, AMBER, "pyro", w2.WAVE, b8.AMBER_WAVE,
            {"weapon:prototype_crescent/weak_point": 1}, {"atk_pct": 0.36}),
        own("prototype_starglitter_r1_on_kaeya",
            "a self Normal and Charged Attack DMG per stack, two" + STAND_IN,
            "Polearm/PrototypeStarglitter/index.tsx:15-38", "Kaeya", "Prototype Starglitter",
            "13402", 1, sword, KAEYA, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1,
            {"weapon:prototype_starglitter/stacks": 2}, {"dmg": 2 * 0.08}),
        own("whiteblind_r1_on_razor", "a self ATK% and DEF% per stack, four",
            "Claymore/Whiteblind/index.tsx:15-39", "Razor", "Whiteblind", "12407", 1, claymore,
            RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1, {"weapon:whiteblind/stacks": 4},
            {"atk_pct": 4 * 0.06, "def_pct": 4 * 0.06}),
        own("compound_bow_r1_on_amber", "a self ATK% per stack, four",
            "Bow/CompoundBow/index.tsx:15-44", "Amber", "Compound Bow", "15407", 1, bow, AMBER,
            "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:compound_bow/stacks": 4},
            {"atk_pct": 4 * 0.04}),
        own("windblume_ode_r1_on_amber", "a self ATK% after a skill",
            "Bow/WindblumeOde/index.tsx:8-18", "Amber", "Windblume Ode", "15413", 1, bow, AMBER,
            "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:windblume_ode/after_skill": 1},
            {"atk_pct": 0.16}),
        own("the_alley_flash_r1_on_ayaka", "a self DMG while not hit",
            "Sword/TheAlleyFlash/index.tsx:9-23", "Kamisato Ayaka", "The Alley Flash", "11410",
            1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:the_alley_flash/untouched": 1}, {"dmg": 0.12}),
        own("the_black_sword_r1_on_kaeya", "a self Normal and Charged Attack DMG",
            "Sword/TheBlackSword/index.tsx:15-42", "Kaeya", "The Black Sword", "11409", 1, sword,
            KAEYA, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1, {}, {"dmg": 0.2}),
        _emblem(mate("xiphos_moonlight_r1_emblem_on_xiangling",
                     "a teammate's weapon: 30% of the wielder's Energy Recharge from EM, read "
                     "by Emblem's burst bonus", "Sword/XiphosMoonlight/index.tsx:17-56",
                     "Kaedehara Kazuha", "Xiphos' Moonlight", "11418", 1,
                     {"elemental_mastery": 800.0}, {},
                     {"dmg": min(0.25 * (1.0 + 0.2 + 0.3 * 0.00036 * 800.0), 0.75)})),
        vape("fruit_of_fulfillment_r1_on_xiangling_vape",
             "a self EM per stack, five, and the 5% ATK lost per stack, into an amplifying "
             "reaction" + STAND_IN, "Catalyst/FruitOfFulfillment/index.tsx:17-46",
             "Fruit of Fulfillment", "14417", 1, {"weapon:fruit_of_fulfillment/stacks": 5},
             {"em": 5 * 24.0, "atk_pct": 5 * -0.05}),
        own("missive_windspear_r1_on_xiangling", "a self ATK% and EM after a reaction",
            "Polearm/MissiveWindspear/index.tsx:8-29", "Xiangling", "Missive Windspear",
            "13419", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:missive_windspear/reaction": 1}, {"atk_pct": 0.12, "em": 48.0}),
        own("moonpiercer_r1_on_xiangling",
            "the active character's ATK% from the Leaf of Revival, the wielder active",
            "Polearm/Moonpiercer/index.tsx:16-36", "Xiangling", "Moonpiercer", "13417", 1, xteam,
            XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:moonpiercer/leaf": 1},
            {"atk_pct": 0.16}),
        vape("ibis_piercer_r1_on_xiangling_vape",
             "a self EM per stack, two, into an amplifying reaction" + STAND_IN,
             "Bow/IbisPiercer/index.tsx:15-33", "Ibis Piercer", "15419", 1,
             {"weapon:ibis_piercer/stacks": 2}, {"em": 2 * 40.0}),
        vape("kings_squire_r1_on_xiangling_vape",
             "a self EM in Teachings of the Forest, into an amplifying reaction" + STAND_IN,
             "Bow/KingsSquire/index.tsx:15-47", "King's Squire", "15417", 1,
             {"weapon:kings_squire/teachings": 1}, {"em": 60.0}),
        own("fading_twilight_r1_dawnblaze_on_amber", "a self DMG in Dawnblaze (stated)",
            "Bow/FadingTwilight/index.tsx:9-32", "Amber", "Fading Twilight", "15411", 1, bow,
            AMBER, "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:fading_twilight/state": "dawnblaze"},
            {"dmg": 0.14}),
        own("flowing_purity_r1_on_kokomi",
            "a self Elemental DMG after a skill, and after the Bond clears Elemental DMG from 24% "
            "of the wielder's own Max HP per 1,000, past its cap, per candidate",
            "Catalyst/FlowingPurity/index.tsx:19-71", "Sangonomiya Kokomi", "Flowing Purity",
            "14425", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:flowing_purity/after_skill": 1, "weapon:flowing_purity/bond": 1},
            {"dmg": 0.08 + min(0.02 * 0.24 * hp_kokomi / 1000, 0.12)}),
        own("ballad_of_the_boundless_blue_r1_on_kokomi",
            "a self Normal Attack DMG per stack, three",
            "Catalyst/BalladOfTheBoundlessBlue/index.tsx:15-48", "Sangonomiya Kokomi",
            "Ballad of the Boundless Blue", "14426", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:ballad_of_the_boundless_blue/hits": 3}, {"dmg": 3 * 0.08}),
        own("dodoco_tales_r1_on_kokomi",
            "a self ATK% after a Charged hit; its Charged Attack DMG does not reach a Normal "
            "Attack", "Catalyst/DodocoTales/index.tsx:8-31", "Sangonomiya Kokomi",
            "Dodoco Tales", "14413", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:dodoco_tales/after_normal": 1, "weapon:dodoco_tales/after_charged": 1},
            {"atk_pct": 0.08}),
        own("song_of_stillness_r1_on_amber", "a self DMG after being healed (stated on)",
            "Bow/SongOfStillness/index.tsx:8-23", "Amber", "Song of Stillness", "15425", 1, bow,
            AMBER, "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:song_of_stillness/healed": 1},
            {"dmg": 0.16}),
        own("scion_of_the_blazing_sun_r1_on_amber_aimed",
            "a self Charged Attack DMG against Heartsearer",
            "Bow/ScionOfTheBlazingSun/index.tsx:16-39", "Amber", "Scion of the Blazing Sun",
            "15424", 1, bow, AMBER, "pyro", w2.AIMED, w.AMBER_AIMED,
            {"weapon:scion_of_the_blazing_sun/heartsearer": 1}, {"dmg": 0.28}),
        own("talking_stick_r1_on_razor",
            "a self ATK% after Pyro (stated on); its Elemental DMG does not reach a Physical hit",
            "Claymore/TalkingStick/index.tsx:10-38", "Razor", "Talking Stick", "12424", 1,
            claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:talking_stick/pyro": 1, "weapon:talking_stick/other": 1},
            {"atk_pct": 0.16}),
        own("sacrificers_staff_r1_on_xiangling", "a self ATK% per stack, three",
            "Polearm/SacrificersStaff/index.tsx:15-43", "Xiangling", "Sacrificer's Staff",
            "13434", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:sacrificers_staff/stacks": 3}, {"atk_pct": 3 * 0.08}),
        own("flower_wreathed_feathers_r1_on_amber_aimed",
            "a self Charged Attack DMG per stack, six",
            "Bow/FlowerWreathedFeathers/index.tsx:14-32", "Amber", "Flower-Wreathed Feathers",
            "15430", 1, bow, AMBER, "pyro", w2.AIMED, w.AMBER_AIMED,
            {"weapon:flower_wreathed_feathers/stacks": 6}, {"dmg": 6 * 0.06}),
        own("fruitful_hook_r1_on_xiangling_plunge",
            "a self Plunging Attack CRIT Rate and DMG after a plunge" + STAND_IN,
            "Claymore/FruitfulHook/index.tsx:8-34", "Xiangling", "Fruitful Hook", "12430", 1,
            xteam, XIANG, "physical", PLUNGE, b4.XIANGLING_HIGH_PLUNGE,
            {"weapon:fruitful_hook/after_plunge": 1}, {"cr": 0.16, "dmg": 0.16}),
        own("flute_of_ezpitzal_r1_on_kachina", "a self DEF% after a skill on a DEF row"
            + STAND_IN, "Sword/FluteOfEzpitzal/index.tsx:8-22", "Kachina", "Flute of Ezpitzal",
            "11431", 1, KACHINA_TEAM, KACHINA, "geo", KACHINA_ROW, base.KACHINA_INDEPENDENT,
            {"weapon:flute_of_ezpitzal/after_skill": 1}, {"def_pct": 0.16}, scaling="def"),
        own("ring_of_yaxche_r1_on_kokomi",
            "a self Normal Attack DMG per 1,000 of the wielder's own Max HP, below its cap, per "
            "candidate", "Catalyst/RingOfYaxche/index.tsx:8-40", "Sangonomiya Kokomi",
            "Ring of Yaxche", "14431", 1, hydro, kokomi_low_hp, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:ring_of_yaxche/crown": 1},
            {"dmg": min(0.006 * hp_low / 1000, 0.16)}),
        own("mountain_bracing_bolt_r1_on_ayaka",
            "a self Elemental Skill DMG and again after another member's skill" + STAND_IN,
            "Polearm/MountainBracingBolt/index.tsx:8-35", "Kamisato Ayaka",
            "Mountain-Bracing Bolt", "13430", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:mountain_bracing_bolt/other_skill": 1}, {"dmg": 0.12 + 0.12}),
        _sea_lord(),
        _proc("prototype_archaic_r1_proc_row_on_razor",
              "a proc row: one Crush (240% ATK, Physical)",
              "Claymore/PrototypeArchaic/index.tsx:16-36",
              "internal/weapons/claymore/prototype/prototype.go:29-57", "Razor",
              "Prototype Archaic", "12406", "prototype_archaic", "crush", "Crush", claymore,
              RAZOR, b8.RAZOR_NA_1, "electro", 1, 2.4),
        _proc("the_viridescent_hunt_r1_proc_row_on_amber",
              "a proc row: eight Cyclone ticks (40% ATK, Physical)",
              "Bow/TheViridescentHunt/index.tsx:16-31",
              "internal/weapons/bow/viridescent/viridescent.go:33-72", "Amber",
              "The Viridescent Hunt", "15409", "the_viridescent_hunt", "cyclone", "Cyclone", bow,
              AMBER, w.AMBER_NA_1, "pyro", 8, 0.4),
        _proc("eye_of_perception_r1_proc_row_on_kokomi",
              "a proc row: five bolt hits, the first and its four bounces (240% ATK, Physical)",
              "Catalyst/EyeOfPerception/index.tsx:16-37",
              "internal/weapons/catalyst/perception/perception.go:52-99", "Sangonomiya Kokomi",
              "Eye of Perception", "14409", "eye_of_perception", "bolt", "Bolt", hydro, KOKOMI,
              b6.KOKOMI_NA_1, "hydro", 5, 2.4),
    ]
