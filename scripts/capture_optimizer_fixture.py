"""Capture real-data optimizer validation fixtures (Task 6a).

Produces the DB-free fixtures under
``backend/tests/fixtures/optimizer/`` used by the math checkpoints in
``docs/DESIGN_optimizer_granularity.md``.

Three modes:

* ``--discs`` (default): dump the source job's candidate disc pool and
  derive the in-frame per-(set, slot) bucket counts. Pure DB reads; this
  is how ``owner_twst1_discs.json`` / ``owner_twst1_buckets.json``
  were produced (the disc rows were exported via psql, then this script
  derives buckets + verifies the estimator).
* ``--payload``: emit ``owner_twst1_payload.json`` (build / enemy /
  Twst1 combo steps) and ``owner_subframe_small.json`` (same payload
  plus the disc pool capped to ≤6 per bucket for tractable CP5 ground
  truth).  The prod source job ``019f162b-…`` is not in the local DB, so
  the build is SYNTHETIC — stats are taken directly from the local DB
  (Ye Shunguang + Ye Shiyuan the Thrall + DB attacks at skill level 12)
  and the wengine is the highest-ATK S-rank Attack weapon in the local DB
  (Cloudcleave Radiance, base_atk=50, scaled to L60).

The disc rows themselves were exported with (psql, prod, read-only):

    SELECT json_agg(json_build_object(
      'disc_id', d.id, 'slot', d.slot, 'set_id', ds.hakushin_id,
      'set_name', ds.name, 'main_stat_type', d.main_stat_type,
      'main_stat_value', d.main_stat_value, 'substats', d.substats)
      ORDER BY d.slot, ds.hakushin_id, d.id)
    FROM discs d JOIN disc_sets ds ON ds.id = d.disc_set_id
    WHERE d.id IN (SELECT jsonb_array_elements_text(request->'disc_ids')
                   FROM optimization_jobs WHERE id = '<JOB_ID>');
"""

from __future__ import annotations

import argparse
import collections
import json
from itertools import combinations
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "backend/tests/fixtures/optimizer"
DISCS_FILE = FIXTURE_DIR / "owner_twst1_discs.json"
BUCKETS_FILE = FIXTURE_DIR / "owner_twst1_buckets.json"
PAYLOAD_FILE = FIXTURE_DIR / "owner_twst1_payload.json"
SUBFRAME_FILE = FIXTURE_DIR / "owner_subframe_small.json"

SOURCE_JOB = "019f162b-74a8-75d0-a5d6-a75287889d96"
OWNER_ID = "019e5510-5be0-74b3-a76b-b64dd3560515"
FRAME = {32700: 2, 33500: 4}  # 2pc Branch & Blade Song + 4pc White Water Ballad

# Maximum discs per (set_id, slot) bucket retained in the "small" subframe.
SUBFRAME_CAP = 6


def frame_combo_count(buckets: dict[tuple[int, int], int], cap: int | None = None) -> int:
    """Exact enumerated combo count for a 2pc+4pc frame, optionally capped at K per bucket."""
    (set_a, _), (set_b, _) = sorted(FRAME.items(), key=lambda kv: kv[1])  # a=2pc, b=4pc
    a = {s: buckets.get((set_a, s), 0) for s in range(1, 7)}
    b = {s: buckets.get((set_b, s), 0) for s in range(1, 7)}
    if cap:
        a = {s: min(v, cap) for s, v in a.items()}
        b = {s: min(v, cap) for s, v in b.items()}
    total = 0
    for two in combinations(range(1, 7), 2):  # slots holding the 2pc set
        prod = a[two[0]] * a[two[1]]
        for s in (s for s in range(1, 7) if s not in two):
            prod *= b[s]
        total += prod
    return total


