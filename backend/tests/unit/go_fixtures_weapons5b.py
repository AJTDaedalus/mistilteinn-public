"""Math-fallback P3, task 12 (fifth batch, continued): the remaining 5-star weapons.

The method and helpers are `go_fixtures_weapons5.py`'s: GO's formula worked by hand with our
seeded refinement values written out, the source from the resolver for a stated wielder, every
condition stated.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_reactions as rx
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base
from tests.unit.go_fixtures_weapons5 import (
    AMBER,
    AYAKA,
    KACHINA,
    KACHINA_ROW,
    KACHINA_TEAM,
    KOKOMI,
    RAZOR,
    STAND_IN,
    XIANG,
    mate,
    own,
    reaction,
    vape,
)

#: Kokomi's seeded burst "Skill DMG" at level 10: an Elemental Burst row on Max HP.
KOKOMI_BURST_HIT = ("Skill DMG|{param1:F1P} Max HP", [0.187488])
KOKOMI_BURST = base._row("burst", "Skill DMG", "burst", 1, KOKOMI_BURST_HIT, None)
PLUNGE = {**base._row("high", "Low/High Plunge DMG (high)", "plunge", 1,
                      b4.XIANGLING_HIGH_PLUNGE, None), "channel": "physical"}


def _hp(stats: tuple[dict[str, float], dict[str, float]]) -> float:
    return base._total(base._stats(*stats), "hp")


def five_star_fixtures() -> list[dict[str, Any]]:
    """The 5-star weapons of this batch, each on its main effect; R1 and R5 for some."""
    sword, bow, claymore, xteam = w2.SWORD, w2.BOW, w2.CLAYMORE, w2.XTEAM
    hydro = w2.CATALYST_HYDRO
    out = [
        own("a_teaspoon_of_transcendence_r1_on_razor", "a self ATK%; the Stellar parts named",
            "Claymore/ATeaspoonOfTranscendence/index.tsx:16-47", "Razor",
            "A Teaspoon of Transcendence", "12516", 1, claymore, RAZOR, "physical", w2.RAZOR_NA,
            b8.RAZOR_NA_1, {}, {"atk_pct": 0.28}),
        own("astral_vultures_crimson_plumage_r1_on_amber_aimed",
            "a self ATK% after a Swirl and Charged Attack DMG with two or more members of another "
            "element (stated)", "Bow/AstralVulturesCrimsonPlumage/index.tsx:18-62", "Amber",
            "Astral Vulture's Crimson Plumage", "15514", 1, bow, AMBER, "pyro", w2.AIMED,
            w.AMBER_AIMED,
            {"weapon:astral_vultures_crimson_plumage/swirl": 1,
             "weapon:astral_vultures_crimson_plumage/others": "two_or_more"},
            {"atk_pct": 0.24, "dmg": 0.48}),
        own("athame_artis_r1_on_amber_burst",
            "a self Elemental Burst CRIT DMG and ATK% after a burst hits; no Hexerei",
            "Sword/AthameArtis/index.tsx:20-77", "Amber", "Athame Artis", "11518", 1, bow, AMBER,
            "pyro", w2.WAVE, b8.AMBER_WAVE,
            {"weapon:athame_artis/burst_hit": 1, "weapon:athame_artis/hexerei": 0},
            {"cd": 0.16, "atk_pct": 0.2}),
        mate("athame_artis_r5_on_xiangling",
             "a teammate's weapon at R5: the active teammate's ATK%, 75% more with Hexerei "
             "(stated on)", "Sword/AthameArtis/index.tsx:20-77", "Kamisato Ayato",
             "Athame Artis", "11518", 5, {},
             {"weapon:athame_artis/burst_hit": 1, "weapon:athame_artis/hexerei": 1},
             {"atk_pct": 0.32 * 1.75}),
        own("beacon_of_the_reed_sea_r1_on_razor",
            "a self ATK% after a skill and after taking DMG (stated on), Max HP% unshielded",
            "Claymore/BeaconOfTheReedSea/index.tsx:8-61", "Razor", "Beacon of the Reed Sea",
            "12511", 1, claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:beacon_of_the_reed_sea/after_skill": 1,
             "weapon:beacon_of_the_reed_sea/after_dmg": 1,
             "weapon:beacon_of_the_reed_sea/no_shield": 1},
            {"atk_pct": 0.2 + 0.2, "hp_pct": 0.32}),
        own("beyond_the_chrysalis_r1_on_ayaka", "a self CRIT DMG in Winds of Devotion",
            "Sword/BeyondTheChrysalis/index.tsx:8-32", "Kamisato Ayaka", "Beyond the Chrysalis",
            "11522", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:beyond_the_chrysalis/devotion": 1}, {"cd": 0.56}),
        own("cashflow_supervision_r1_on_kokomi",
            "a self ATK% and Normal Attack DMG per stack, three",
            "Catalyst/CashflowSupervision/index.tsx:17-80", "Sangonomiya Kokomi",
            "Cashflow Supervision", "14513", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:cashflow_supervision/stacks": 3},
            {"atk_pct": 0.16, "dmg": 3 * 0.16}),
        own("cranes_echoing_call_r1_on_xiangling_plunge",
            "the party's Plunging Attack DMG, the wielder among them" + STAND_IN,
            "Catalyst/CranesEchoingCall/index.tsx:8-29", "Xiangling", "Crane's Echoing Call",
            "14515", 1, xteam, XIANG, "physical", PLUNGE, b4.XIANGLING_HIGH_PLUNGE,
            {"weapon:cranes_echoing_call/plunged": 1}, {"dmg": 0.28}),
        own("crimson_moons_semblance_r1_on_xiangling",
            "a self DMG with a Bond of Life of 30% Max HP or more (stated)",
            "Polearm/CrimsonMoonsSemblance/index.tsx:8-34", "Xiangling",
            "Crimson Moon's Semblance", "13512", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:crimson_moons_semblance/bond": "at_least_30"}, {"dmg": 0.12 + 0.24}),
        own("disaster_and_remorse_r1_on_xiangling",
            "a self Elemental Burst DMG in Irreparable; no Hexerei",
            "Polearm/DisasterAndRemorse/index.tsx:18-51", "Xiangling", "Disaster and Remorse",
            "13517", 1, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:disaster_and_remorse/unforgivable": 1,
             "weapon:disaster_and_remorse/irreparable": 1,
             "weapon:disaster_and_remorse/hexerei": 0}, {"dmg": 0.4}),
        own("disaster_and_remorse_r5_hexerei_on_xiangling",
            "the same at R5 with Hexerei (stated on): 75% more",
            "Polearm/DisasterAndRemorse/index.tsx:18-51", "Xiangling", "Disaster and Remorse",
            "13517", 5, xteam, XIANG, "pyro", w.NADO, base.PYRONADO,
            {"weapon:disaster_and_remorse/unforgivable": 1,
             "weapon:disaster_and_remorse/irreparable": 1,
             "weapon:disaster_and_remorse/hexerei": 1}, {"dmg": 0.8 * 1.75}),
        own("everlasting_moonglow_r1_on_kokomi",
            "a self Normal Attack flat DMG from the wielder's own Max HP, per candidate",
            "Catalyst/EverlastingMoonglow/index.tsx:9-37", "Sangonomiya Kokomi",
            "Everlasting Moonglow", "14506", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {}, {"flat": 0.01 * _hp(KOKOMI)}),
        own("fang_of_the_mountain_king_r1_on_xiangling",
            "a self Elemental Skill and Burst DMG per stack, six" + STAND_IN,
            "Claymore/FangOfTheMountainKing/index.tsx:15-38", "Xiangling",
            "Fang of the Mountain King", "12513", 1, xteam, XIANG, "pyro", w.NADO,
            base.PYRONADO, {"weapon:fang_of_the_mountain_king/stacks": 6}, {"dmg": 6 * 0.1}),
        own("hunters_path_r1_on_amber_aimed",
            "a self Elemental DMG, and Charged Attack flat DMG from the wielder's own EM in "
            "Tireless Hunt, per candidate", "Bow/HuntersPath/index.tsx:9-35", "Amber",
            "Hunter's Path", "15511", 1, bow, (w.AMBER_BASE, {**w.AMBER_ARTIFACTS,
                                                          "elemental_mastery": 200.0}),
            "pyro", w2.AIMED, w.AMBER_AIMED, {"weapon:hunters_path/hunt": 1},
            {"dmg": 0.12,
             "flat": 1.6 * (w.AMBER_BASE.get("elemental_mastery", 0.0) + 200.0)}),
        mate("hymn_of_the_maelstrom_r1_capped_on_xiangling",
             "a teammate's weapon: the active character's ATK% per 1,000 of the wielder's Max HP "
             "over 40,000, at its cap, three stacks",
             "Catalyst/HymnOfTheMaelstrom/index.tsx:24-83",
             "Sangonomiya Kokomi", "Hymn of the Maelstrom", "14524", 1,
             {"base_hp": 15000.0, "hp_pct": 3.0, "flat_hp": 4780.0},
             {"weapon:hymn_of_the_maelstrom/stacks": 3,
              "weapon:hymn_of_the_maelstrom/frozen_swirl": 0},
             {"atk_pct": 3 * min(0.004 * (15000.0 * 4 + 4780.0 - 40000.0) / 1000, 0.08)}),
    ]
    big_hp = (KOKOMI[0], {**KOKOMI[1], "hp_pct": 3.0})
    for r, per, cap, stats, tag in ((1, 0.003, 0.12, KOKOMI, ""),
                                    (5, 0.011, 0.44, big_hp, "past_its_cap_")):
        out.append(own(
            f"jadefalls_splendor_r{r}_{tag}on_kokomi",
            "a self Elemental DMG of the wielder's element per 1,000 of their own Max HP, "
            "per candidate, " + ("past" if tag else "below") + " its cap",
            "Catalyst/JadefallsSplendor/index.tsx:9-50", "Sangonomiya Kokomi",
            "Jadefall's Splendor", "14505", r, hydro, stats, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:jadefalls_splendor/regalia": 1},
            {"dmg": min(per * _hp(stats) / 1000, cap)}))
    out += [
        own("lumidouce_elegy_r1_on_xiangling", "a self ATK% and DMG per stack, two",
            "Polearm/LumidouceElegy/index.tsx:16-39", "Xiangling", "Lumidouce Elegy", "13513", 1,
            xteam, XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:lumidouce_elegy/stacks": 2},
            {"atk_pct": 0.15, "dmg": 2 * 0.18}),
    ]
    for name, slug, nid, go in (("Memory of Dust", "memory_of_dust", "14504",
                                 "Catalyst/MemoryOfDust/index.tsx:17-42"),
                                ("The Unforged", "the_unforged", "12504",
                                 "Claymore/TheUnforged/index.tsx:17-40")):
        out.append(own(f"{slug}_r1_shielded_on_razor",
                       "a self ATK% per stack, five, doubled under a shield (stated on)", go,
                       "Razor", name, nid, 1, claymore, RAZOR, "physical", w2.RAZOR_NA,
                       b8.RAZOR_NA_1, {f"weapon:{slug}/stacks": 5, f"weapon:{slug}/shield": 1},
                       {"atk_pct": 2 * 5 * 0.04}))
    out += [
        own("nocturnes_curtain_call_r1_on_kokomi_burst",
            "a self Max HP% in Bountiful Sea's Sacred Wine on a Max HP row",
            "Catalyst/NocturnesCurtainCall/index.tsx:12-45", "Sangonomiya Kokomi",
            "Nocturne's Curtain Call", "14522", 1, hydro, KOKOMI, "hydro", KOKOMI_BURST,
            KOKOMI_BURST_HIT, {"weapon:nocturnes_curtain_call/wine": 1}, {"hp_pct": 0.14},
            scaling="hp"),
        own("reliquary_of_truth_r1_on_kokomi",
            "a self CRIT Rate, and EM and CRIT DMG each 50% more with both effects (stated on)",
            "Catalyst/ReliquaryOfTruth/index.tsx:15-61", "Sangonomiya Kokomi",
            "Reliquary of Truth", "14521", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1,
            {"weapon:reliquary_of_truth/lies": 1, "weapon:reliquary_of_truth/truth": 1},
            {"cr": 0.08, "em": 80.0 * 1.5, "cd": 0.24 * 1.5}),
        own("silvershower_heartstrings_r1_on_kokomi_burst",
            "a self Max HP% at three Remedy stacks and Elemental Burst CRIT Rate, on a Max HP "
            "burst row" + STAND_IN, "Bow/SilvershowerHeartstrings/index.tsx:15-46",
            "Sangonomiya Kokomi", "Silvershower Heartstrings", "15513", 1, hydro, KOKOMI,
            "hydro", KOKOMI_BURST, KOKOMI_BURST_HIT,
            {"weapon:silvershower_heartstrings/remedy": 3}, {"hp_pct": 0.4, "cr": 0.28},
            scaling="hp"),
        own("splendor_of_tranquil_waters_r1_on_ayaka",
            "a self Elemental Skill DMG per stack, three, and Max HP% per stack, two",
            "Sword/SplendorOfTranquilWaters/index.tsx:15-48", "Kamisato Ayaka",
            "Splendor of Tranquil Waters", "11513", 1, sword, AYAKA, "cryo", w2.PRESS,
            base.HYOUKA,
            {"weapon:splendor_of_tranquil_waters/self_hp": 3,
             "weapon:splendor_of_tranquil_waters/team_hp": 2},
            {"dmg": 3 * 0.08, "hp_pct": 2 * 0.14}),
    ]
    xem = (XIANG[0], {**XIANG[1], "elemental_mastery": 300.0})
    em = base._stats(*xem)["elemental_mastery"]
    out += [
        own("staff_of_the_scarlet_sands_r1_on_xiangling",
            "a self ATK from the wielder's own EM and three stacks more, per candidate",
            "Polearm/StaffOfTheScarletSands/index.tsx:17-60", "Xiangling",
            "Staff of the Scarlet Sands", "13511", 1, xteam, xem, "pyro", w.NADO, base.PYRONADO,
            {"weapon:staff_of_the_scarlet_sands/stacks": 3},
            {"flat_atk": (0.52 + 3 * 0.28) * em}),
        vape("sunny_morning_sleep_in_r1_on_xiangling_vape",
             "a self EM after a Swirl, a skill and a burst, into an amplifying reaction"
             + STAND_IN, "Catalyst/SunnyMorningSleepIn/index.tsx:8-41", "Sunny Morning Sleep-In",
             "14518", 1,
             {"weapon:sunny_morning_sleep_in/swirl": 1,
              "weapon:sunny_morning_sleep_in/after_skill": 1,
              "weapon:sunny_morning_sleep_in/after_burst": 1}, {"em": 120.0 + 96.0 + 32.0}),
        own("surfs_up_r1_on_kokomi", "a self Max HP% and Normal Attack DMG per stack, four",
            "Catalyst/SurfsUp/index.tsx:17-50", "Sangonomiya Kokomi", "Surf's Up", "14516", 1,
            hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1, {"weapon:surfs_up/stacks": 4},
            {"hp_pct": 0.2, "dmg": 4 * 0.12}),
        own("the_daybreak_chronicles_r1_on_amber_burst",
            "a self Normal Attack, Elemental Skill and Burst DMG at six steps",
            "Bow/TheDaybreakChronicles/index.tsx:16-41", "Amber", "The Daybreak Chronicles",
            "15515", 1, bow, AMBER, "pyro", w2.WAVE, b8.AMBER_WAVE,
            {"weapon:the_daybreak_chronicles/passive": 6}, {"dmg": 6 * 0.1}),
        own("the_first_great_magic_r1_on_amber_aimed",
            "a self Charged Attack DMG and Gimmick's ATK% at three members of the wielder's "
            "element (a teammate count)", "Bow/TheFirstGreatMagic/index.tsx:21-75", "Amber",
            "The First Great Magic", "15512", 1,
            {**bow, "member_elements": ["pyro", "pyro", "pyro", "cryo"]}, AMBER, "pyro",
            w2.AIMED, w.AMBER_AIMED, {}, {"dmg": 0.16, "atk_pct": 0.48}),
        own("tome_of_the_eternal_flow_r1_on_amber_aimed",
            "a self Charged Attack DMG per stack, three" + STAND_IN,
            "Catalyst/TomeOfTheEternalFlow/index.tsx:17-48", "Amber", "Tome of the Eternal Flow",
            "14514", 1, bow, AMBER, "pyro", w2.AIMED, w.AMBER_AIMED,
            {"weapon:tome_of_the_eternal_flow/stacks": 3}, {"dmg": 3 * 0.14}),
        own("tulaytullahs_remembrance_r1_on_kokomi",
            "a self Normal Attack DMG at its maximum, ten steps (GO `min(max, time + hits)`)",
            "Catalyst/TulaytullahsRemembrance/index.tsx:18-84", "Sangonomiya Kokomi",
            "Tulaytullah's Remembrance", "14512", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA,
            b6.KOKOMI_NA_1, {"weapon:tulaytullahs_remembrance/steps": 10}, {"dmg": 0.48}),
        own("uraku_misugiri_r1_on_ayaka",
            "a self Elemental Skill DMG doubled after Geo DMG (a Geo member in the team), and "
            "DEF%", "Sword/UrakuMisugiri/index.tsx:16-48", "Kamisato Ayaka", "Uraku Misugiri",
            "11514", 1, {**sword, "member_elements": ["cryo", "geo"]}, AYAKA, "cryo", w2.PRESS,
            base.HYOUKA, {"weapon:uraku_misugiri/geo": 1}, {"dmg": 2 * 0.24, "def_pct": 0.2}),
        own("verdict_r1_on_ayaka", "a self Elemental Skill DMG per Seal, two" + STAND_IN,
            "Claymore/Verdict/index.tsx:17-50", "Kamisato Ayaka", "Verdict", "12512", 1, sword,
            AYAKA, "cryo", w2.PRESS, base.HYOUKA, {"weapon:verdict/seals": 2},
            {"dmg": 2 * 0.18}),
        own("vivid_notions_r1_on_xiangling_plunge",
            "a self ATK% and both Plunging Attack CRIT DMG effects" + STAND_IN,
            "Catalyst/VividNotions/index.tsx:8-37", "Xiangling", "Vivid Notions", "14519", 1,
            xteam, XIANG, "physical", PLUNGE, b4.XIANGLING_HIGH_PLUNGE,
            {"weapon:vivid_notions/dawn": 1, "weapon:vivid_notions/twilight": 1},
            {"atk_pct": 0.28, "cd": 0.28 + 0.4}),
        own("whitelake_frostfeather_r1_on_ayaka", "a self ATK% per stack, three",
            "Sword/WhitelakeFrostfeather/index.tsx:12-39", "Kamisato Ayaka",
            "Whitelake Frostfeather", "11520", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:whitelake_frostfeather/stacks": 3}, {"atk_pct": 3 * 0.08}),
        own("golden_frostbound_oath_r1_on_kachina",
            "a self DEF% and Geo DMG in Frost Fae's Favor, on a Geo DEF row" + STAND_IN,
            "Bow/GoldenFrostboundOath/index.tsx:15-54", "Kachina", "Golden Frostbound Oath",
            "15516", 1, KACHINA_TEAM, KACHINA, "geo", KACHINA_ROW, base.KACHINA_INDEPENDENT,
            {"weapon:golden_frostbound_oath/favor": 1,
             "weapon:golden_frostbound_oath/moondrift": 0},
            {"def_pct": 0.16, "dmg": 0.4}, scaling="def"),
    ]
    out += _reactions()
    return out


def _reactions() -> list[dict[str, Any]]:
    flins = (b8.FLINS_BASE, rx.FLINS_ARTIFACTS)
    fs = base._stats(*flins)

    def lunar_charged(trans_def: float) -> float:
        """Two Lunar-Charged contributions with Fractured Halo's Electrifying Edict (40%,
        `FracturedHalo/index.tsx:11,24-32,38-42`); its ATK% does not reach the row."""
        return 2 * rx._lunar(3.0, fs["elemental_mastery"], 0.4, crit_rate=fs["crit_rate"],
                             crit_dmg=fs["crit_dmg"], trans_def=trans_def)

    geo = base._stats(rx.GEO_BASE, rx.GEO_ARTIFACTS)

    def lunar_crystallize(trans_def: float) -> float:
        """Three Lunar-Crystallize contributions in Frost Fae's Favor (40%,
        `GoldenFrostboundOath/index.tsx:19,24-30,46`); its Geo DMG does not reach the row."""
        return 3 * rx._lunar(1.6, geo["elemental_mastery"], 0.4, crit_rate=geo["crit_rate"],
                             crit_dmg=geo["crit_dmg"], trans_def=trans_def)

    nahida = (b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    nahida_em = base._stats(*nahida)["elemental_mastery"]

    def bloom(trans_def: float) -> float:
        """Two blooms with both of Nightweaver's effects: 60 + 60 EM and 120% Bloom DMG
        (`NightweaversLookingGlass/index.tsx:18-20,28-53,72-79`)."""
        return 2 * rx._trans(2.0, nahida_em + 120.0, 1.2, trans_def=trans_def)

    electro = {"element": "electro", "weapon_type": "WEAPON_POLE",
               "member_elements": ["electro", "hydro"]}
    return [
        reaction("fractured_halo_r1_lunar_charged_on_flins",
                 "a Lunar-Charged row: the party's Lunar-Charged DMG after the wielder's shield "
                 "(stated on), the wielder among them",
                 [rx.SPECIAL, rx.CONSTANTS, "libs/gi/wr/src/reaction/lunar.ts:10-40",
                  f"{w.WEAPONS}Polearm/FracturedHalo/index.tsx:8-43"],
                 "Flins", "Fractured Halo", "13515", 1, electro, flins, "electro",
                 [rx._reaction_row("lc", "lunar_charged", 2, label="lunar-charged")],
                 {"weapon:fractured_halo/after": 1, "weapon:fractured_halo/shield": 1},
                 lunar_charged, lunar=True),
        reaction("golden_frostbound_oath_r1_lunar_crystallize",
                 "a Lunar-Crystallize row: a self Lunar-Crystallize DMG in Frost Fae's Favor; a "
                 "Geo trigger wields it",
                 [rx.SPECIAL, rx.CONSTANTS, "libs/gi/wr/src/reaction/lunar.ts:10-40",
                  f"{w.WEAPONS}Bow/GoldenFrostboundOath/index.tsx:15-54"],
                 "a Geo trigger", "Golden Frostbound Oath", "15516", 1,
                 {"element": "geo", "weapon_type": "WEAPON_BOW",
                  "member_elements": ["geo", "hydro"]}, (rx.GEO_BASE, rx.GEO_ARTIFACTS), "geo",
                 [rx._reaction_row("lcr", "lunar_crystallize", 3, label="lunar-crystallize")],
                 {"weapon:golden_frostbound_oath/favor": 1,
                  "weapon:golden_frostbound_oath/moondrift": 0}, lunar_crystallize, lunar=True),
        reaction("nightweavers_looking_glass_r1_bloom_on_nahida",
                 "a bloom row: both effects stated on, the wielder's EM and the party's Bloom DMG",
                 [rx.TRANS, rx.CONSTANTS,
                  f"{w.WEAPONS}Catalyst/NightweaversLookingGlass/index.tsx:15-85"],
                 "Nahida", "Nightweaver's Looking Glass", "14520", 1,
                 {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
                  "member_elements": ["dendro", "hydro"]}, nahida, "dendro",
                 [rx._reaction_row("bloom", "bloom", 2)],
                 {"weapon:nightweavers_looking_glass/prayer": 1,
                  "weapon:nightweavers_looking_glass/verse": 1}, bloom),
    ]
