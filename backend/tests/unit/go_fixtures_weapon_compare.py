"""Owner approvals of 2026-11-14 after #389 (`docs/DECISIONS.md` §45): GO fixtures for the
weapon conversions on the wielder, Millennial Movement non-stacking, and weapon proc rows.

The method is `go_fixtures_weapons.py`'s, unchanged: each figure is GO's formula worked by hand
(`formula.ts:434-453`) with our seeded refinement values written out, never read through the
resolver; the weapon source is the resolver's for a stated wielder. Every fixture states every
condition its sources read. Where a passive does not read the weapon class, Xiangling stands in
as the wielder of a row the effect reaches, and `covers` says so.

- **Conversions on the wielder.** Engulfing Lightning's ATK% from ER above 100% (GO
  `EngulfingLightning/index.tsx:18-31`, `min(x × (premod.enerRech_ − 1), max)`), Key of
  Khaj-Nisut's EM from Max HP (`KeyOfKhajNisut/index.tsx:19-60`, `total.hp`, carrying its own
  HP%), Makhaira Aquamarine's and Wandering Evenstar's ATK from EM (`premod.eleMas`), and Peak
  Patrol Song's party DMG from DEF up to 3,200 (`PeakPatrolSong/index.tsx:51-64`, `total.def`
  with the Ode's own DEF%) below and past its cap. Each moves with the candidate: `formula:
  verify` fails a frozen copy.
- **Non-stacking.** Two Millennial Movement wielders, both on. GO applies the shared ATK% for
  the writer whose character key sorts first (`SheetUtil.tsx:102-117`, `uiData.ts:266-276`) —
  `KaedeharaKazuha` before `Venti`, Kazuha's R1 Freedom-Sworn 20%. **The estimate applies the
  stronger** (owner ruling 2026-11-15, `docs/DECISIONS.md` §46), Venti's R5 Elegy 40%: the
  fixture's `expected` is ours and its `go_value` GO's, a recorded divergence. Elegy's EM
  (`millenialelemas`, no rival) applies under both.
- **Proc rows.** Aquila Favonia's Falcon (`premod.atk`), Skyward Harp's AoE (`total.atk`, its
  own CRIT DMG applying) and Skyward Pride's vacuum blade (its own all-DMG applying): GO
  `customDmgNode(prod(x, atk), 'elemental', {hit: {ele: physical}})` (`dataUtil.tsx:113-138`),
  the whole chain with no move-scoped bonus.
"""

from __future__ import annotations

from typing import Any

from app.formula.genshin import weapon_passives
from app.schemas.formula import FormulaBonusRead
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import go_fixtures_weapons as w
from tests.unit import go_fixtures_weapons2 as w2
from tests.unit import test_go_formula_fixtures as base

SHEETS = "libs/gi/sheets/src/"
NONSTACK = [f"{SHEETS}SheetUtil.tsx:102-117", "libs/gi/uidata/src/uiData.ts:217-218,266-276"]
PROC = f"{SHEETS}Characters/dataUtil.tsx:113-138"


def source(nanoka_id: str, refinement: int, wielder: str, stats: dict[str, float], *,
           subject: bool, rank: str | None = None, receiver_element: str = "pyro",
           team_elements: list[str] | None = None) -> dict[str, Any]:
    """`w.weapon_source`, plus what this batch adds to the wire: the wielder's GO key and the
    weapon's procs (`FormulaKitSourceRead.stack_rank`, `.procs`)."""
    passive = weapon_passives.passive_for(nanoka_id)
    assert passive is not None, nanoka_id
    resolved = weapon_passives.resolve(
        passive,
        weapon_passives.Wielder(wielder, refinement, list(passive.pins[refinement]),
                                base._stated_registry(stats), stack_rank=rank),
        wielder_is_subject=subject, receiver_element=receiver_element,
        team_elements=team_elements,
    )
    out = {"id": resolved.source_id, "label": resolved.label, "citation": resolved.citation,
           "bonus": FormulaBonusRead.of(resolved.bonus).model_dump()}
    if rank is not None:
        out["stack_rank"] = rank
    if resolved.procs:
        out["procs"] = [p.model_dump(mode="json") for p in resolved.procs]
    return out