def derive_buckets() -> dict:
    """Derive in-frame bucket counts from the committed disc pool and verify the estimator."""
    discs = json.loads(DISCS_FILE.read_text())
    counts: dict[tuple[int, int], int] = collections.Counter(
        (d["set_id"], d["slot"]) for d in discs if d["set_id"] in FRAME
    )
    names = {d["set_id"]: d.get("set_name", "") for d in discs if d["set_id"] in FRAME}
    rows = [
        {"set_id": sid, "set_name": names.get(sid, ""), "slot": slot, "count": counts.get((sid, slot), 0)}
        for sid in FRAME
        for slot in range(1, 7)
    ]
    out = {
        "source_job": SOURCE_JOB,
        "owner_id": OWNER_ID,
        "frame": {str(k): v for k, v in FRAME.items()},
        "n_candidates": len(discs),
        "exhaustive_combos": frame_combo_count(counts),
        "buckets": rows,
    }
    BUCKETS_FILE.write_text(json.dumps(out, indent=2) + "\n")
    print(f"{len(discs)} candidates; exhaustive(frame) = {out['exhaustive_combos']:,}")
    for k in (7, 8, 12):
        print(f"  uniform K={k}: {frame_combo_count(counts, k):,}")
    return out


def _build_payload() -> dict:
    """Construct the synthetic Twst1 payload from locally-verified DB values.

    Source verification (local DB, 2026-06-30):
      Agent: Ye Shunguang — physical / attack, base_atk=135, atk_growth=82578,
             base_crit_rate=500, base_crit_dmg=5000,
             base_anomaly_proficiency=94, base_anomaly_mastery=93,
             base_energy_regen=120.
      Enemy: Ye Shiyuan the Thrall — level=60, defense=60,
             physical_res=-2000, stun_dmg_taken_ratio=10000.
      Wengine: Cloudcleave Radiance — specialty=attack, base_atk=50.

    Level-60 scaling (snapshot_builder formulas):
      agent_base_atk  = base + growth*(59)//10000 + promo5_fallback
                      = 135 + (82578*59)//10000 + int(135*1.79)
                      = 135 + 487 + 241 = 863.
      wengine_base_atk = int(50 * (1 + 94090/10000 + 0.8922*5))
                       = int(50 * 14.870) = 743.
      stun_dmg_mult   = 10000 + 10000 = 20000.

    Combo (Twst1 — simplified Ye Shunguang rotation at skill level 12):
      DB multipliers at skill level L: mult = damage_base + damage_growth*(L-1).
      Chosen attacks (skill_key, hit_index → id):
        Basic Swiftedge H0: 7940 + 730*11  = 15970 bp
        Basic Swiftedge H1: 24410 + 2220*11 = 48830 bp
        Basic Swiftedge H2: 12460 + 1140*11 = 25000 bp
        Basic Swiftedge H3: 36800 + 3350*11 = 73650 bp
        EX Return to Dust:  116110 + 10560*11 = 232270 bp
        Chain Lure Thunder: 90860 + 8260*11  = 181720 bp
    """
    base_build = {
        "agent_base_atk": 863,
        "wengine_base_atk": 743,
        "agent_element": "physical",
        "agent_specialty": "attack",
        "agent_name": "Ye Shunguang",
        "agent_level": 60,
        "agent_crit_rate": 500,
        "agent_crit_dmg": 5000,
        "agent_anomaly_proficiency": 94,
        "agent_anomaly_mastery": 93,
        "agent_base_energy_regen": 120,
        "agent_pen_ratio": 0,
        "agent_pen_flat": 0,
    }
    enemy = {
        "level": 60,
        "base_def": 60,
        "element_res": -2000,
        "stun_dmg_mult": 20000,
        "res_map": {
            "physical": -2000,
            "fire": 0,
            "ice": 0,
            "electric": 0,
            "ether": 0,
        },
    }
    combo_steps = [
        {
            "step_type": "ComboStep",
            "label": "Swiftedge-H0",
            "attack_id": "019f104b-e794-78f3-aad0-f50f98c0c618",
            "attack_name": "Basic Attack: Swiftedge",
            "scope": "basic",
            "multiplier": 15970,
            "element": "physical",
        },
        {
            "step_type": "ComboStep",
            "label": "Swiftedge-H1",
            "attack_id": "019f104b-e794-78f3-aad0-f5159c32b1c2",
            "attack_name": "Basic Attack: Swiftedge",
            "scope": "basic",
            "multiplier": 48830,
            "element": "physical",
        },
        {
            "step_type": "ComboStep",
            "label": "Swiftedge-H2",
            "attack_id": "019f104b-e794-78f3-aad0-f5231ddf09c6",
            "attack_name": "Basic Attack: Swiftedge",
            "scope": "basic",
            "multiplier": 25000,
            "element": "physical",
        },
        {
            "step_type": "ComboStep",
            "label": "Swiftedge-H3",
            "attack_id": "019f104b-e794-78f3-aad0-f53ec26e9cd1",
            "attack_name": "Basic Attack: Swiftedge",
            "scope": "basic",
            "multiplier": 73650,
            "element": "physical",
        },
        {
            "step_type": "ComboStep",
            "label": "EX",
            "attack_id": "019f104b-e794-78f3-aad0-f65caea897ae",
            "attack_name": "EX Special Attack: Enlightened Mind - Return to Dust",
            "scope": "ex_special",
            "multiplier": 232270,
            "element": "physical",
        },
        {
            "step_type": "ComboStep",
            "label": "Chain",
            "attack_id": "019f104b-e794-78f3-aad0-f680baf6335d",
            "attack_name": "Chain Attack: Enlightened Mind - Lure Thunder",
            "scope": "chain",
            "multiplier": 181720,
            "element": "physical",
        },
    ]
    return {
        "provenance": (
            "SYNTHETIC — prod job 019f162b unavailable in local DB. "
            "Agent + enemy stats queried from local DB (2026-06-30). "
            "Wengine: Cloudcleave Radiance S-rank at L60. "
            "Combo: simplified Twst1 Ye Shunguang rotation at skill level 12."
        ),
        "source_job": SOURCE_JOB,
        "agent": "Ye Shunguang",
        "combo_name": "Twst1",
        "wengine": "Cloudcleave Radiance",
        "disc_frame": {str(k): v for k, v in FRAME.items()},
        "disc_set_ids": sorted(FRAME.keys()),
        "base_build": base_build,
        "enemy": enemy,
        "combo_steps": combo_steps,
    }


