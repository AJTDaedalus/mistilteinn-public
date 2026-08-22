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

from app.services.gcsim_config import build_config

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


def main() -> None:
    """Write one config per case."""
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (build, actions) in CASES.items():
        path = OUT / f"{name}.txt"
        path.write_text(build_config(build, actions=actions))
        print(f"wrote {path.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