def _mine(name: str, covers: str, go: str, weapon: str, nanoka_id: str, r: int,
          artifacts: dict[str, float], row: dict[str, Any], conditionals: dict[str, Any],
          figure: Any, divergence: str = "none: no reaction") -> dict[str, Any]:
    """Xiangling wielding the weapon, as the optimized character."""
    return w._fx(name, covers, [w.FORMULA, f"{w.WEAPONS}{go}"],
                 w._wielder("Xiangling", weapon, r, w.SUBJECT), w2.XTEAM, w2.XB, artifacts,
                 "pyro", [row], source(nanoka_id, r, "Xiangling", w2.XB, subject=True),
                 conditionals, figure, divergence)


def _xiangling(artifacts: dict[str, float], x: dict[str, float], *,
               vape: bool = False) -> Any:
    return w._figure(w2.XB, artifacts, base.PYRONADO, "pyro", x, amplifying=vape)


def conversion_fixtures() -> list[dict[str, Any]]:
    """The four conversions #389 withheld on the wielder, each now per candidate."""
    xa = w2.XA
    stats = base._stats(w2.XB, xa)
    em = stats["elemental_mastery"]
    out: list[dict[str, Any]] = []

    # Engulfing Lightning R1, Timeless Dream on: ER 1.0 + the candidate's 0.2 + 0.3 = 1.5.
    er = 1.0 + 0.2 + 0.3
    engulfing = _mine(
        "engulfing_lightning_r1_atk_from_er_on_xiangling",
        "a self ATK% from the wielder's own Energy Recharge above 100%, per candidate "
        "(atk_pct_from_er), the ER including the passive's own Timeless Dream",
        "Polearm/EngulfingLightning/index.tsx:16-52", "Engulfing Lightning", "13509", 1,
        {**xa, "energy_recharge": 0.2}, w.NADO, {"weapon:engulfing_lightning/dream": 1},
        _xiangling(xa, {"atk_pct": min(0.28 * (er - 1), 0.8)}))
    out.append(engulfing)
    # Past the 80% cap: a candidate carrying 300% ER, 0.28 × (4.3 − 1) = 0.924 → 0.8.
    er_past = 1.0 + 3.0 + 0.3
    past = _mine(
        "engulfing_lightning_r1_past_its_cap_on_xiangling",
        "the same past its 80% cap (a candidate with 300% Energy Recharge)",
        "Polearm/EngulfingLightning/index.tsx:16-52", "Engulfing Lightning", "13509", 1,
        {**xa, "energy_recharge": 3.0}, w.NADO, {"weapon:engulfing_lightning/dream": 1},
        _xiangling(xa, {"atk_pct": min(0.28 * (er_past - 1), 0.8)}))
    past["cap_state"] = "past"
    out.append(past)

    # Key of Khaj-Nisut R1 at three stacks: EM from the wielder's own Max HP (total, carrying
    # the weapon's own 20% HP), self 3 × 0.12% and the party share 0.2%; into a vaporize.
    key_arts = {**xa, "hp_pct": 0.466}
    hp = w2.XB["base_hp"] * (1 + 0.466 + 0.2) + w2.XB["flat_hp"]
    out.append(w._fx(
        "key_of_khaj_nisut_r1_em_from_hp_on_xiangling_vape",
        "a self EM from the wielder's own Max HP per stack and the party share at three stacks, "
        "per candidate (em_from_hp); Xiangling stands in as a sword's wielder",
        [w.FORMULA_AMP, f"{w.WEAPONS}Sword/KeyOfKhajNisut/index.tsx:17-84"],
        w._wielder("Xiangling", "Key of Khaj-Nisut", 1, w.SUBJECT), w2.XTEAM, w2.XB,
        key_arts, "pyro", [w.NADO_VAPE],
        source("11511", 1, "Xiangling", w2.XB, subject=True),
        {"weapon:key_of_khaj_nisut/stacks": 3},
        _xiangling(key_arts, {"hp_pct": 0.2, "em": (3 * 0.0012 + 0.002) * hp}, vape=True),
        w.AMP_DIVERGENCE))

    # Makhaira Aquamarine R1 / Wandering Evenstar R5: ATK from the wielder's own EM.
    out.append(_mine(
        "makhaira_aquamarine_r1_atk_from_em_on_xiangling",
        "a self flat ATK from the wielder's own EM, per candidate (flat_atk_from_em); "
        "Xiangling stands in as a claymore's wielder",
        "Claymore/MakhairaAquamarine/index.tsx:16-44", "Makhaira Aquamarine", "12415", 1,
        xa, w.NADO, {}, _xiangling(xa, {"flat_atk": 0.24 * em})))
    out.append(_mine(
        "wandering_evenstar_r5_atk_from_em_on_xiangling",
        "the same at R5 (48%); Xiangling stands in as a catalyst's wielder",
        "Catalyst/WanderingEvenstar/index.tsx:16-44", "Wandering Evenstar", "14416", 5,
        xa, w.NADO, {}, _xiangling(xa, {"flat_atk": 0.48 * em})))

    # Peak Patrol Song R1, two Ode stacks and the party bonus: DEF% 2 × 8% and Elemental DMG
    # 2 × 10% on the wielder, and 8% per 1,000 of their own total DEF (with the Ode DEF%), to
    # 3,200 DEF.
    for label, def_pct, state in (("below", 0.0, "below"), ("past", 4.0, "past")):
        arts = {**xa, "def_pct": def_pct}
        total_def = w2.XB["base_def"] * (1 + def_pct + 0.16)
        party = 0.08 * min(total_def, 3200.0) / 1000
        fixture = _mine(
            f"peak_patrol_song_r1_dmg_from_def_{label}_its_cap_on_xiangling",
            f"a self party DMG from the wielder's own DEF per candidate (dmg_bonus_from_def), "
            f"{label} the 3,200 DEF stat cap; the Ode's own DEF% in the DEF it reads; Xiangling "
            "stands in as a sword's wielder",
            "Sword/PeakPatrolSong/index.tsx:22-77", "Peak Patrol Song", "11516", 1, arts,
            w.NADO, {"weapon:peak_patrol_song/ode": 2, "weapon:peak_patrol_song/maxed": 1},
            _xiangling(arts, {"def_pct": 0.16, "dmg": 2 * 0.1 + party}))
        fixture["cap_state"] = state
        out.append(fixture)
    return out