def capture_payload() -> None:
    """Write owner_twst1_payload.json and owner_subframe_small.json."""
    payload = _build_payload()
    PAYLOAD_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Written: {PAYLOAD_FILE.name}")
    print(f"  agent={payload['agent']}, combo={payload['combo_name']}")
    print(f"  steps={len(payload['combo_steps'])}")

    # Subframe: cap each (set_id, slot) bucket to SUBFRAME_CAP discs
    discs = json.loads(DISCS_FILE.read_text())
    bucket_seen: dict[tuple[int, int], int] = collections.defaultdict(int)
    capped: list[dict] = []
    for d in discs:
        key = (d["set_id"], d["slot"])
        if bucket_seen[key] < SUBFRAME_CAP:
            capped.append(d)
            bucket_seen[key] += 1

    capped_counts: dict[tuple[int, int], int] = collections.Counter(
        (d["set_id"], d["slot"]) for d in capped if d["set_id"] in FRAME
    )
    subframe_combos = frame_combo_count(capped_counts)
    subframe = dict(payload)
    subframe["provenance"] = payload["provenance"] + (
        f" Disc pool capped to ≤{SUBFRAME_CAP} per (set_id, slot) bucket "
        "for tractable exhaustive ground truth (CP5)."
    )
    subframe["discs"] = capped
    subframe["n_discs"] = len(capped)
    subframe["exhaustive_combos"] = subframe_combos

    SUBFRAME_FILE.write_text(json.dumps(subframe, indent=2) + "\n")
    print(f"Written: {SUBFRAME_FILE.name}")
    print(f"  {len(capped)} discs (capped ≤{SUBFRAME_CAP}/bucket); "
          f"exhaustive(frame) = {subframe_combos:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discs", action="store_true", help="derive buckets from the disc pool (default)")
    parser.add_argument("--payload", action="store_true", help="emit payload + subframe fixtures")
    args = parser.parse_args()
    if args.payload:
        capture_payload()
    else:
        derive_buckets()


if __name__ == "__main__":
    main()
