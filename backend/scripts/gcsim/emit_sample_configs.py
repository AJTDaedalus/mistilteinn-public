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

import types
from pathlib import Path

from app.services import gcsim_keys
from app.services.gcsim_config import build_config
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


#: The R.3 pair. One rotation, compiled two ways, and the **difference between them is the
#: gate**.
#:
#: `rotation_gated` is what `rotation_compiler` really emits: a `while 1` loop with a
#: readiness gate on every step. `rotation_ungated` is the same rotation written the way a
#: person reasonably would before learning gcsim's two silent behaviours — no loop, no gates.
#:
#: Both are configs gcsim **accepts**, which is exactly the point: acceptance proves nothing.
#: `verify-gcsim-config.mjs` runs both and requires the first to cycle many times and the
#: second to run once. A gate that only ever sees passing input cannot be trusted to fail.
ROTATION_STEPS = [
    {"character": "10000002", "action": "burst", "repeat": 1},
    {"character": "10000002", "action": "skill", "repeat": 1},
    {"character": "10000002", "action": "attack", "repeat": 3},
]


def _rotation_cases() -> dict[str, str]:
    """The gated config, and the ungated control it is measured against."""
    character = _character("10000002", "Kamisato Ayaka", "Cryo")
    build = _build(character, "Mistsplitter Reforged", "Blizzard Strayer")
    roster = {"10000002": character}

    gated = compile_rotation(ROTATION_STEPS, roster)

    # The control, built by stripping the compiler's own output rather than by writing a
    # second emitter. Two generators would drift, and the one that drifted would be the one
    # nobody reads — leaving the gate comparing the real config against a stale idea of what
    # "wrong" looks like.
    key = gcsim_keys.character_key(character.nanoka_id, character.name, character.element)
    ungated_lines = [f"active {key};"]
    for step in ROTATION_STEPS:
        repeat = step["repeat"]
        call = f"{key} {step['action']}:{repeat};" if repeat > 1 else f"{key} {step['action']};"
        ungated_lines.append(call)

    return {
        "rotation_gated": build_config(build, action_block=gated),
        "rotation_ungated": build_config(build, action_block="\n".join(ungated_lines)),
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


if __name__ == "__main__":
    main()
