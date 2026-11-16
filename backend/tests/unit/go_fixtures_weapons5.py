"""Math-fallback P3, task 12 (fifth batch, owner 2026-11-15: "More weapon files").

The method is `go_fixtures_weapons.py`'s, unchanged: each figure is GO's formula worked by hand
(`formula.ts:434-453`, or `trans.ts`/`special.ts` for a reaction row) with our seeded refinement
values written out here, never read through the resolver; the weapon source is the resolver's for
a stated wielder. Every fixture states every condition its source reads. Where a passive does not
read the weapon class, a character of another class stands in as the wielder of a row the effect
reaches, and `covers` says so.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_reactions as rx
from tests.unit import go_fixtures_weapon_compare as cmp
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base

XB, XA = w2.XB, w2.XA
AYAKA = (w2.AB, w2.AA)
KAEYA = (w2.KB, w2.KA)
RAZOR = (w2.RB, w2.RA)
AMBER = (w.AMBER_BASE, w.AMBER_ARTIFACTS)
KOKOMI = (w2.KOB, w2.KOA)
XIANG = (XB, XA)
KACHINA = (base.KACHINA_BASE, base.KACHINA_ARTIFACTS)
KACHINA_TEAM = {"element": "geo", "weapon_type": "WEAPON_POLE", "member_elements": ["geo", "pyro"]}
KACHINA_ROW = base._row("independent", "Turbo Twirly Independent DMG", "skill", 1,
                        base.KACHINA_INDEPENDENT, None)
#: A stand-in: what the passive reads is not the weapon class.
STAND_IN = " (a stand-in wielder: the passive does not read the weapon class)"


def own(name: str, covers: str, go: str, who: str, weapon: str, nanoka_id: str, r: int,
        team: dict[str, Any], stats: tuple[dict[str, float], dict[str, float]], channel: str,
        row: dict[str, Any], talent: tuple[str, list[float]], conditionals: dict[str, Any],
        x: dict[str, float], *, scaling: str = "atk") -> dict[str, Any]:
    """A fixture whose wielder is the optimized character (`w2.mine`, any scaling stat)."""
    return w._fx(
        name, covers, [w.FORMULA, f"{w.WEAPONS}{go}"], w._wielder(who, weapon, r, w.SUBJECT),
        team, stats[0], stats[1], channel, [row],
        cmp.source(nanoka_id, r, who, stats[0], subject=True, receiver_element=team["element"],
                   team_elements=team.get("member_elements")),
        conditionals, w._figure(stats[0], stats[1], talent, channel, x, scaling=scaling))


def vape(name: str, covers: str, go: str, weapon: str, nanoka_id: str, r: int,
         conditionals: dict[str, Any], x: dict[str, float]) -> dict[str, Any]:
    """Xiangling's vaporized Pyronado with her own weapon: an EM passive, amplified, carrying the
    recorded 2.78 vs 25/9."""
    return w._fx(
        name, covers, [w.FORMULA_AMP, f"{w.WEAPONS}{go}"],
        w._wielder("Xiangling", weapon, r, w.SUBJECT), w2.XTEAM, XB, XA, "pyro", [w.NADO_VAPE],
        cmp.source(nanoka_id, r, "Xiangling", XB, subject=True), conditionals,
        w._figure(XB, XA, base.PYRONADO, "pyro", x, amplifying=True), w.AMP_DIVERGENCE)


def mate(name: str, covers: str, go: str, who: str, weapon: str, nanoka_id: str, r: int,
         stats: dict[str, float], conditionals: dict[str, Any], x: dict[str, float], *,
         amplifying: bool = False) -> dict[str, Any]:
    """A teammate's weapon on Xiangling's Pyronado (vaporized where its effect is EM)."""
    return w._fx(
        name, covers, [w.FORMULA_AMP if amplifying else w.FORMULA, f"{w.WEAPONS}{go}"],
        w._wielder(who, weapon, r, stats), w2.XTEAM, XB, XA, "pyro",
        [w.NADO_VAPE if amplifying else w.NADO],
        cmp.source(nanoka_id, r, who, stats, subject=False, receiver_element="pyro",
                   team_elements=list(w.XIANGLING_TEAM)),
        conditionals, w._figure(XB, XA, base.PYRONADO, "pyro", x, amplifying=amplifying),
        w.AMP_DIVERGENCE if amplifying else "none: no reaction")


def reaction(name: str, covers: str, go: list[str], who: str, weapon: str, nanoka_id: str,
             r: int, team: dict[str, Any], stats: tuple[dict[str, float], dict[str, float]],
             channel: str, rows: list[dict[str, Any]], conditionals: dict[str, Any],
             figure: Any, *, lunar: bool = False) -> dict[str, Any]:
    """A reaction row with the wielder's own weapon, as `go_fixtures_reactions` builds them:
    ours at gcsim's transformative DEF (and solo Lunar weight), GO's at its own."""
    source = cmp.source(nanoka_id, r, who, stats[0], subject=True,
                        receiver_element=team["element"])
    fig = rx._go_def(figure)
    if lunar:
        fig = rx._lunar_weight(fig)
    return rx._fixture(name, covers, go, [w._wielder(who, weapon, r, w.SUBJECT)], team, stats,
                       [], channel, rows, [source], conditionals, fig,
                       rx.LUNAR_DIVERGENCE if lunar else rx.TRANS_DIVERGENCE)


def owner_fixtures() -> list[dict[str, Any]]:
    """The owner's own weapons with no file before this batch, each on its main effect."""
    out: list[dict[str, Any]] = []
    for r, cd, dmg in ((1, 0.2, 0.16), (5, 0.4, 0.32)):
        out.append(own(f"absolution_r{r}_on_ayaka",
                       "a self CRIT DMG and DMG per Bond of Life stack, three",
                       "Sword/Absolution/index.tsx:16-38", "Kamisato Ayaka", "Absolution",
                       "11515", r, w2.SWORD, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
                       {"weapon:absolution/bond": 3}, {"cd": cd, "dmg": 3 * dmg}))
    out += [
        own("azurelight_r1_at_zero_energy_on_ayaka",
            "a self ATK% after a skill, and ATK% and CRIT DMG again at 0 Energy (stated on)",
            "Sword/Azurelight/index.tsx:8-47", "Kamisato Ayaka", "Azurelight", "11517", 1,
            w2.SWORD, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:azurelight/after_skill": 1, "weapon:azurelight/no_energy": 1},
            {"atk_pct": 0.24 + 0.24, "cd": 0.4}),
        vape("etherlight_spindlelute_r1_on_xiangling_vape",
             "a self EM after a skill, into an amplifying reaction" + STAND_IN,
             "Catalyst/EtherlightSpindlelute/index.tsx:8-23", "Etherlight Spindlelute", "14432", 1,
             {"weapon:etherlight_spindlelute/after_skill": 1}, {"em": 100.0}),
        vape("cloudforged_r1_on_xiangling_vape",
             "a self EM per stack, two, into an amplifying reaction" + STAND_IN,
             "Bow/Cloudforged/index.tsx:15-33", "Cloudforged", "15426", 1,
             {"weapon:cloudforged/stacks": 2}, {"em": 2 * 40.0}),
        own("slingshot_r1_within_on_amber_aimed",
            "a self Normal and Charged Attack DMG for a hit within 0.3s",
            "Bow/Slingshot/index.tsx:15-37", "Amber", "Slingshot", "15304", 1, w2.BOW, AMBER,
            "pyro", w2.AIMED, w.AMBER_AIMED, {"weapon:slingshot/shot": "within"}, {"dmg": 0.36}),
        own("slingshot_r5_beyond_on_amber_aimed",
            "the decrease beyond 0.3s, published positive and negated (GO `percent(-0.1)`)",
            "Bow/Slingshot/index.tsx:15-37", "Amber", "Slingshot", "15304", 5, w2.BOW, AMBER,
            "pyro", w2.AIMED, w.AMBER_AIMED, {"weapon:slingshot/shot": "beyond"}, {"dmg": -0.1}),
        own("footprint_of_the_rainbow_r1_on_kachina",
            "a self DEF% after a skill on a DEF-scaling row",
            "Polearm/FootprintOfTheRainbow/index.tsx:8-22", "Kachina", "Footprint of the Rainbow",
            "13431", 1, KACHINA_TEAM, KACHINA, "geo", KACHINA_ROW, base.KACHINA_INDEPENDENT,
            {"weapon:footprint_of_the_rainbow/after_skill": 1}, {"def_pct": 0.16},
            scaling="def"),
        own("gest_of_the_mighty_wolf_r1_on_razor",
            "a self DMG per stack, four, and CRIT DMG per stack with Hexerei (stated on)",
            "Claymore/GestOfTheMightyWolf/index.tsx:18-46", "Razor", "Gest of the Mighty Wolf",
            "12515", 1, w2.CLAYMORE, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:gest_of_the_mighty_wolf/stacks": 4,
             "weapon:gest_of_the_mighty_wolf/hexerei": 1},
            {"dmg": 4 * 0.075, "cd": 4 * 0.075}),
        own("black_tassel_r1_on_xiangling", "a self DMG against slimes (stated on)",
            "Polearm/BlackTassel/index.tsx:8-22", "Xiangling", "Black Tassel", "13303", 1,
            w2.XTEAM, XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:black_tassel/slime": 1},
            {"dmg": 0.4}),
        own("ultimate_overlords_mega_magic_sword_r1_on_razor",
            "a self ATK% and the Melusines' further ATK% at its maximum (GO 12 times 1%)",
            "Claymore/UltimateOverlordsMegaMagicSword/index.tsx:18-50", "Razor",
            "\"Ultimate Overlord's Mega Magic Sword\"", "12426", 1, w2.CLAYMORE, RAZOR,
            "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:ultimate_overlords_mega_magic_sword/melusines": 1},
            {"atk_pct": 0.12 + 0.12}),
        own("emerald_orb_r1_on_kokomi", "a self ATK% after a reaction",
            "Catalyst/EmeraldOrb/index.tsx:8-23", "Sangonomiya Kokomi", "Emerald Orb", "14304", 1,
            w2.CATALYST_HYDRO, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:emerald_orb/rapids": 1}, {"atk_pct": 0.2}),
        own("calamity_of_eshu_r1_on_kaeya",
            "a self Normal and Charged Attack DMG and CRIT Rate while shielded (stated on)",
            "Sword/CalamityOfEshu/index.tsx:8-33", "Kaeya", "Calamity of Eshu", "11432", 1,
            w2.SWORD, KAEYA, "physical", w2.KAEYA_NA, b8.KAEYA_NA_1,
            {"weapon:calamity_of_eshu/shield": 1}, {"dmg": 0.2, "cr": 0.08}),
        own("ferrous_shadow_r1_on_amber_aimed",
            "a self Charged Attack DMG below the HP threshold (stated on)" + STAND_IN,
            "Claymore/FerrousShadow/index.tsx:8-23", "Amber", "Ferrous Shadow", "12301", 1,
            w2.BOW, AMBER, "pyro", w2.AIMED, w.AMBER_AIMED, {"weapon:ferrous_shadow/low_hp": 1},
            {"dmg": 0.3}),
        own("earth_shaker_r5_on_ayaka",
            "a self Elemental Skill DMG after a party Pyro reaction (stated on), at R5" + STAND_IN,
            "Claymore/EarthShaker/index.tsx:8-22", "Kamisato Ayaka", "Earth Shaker", "12431", 5,
            w2.SWORD, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:earth_shaker/pyro_reaction": 1}, {"dmg": 0.32}),
    ]
    # Angelos' Heptades: the active character's DMG from the wielder's premod ATK, which carries
    # the weapon's own ATK% (GO `input.premod.atk`), per 1,000, capped.
    for r, own_atk, per, cap, atk_pct in ((1, 0.12, 0.10, 0.26, 1.2), (5, 0.24, 0.22, 0.58, 2.0)):
        stats = {"base_atk": 900.0, "atk_pct": atk_pct, "flat_atk": 311.0}
        atk = 900.0 * (1 + atk_pct + own_atk) + 311.0
        out.append(mate(
            f"angelos_heptades_r{r}_{'past_its_cap_' if r == 5 else ''}on_xiangling",
            "a teammate's weapon: the active character's DMG per 1,000 of the wielder's ATK "
            "(with its own ATK%) after a shield, " + ("past" if r == 5 else "below") + " its cap",
            "Catalyst/AngelosHeptades/index.tsx:22-83", "Lauma", "Angelos' Heptades", "14523", r,
            stats, {"weapon:angelos_heptades/shield": 1}, {"dmg": min(per * atk / 1000, cap)}))
    # The Flute's Chord at R5 (gcsim `0.75 + 0.25 × r`, our list; GO writes 200% at every
    # refinement, so R5 is where the two agree).
    out.append(w._fx(
        "the_flute_r5_proc_row_on_kaeya",
        "a proc row: two Chord instances (200% ATK at R5, Physical)",
        [w.FORMULA, f"{w.WEAPONS}Sword/TheFlute/index.tsx:16-28", cmp.PROC],
        w._wielder("Kaeya", "The Flute", 5, w.SUBJECT), w2.SWORD, *KAEYA, "cryo",
        [cmp._proc_row("weapon:the_flute", "chord", 2, b8.KAEYA_NA_1, "Chord")],
        cmp.source("11402", 5, "Kaeya", w2.KB, subject=True, receiver_element="cryo"), {},
        cmp._proc_figure(*KAEYA, count=2, multiplier=2.0)))
    out += _owner_reactions()
    return out


def _owner_reactions() -> list[dict[str, Any]]:
    flins = (b8.FLINS_BASE, rx.FLINS_ARTIFACTS)
    flins_stats = base._stats(*flins)

    def lunar_charged(trans_def: float) -> float:
        """Two Lunar-Charged contributions with Bloodsoaked Ruins after a burst (36%) and
        Requiem of Ruin's 28% CRIT DMG (`BloodsoakedRuins/index.tsx:9-31`); his own CRIT
        applies (`special.ts:43-75`)."""
        return 2 * rx._lunar(3.0, flins_stats["elemental_mastery"], 0.36,
                             crit_rate=flins_stats["crit_rate"],
                             crit_dmg=flins_stats["crit_dmg"] + 0.28, trans_def=trans_def)

    nahida = (b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    nahida_em = base._stats(*nahida)["elemental_mastery"]

    def bloom(trans_def: float) -> float:
        """Two blooms with Blackmarrow Lantern's 48% Bloom DMG (`BlackmarrowLantern/index.tsx:
        17-25,44`)."""
        return 2 * rx._trans(2.0, nahida_em, 0.48, trans_def=trans_def)

    geo = base._stats(rx.GEO_BASE, rx.GEO_ARTIFACTS)

    def lunar_crystallize(trans_def: float) -> float:
        """Three Lunar-Crystallize contributions with Lightbearing Moonshard's 64% after a skill
        (`LightbearingMoonshard/index.tsx:17-28`)."""
        return 3 * rx._lunar(1.6, geo["elemental_mastery"], 0.64, crit_rate=geo["crit_rate"],
                             crit_dmg=geo["crit_dmg"], trans_def=trans_def)

    return [
        reaction("bloodsoaked_ruins_r1_lunar_charged_on_flins",
                 "a Lunar-Charged row: a self Lunar-Charged DMG after a burst and Requiem of "
                 "Ruin's CRIT DMG (both stated on), the trigger's own CRIT reaching it",
                 [rx.SPECIAL, rx.CONSTANTS, "libs/gi/wr/src/reaction/lunar.ts:10-40",
                  f"{w.WEAPONS}Polearm/BloodsoakedRuins/index.tsx:8-31"],
                 "Flins", "Bloodsoaked Ruins", "13516", 1,
                 {"element": "electro", "weapon_type": "WEAPON_POLE",
                  "member_elements": ["electro", "hydro"]}, flins, "electro",
                 [rx._reaction_row("lc", "lunar_charged", 2, label="lunar-charged")],
                 {"weapon:bloodsoaked_ruins/after_burst": 1,
                  "weapon:bloodsoaked_ruins/after_lc": 1}, lunar_charged, lunar=True),
        reaction("blackmarrow_lantern_r1_bloom_on_nahida",
                 "a bloom row: a self Bloom DMG bonus",
                 [rx.TRANS, rx.CONSTANTS,
                  f"{w.WEAPONS}Catalyst/BlackmarrowLantern/index.tsx:15-47"],
                 "Nahida", "Blackmarrow Lantern", "14433", 1,
                 {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
                  "member_elements": ["dendro", "hydro"]}, nahida, "dendro",
                 [rx._reaction_row("bloom", "bloom", 2)], {}, bloom),
        reaction("lightbearing_moonshard_r1_lunar_crystallize",
                 "a Lunar-Crystallize row: a self Lunar-Crystallize DMG after a skill (stated "
                 "on); a Geo trigger wields it",
                 [rx.SPECIAL, rx.CONSTANTS, "libs/gi/wr/src/reaction/lunar.ts:10-40",
                  f"{w.WEAPONS}Sword/LightbearingMoonshard/index.tsx:8-30"],
                 "a Geo trigger", "Lightbearing Moonshard", "11519", 1,
                 {"element": "geo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
                  "member_elements": ["geo", "hydro"]}, (rx.GEO_BASE, rx.GEO_ARTIFACTS), "geo",
                 [rx._reaction_row("lcr", "lunar_crystallize", 3, label="lunar-crystallize")],
                 {"weapon:lightbearing_moonshard/after_skill": 1}, lunar_crystallize, lunar=True),
    ]


def weapon_fixtures_5() -> list[dict[str, Any]]:
    """Every fixture of this batch (the later modules import this one's helpers)."""
    from tests.unit.go_fixtures_weapons5b import five_star_fixtures
    from tests.unit.go_fixtures_weapons5c import four_star_fixtures_a
    return [*owner_fixtures(), *five_star_fixtures(), *four_star_fixtures_a()]
