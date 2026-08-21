"""Capture trusted (id → value) anchor snapshots from the DB for triangulation.

The DB is the source of truth (seeded from nanoka). FileCfg column triangulation
(T2.2) joins a table's hash-obfuscated columns to these snapshots and labels a
column only when it reproduces a trusted field. Snapshotting means re-derivation
needs no live DB; **re-capture after a reseed** (hash columns also rotate per
patch — see ``build_column_dicts.py``).

Writes:

* ``schema/_db_attack_anchors.json``   — per-attack multipliers (AvatarSkillTemplateTb)
* ``schema/_db_agent_anchors.json``    — per-agent base stats + metadata (AvatarBattleTemplateTb)
* ``schema/_db_wengine_anchors.json``  — per-W-Engine base/secondary stat (WeaponTemplateTb)
* ``schema/_db_enemy_anchors.json``    — per-enemy DEF/RES/capacity (Monster* — T2.2e)

Run inside the backend container (needs DATABASE_URL)::

    python -m scripts.dimbreath.capture_db_anchors
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.database import async_session_factory
from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.w_engine import WEngine
from scripts.dimbreath.fetch import SCHEMA_DIR

_AGENT_FIELDS = [
    "element",
    "specialty",
    "rarity",
    "faction_id",
    "base_hp",
    "base_atk",
    "base_def",
    "hp_growth",
    "atk_growth",
    "def_growth",
    "base_crit_rate",
    "base_crit_dmg",
    "base_anomaly_mastery",
    "base_anomaly_proficiency",
    "base_impact",
    "base_energy_regen",
    "base_pen_flat",
    "base_pen_ratio",
]

_ATTACK_FIELDS = [
    "damage_base",
    "damage_growth",
    "stun_base",
    "stun_growth",
    "energy_gain",
    "anomaly_buildup",
    "skill_key",
]


_WENGINE_FIELDS = [
    "base_atk",
    "secondary_stat_value",
    "secondary_stat_type",
    "rarity",
    "specialty",
    "name",
]

# Per-enemy combat fields for Monster* triangulation (T2.2e). Captured now so the
# Monster builder has anchors ready; note the per-monster combat stats are *not*
# stored value-matchably in MonsterConfigTemplateTb (a spawn/config table keyed by
# config id) — they come from a referenced property template + level curve. See
# docs/MAP_column_dictionaries.md (T2.2e thread).
_ENEMY_FIELDS = [
    "defense",
    "hp",
    "atk",
    "physical_res", "fire_res", "ice_res", "electric_res", "ether_res", "wind_res",
    "anomaly_capacity_physical", "anomaly_capacity_fire", "anomaly_capacity_ice",
    "anomaly_capacity_electric", "anomaly_capacity_ether", "anomaly_capacity_wind",
    "stun_dmg_taken_ratio", "stun_threshold", "rarity",
]


def _norm(v: Any) -> Any:
    """Enum columns come back as Element/Specialty/Rarity — store their value."""
    return v.value if hasattr(v, "value") else v


async def _capture() -> None:
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        attacks = (await session.execute(select(Attack))).scalars().all()
        wengines = (await session.execute(select(WEngine))).scalars().all()
        enemies = (await session.execute(select(EnemyProfile))).scalars().all()

    agent_rows = [
        {"avatar_id": a.hakushin_id, "name": a.name,
         **{f: _norm(getattr(a, f)) for f in _AGENT_FIELDS}}
        for a in agents
    ]
    agent_rows.sort(key=lambda r: r["avatar_id"])
    _write(
        "_db_agent_anchors.json",
        note=(
            "DB Agent-table anchors for FileCfg column triangulation (T2.2b, "
            "AvatarBattleTemplateTb). Source of truth = Postgres (seeded from "
            "nanoka). Re-capture after reseed; hash columns also rotate per patch."
        ),
        fields=_AGENT_FIELDS,
        key="agents",
        rows=agent_rows,
    )

    attack_rows = [
        {"skill_id": a.hakushin_skill_id,
         **{f: _norm(getattr(a, f)) for f in _ATTACK_FIELDS}}
        for a in attacks
    ]
    attack_rows.sort(key=lambda r: r["skill_id"])
    _write(
        "_db_attack_anchors.json",
        note=(
            "DB Attack-table anchors for FileCfg column triangulation (T2.2). "
            "Source of truth = Postgres (seeded from nanoka). Re-capture after "
            "reseed."
        ),
        fields=_ATTACK_FIELDS,
        key="attacks",
        rows=attack_rows,
    )

    wengine_rows = [
        {"weapon_id": w.hakushin_id,
         **{f: _norm(getattr(w, f)) for f in _WENGINE_FIELDS}}
        for w in wengines
    ]
    wengine_rows.sort(key=lambda r: r["weapon_id"])
    _write(
        "_db_wengine_anchors.json",
        note=(
            "DB WEngine-table anchors for FileCfg column triangulation (T2.2d, "
            "WeaponTemplateTb). Source of truth = Postgres (seeded from nanoka). "
            "Re-capture after reseed; hash columns also rotate per patch."
        ),
        fields=_WENGINE_FIELDS,
        key="wengines",
        rows=wengine_rows,
    )

    enemy_rows = [
        {"monster_id": e.hakushin_id,
         **{f: _norm(getattr(e, f)) for f in _ENEMY_FIELDS}}
        for e in enemies
        if e.hakushin_id is not None
    ]
    enemy_rows.sort(key=lambda r: r["monster_id"])
    _write(
        "_db_enemy_anchors.json",
        note=(
            "DB EnemyProfile anchors for FileCfg Monster* triangulation (T2.2e). "
            "Source of truth = Postgres (seeded from nanoka). NOTE: per-monster "
            "DEF/RES/capacity are NOT stored value-matchably in "
            "MonsterConfigTemplateTb (config table keyed by spawn-config id); they "
            "derive from a referenced property template + level curve. T2.2e must "
            "locate that property table first — see docs/MAP_column_dictionaries.md."
        ),
        fields=_ENEMY_FIELDS,
        key="enemies",
        rows=enemy_rows,
    )


def _write(filename: str, *, note: str, fields: list[str], key: str,
           rows: list[dict[str, Any]]) -> None:
    out = SCHEMA_DIR / filename
    doc = {
        "_note": note,
        "captured_at": datetime.now(UTC).isoformat(),
        "count": len(rows),
        "fields": fields,
        key: rows,
    }
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out.name}: {len(rows)} {key}")


if __name__ == "__main__":
    asyncio.run(_capture())
