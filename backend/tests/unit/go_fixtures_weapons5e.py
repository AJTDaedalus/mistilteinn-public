"""Math-fallback P3, task 12 (fifth batch, continued): the 3-star weapons, and six newer 4-stars.

The method and helpers are `go_fixtures_weapons5.py`'s and `go_fixtures_weapons5d.py`'s.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base
from tests.unit.go_fixtures_weapons5 import (
    AMBER,
    AYAKA,
    KOKOMI,
    RAZOR,
    STAND_IN,
    XIANG,
    own,
    vape,
)
from tests.unit.go_fixtures_weapons5d import _proc


def three_star_fixtures() -> list[dict[str, Any]]:
    """Each weapon on its main effect."""
    sword, claymore, hydro = w2.SWORD, w2.CLAYMORE, w2.CATALYST_HYDRO
    out = [
        own("bloodtainted_greatsword_r1_on_razor",
            "a self DMG against a Pyro- or Electro-affected opponent (stated on)",
            "Claymore/BloodtaintedGreatsword/index.tsx:8-21", "Razor",
            "Bloodtainted Greatsword", "12302", 1, claymore, RAZOR, "physical", w2.RAZOR_NA,
            b8.RAZOR_NA_1, {"weapon:bloodtainted_greatsword/aura": 1}, {"dmg": 0.12}),
        own("cool_steel_r1_on_ayaka",
            "a self DMG against a Hydro- or Cryo-affected opponent (stated on)",
            "Sword/CoolSteel/index.tsx:8-22", "Kamisato Ayaka", "Cool Steel", "11301", 1, sword,
            AYAKA, "cryo", w2.PRESS, base.HYOUKA, {"weapon:cool_steel/aura": 1}, {"dmg": 0.12}),
        own("magic_guide_r1_on_kokomi",
            "a self DMG against a Hydro- or Electro-affected opponent (stated on)",
            "Catalyst/MagicGuide/index.tsx:8-21", "Sangonomiya Kokomi", "Magic Guide", "14301",
            1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:magic_guide/aura": 1}, {"dmg": 0.12}),
        own("raven_bow_r5_on_amber",
            "a self DMG against a Hydro- or Pyro-affected opponent (stated on), at R5",
            "Bow/RavenBow/index.tsx:8-23", "Amber", "Raven Bow", "15301", 5, w2.BOW, AMBER,
            "pyro", w2.WAVE, b8.AMBER_WAVE, {"weapon:raven_bow/aura": 1}, {"dmg": 0.24}),
        own("dark_iron_sword_r1_on_ayaka",
            "a self ATK% after an Electro-related reaction (GO's R5 entry is 0.5, the list's "
            "0.4; R1 agrees)", "Sword/DarkIronSword/index.tsx:8-22", "Kamisato Ayaka",
            "Dark Iron Sword", "11304", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:dark_iron_sword/reaction": 1}, {"atk_pct": 0.2}),
        own("harbinger_of_dawn_r1_on_ayaka", "a self CRIT Rate above 90% HP",
            "Sword/HarbingerOfDawn/index.tsx:8-22", "Kamisato Ayaka", "Harbinger of Dawn",
            "11302", 1, sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:harbinger_of_dawn/hp": 1}, {"cr": 0.14}),
        own("skyrider_greatsword_r1_on_razor", "a self ATK% per stack, four",
            "Claymore/SkyriderGreatsword/index.tsx:15-31", "Razor", "Skyrider Greatsword",
            "12306", 1, claymore, RAZOR, "physical", w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:skyrider_greatsword/stacks": 4}, {"atk_pct": 4 * 0.06}),
        own("skyrider_sword_r1_on_ayaka", "a self ATK% after a burst",
            "Sword/SkyriderSword/index.tsx:8-28", "Kamisato Ayaka", "Skyrider Sword", "11306", 1,
            sword, AYAKA, "cryo", w2.PRESS, base.HYOUKA,
            {"weapon:skyrider_sword/after_burst": 1}, {"atk_pct": 0.12}),
        own("twin_nephrite_r1_on_kokomi", "a self ATK% after a kill (stated on)",
            "Catalyst/TwinNephrite/index.tsx:8-29", "Sangonomiya Kokomi", "Twin Nephrite",
            "14305", 1, hydro, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:twin_nephrite/kill": 1}, {"atk_pct": 0.12}),
    ]
    for name, slug, nid, key, label, go, gcsim, mult in (
            ("Debate Club", "debate_club", "12305", "blunt", "Blunt Conclusion",
             "Claymore/DebateClub/index.tsx:16-36",
             "internal/weapons/claymore/debateclub/debateclub.go:32-81", 0.6),
            ("Fillet Blade", "fillet_blade", "11305", "gash", "Gash",
             "Sword/FilletBlade/index.tsx:16-38",
             "internal/weapons/sword/filletblade/filletblade.go:32-63", 2.4),
            ("Halberd", "halberd", "13302", "heavy", "Heavy", "Polearm/Halberd/index.tsx:16-36",
             "internal/weapons/spear/halberd/halberd.go:31-61", 1.6)):
        out.append(_proc(f"{slug}_r1_proc_row_on_xiangling",
                         f"a proc row: one {label} instance ({mult:.0%} ATK, Physical)"
                         + STAND_IN, go, gcsim, "Xiangling", name, nid, slug, key, label,
                         w2.XTEAM, XIANG, base.PYRONADO, "pyro", 1, mult))
    return out


def newer_four_star_fixtures() -> list[dict[str, Any]]:
    """Newer 4-star weapons whose damage parts are ordinary stats."""
    return [
        own("blade_of_atonement_r1_on_razor",
            "a self EM after a reaction and ATK% after Stellar Glimmer (both stated on; GO gates "
            "the ATK% on the reaction toggle too)", "Claymore/BladeOfAtonement/index.tsx:8-31",
            "Razor", "Blade of Atonement", "12436", 1, w2.CLAYMORE, RAZOR, "physical",
            w2.RAZOR_NA, b8.RAZOR_NA_1,
            {"weapon:blade_of_atonement/react": 1, "weapon:blade_of_atonement/stellar": 1},
            {"em": 64.0, "atk_pct": 0.16}),
        own("clash_of_kings_r1_on_kokomi", "a self ATK% and EM after a skill",
            "Catalyst/ClashOfKings/index.tsx:8-30", "Sangonomiya Kokomi", "Clash of Kings",
            "14435", 1, w2.CATALYST_HYDRO, KOKOMI, "hydro", w2.KOKOMI_NA, b6.KOKOMI_NA_1,
            {"weapon:clash_of_kings/skill": 1}, {"atk_pct": 0.2, "em": 100.0}),
        vape("dawning_frost_r1_on_xiangling_vape",
             "a self EM after a Charged hit and a skill hit, into an amplifying reaction"
             + STAND_IN, "Catalyst/DawningFrost/index.tsx:8-30", "Dawning Frost", "14434", 1,
             {"weapon:dawning_frost/charged_hit": 1, "weapon:dawning_frost/skill_hit": 1},
             {"em": 72.0 + 48.0}),
        vape("echoes_of_the_heart_r1_on_xiangling_vape",
             "a self EM after a reaction, into an amplifying reaction" + STAND_IN,
             "Catalyst/EchoesOfTheHeart/index.tsx:12-34", "Echoes of the Heart", "14436", 1,
             {"weapon:echoes_of_the_heart/react": 1}, {"em": 60.0}),
        own("emberwell_r1_on_ayaka", "a self ATK% after a reaction",
            "Sword/Emberwell/index.tsx:12-34", "Kamisato Ayaka", "Emberwell", "11436", 1,
            w2.SWORD, AYAKA, "cryo", w2.PRESS, base.HYOUKA, {"weapon:emberwell/react": 1},
            {"atk_pct": 0.16}),
        own("frostbreath_r1_on_xiangling", "a self ATK% after a Cryo- or Hydro-related reaction",
            "Polearm/Frostbreath/index.tsx:8-23", "Xiangling", "Frostbreath", "13435", 1,
            w2.XTEAM, XIANG, "pyro", w.NADO, base.PYRONADO, {"weapon:frostbreath/react": 1},
            {"atk_pct": 0.2}),
    ]
