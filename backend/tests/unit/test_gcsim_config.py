"""B.3 — emitting a gcsim config from a stored build.

The test that matters is not "the string looks right". It is
`scripts/verify-gcsim-config.mjs`, which feeds an emitted config to **gcsim's own
`validateConfig`** — the only authority on whether this text is a config. String assertions
here pin the decisions; the validator pins that the result is real.
"""

from __future__ import annotations

import types

import pytest

from app.services import gcsim_config
from app.services.gcsim_config import (
    Calibration,
    GcsimConfigError,
    SubstituteWeapon,
    build_config,
)
from app.services.gcsim_keys import GcsimKeyError


def _build(**overrides):
    character = types.SimpleNamespace(
        nanoka_id="10000002", name="Kamisato Ayaka", element="Cryo",
    )
    artifact_set = types.SimpleNamespace(name="Blizzard Strayer")
    artifacts = [
        types.SimpleNamespace(
            artifact_set=artifact_set,
            main_stat_type="FIGHT_PROP_CRITICAL_HURT",
            main_stat_value=0.155,
            substats=[{"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.116}],
        )
        for _ in range(4)
    ]
    fields = {
        "id": "b1", "character": character,
        "weapon": types.SimpleNamespace(name="Mistsplitter Reforged"),
        "artifacts": artifacts, "character_level": 90, "constellation_level": 0,
        "weapon_level": 90, "refinement": 1,
        "talent_levels": {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9},
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


def test_it_emits_the_gcsim_key_not_the_display_name():
    config = build_config(_build(), actions=["burst"])

    assert "kamisatoayaka char" in config
    assert 'weapon="mistsplitterreforged"' in config
    assert 'set="blizzardstrayer" count=4' in config


def test_artifacts_become_set_counts_plus_one_stat_total():
    """gcsim does not model individual artifacts — it takes set counts and a stat sum.

    Which is precisely why the optimizer is this project's job and not gcsim's: gcsim can
    score a build, but it has no notion of *which five pieces* produced it.
    """
    config = build_config(_build(), actions=["burst"])

    assert "add stats" in config
    # Four pieces at 0.116 ATK% and 0.155 crit DMG, summed once.
    assert "atk%=0.464" in config
    assert "cd=0.62" in config


def test_talents_are_emitted_in_gcsims_order():
    config = build_config(
        _build(talent_levels={"normal_attack": 1, "elemental_skill": 6, "elemental_burst": 9}),
        actions=["burst"],
    )

    assert "talent=1,6,9;" in config


def test_a_missing_talent_level_defaults_to_one_rather_than_zero():
    """A talent is level 1 at minimum. Zero is not a level the game has, and gcsim would
    either reject it or simulate something impossible."""
    config = build_config(_build(talent_levels={}), actions=["burst"])

    assert "talent=1,1,1;" in config


# ---- Refusals --------------------------------------------------------------

def test_a_build_with_no_character_is_refused():
    with pytest.raises(GcsimConfigError, match="nothing to simulate"):
        build_config(_build(character=None), actions=["burst"])


def test_an_empty_action_list_is_refused():
    """gcsim needs a rotation, and this repo has no rotation model. A guessed one would
    simulate something other than what was asked for."""
    with pytest.raises(GcsimConfigError, match="action list"):
        build_config(_build(), actions=[])


def test_a_stat_gcsim_cannot_name_is_refused_rather_than_dropped():
    """Dropping it would understate the build by however much it was worth, silently."""
    odd = types.SimpleNamespace(
        artifact_set=None, main_stat_type="FIGHT_PROP_SHIELD_COST_MINUS_RATIO",
        main_stat_value=0.2, substats=[],
    )
    with pytest.raises(GcsimConfigError, match="no stat name"):
        build_config(_build(artifacts=[odd]), actions=["burst"])


def test_a_character_gcsim_does_not_implement_is_refused():
    newer = types.SimpleNamespace(nanoka_id="10000122", name="Nefer", element="Pyro")
    with pytest.raises(GcsimKeyError, match="Nefer"):
        build_config(_build(character=newer), actions=["burst"])


def test_an_enemy_with_uneven_resistances_is_refused_not_averaged():
    """A gcsim target takes one `resist=`. Averaging eight channels simulates an enemy that
    does not exist, and returns a number for it."""
    enemy = types.SimpleNamespace(
        name="Cryo Regisvine", level=90,
        physical_res=0.1, anemo_res=0.1, cryo_res=0.5, dendro_res=0.1,
        electro_res=0.1, geo_res=0.1, hydro_res=0.1, pyro_res=0.1,
    )
    with pytest.raises(GcsimConfigError, match="uneven resistances"):
        build_config(_build(), actions=["burst"], enemy=enemy)


def test_an_evenly_resistant_enemy_is_emitted():
    enemy = types.SimpleNamespace(
        name="Dummy", level=100,
        **{f"{c}_res": 0.1 for c in
           ("physical", "anemo", "cryo", "dendro", "electro", "geo", "hydro", "pyro")},
    )
    config = build_config(_build(), actions=["burst"], enemy=enemy)

    assert "target lvl=100 resist=0.1 pos=0,1 hp=999999999;" in config


# ── W.2/W.3 — substituting a candidate weapon ────────────────────────────────
#
# **W.3's entire purpose is the second test below.** A substitution that silently keeps the
# worn weapon produces a flat ranking — every candidate scoring the worn weapon's number —
# and that reads as "these weapons are equivalent" rather than as a bug. A user would believe
# it. So the assertion is not merely "the candidate appears": it is that two *different*
# candidates produce two *different* configs, which a no-op cannot satisfy.


def _candidate(name="The Stringless", level=90, refinement=1):
    return SubstituteWeapon(
        weapon=types.SimpleNamespace(name=name), level=level, refinement=refinement,
    )


def test_the_candidate_replaces_the_worn_weapon():
    config = build_config(_build(), actions=["burst"], substitute_weapon=_candidate())

    assert 'weapon="thestringless"' in config
    assert "mistsplitterreforged" not in config


def test_two_candidates_produce_two_different_configs():
    """The no-op check. If substitution does nothing these are byte-identical."""
    a = build_config(_build(), actions=["burst"], substitute_weapon=_candidate("The Stringless"))
    b = build_config(_build(), actions=["burst"], substitute_weapon=_candidate("Rust"))

    assert a != b
    assert 'weapon="thestringless"' in a
    assert 'weapon="rust"' in b


def test_only_the_weapon_line_changes():
    """Everything else must be held fixed, or the comparison is not about weapons.

    A substitution that perturbed the character, artifacts or target would produce a ranking
    of *configs* while claiming to be a ranking of weapons.
    """
    worn = build_config(_build(), actions=["burst"]).splitlines()
    swapped = build_config(
        _build(), actions=["burst"], substitute_weapon=_candidate(),
    ).splitlines()

    assert len(worn) == len(swapped)
    differing = [i for i, (x, y) in enumerate(zip(worn, swapped, strict=True)) if x != y]
    assert len(differing) == 1
    assert "weapon=" in worn[differing[0]]


def test_the_candidates_level_and_refinement_are_emitted():
    config = build_config(
        _build(), actions=["burst"], substitute_weapon=_candidate(level=70, refinement=5),
    )

    assert "lvl=70/90 refine=5;" in config


def test_a_candidate_is_emitted_even_when_the_build_wears_nothing():
    """"Compare these against nothing worn" is a coherent question.

    Falling through to the no-weapon branch would answer a different one — and would do it by
    emitting a config with no weapon line at all, which gcsim accepts.
    """
    config = build_config(
        _build(weapon=None), actions=["burst"], substitute_weapon=_candidate(),
    )

    assert 'weapon="thestringless"' in config


def test_without_a_candidate_the_worn_weapon_is_still_used():
    """The default path must not regress: this is what every existing caller does."""
    config = build_config(_build(), actions=["burst"])

    assert 'weapon="mistsplitterreforged"' in config


def test_a_candidate_gcsim_does_not_implement_refuses():
    """The refusal propagates rather than the candidate being dropped.

    A dropped candidate would leave a config with no weapon line — a weaker build simulated
    successfully, ranked, and presented as that weapon's score.
    """
    with pytest.raises(GcsimKeyError):
        build_config(
            _build(), actions=["burst"], substitute_weapon=_candidate("Not A Real Weapon"),
        )


# ── R.3 — calibration configs ────────────────────────────────────────────────
#
# A calibration replaces the build's artifacts with **one 4-piece set and an Energy Recharge**.
# Both halves are load-bearing and neither is obvious:
#
# - The **set** is equipped because all 60 sets with a 4-piece have a conditional one, and the
#   kernel understates them by 15-25% (R.2). Only gcsim can apply it.
# - The **ER** is not zero. It is an artifact stat, so a zero-ER calibration lands on a
#   different burst count — measured at 2 against a real candidate's 3
#   (`RESEARCH_recipe_risks.md` §1).


def _calibration(set_key="blizzardstrayer", energy_recharge=0.30):
    return Calibration(set_key=set_key, energy_recharge=energy_recharge)


def test_a_calibration_equips_the_set_and_the_energy_recharge():
    config = build_config(_build(), actions=["burst"], calibration=_calibration())

    assert 'add set="blizzardstrayer" count=4;' in config
    assert "add stats er=0.3;" in config


def test_a_calibration_emits_no_other_stat():
    """The candidate's stats are what the search varies. One baked in here is counted twice."""
    config = build_config(_build(), actions=["burst"], calibration=_calibration())
    stats_lines = [line for line in config.splitlines() if "add stats" in line]

    assert stats_lines == ["kamisatoayaka add stats er=0.3;"]


def test_a_calibration_replaces_the_build_s_own_artifacts():
    """Falling through would bake the build's substats into every recipe scored against it."""
    build = _build()
    assert build.artifacts, "the fixture must start with artifacts, or this proves nothing"

    config = build_config(build, actions=["burst"], calibration=_calibration())

    assert "blizzardstrayer" in config
    assert "add stats atk%" not in config


def test_a_calibration_with_no_set_still_states_its_energy_recharge():
    """A combination reaching no 4-piece still needs a recipe, and still needs an ER.

    Absent would read as "unspecified" rather than "none", and a recipe's minimum ER is only
    meaningful against a calibration that states one.
    """
    config = build_config(
        _build(), actions=["burst"], calibration=_calibration(set_key=None),
    )

    assert "add set=" not in config
    assert "add stats er=0.3;" in config


def test_zero_energy_recharge_is_emitted_rather_than_omitted():
    config = build_config(
        _build(), actions=["burst"], calibration=_calibration(energy_recharge=0.0),
    )

    assert "add stats er=0;" in config


def test_without_a_calibration_the_build_s_artifacts_are_used():
    """The default path must not regress — this is what every existing caller does."""
    config = build_config(_build(), actions=["burst"])

    assert 'set="blizzardstrayer" count=4' in config
    assert "add stats" in config


def test_a_two_piece_calibration_equips_both_sets_at_two():
    """B.3 — a 2+2 state, so gcsim applies a conditional 2-piece rather than us deriving it.

    Six of the nine conditional 2-piece bonuses are ability-scoped (Noblesse Oblige's burst
    +20 %, Marechaussee Hunter's normal/charged +15 %). A flat stat pool cannot say *only on
    burst hits*, so owner ruling 1 calibrates them.
    """
    config = build_config(
        _build(),
        actions=["burst"],
        calibration=Calibration(
            set_key=None, energy_recharge=0.30,
            two_piece_set_keys=("noblesseoblige", "gladiatorsfinale"),
        ),
    )

    assert 'add set="noblesseoblige" count=2;' in config
    assert 'add set="gladiatorsfinale" count=2;' in config
    assert "count=4" not in config


def test_a_calibration_refuses_to_be_both_a_four_piece_and_a_two_plus_two():
    """Five slots cannot hold both, and emitting it would describe a build that cannot exist."""
    with pytest.raises(ValueError, match="either a 4-piece or a 2\\+2"):
        Calibration(
            set_key="blizzardstrayer", energy_recharge=0.30,
            two_piece_set_keys=("noblesseoblige",),
        )


def test_a_calibration_refuses_more_two_piece_sets_than_slots_allow():
    """Three 2-piece sets need six slots."""
    with pytest.raises(ValueError, match="at most two"):
        Calibration(
            set_key=None, energy_recharge=0.30,
            two_piece_set_keys=("a", "b", "c"),
        )


# ── everyone the rotation names has to be declared ───────────────────────────
#
# **The zero-damage bug.** `/builds/{id}/calibrate` emitted one character's stanza beside a
# four-character action block. gcsim does not reject that: it accepts the config and simulates
# *nobody* — `character_details` comes back `[]`, the log is two bytes, every damage is zero —
# while `sample()` returns perfectly valid JSON throughout. So a caller checking "did it parse"
# saw a clean result describing an empty simulation, calibrated a recipe of zeros from it, and
# `/optimize` ranked ten builds at 0 damage while labelling them `isExact`.
#
# Measured against the real config: 2 bytes of log before, 3,069,118 after.
# `AUDIT_fribbels_parity.md` §9a.


def _mate(key_name: str, nanoka_id: str, element: str, **overrides):
    return _build(
        id=f"b-{nanoka_id}",
        character=types.SimpleNamespace(
            nanoka_id=nanoka_id, name=key_name, element=element,
        ),
        **overrides,
    )


_TEAM_BLOCK = (
    "active furina;\n"
    "while 1 {\n"
    "    if .furina.burst.ready { furina burst; }\n"
    "    if .kamisatoayaka.attack.ready { kamisatoayaka attack:3; }\n"
    "}\n"
)


def test_a_rotation_naming_an_undeclared_character_is_refused():
    """The guard. Without it this config is accepted by gcsim and simulates nobody."""
    with pytest.raises(GcsimConfigError, match="furina"):
        build_config(_build(), action_block=_TEAM_BLOCK)


def test_declaring_the_teammate_makes_the_same_rotation_emit():
    config = build_config(
        _build(),
        teammates=[_mate("Furina", "10000089", "Hydro")],
        action_block=_TEAM_BLOCK,
    )

    assert "furina char" in config
    assert "kamisatoayaka char" in config


def test_a_teammate_carries_their_own_gear_not_the_calibration():
    """A Furina at calibration stats is a different Furina.

    Her buffs are what the subject's damage is being measured *inside*, which is the whole of
    the owner's ruling that ranking asks "given this character in this team"
    (`DECISIONS.md` §22). Calibration replaces only the subject's artifacts.
    """
    config = build_config(
        _build(),
        teammates=[_mate("Furina", "10000089", "Hydro")],
        calibration=_calibration(set_key=None),
        action_block=_TEAM_BLOCK,
    )

    assert 'furina add set="blizzardstrayer" count=4' in config
    assert "kamisatoayaka add stats er=0.3" in config


def test_the_subject_is_never_emitted_twice():
    """A team includes the build being calibrated. Declaring them again would give gcsim two
    stanzas for one character."""
    subject = _build()
    config = build_config(subject, teammates=[subject], action_block=None, actions=["burst"])

    assert config.count("kamisatoayaka char") == 1


def test_a_solo_rotation_still_needs_no_teammates():
    """The guard must not turn every single-character config into a refusal — which is most of
    what this module emits."""
    config = build_config(_build(), actions=["burst"])

    assert "kamisatoayaka char" in config


def test_the_undeclared_character_guard_sees_a_variant_statement():
    """`skill[hold=1]` names a character exactly as `skill` does.

    The guard exists because gcsim **accepts** a config naming somebody it never declared and
    simulates nobody — `character_details` comes back empty and the damage is zero, in valid
    JSON. Before the parameter group was added to its pattern it matched nothing on a variant
    line, so a config whose only mention of a character was a hold would have walked past it.
    """
    from app.services.gcsim_config import _NAMES_A_CHARACTER

    variant = "if .chevreuse.skill.ready { chevreuse skill[hold=1]; }"
    plain = "if .chevreuse.skill.ready { chevreuse skill; }"

    assert _NAMES_A_CHARACTER.search(variant) is not None
    assert _NAMES_A_CHARACTER.search(variant).group(2) == "chevreuse"
    assert _NAMES_A_CHARACTER.search(plain).group(2) == "chevreuse"


def test_the_guard_sees_a_variant_that_also_repeats():
    from app.services.gcsim_config import _NAMES_A_CHARACTER

    line = "if .chevreuse.skill.ready { chevreuse skill[hold=1]:2; }"

    assert _NAMES_A_CHARACTER.search(line).group(2) == "chevreuse"


def test_the_energy_drip_is_emitted_only_for_the_waiting_model() -> None:
    """**Without it, waiting does not terminate.**

    gcsim has no watchdog: an ungated burst nobody can fund blocks the run while a per-frame
    stats slice grows — measured at 2.4 GB and `fatal error: out of memory`. The drip bounds
    the wait, and the *length* of that wait is the Energy Recharge penalty the waiting model
    exists to price.

    **Cited, not chosen.** Five configs use this exact line — four under `references/gcsim_db/`
    and the owner's own import — and three of them call it *standard Energy drops*. A number
    this repo invented for a ranking is the failure `CLAUDE.md` names as fairy's worst.
    """
    build = _build()

    plain = build_config(build, actions=["burst"])
    waiting = build_config(build, actions=["burst"], energy_drip=True)

    assert gcsim_config.ENERGY_DRIP not in plain
    assert gcsim_config.ENERGY_DRIP in waiting
    assert gcsim_config.ENERGY_DRIP == "energy every interval=480,720 amount=1;"