#: The owner's ruling of 2026-11-15 (`docs/DECISIONS.md` §46), where it moves a figure off GO's.
STRONGER_DIVERGENCE = (
    "non-stacking: the stronger buff applies (owner ruling 2026-11-15) — Venti's R5 Elegy 40% "
    "ATK; GO applies Kazuha's R1 Freedom-Sworn 20%, his character key sorting first "
    "(uiData.ts:266-276); `go_value` is GO's figure under GO's rule"
)


def non_stack_fixtures() -> list[dict[str, Any]]:
    """Two Millennial Movement wielders: one applies, **the stronger** (owner ruling 2026-11-15,
    `docs/DECISIONS.md` §46) — where GO applies the one whose wielder's key sorts first.

    `expected` is ours: Venti's R5 Elegy 40% ATK, larger than Kazuha's R1 Freedom-Sworn 20%.
    `go_value` is GO's own figure, Freedom-Sworn's 20% (and GO's 25/9), stated beside it. The
    family is decided per GO name: Elegy's EM (`millenialelemas`) has no rival and applies under
    both rules; Freedom-Sworn's normal/charged/plunge DMG (`millenialncpdmg`) has none either and
    misses a burst row under both.
    """
    team = {**w2.XTEAM, "member_elements": ["pyro", "anemo", "anemo", "hydro"]}
    venti = source("15503", 5, "Venti", {}, subject=False, rank="Venti",
                   team_elements=team["member_elements"])
    kazuha = source("11503", 1, "Kaedehara Kazuha", {}, subject=False, rank="KaedeharaKazuha",
                    team_elements=team["member_elements"])
    ours = _xiangling(w2.XA, {"em": 200.0, "atk_pct": 0.4}, vape=True)
    gos = _xiangling(w2.XA, {"em": 200.0, "atk_pct": 0.2}, vape=True)
    fixture = w._fx(
        "millennial_movement_one_the_stronger_elegy_over_freedom_sworn_on_xiangling_vape",
        "two Millennial Movement wielders, both on: one shared ATK% applies — the stronger, "
        "Venti's R5 Elegy 40% (owner ruling 2026-11-15), where GO applies Kazuha's R1 "
        "Freedom-Sworn 20% by key order; Elegy's EM, which nothing else shares, applies",
        [w.FORMULA_AMP, f"{w.WEAPONS}Bow/ElegyForTheEnd/index.tsx:8-43",
         f"{w.WEAPONS}Sword/FreedomSworn/index.tsx:9-59", *NONSTACK],
        w._wielder("Venti", "Elegy for the End", 5, {}), team, w2.XB, w2.XA, "pyro",
        [w.NADO_VAPE], venti,
        {"weapon:elegy_for_the_end/farewell": 1, "weapon:freedom_sworn/song": 1},
        ours, f"{w.AMP_DIVERGENCE}; {STRONGER_DIVERGENCE}")
    fixture["go_value"] = gos(base.GO_EM_COEFFICIENT)
    fixture["givers"].append(w._wielder("Kaedehara Kazuha", "Freedom-Sworn", 1, {}))
    fixture["sources"].append(kazuha)
    fixture["non_stack"] = "millenialatk"
    fixture["non_stack_rule"] = "stronger"
    return [fixture]


