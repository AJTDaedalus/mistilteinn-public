"""Sweep every damage-bearing skill row that exists upstream but is never seeded (#180).

nanoka publishes only the moves the in-game skill panel lists, so a move with no panel
entry has no `attacks` row — and every DB-backed check is then structurally unable to see
it. L4 and L5 both answer "does this move key resolve to a DB row?", which is unanswerable
for a move that has no DB row. #165 found five such rows on Remielle and shipped L6, which
watches the multipliers a kit has already **hand-copied**. #180 is the population those
copies were drawn from: 126 damage-bearing rows across 41 agents that nothing watches at
all.

This script is the discovery half. It diffs `AvatarSkillTemplateTb` at the pinned SHA
against the seeded `attacks` table, classifies every unseeded damage-bearing row by its own
signature, and writes `app/data/validation/unseeded_skill_rows.json`. `validate_kits.py`'s
LU then reads that committed artifact and fails on any row with no ledger entry — so a new
unseeded row appearing upstream fails the build instead of arriving invisibly.

The split is the same one #165 established, for the same reason: fetching and DB access are
manual steps with flaky dependencies, so they must not sit inside the gate (a flaky gate
trains reviewers to wave it through — CLAUDE.md). The gate reads a committed artifact; only
regeneration touches the network or Postgres.

**Two hard refusals, both of which write nothing and exit non-zero.** Each exists because
its failure mode is silent:

1. **No DB, or a DB with no seeded attacks.** Without the seeded set every upstream row
   looks unseeded, so a DB-less run would publish a snapshot asserting ~1200 unmodelled
   rows and look exactly like a successful one. This is CLAUDE.md's "a skipped level
   BLOCKS, it is never a pass" applied where its absence does the most damage.
2. **A column map that cannot reproduce its DB anchors.** Inherited verbatim from
   `build_upstream_mv.py`: the column hashes rotate per patch, and a wrong column publishes
   plausible wrong numbers into the gate, which is worse than no gate.

Classification compares an unseeded row against **the seeded rows of its own avatar**, both
sides read from the same upstream table so the comparison stays in one unit space. Never
across avatars: #77's remediation table made exactly that mistake corpus-wide.

Run::

    cd backend && python -m scripts.dimbreath.build_unseeded_rows --dry-run  # report only
    cd backend && python -m scripts.dimbreath.build_unseeded_rows            # write
    cd backend && python -m scripts.dimbreath.build_unseeded_rows --check    # verify
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database import async_session_factory
from app.models.agent import Agent, Attack
from scripts.dimbreath.columns import (
    MATCH_THRESHOLD,
    TableShapeError,
    column_value_match,
    confident_map,
    unique_key_column,
    wrapper_rows,
)
from scripts.dimbreath.fetch import SCHEMA_DIR, fetch_json, pinned_sha

BACKEND_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = BACKEND_ROOT / "app" / "data" / "validation" / "unseeded_skill_rows.json"

TABLE = "FileCfg/AvatarSkillTemplateTb.json"
SKILL_LIST_TABLE = "FileCfg/SkillListConfigTemplateTb.json"
ABILITY_TABLE = "FileCfg/AbilityConfigTemplateTb.json"
_ANCHOR_PATH = SCHEMA_DIR / "_db_attack_anchors.json"

# Skill ids are 7-digit `<avatar><nnn>`; the bound is what separates them from the other
# id spaces sharing these tables (buff ids, ability ids, item ids).
_SKILL_ID_MIN, _SKILL_ID_MAX = 1_000_000, 2_000_000

# How many seeded skill ids a column must carry before it counts as a *reference* to
# skills rather than a coincidence of range. Low enough that one referencing column is
# recognised, high enough that an unrelated id space overlapping by a few values is not.
_ABILITY_MIN_OVERLAP = 20

# The six columns re-derived from DB anchors on every run. `damage_*` decides whether a row
# is damage-bearing at all; the other four are the side signature classification reads.
VALUE_FIELDS = [
    "damage_base",
    "damage_growth",
    "stun_base",
    "stun_growth",
    "energy_gain",
    "anomaly_buildup",
]

# Daze, energy and anomaly buildup — what a row does *besides* damage. A row that deals
# damage and touches none of them is not shaped like a button the player presses; that is
# the Remielle 1581001 / 1581025 signature (docs/RESEARCH_unseeded_skill_rows.md §3).
SIDE_FIELDS = ("stun_base", "stun_growth", "energy_gain", "anomaly_buildup")

BUCKETS = (
    "inert",
    "exact_dup_of_seeded",
    "variant_of_seeded",
    "novel_signature",
)


class EmptyRosterError(RuntimeError):
    """The DB answered but holds no seeded attacks — refusal 1 (see module docstring)."""


class ColumnMapError(RuntimeError):
    """A value column failed to reproduce its DB anchor — refusal 2."""


# ── DB side ────────────────────────────────────────────────────────────────
async def _load_db_state() -> tuple[dict[int, str], set[int]]:
    """`({avatar_id: name}, {seeded skill id})` — the two things the sweep needs from Postgres."""
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        attacks = (await session.execute(select(Attack))).scalars().all()
    roster = {a.hakushin_id: a.name for a in agents if a.hakushin_id}
    seeded = {a.hakushin_skill_id for a in attacks if a.hakushin_skill_id}
    return roster, seeded


def load_db_state() -> tuple[dict[int, str], set[int]]:
    """Refusal 1. Any DB failure — unreachable, unseeded, empty — is fatal, never a warning.

    An empty seeded set is the dangerous case rather than the obvious one: it does not
    raise anywhere downstream, it just makes every upstream row look unmodelled.
    """
    try:
        roster, seeded = asyncio.run(_load_db_state())
    except Exception as exc:
        raise EmptyRosterError(
            f"DB not reachable ({type(exc).__name__}: {exc}). This sweep decides which "
            "rows are unseeded by diffing against the seeded `attacks` table; without "
            "it every upstream row "
            "looks unseeded and the snapshot would be confidently wrong. Start and seed "
            "the DB:\n"
            "    docker compose up -d db\n"
            "    cd backend && python -m scripts.seed_db --skip-icons"
        ) from exc
    if not seeded or not roster:
        raise EmptyRosterError(
            f"DB reachable but holds {len(roster)} agent(s) and {len(seeded)} seeded "
            "attack row(s) — refusing to sweep against an unseeded DB, which would "
            "classify every upstream row as unseeded. Re-seed:\n"
            "    cd backend && python -m scripts.seed_db --skip-icons"
        )
    return roster, seeded


# ── Upstream side ──────────────────────────────────────────────────────────
def load_anchors() -> dict[int, dict[str, Any]]:
    """DB attack anchors: `{skill_id: {field: trusted value}}`, for column derivation."""
    doc = json.loads(_ANCHOR_PATH.read_text())
    return {a["skill_id"]: a for a in doc["attacks"]}


def derive_columns(
    rows: list[dict[str, Any]], anchors: dict[int, dict[str, Any]]
) -> tuple[str, dict[str, str], dict[str, float]]:
    """Refusal 2. `(key column, {field: column}, {field: anchor ratio})`."""
    key_col = unique_key_column(rows, anchors)
    report = column_value_match(rows, key_col, anchors, VALUE_FIELDS)
    field_to_col = {field: col for col, field in confident_map(report).items()}
    missing = [f for f in VALUE_FIELDS if f not in field_to_col]
    if missing:
        raise ColumnMapError(
            f"could not re-derive {missing} against DB anchors at or above "
            f"{MATCH_THRESHOLD:.0%} — refusing to write a snapshot from an unverified "
            "column map (the hashes rotate per patch; re-capture anchors after a reseed)"
        )
    ratios = {field: round(report[col]["ratio"], 4) for field, col in field_to_col.items()}
    return key_col, field_to_col, ratios


def _values(row: dict[str, Any], cols: dict[str, str]) -> dict[str, int]:
    return {field: row.get(cols[field]) or 0 for field in VALUE_FIELDS}


def _side_signature(values: dict[str, int]) -> tuple[int, ...]:
    return tuple(values[f] for f in SIDE_FIELDS)


def classify(
    values: dict[str, int], seeded_values: list[tuple[int, dict[str, int]]]
) -> tuple[str, int | None]:
    """Bucket one unseeded row against **its own avatar's** seeded rows.

    Returns `(bucket, twin_skill_id | None)`. The order below is precedence, and it is
    fixed deliberately rather than left to whichever `if` happens to be written first:

    1. `inert` wins outright. An all-zero side signature is a statement about the row
       itself. Matching *another* all-zero row says nothing — there is no signature there
       to share (Yuzuha 1411025 is that case, and it must not be filed as a variant of a
       row it merely resembles in having no properties).
    2. `exact_dup_of_seeded` — same side signature **and** the same damage base and growth
       as a seeded row. Evidence of an alternate id for a modelled move, never proof: two
       different moves may share a multiplier, which is why a curator still records the
       disposition and only the owner authorizes it (DESIGN §5).
    3. `variant_of_seeded` — same side signature, different damage.
    4. `novel_signature` — nothing of this avatar's looks like it.
    """
    signature = _side_signature(values)
    if not any(signature):
        return "inert", None

    twins = [(sid, v) for sid, v in seeded_values if _side_signature(v) == signature]
    if not twins:
        return "novel_signature", None

    exact = [
        sid
        for sid, v in twins
        if v["damage_base"] == values["damage_base"]
        and v["damage_growth"] == values["damage_growth"]
    ]
    if exact:
        return "exact_dup_of_seeded", min(exact)
    return "variant_of_seeded", min(sid for sid, _ in twins)


def _skill_list_ids(key_col_hint: dict[int, Any] | None = None) -> set[int]:
    """Ids present in `SkillListConfigTemplateTb`, for a **collision note only**.

    That table numbers UI skill-panel entries `<aid>001…<aid>015`; `AvatarSkillTemplateTb`
    numbers multiplier rows. They collide numerically and mean different things — UI entry
    1581011 is Remielle's Ultimate, multiplier row 1581011 is her EX Special. Reading a
    *name* for a multiplier row out of the skill list produces a confident, wrong answer
    (docs/RESEARCH_unseeded_skill_rows.md §1). So this returns ids and never names, and
    the snapshot records the overlap as a caution flag rather than as evidence.
    """
    rows = wrapper_rows(fetch_json(SKILL_LIST_TABLE))
    if not rows:
        return set()
    ids: set[int] = set()
    try:
        key_col = unique_key_column(rows, key_col_hint or {})
    except TableShapeError:
        # Same call as `ability_reference_ids` guards, and for the same reason: this field
        # is a caution flag, not evidence. A shape change upstream must degrade it, never
        # take down a sweep whose actual output — which rows are unseeded — does not
        # depend on it at all.
        return set()
    for row in rows:
        value = row.get(key_col)
        if isinstance(value, int):
            ids.add(value)
    return ids


def ability_reference_ids(seeded: set[int]) -> tuple[set[int] | None, str]:
    """Skill ids referenced by `AbilityConfigTemplateTb`, or `(None, reason)` if it holds none.

    A row referenced by an ability is a damage instance an ability triggers — exactly the
    hypothesis RESEARCH §3 records for Remielle's 1581001 / 1581025 — so membership would
    be the single most useful discriminator available. It is derived, never assumed: a
    column counts as a reference column only if the ids it carries actually intersect the
    **seeded** skill ids, which are known to be real skill ids. Deriving it this way means
    the signal starts working by itself if a future pin adds such a column.

    At `475dd0195645` no column qualifies: the table is ability ids plus parameter *name*
    strings, and the only skill-shaped ints in it are its own keys. That is a structural
    absence, not a failed heuristic, and it independently corroborates the hand search in
    RESEARCH §3. The honest answer is then `null` for every row — **never** a blob
    substring scan, which is the probe that returned an all-False answer nobody should
    trust (DESIGN §2).
    """
    rows = wrapper_rows(fetch_json(ABILITY_TABLE))
    if not rows:
        return None, f"{ABILITY_TABLE} is empty at this pin"

    try:
        key_col = unique_key_column(rows, {})
    except TableShapeError as exc:
        # An optional discriminator must never take the sweep down with it: the snapshot
        # is still correct without this field, and `null` already means "not derivable".
        return None, f"AbilityConfigTemplateTb key column not derivable ({exc})"

    per_column: dict[str, set[int]] = {}
    for row in rows:
        for col, value in row.items():
            if col == key_col or not isinstance(value, int):
                continue
            if _SKILL_ID_MIN < value < _SKILL_ID_MAX:
                per_column.setdefault(col, set()).add(value)

    referencing = {
        col: ids for col, ids in per_column.items() if len(ids & seeded) >= _ABILITY_MIN_OVERLAP
    }
    if not referencing:
        return None, (
            "no column of AbilityConfigTemplateTb carries skill ids that intersect the "
            f"seeded set (needed {_ABILITY_MIN_OVERLAP}); at this pin the table holds "
            "ability ids and parameter name strings only, so ability membership is not "
            "derivable — recorded as null rather than guessed"
        )
    merged: set[int] = set()
    for ids in referencing.values():
        merged |= ids
    return merged, f"derived from column(s) {', '.join(sorted(referencing))}"


def sweep() -> dict[str, Any]:
    """Assemble the snapshot document. Raises on either refusal; writes nothing itself."""
    roster, seeded = load_db_state()
    rows = wrapper_rows(fetch_json(TABLE))
    anchors = load_anchors()
    key_col, cols, ratios = derive_columns(rows, anchors)

    by_avatar: dict[int, list[tuple[int, dict[str, int]]]] = {}
    candidates: list[tuple[int, int, dict[str, int]]] = []
    for row in rows:
        skill_id = row.get(key_col)
        if not isinstance(skill_id, int):
            continue
        avatar_id = skill_id // 1000
        if avatar_id not in roster:
            # Upstream characters with no DB agent are LR's axis, not this sweep's
            # (DESIGN §7): their whole roster entry is the gap, not one row of it.
            continue
        values = _values(row, cols)
        if skill_id in seeded:
            by_avatar.setdefault(avatar_id, []).append((skill_id, values))
        elif values["damage_base"] > 0:
            candidates.append((skill_id, avatar_id, values))

    skill_list_ids = _skill_list_ids(anchors)
    ability_ids, ability_note = ability_reference_ids(seeded)

    out: dict[str, Any] = {}
    buckets: Counter[str] = Counter()
    for skill_id, avatar_id, values in sorted(candidates):
        bucket, twin = classify(values, by_avatar.get(avatar_id, []))
        buckets[bucket] += 1
        entry: dict[str, Any] = {
            "avatar_id": avatar_id,
            "agent_name": roster[avatar_id],
            "bucket": bucket,
            **values,
            "in_skill_list_id_space": skill_id in skill_list_ids,
            "referenced_by_ability": None if ability_ids is None else skill_id in ability_ids,
        }
        if twin is not None:
            twin_values = next(v for sid, v in by_avatar[avatar_id] if sid == twin)
            entry["twin_skill_id"] = twin
            # LU re-derives the `duplicate_of_modelled` class predicate offline and has no
            # DB to look the twin up in, so the twin's numbers travel with the row.
            entry["twin_values"] = twin_values
        out[str(skill_id)] = entry

    return {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "pinned_sha": pinned_sha(),
            "table": "AvatarSkillTemplateTb",
            "key_column": key_col,
            "columns": cols,
            "anchor_ratios": ratios,
            "anchor_source": "schema/_db_attack_anchors.json (DB Attack rows)",
            "db_agents": len(roster),
            "db_seeded_attacks": len(seeded),
            "agents_affected": len({e["avatar_id"] for e in out.values()}),
            "buckets": dict(sorted(buckets.items())),
            "ability_signal": ability_note,
            "note": (
                "Damage-bearing AvatarSkillTemplateTb rows that exist upstream but have no "
                "seeded `attacks` row (issue #180). Read by validate_kits LU, which fails "
                "on any row with no entry in unseeded_row_ledger.json. Regenerate with "
                "`python -m scripts.dimbreath.build_unseeded_rows`; never hand-edit — the "
                "column hashes rotate per patch and are re-derived from anchors every run. "
                "`in_skill_list_id_space` is a collision caution, NOT a name: the skill "
                "list numbers UI panel entries in the same numeric space (RESEARCH §1)."
            ),
        },
        "rows": out,
    }


def _report(doc: dict[str, Any]) -> str:
    """One-screen summary of a sweep: pin, column map, DB size, counts per bucket."""
    meta = doc["_meta"]
    lines = [
        f"pin {meta['pinned_sha'][:12]} · key column {meta['key_column']}",
        "columns: "
        + ", ".join(
            f"{f}={c} ({meta['anchor_ratios'][f]:.1%})" for f, c in meta["columns"].items()
        ),
        f"DB: {meta['db_agents']} agents, {meta['db_seeded_attacks']} seeded attack rows",
        (
            f"unseeded damage-bearing rows: {len(doc['rows'])} "
            f"across {meta['agents_affected']} agents"
        ),
    ]
    lines += [f"  {bucket}: {n}" for bucket, n in meta["buckets"].items()]
    return "\n".join(lines)


def main() -> int:
    """Sweep, then report / write / check depending on the flags."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="sweep and report; write nothing")
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-sweep and compare against the committed snapshot; write nothing",
    )
    args = parser.parse_args()

    try:
        doc = sweep()
    except (EmptyRosterError, ColumnMapError) as exc:
        print(f"refusing to sweep: {exc}", file=sys.stderr)
        return 1

    print(_report(doc))
    if args.dry_run:
        return 0

    if args.check:
        return _check(doc)

    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_PATH.relative_to(BACKEND_ROOT)}")
    return 0


