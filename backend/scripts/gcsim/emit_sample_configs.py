"""Emit sample gcsim configs for the browser-side validator to check.

    cd backend && python -m scripts.gcsim.emit_sample_configs

`frontend/scripts/verify-gcsim-config.mjs` feeds these to gcsim's own `validateConfig`. The
split exists because the emitter is Python and the only authority on what a valid config is
is a WebAssembly module — so the two halves meet through files rather than through a claim.

Cases are hand-written rather than seeded from the database on purpose: this gate is about
the *emitter's* output being well-formed, and a case that needs a seeded database is a gate
that skips when the database is absent.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from app.services import gcsim_keys
from app.services.gcsim_config import Calibration, build_config
from app.services.rotation_compiler import compile_rotation

OUT = Path(__file__).resolve().parents[3] / "frontend" / "gcsim" / "emitted"


def _character(nanoka_id: str, name: str, element: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(nanoka_id=nanoka_id, name=name, element=element)


def _build(
    character: types.SimpleNamespace,
    weapon_name: str,
    set_name: str,
    **overrides: object,
) -> types.SimpleNamespace:
    artifact_set = types.SimpleNamespace(name=set_name)
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
        "id": "sample", "character": character,
        "weapon": types.SimpleNamespace(name=weapon_name),
        "artifacts": artifacts, "character_level": 90, "constellation_level": 0,
        "weapon_level": 90, "refinement": 1,
        "talent_levels": {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9},
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


#: One ordinary character, and one Traveler — the case normalisation cannot reach.
CASES = {
    "ayaka": (
        _build(_character("10000002", "Kamisato Ayaka", "Cryo"),
               "Mistsplitter Reforged", "Blizzard Strayer"),
        ["burst", "skill", "attack:3"],
    ),
    "traveler_pyro": (
        _build(_character("10000005-2", "Traveler", "Pyro"),
               "Favonius Sword", "Gladiator's Finale"),
        ["skill", "attack:2"],
    ),
}


#: The R.3 pair, rewritten for the emitter that runs a rotation **to completion**.
#:
#: The old pair asked whether the compiled config *looped* — `while 1` against a bare list —
#: because the failure of the day was a rotation that ran once over a ninety-second clock.
#: That question is now meaningless: there is no loop and no clock, and a rotation runs
#: exactly as long as its author wrote it.
#:
#: The property that replaced it is the one the owner actually asked for: **the emitted config
#: performs the rotation's own number of cycles.** So the pair is the same rotation authored
#: twice, at `group_repeat` 3 and 1, and the check requires gcsim to report 3 and 1.
#:
#: Both are configs gcsim accepts, which is still the point — acceptance proves nothing. The
#: single-cycle case is the control: without it this would be a gate that has only ever seen
#: passing input, which is not a gate.
#:
#: **The counted action is the skill, not the burst.** A burst is the one action the compiler
#: gates, so a starved rotation skips it and the count would measure energy rather than
#: length. A skill only ever waits for its cooldown, and gcsim always waits.
def _rotation_steps(group_repeat: int) -> list[dict[str, object]]:
    return [
        {"character": "10000002", "action": "burst", "repeat": 1,
         "group": "core", "group_repeat": group_repeat},
        {"character": "10000002", "action": "skill", "repeat": 1,
         "group": "core", "group_repeat": group_repeat},
        {"character": "10000002", "action": "attack", "repeat": 3,
         "group": "core", "group_repeat": group_repeat},
    ]


#: How many cycles the repeated case is authored with.
#:
#: **Written to a manifest beside the configs, not re-read from them.** The first cut of the
#: verifier counted the cycles in the emitted file and compared that to what gcsim ran — which
#: compares the config against itself and passes for *any* number the compiler happens to
#: emit. Deleting a cycle from the fixture was not caught. The authored count has to come from
#: outside the artefact being checked or the check has only one possible answer.
ROTATION_CYCLES = 3


def _rotation_cases() -> dict[str, str]:
    """The gated config, and the ungated control it is measured against."""
    character = _character("10000002", "Kamisato Ayaka", "Cryo")
    build = _build(character, "Mistsplitter Reforged", "Blizzard Strayer")
    roster = {"10000002": character}

    repeated = compile_rotation(_rotation_steps(ROTATION_CYCLES), roster)

    # The control, produced by the **same** compiler with a different authored repeat, rather
    # than by a second emitter written to look wrong. Two generators would drift, and the one
    # that drifted would be the one nobody reads.
    once = compile_rotation(_rotation_steps(1), roster)

    # R.3. A calibration replaces the build's artifacts with one 4-piece set and an ER, and
    # it is emitted here so the existing `gcsim:verify-config` gate proves gcsim accepts it —
    # rather than a second gate that would have to be kept in step with this one.
    #
    # **The ER is +30 %, which is a measurement.** R.2a swept this rotation and found the
    # burst count only reaches 3 with `sd == 0` from there; a zero-ER calibration lands on 2
    # and would describe a rotation nobody is scoring (`RESEARCH_recipe_risks.md` §1).
    calibrated = build_config(
        build,
        action_block=repeated,
        calibration=Calibration(
            set_key=gcsim_keys.artifact_set_key("Blizzard Strayer"),
            energy_recharge=0.30,
        ),
    )

    return {
        "rotation_repeated": build_config(build, action_block=repeated),
        "rotation_once": build_config(build, action_block=once),
        "rotation_calibrated": calibrated,
    }


def main() -> None:
    """Write one config per case."""
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (build, actions) in CASES.items():
        path = OUT / f"{name}.txt"
        path.write_text(build_config(build, actions=actions))
        print(f"wrote {path.relative_to(OUT.parents[2])}")
    for name, text in _rotation_cases().items():
        path = OUT / f"{name}.txt"
        path.write_text(text)
        print(f"wrote {path.relative_to(OUT.parents[2])}")
    manifest = OUT / "rotation_cycles.json"
    manifest.write_text(json.dumps(
        {"rotation_repeated": ROTATION_CYCLES, "rotation_once": 1}, indent=2) + "\n")
    print(f"wrote {manifest.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
