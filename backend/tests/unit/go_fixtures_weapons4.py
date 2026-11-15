"""Math-fallback P3, task 12 (fourth batch): the remaining team-buff weapons and the owner's own.

The method is `go_fixtures_weapons.py`'s, unchanged. A teammate wielder's pass-1 stats are
written out where an effect reads one (Makhaira Aquamarine's EM, Peak Patrol Song's DEF). Where
the passive does not read the weapon class, a fixture may use another character as a stand-in
wielder of a row the effect reaches; its `covers` says so.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base

mine = w2.mine
XTEAM = w2.XTEAM


def _teammate(name: str, covers: str, go: str, who: str, weapon: str, nanoka_id: str, r: int,
              stats: dict[str, float], conditionals: dict[str, Any], x: dict[str, float], *,
              vape: bool = False) -> dict[str, Any]:
    """A teammate's weapon on Xiangling's Pyronado (vaporized where its effect is EM)."""
    return w._fx(
        name, covers, [w.FORMULA_AMP if vape else w.FORMULA, f"{w.WEAPONS}{go}"],
        w._wielder(who, weapon, r, stats), XTEAM, w2.XB, w2.XA, "pyro",
        [w.NADO_VAPE if vape else w.NADO],
        w.weapon_source(nanoka_id, r, who, stats, subject=False, receiver_element="pyro",
                        team_elements=list(w.XIANGLING_TEAM)),
        conditionals,
        w._figure(w2.XB, w2.XA, base.PYRONADO, "pyro", x, amplifying=vape),
        w.AMP_DIVERGENCE if vape else "none: no reaction")


def team_weapon_fixtures() -> list[dict[str, Any]]:
    """One fixture per weapon on its main effect."""
    return [
        _teammate("hakushin_ring_r1_on_xiangling",
                  "a teammate's weapon: the receiver's element DMG after an Electro reaction "
                  "with that element (receiver_elements)",
                  "Catalyst/HakushinRing/index.tsx:19-56", "Raiden Shogun", "Hakushin Ring",
                  "14414", 1, {}, {"weapon:hakushin_ring/reaction": "pyro"}, {"dmg": 0.1}),
        _teammate("forest_regalia_r1_on_xiangling_vape",
                  "a teammate's weapon: EM to the active character from the Leaf",
                  "Claymore/ForestRegalia/index.tsx:15-37", "Dehya", "Forest Regalia", "12417",
                  1, {}, {"weapon:forest_regalia/leaf": 1}, {"em": 60.0}, vape=True),
        _teammate("makhaira_aquamarine_r1_on_xiangling",
                  "a teammate's weapon: 30% of the wielder's ATK from their own EM to the others",
                  "Claymore/MakhairaAquamarine/index.tsx:16-44", "Dehya",
                  "Makhaira Aquamarine", "12415", 1, {"elemental_mastery": 600.0}, {},
                  {"flat_atk": 0.24 * 0.3 * 600.0}),
        _teammate("wandering_evenstar_r5_on_xiangling",
                  "a teammate's weapon at R5: 30% of the wielder's ATK from their own EM",
                  "Catalyst/WanderingEvenstar/index.tsx:16-44", "Nahida", "Wandering Evenstar",
                  "14416", 5, {"elemental_mastery": 800.0}, {},
                  {"flat_atk": 0.48 * 0.3 * 800.0}),
        _teammate("a_thousand_floating_dreams_r1_on_xiangling_vape",
                  "a teammate's weapon: the other party members' EM",
                  "Catalyst/AThousandFloatingDreams/index.tsx:21-77", "Nahida",
                  "A Thousand Floating Dreams", "14511", 1, {}, {}, {"em": 40.0}, vape=True),
        _teammate("symphonist_of_scents_r1_on_xiangling",
                  "a teammate's weapon: Sweet Echoes' ATK% after the wielder heals",
                  "Polearm/SymphonistOfScents/index.tsx:8-35", "Escoffier",
                  "Symphonist of Scents", "13514", 1, {},
                  {"weapon:symphonist_of_scents/healing": 1},
                  {"atk_pct": 0.32}),
        _teammate("peak_patrol_song_r1_on_xiangling",
                  "a teammate's weapon: party Elemental DMG per 1,000 of the wielder's DEF",
                  "Sword/PeakPatrolSong/index.tsx:22-77", "Xilonen", "Peak Patrol Song",
                  "11516", 1, {"base_def": 800.0, "def_pct": 1.5},
                  {"weapon:peak_patrol_song/maxed": 1}, {"dmg": 0.08 * 2.0}),
        _teammate("peak_patrol_song_r5_past_its_def_cap_on_xiangling",
                  "the same at R5, the wielder's 4,000 DEF counted to 3,200 (a stat cap)",
                  "Sword/PeakPatrolSong/index.tsx:22-77", "Xilonen", "Peak Patrol Song",
                  "11516", 5, {"base_def": 800.0, "def_pct": 4.0},
                  {"weapon:peak_patrol_song/maxed": 1}, {"dmg": 0.16 * 3.2}),
        _teammate("starcallers_watch_r1_on_xiangling",
                  "a teammate's weapon: the active character's DMG after the wielder's shield",
                  "Catalyst/StarcallersWatch/index.tsx:15-45", "Lauma", "Starcaller's Watch",
                  "14517", 1, {}, {"weapon:starcallers_watch/shield": 1}, {"dmg": 0.28}),
    ]


def owner_weapon_fixtures() -> list[dict[str, Any]]:
    """The owner's own weapons by use, each on a wielder's row its effect reaches."""
    ayaka = (w2.AB, w2.AA)
    ayaka_hp = (w2.AB, {**w2.AA, "hp_pct": 1.0, "flat_hp": 4780.0})
    ayaka_em = (w2.AB, {**w2.AA, "elemental_mastery": 200.0})
    xian = (w2.XB, w2.XA)
    razor = (w2.RB, w2.RA)
    out = [
        mine("fleuve_cendre_ferryman_r1_on_ayaka", "a self Elemental Skill CRIT Rate",
             "Sword/FleuveCendreFerryman/index.tsx:8-27", "Kamisato Ayaka",
             "Fleuve Cendre Ferryman", "11426", 1, w2.SWORD, ayaka, "cryo", w2.PRESS,
             base.HYOUKA, {"weapon:fleuve_cendre_ferryman/after_skill": 1}, {"cr": 0.08}),
        mine("wolf_fang_r1_on_ayaka",
             "a self Elemental Skill and Burst DMG and a skill CRIT Rate per stack, four",
             "Sword/WolfFang/index.tsx:16-52", "Kamisato Ayaka", "Wolf-Fang", "11424", 1,
             w2.SWORD, ayaka, "cryo", w2.PRESS, base.HYOUKA,
             {"weapon:wolf_fang/skill_stacks": 4, "weapon:wolf_fang/burst_stacks": 4},
             {"dmg": 0.16, "cr": 4 * 0.02}),
        mine("tamayuratei_no_ohanashi_r1_on_xiangling", "a self ATK% after an Elemental Skill",
             "Polearm/TamayurateiNoOhanashi/index.tsx:8-22", "Xiangling",
             "Tamayuratei no Ohanashi", "13432", 1, XTEAM, xian, "pyro", w.NADO, base.PYRONADO,
             {"weapon:tamayuratei_no_ohanashi/after_skill": 1}, {"atk_pct": 0.2}),
        mine("aqua_simulacra_r1_on_amber_burst", "a self HP% and DMG with opponents nearby",
             "Bow/AquaSimulacra/index.tsx:8-28", "Amber", "Aqua Simulacra", "15508", 1, w2.BOW,
             (w.AMBER_BASE, w.AMBER_ARTIFACTS), "pyro", w2.WAVE, b8.AMBER_WAVE,
             {"weapon:aqua_simulacra/nearby": 1}, {"hp_pct": 0.16, "dmg": 0.2}),
        mine("light_of_foliar_incision_r1_on_ayaka",
             "a self CRIT Rate and skill flat damage from the wielder's own EM, per candidate",
             "Sword/LightOfFoliarIncision/index.tsx:8-45", "Kamisato Ayaka",
             "Light of Foliar Incision", "11512", 1, w2.SWORD, ayaka_em, "cryo", w2.PRESS,
             base.HYOUKA, {"weapon:light_of_foliar_incision/foliar": 1},
             {"cr": 0.04, "flat": 1.2 * 200.0}),
        mine("flame_forged_insight_r1_on_xiangling_vape",
             "a self EM after a reaction, into an amplifying reaction (a stand-in wielder: the "
             "passive does not read the weapon class)",
             "Claymore/FlameForgedInsight/index.tsx:8-25", "Xiangling", "Flame-Forged Insight",
             "12432", 1, XTEAM, xian, "pyro", w.NADO_VAPE, base.PYRONADO,
             {"weapon:flame_forged_insight/triggered": 1}, {"em": 60.0}),
    ]
    # The amplified one: the figure with each coefficient, as every amplified fixture has.
    flame = out[-1]
    flame["expected"] = w._figure(w2.XB, w2.XA, base.PYRONADO, "pyro", {"em": 60.0},
                                  amplifying=True)(base.OUR_EM_COEFFICIENT)
    flame["go_value"] = w._figure(w2.XB, w2.XA, base.PYRONADO, "pyro", {"em": 60.0},
                                  amplifying=True)(base.GO_EM_COEFFICIENT)
    flame["divergence"] = w.AMP_DIVERGENCE
    # Both builds move HP, so a conversion frozen at the zero-artifact build would miss.
    ayaka_flat_hp = (w2.AB, {**w2.AA, "flat_hp": 4780.0})
    for hp_stats, state in ((ayaka_flat_hp, "below"), (ayaka_hp, "past")):
        hp = w2.AB["base_hp"] * (1 + hp_stats[1].get("hp_pct", 0.0)) + hp_stats[1].get(
            "flat_hp", 0.0)
        fixture = mine(
            f"finale_of_the_deep_r1_{state}_its_cap_on_ayaka",
            f"a self ATK% after a skill and ATK from the Bond cleared (25% of Max HP), capped "
            f"at 150 and {state} it, per candidate",
            "Sword/FinaleOfTheDeep/index.tsx:15-55", "Kamisato Ayaka", "Finale of the Deep",
            "11425", 1, w2.SWORD, hp_stats, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:finale_of_the_deep/after_skill": 1, "weapon:finale_of_the_deep/bond": 1},
            {"atk_pct": 0.12, "flat_atk": min(0.024 * 0.25 * hp, 150.0)})
        fixture["cap_state"] = state
        out.append(fixture)
    for ns in (0, 1):
        out.append(mine(
            f"a_thousand_blazing_suns_r1{'_nightsoul' if ns else ''}_on_razor",
            "a self CRIT DMG and ATK% in Scorching Brilliance"
            + (", each +75% in Nightsoul's Blessing (stated on)" if ns else ""),
            "Claymore/AThousandBlazingSuns/index.tsx:15-48", "Razor",
            "A Thousand Blazing Suns", "12514", 1, w2.CLAYMORE, razor, "physical", w2.RAZOR_NA,
            b8.RAZOR_NA_1,
            {"weapon:a_thousand_blazing_suns/brilliance": 1,
             "weapon:a_thousand_blazing_suns/nightsoul": ns},
            {"cd": 0.2 * (1 + 0.75 * ns), "atk_pct": 0.28 * (1 + 0.75 * ns)}))
    return out