def _check(doc: dict[str, Any]) -> int:
    """Diff a fresh sweep against the committed snapshot. Drift is a failure, not a note."""
    if not OUT_PATH.is_file():
        print(f"{OUT_PATH.name} does not exist — run without --check", file=sys.stderr)
        return 1
    current = json.loads(OUT_PATH.read_text())
    fresh, committed = doc["rows"], current.get("rows", {})
    appeared = sorted(set(fresh) - set(committed), key=int)
    disappeared = sorted(set(committed) - set(fresh), key=int)
    changed = sorted(
        (sid for sid in set(fresh) & set(committed) if fresh[sid] != committed[sid]), key=int
    )
    pin_drift = current.get("_meta", {}).get("pinned_sha") != doc["_meta"]["pinned_sha"]

    if not (appeared or disappeared or changed or pin_drift):
        print(f"snapshot matches a fresh sweep at {doc['_meta']['pinned_sha'][:12]}")
        return 0
    if pin_drift:
        print("pinned SHA differs from the committed snapshot", file=sys.stderr)
    for label, ids in (("appeared", appeared), ("disappeared", disappeared), ("changed", changed)):
        if ids:
            print(f"{label}: {', '.join(ids)}", file=sys.stderr)
    print(
        "snapshot is out of date — re-run without --check, then re-triage any new row "
        "(LU will fail on it until it is ledgered)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
