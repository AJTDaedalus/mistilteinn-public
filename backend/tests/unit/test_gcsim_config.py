"""B.3 — emitting a gcsim config from a stored build.

The test that matters is not "the string looks right". It is
`scripts/verify-gcsim-config.mjs`, which feeds an emitted config to **gcsim's own
`validateConfig`** — the only authority on whether this text is a config. String assertions
here pin the decisions; the validator pins that the result is real.
"""

from __future__ import annotations

import types

import pytest

from app.services.gcsim_config import GcsimConfigError, build_config
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

    assert "target lvl=100 resist=0.1 pos=0,1;" in config