def _proc_row(source_id: str, key: str, count: float, talent: tuple[str, list[float]],
              label: str) -> dict[str, Any]:
    """A proc row: `count` instances of a weapon proc. The talent row only fetches the build's
    context, as a reaction row's does; the proc's own multiplier is read from the source."""
    row = base._row(f"proc_{key}", label, "normal", count, talent, None)
    row.update({"proc": {"source": source_id, "key": key}, "move": None,
                "channel": "physical"})
    return row


def _proc_figure(base_stats: dict[str, float], artifacts: dict[str, float], *,
                 count: float, multiplier: float, atk_pct: float = 0.0, dmg: float = 0.0,
                 cd: float = 0.0) -> Any:
    stats = base._stats(base_stats, artifacts)
    atk = base._total(stats, "atk", atk_pct)
    return lambda _c: b4._go_hit(
        base_damage=count * multiplier * atk,
        dmg_bonus=stats.get("physical_dmg_bonus", 0.0) + dmg,
        crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"] + cd)


def proc_fixtures() -> list[dict[str, Any]]:
    """Weapon proc rows on their wielder."""
    kb, ka = b8.KAEYA_BASE, b8.PHYSICAL_ARTIFACTS
    amber = (w.AMBER_BASE, w.AMBER_ARTIFACTS)
    rb, ra = b8.RAZOR_BASE, b8.RAZOR_ARTIFACTS
    return [
        w._fx("aquila_favonia_r1_falcon_proc_row_on_kaeya",
              "a proc row: two Falcon instances (200% of premod ATK, Physical), the wielder's "
              "own ATK% in that ATK",
              [w.FORMULA, f"{w.WEAPONS}Sword/AquilaFavonia/index.tsx:17-57", PROC],
              w._wielder("Kaeya", "Aquila Favonia", 1, w.SUBJECT), w2.SWORD, kb, ka, "cryo",
              [_proc_row("weapon:aquila_favonia", "falcon", 2, b8.KAEYA_NA_1, "Falcon")],
              source("11501", 1, "Kaeya", kb, subject=True, receiver_element="cryo"), {},
              _proc_figure(kb, ka, count=2, multiplier=2.0, atk_pct=0.2)),
        w._fx("skyward_harp_r1_proc_row_on_amber",
              "a proc row: three Echoing Ballad instances (125% ATK, Physical), the harp's own "
              "CRIT DMG applying to them",
              [w.FORMULA, f"{w.WEAPONS}Bow/SkywardHarp/index.tsx:17-40", PROC],
              w._wielder("Amber", "Skyward Harp", 1, w.SUBJECT), w2.BOW, *amber, "pyro",
              [_proc_row("weapon:skyward_harp", "echoing", 3, w.AMBER_NA_1, "Echoing Ballad")],
              source("15501", 1, "Amber", amber[0], subject=True), {},
              _proc_figure(*amber, count=3, multiplier=1.25, cd=0.2)),
        w._fx("skyward_pride_r5_proc_row_on_razor",
              "a proc row at R5: eight vacuum blades (160% ATK, Physical), the Pride's own "
              "all-DMG applying to them",
              [w.FORMULA, f"{w.WEAPONS}Claymore/SkywardPride/index.tsx:16-46", PROC],
              w._wielder("Razor", "Skyward Pride", 5, w.SUBJECT), w2.CLAYMORE, rb, ra,
              "electro",
              [_proc_row("weapon:skyward_pride", "vacuum", 8, b8.RAZOR_NA_1, "Vacuum blade")],
              source("12501", 5, "Razor", rb, subject=True, receiver_element="electro"), {},
              _proc_figure(rb, ra, count=8, multiplier=1.6, dmg=0.16)),
    ]


def weapon_compare_fixtures() -> list[dict[str, Any]]:
    """Every fixture of this batch."""
    return [*conversion_fixtures(), *non_stack_fixtures(), *proc_fixtures()]
