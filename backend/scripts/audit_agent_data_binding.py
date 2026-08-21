#!/usr/bin/env python3
"""Audit move-key and agent-binding integrity across the per-agent data directories.

Walks ``app/data/moves/agents/`` and ``app/data/skill_overrides/`` and reports, per
file, every attack-name key that does not resolve to an attack owned by that file's
agent. This is the affirmative check neither directory has ever had: every existing
guard (``_RESERVED_MOVE_KEYS``, the seeder's warn-and-skip) is a denylist of a known-bad
shape, not a positive assertion that a key resolves. See docs/DESIGN_move_key_resolution.md.

Findings are classified:

  BIND     the file's own agent binding fails to resolve to a real ``agents.name``
           (moves/agents/: ``agent_name``; skill_overrides/: same field). Key-level
           checks are skipped for a BIND file — there is no owning agent to check against.
  FOREIGN  the key resolves, but to a *different* agent's attack (the Grace class:
           per-agent scoping is what catches this; a global match would pass it)
  DEAD     the key resolves to no attack at all, for any agent
  NBSP     the key resolves only after Unicode-whitespace normalisation (NBSP/U+00A0
           appears in a handful of DB attack names)

Usage:
    python -m scripts.audit_agent_data_binding
    python -m scripts.audit_agent_data_binding --json
    python -m scripts.audit_agent_data_binding --buildup

Exits non-zero if any finding is reported. ``--buildup`` adds an informational report
of curated ``buildup`` values that disagree with their move's DB row sum; that is a
curation backlog rather than a resolution defect, so it never affects the exit code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from app.data.loaders.moves import load_agent_moves
from app.data.loaders.skill_overrides import load_skill_overrides
from app.database import async_session_factory
from app.models.agent import Agent, Attack
from app.models.enums import PotentialVariant
from app.repositories.attack import visible_to

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MOVES_DIR = BACKEND_ROOT / "app" / "data" / "moves" / "agents"
SKILL_OVERRIDES_DIR = BACKEND_ROOT / "app" / "data" / "skill_overrides"

# Keys that are not attack names by design — synthetic hooks the simulator matches on
# a fixed string rather than a DB row. Anything not in this set is expected to resolve.
PSEUDO_KEYS: frozenset[str] = frozenset({"stun_onset_abloom"})

_WHITESPACE_RE = re.compile(r"[\s\xa0]+")


def _normalize(s: str) -> str:
    """Collapse all whitespace (including NBSP/U+00A0) to a single plain space."""
    return _WHITESPACE_RE.sub(" ", s).strip()


@dataclass(frozen=True)
class Finding:
    """One unresolved (or NBSP-fragile) key, addressed to a specific file."""

    classification: str  # "BIND" | "FOREIGN" | "DEAD" | "NBSP"
    directory: str  # "moves" | "skill_overrides"
    source_file: str
    agent_name: str | None
    key: str | None
    detail: str


async def load_db_state() -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    """Return agent-name/id maps and attack-name indexes needed to classify a key.

    Returns (agent_name -> agent_id, agent_id -> [raw attack names], normalised
    attack name -> agent_id). The third map is the global (any-agent) NBSP-normalised
    lookup that distinguishes FOREIGN from DEAD.
    """
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        attacks = (await session.execute(select(Attack))).scalars().all()

    name_to_id = {a.name: a.id for a in agents}
    id_to_attack_names: dict[str, list[str]] = {}
    for at in attacks:
        id_to_attack_names.setdefault(at.agent_id, []).append(at.name)

    norm_name_to_agent_id: dict[str, str] = {}
    for at in attacks:
        norm_name_to_agent_id.setdefault(_normalize(at.name), at.agent_id)

    return name_to_id, id_to_attack_names, norm_name_to_agent_id


def classify_key(
    *,
    key: str,
    directory: str,
    source_file: str,
    agent_name: str,
    owned_names: list[str],
    norm_name_to_agent_id: dict[str, str],
    id_to_name: dict[str, str],
) -> Finding | None:
    """Classify one move key against pre-fetched DB state; ``None`` if it resolves clean.

    Public so validate_kits L4 (docs/TASKS_move_key_resolution.md Task 3) can reuse the
    exact same classification the audit script uses, rather than re-deriving it.
    """
    if key in PSEUDO_KEYS:
        return None

    if key in owned_names:
        return None  # exact match, owned — clean.

    norm_key = _normalize(key)
    owned_norm = {_normalize(n) for n in owned_names}
    if norm_key in owned_norm:
        return Finding(
            classification="NBSP",
            directory=directory,
            source_file=source_file,
            agent_name=agent_name,
            key=key,
            detail="resolves to an owned attack only after Unicode-whitespace normalisation",
        )

    owning_agent_id = norm_name_to_agent_id.get(norm_key)
    if owning_agent_id is not None:
        owner = id_to_name.get(owning_agent_id, owning_agent_id)
        return Finding(
            classification="FOREIGN",
            directory=directory,
            source_file=source_file,
            agent_name=agent_name,
            key=key,
            detail=f"resolves to an attack owned by a different agent: {owner}",
        )

    return Finding(
        classification="DEAD",
        directory=directory,
        source_file=source_file,
        agent_name=agent_name,
        key=key,
        detail="resolves to no attack for any agent",
    )


def audit_moves(
    name_to_id: dict[str, str],
    id_to_attack_names: dict[str, list[str]],
    norm_name_to_agent_id: dict[str, str],
    id_to_name: dict[str, str],
) -> list[Finding]:
    """Audit every file in ``app/data/moves/agents/`` against pre-fetched DB state."""
    findings: list[Finding] = []
    specs = load_agent_moves(MOVES_DIR)
    for stem, spec in specs.items():
        source_file = f"{stem}.json"
        agent_name = spec.agent_name
        if agent_name is None or agent_name not in name_to_id:
            findings.append(
                Finding(
                    classification="BIND",
                    directory="moves",
                    source_file=source_file,
                    agent_name=agent_name,
                    key=None,
                    detail=f"agent_name {agent_name!r} does not resolve to a real agents.name",
                )
            )
            continue

        agent_id = name_to_id[agent_name]
        owned_names = id_to_attack_names.get(agent_id, [])
        for key in spec.moves:
            finding = classify_key(
                key=key,
                directory="moves",
                source_file=source_file,
                agent_name=agent_name,
                owned_names=owned_names,
                norm_name_to_agent_id=norm_name_to_agent_id,
                id_to_name=id_to_name,
            )
            if finding is not None:
                findings.append(finding)
    return findings


def audit_skill_overrides(
    name_to_id: dict[str, str],
    id_to_attack_names: dict[str, list[str]],
    norm_name_to_agent_id: dict[str, str],
    id_to_name: dict[str, str],
) -> list[Finding]:
    """Audit every file in ``app/data/skill_overrides/`` against pre-fetched DB state."""
    findings: list[Finding] = []
    overrides = load_skill_overrides(SKILL_OVERRIDES_DIR)
    for stem, override in overrides.items():
        source_file = f"{stem}.json"
        agent_name = override.agent_name
        if agent_name not in name_to_id:
            findings.append(
                Finding(
                    classification="BIND",
                    directory="skill_overrides",
                    source_file=source_file,
                    agent_name=agent_name,
                    key=None,
                    detail=f"agent_name {agent_name!r} does not resolve to a real agents.name",
                )
            )
            continue

        agent_id = name_to_id[agent_name]
        owned_names = id_to_attack_names.get(agent_id, [])
        for key in override.moves:
            finding = classify_key(
                key=key,
                directory="skill_overrides",
                source_file=source_file,
                agent_name=agent_name,
                owned_names=owned_names,
                norm_name_to_agent_id=norm_name_to_agent_id,
                id_to_name=id_to_name,
            )
            if finding is not None:
                findings.append(finding)
    return findings


class DatabaseNotSeededError(RuntimeError):
    """Raised by :func:`run_audit` when the DB is unreachable or has no agents."""


# Curated buildups that are RIGHT to disagree with their move's DB row sum, because the
# row set is not the move: the game never plays every row. Each entry needs the same
# receipt the move's own `notes` carries — a primary source and the arithmetic — and is
# retired by fixing the row set, never by editing the curated number to match it.
#
# Keyed (agent_name, attack name) so it survives a file rename. Deliberately NOT a
# waiver file: there are one or two of these, the reason belongs next to the data, and
# `known_issues.json` is scoped to validate_kits' kit-modifier findings.
#
# Jane's "Basic Attack: Salchow Jump" entry (nanoka summed both the base-kit and
# Potential-upgrade variant of the same hit into 3 DB rows instead of 2) was retired by
# issue #85: NanokaImporter now drops `potential: [0]` entries, so the DB row sum
# (51232) agrees with the curated buildup directly. See jane.json's `notes` field.
DOCUMENTED_DEVIATIONS: dict[tuple[str, str], str] = {
    ("Trigger", "Basic Attack: Silenced Shot"): (
        "2 DB rows after the D-CH6 split (Shot 2,700 + Finishing Move 11,926 = 14,626), against a "
        "curated 22,726. The gap is the point of the move: it is a `per_tick` channel "
        "(D-CH1a), so "
        "a full 4-shot hold lands the Shot row FOUR times -- 4 x 2,700 + 11,926 = 22,726. The DB "
        "sum is one shot, not a hold, so it is not the reachable figure for any press. "
        "`Counter` is absent from both numbers because it is a separate selectable move now "
        "(D-CH6): it fires on an automatic Perfect Dodge, i.e. on the enemy attacking, and fairy "
        "models no enemy attacks. Like the Norma and Piper entries below and unlike Alice and "
        "Hugo, this is NOT waiting on issue #89 -- the mechanism expresses the move exactly. "
        "CAVEAT worth carrying: the 4 in that arithmetic is tick_s = 1.0s from an owner "
        "observation stated as approximate, so this figure inherits that uncertainty "
        "proportionally. Task 19c of docs/TASKS_channeled_moves.md."
    ),
    ("Norma", "EX Special Attack: En-Nah Barrage"): (
        "6 DB rows, FOUR of which fire per press. The two warhead rows are mutually "
        "exclusive and selected by ENEMY STUN STATE, not by the player -- "
        "Norma_Skill_ExSpecial_01_Desc: 'launch different types of missiles based on the "
        "target's state: when the primary target is not Stunned, launches an Armor-Piercing "
        "Warhead ... when the primary target is Stunned, launches a High-Explosive Warhead'. "
        "So the DB sum 94893 is unreachable: it adds both warhead pairs. Curated 82528 is the "
        "reachable total for the modelled form -- Armor-Piercing at a full 2s hold: 14435 "
        "(Shot) + 21653 (AP Warhead) + 2.0 x 9288 (Extended Shot Per Sec) + 2.0 x 13932 "
        "(Extended Shot AP Per Sec). Authored as a `channel` (per_second basis, max_s = 2.0 "
        "cited from her own skill text) with the warhead axis expressed as per-row "
        "`select_when` gates under owner ruling D-CH5. Like the Piper entry below and unlike "
        "Alice and Hugo, this deviation is NOT waiting on issue #89: the mechanism expresses "
        "the move exactly, so the deviation is permanent by construction. Task 17d of "
        "docs/TASKS_channeled_moves.md; design in DESIGN_channeled_moves.md section 12."
    ),
    ("Piper", "Special Attack: One Trillion Tons"): (
        "3 DB rows, ONE damage instance. The rows are mutually-exclusive charge levels — "
        "nanoka labels them 'Level-1 / Level-2 / Level-3 Charged Attack DMG Multiplier' "
        "(skills 1281006/7/8), and the skill text (under Piper's TextMap CODENAME 'Clara', "
        "Clara_Skill_Special_01_Desc) reads 'Hold to extend the skill duration ... increasing "
        "the charge level of the skill up to 2 times'. One press lands exactly one level, so "
        "the DB sum 43169 is unreachable; the three reachable totals are 9333, 10336 and "
        "23500. Curated 23500 is Level-3, the full-charge case, matching this corpus's "
        "convention of authoring the modelled form — while the resolver's own no-label "
        "default is Level-1, so an unlabelled step still resolves at the conservative end. "
        "Re-classified atomic -> variant on 2026-08-19, which is what makes the deviation "
        "correct rather than merely tolerated: as `atomic` the engine fired all three levels "
        "on every press, a 1.84x over-count against Level-3. Unlike the Alice and Hugo "
        "entries below this one is NOT waiting on issue #89 — `variant` already expresses it "
        "exactly, and the deviation is permanent by construction. Task 1 of "
        "docs/TASKS_channeled_moves.md; surfaced by the Task 2 sweep, receipt in "
        "docs/LOG_channeled_moves.md."
    ),
    ("Alice", "Basic Attack: Celestial Overture"): (
        "6 DB rows, 5 presses. nanoka 3.1 skill_list['1401001'].desc spells out five "
        "<Icon_Normal> input tokens and the skill text says 'Perform up to 5 slashes'; the "
        "sixth row is labelled '5th-Hit (Enhanced) DMG Multiplier' (skill 1401006) — a "
        "qualifier on the SAME ordinal, not a sixth press. Press 5 plays row 4 OR row 5, "
        "never both, so no cycle sums all six rows and the DB sum 45735 double-counts it. "
        "Curated 30135 is the base five-press cycle (2976+5213+4445+7781+9720); the "
        "enhanced cycle is 36015 (rows 0-3 + row 5) and MoveBuildupSpec, keyed by move "
        "name, cannot hold both. Retired by issue #89 giving the schema a way to express "
        "a variant row inside a press chain — then author both cycles and delete this. "
        "Task 9 of docs/TASKS_sequential_variant.md; receipt in "
        "docs/LOG_sequential_variant.md."
    ),
    ("Hugo", "Basic Attack: Dark Abyss Concerto"): (
        "3 DB rows, 2 damage instances, ONE input — the skill_list entry named for this "
        "move reads '<Icon_Normal> (Hold after the 4th hit of Dark Abyss Quartet)'. One "
        "activation lands Slash plus exactly one of Shot / Charged Shot, because Charged "
        "Shot replaces Shot rather than following it (the Chain Attack text calls the shot "
        "it activates 'a charged shot'; nanoka labels the equivalent rows on this agent's "
        "Dodge Counter and Quick Assist 'ALT Shot' / 'ALT Charged Shot'; the two forms sit "
        "at a uniform 1.967x ratio). So the DB sum 28003 is unreachable — the reachable "
        "totals are 16079 un-charged and 21947 charged. Curated 16079 is the un-charged "
        "activation (10023 + 6056), matching the call already made on Dodge Counter, Quick "
        "Assist and Dark Abyss Quartet; the charged form cannot be held alongside it. "
        "Re-classified sequential -> atomic in the same change (its skill_overrides entry "
        "was deleted), which makes the gauge exact and the damage multiplier a +74.1% "
        "over-count (40070 emitted vs 23010 true) — the same residual Dodge Counter and "
        "Elegy already carry. Retired by issue #89 letting one activation hold two "
        "alternative rows. Task 11a of docs/TASKS_sequential_variant.md; PLANNER "
        "RESOLUTION and receipt in docs/LOG_sequential_variant.md."
    ),
    ("Hugo", "Basic Attack: Dark Abyss Quartet"): (
        "6 DB rows, 4 presses. The skill text says 'Perform up to FOUR attacks forward' and "
        "'the fourth attack is a shot… hold to charge and perform a charged shot'; nanoka "
        "splits the move into '(1st, 2nd, and 3rd hit)' Physical and '(4th hit)' Ice "
        "skill_list entries, and the DB rows' zero/non-zero gauge boundary falls exactly "
        "there. So press 4 emits Slash plus ONE of Shot / Charged Shot — Charged Shot "
        "replaces Shot rather than following it (the Chain Attack text calls the shot it "
        "activates 'a charged shot'; the two forms sit at a uniform 1.967x ratio). No cycle "
        "sums both, so the DB sum 20968 is unreachable. Curated 13198 is the un-charged "
        "cycle (9581 + 3617); the charged cycle is 17351 and cannot be held alongside it. "
        "Retired by issue #89 letting a press hold two alternative rows. Task 12 of "
        "docs/TASKS_sequential_variant.md."
    ),
    ("Hugo", "Dodge Counter: Phantasm - Slash"): (
        "3 DB rows, 2 damage instances. nanoka labels rows 1 and 2 'ALT Shot' and 'ALT "
        "Charged Shot' — mutually exclusive forms of the same shot (the Chain Attack text "
        "says the shot this skill activates 'is considered a charged shot', and the two "
        "forms sit at a uniform ratio). One activation lands the base hit plus exactly one "
        "shot form, so the DB sum 35663 is unreachable — +71.2% over the un-charged total. "
        "Curated 20833 is that activation (9500 + 11333); the charged form is 24330 and "
        "cannot be held alongside it. Retired by issue #89 letting a move hold two "
        "alternative rows. Fixed on fix/sequential-variant-cycle; receipt in "
        "docs/LOG_sequential_variant.md."
    ),
    ("Hugo", "Quick Assist: Elegy"): (
        "Identical shape to this agent's Dodge Counter: Phantasm - Slash — rows 1 and 2 are "
        "nanoka's 'ALT Shot' and 'ALT Charged Shot', so the DB sum 17831 is unreachable by "
        "any activation (+71.2%). Curated 10416 is the un-charged activation (4750 + 5666); "
        "the charged form is 12165. Retired by issue #89. Fixed on "
        "fix/sequential-variant-cycle; receipt in docs/LOG_sequential_variant.md."
    ),
    ("Caesar", "Basic Attack: Rampaging Slash"): (
        "7 DB rows, 6 presses. The skill text says 'Unleashes up to 6 slashes ahead' and "
        "skill 1071008 is labelled '3rd-Hit (ALT)' — an alternative third press, not a "
        "seventh. Unlike Lucy's ALT row it carries real gauge (7432), so the DB sum 71302 "
        "counts both third-hit forms and no six-press cycle reaches it. Curated 63870 is "
        "that cycle (2142 + 3409 + 11104 + 6812 + 13879 + 26524). Retired by issue #89 "
        "resolving which third hit plays. Task 14 of docs/TASKS_sequential_variant.md."
    ),
}


@dataclass(frozen=True)
class BuildupDrift:
    """One curated `buildup` that disagrees with the sum of its move's DB rows."""

    source_file: str
    agent_name: str
    key: str
    spec_buildup: int
    db_sum: int
    db_rows: int
    hit_mode: str

    @property
    def ratio(self) -> float:
        """Curated value as a multiple of the DB sum (`inf` when the DB sum is 0)."""
        return self.spec_buildup / self.db_sum if self.db_sum else float("inf")

    @property
    def documented_reason(self) -> str | None:
        """The :data:`DOCUMENTED_DEVIATIONS` rationale, or ``None`` if unexplained."""
        return DOCUMENTED_DEVIATIONS.get((self.agent_name, self.key))


async def load_buildup_state() -> tuple[
    dict[str, str], dict[tuple[str, str], tuple[int, int, str]]
]:
    """Return (agent_name -> id, (agent_id, attack_name) -> (buildup sum, row count, mode)).

    Rows are the UNLOCKED Potential kit (#90). Since #90 `attacks` holds both states, so
    an unfiltered sum double-counts the moves whose base row has a Potential replacement
    rather than being absent -- Jane's Salchow Jump reads 78572 (= the authored 51232
    plus the superseded base row's 27340). Every curated `buildup` in this corpus was
    authored against the Potential-unlocked kit, which was the only kit fairy stored
    between #85 and #90, so that is the variant they must be compared against.
    """
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        attacks = (
            await session.execute(
                select(Attack).where(visible_to(PotentialVariant.UNLOCKED))
            )
        ).scalars().all()

    name_to_id = {a.name: a.id for a in agents}
    agg: dict[tuple[str, str], tuple[int, int, str]] = {}
    for at in attacks:
        key = (at.agent_id, at.name)
        total, count, _ = agg.get(key, (0, 0, str(at.hit_mode)))
        agg[key] = (total + (at.anomaly_buildup or 0), count + 1, str(at.hit_mode))
    return name_to_id, agg


async def audit_buildup_drift() -> list[BuildupDrift]:
    """Report curated `buildup` values that disagree with their move's DB row sum.

    Deliberately NOT part of :func:`run_audit`, and so not wired into validate_kits L4
    or the merge gate. L4 answers a *resolution* question ("does this key name a real,
    correctly-owned attack?"), which is machine-decidable. Whether a curated number is
    *right* is a different class that `docs/DECISIONS.md` (search "Move-key resolution")
    explicitly defers: the DB sum is the convention for most moves but not an oracle —
    Yuzuha's Hard Candy Shot is authored at 12 000 against a DB sum of 0, which no
    automatic rule resolves. Overwriting these to silence the report would be exactly
    the "edit a number until the check goes quiet" move `known_issues.json` forbids.

    This exists so the drift is *visible and enumerable* for a future re-curation pass
    instead of being discoverable only by accident, which is how the stale Burnice
    value in Task 8 was found.

    Entries whose `buildup` is omitted (None) are skipped: since the omitted-buildup
    fix those fall back to the DB rows at sim time, so they cannot drift.
    """
    try:
        name_to_id, agg = await load_buildup_state()
    except Exception as exc:  # mirrors run_audit: any DB failure is "not seeded"
        raise DatabaseNotSeededError(f"DB not reachable: {exc}") from exc
    if not name_to_id:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    drifts: list[BuildupDrift] = []
    for stem, spec in sorted(load_agent_moves(MOVES_DIR).items()):
        agent_id = name_to_id.get(spec.agent_name or "")
        if agent_id is None:
            continue
        for key, move in spec.moves.items():
            if move.buildup is None:
                continue
            entry = agg.get((agent_id, key))
            if entry is None or move.buildup == entry[0]:
                continue
            db_sum, db_rows, hit_mode = entry
            drifts.append(
                BuildupDrift(
                    source_file=f"{stem}.json",
                    agent_name=spec.agent_name or "",
                    key=key,
                    spec_buildup=move.buildup,
                    db_sum=db_sum,
                    db_rows=db_rows,
                    hit_mode=hit_mode,
                )
            )
    return drifts


async def run_audit() -> list[Finding]:
    """Load DB state once, then audit both moves/agents/ and skill_overrides/ against it.

    Raises :class:`DatabaseNotSeededError` if the DB is unreachable or empty — callers
    that need to skip cleanly (e.g. validate_kits L4, matching the other integration
    tests that require a seeded DB) should catch it.
    """
    try:
        name_to_id, id_to_attack_names, norm_name_to_agent_id = await load_db_state()
    except Exception as exc:
        raise DatabaseNotSeededError(f"DB not reachable: {exc}") from exc
    if not name_to_id:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    id_to_name = {v: k for k, v in name_to_id.items()}
    findings: list[Finding] = []
    findings.extend(audit_moves(name_to_id, id_to_attack_names, norm_name_to_agent_id, id_to_name))
    findings.extend(
        audit_skill_overrides(name_to_id, id_to_attack_names, norm_name_to_agent_id, id_to_name)
    )
    return findings


def _print_report(findings: list[Finding]) -> None:
    if not findings:
        print("No findings — every key in moves/agents/ and skill_overrides/ resolves.")
        return

    by_class: dict[str, list[Finding]] = {}
    for f in findings:
        by_class.setdefault(f.classification, []).append(f)

    print(f"{len(findings)} finding(s):\n")
    for classification in ("BIND", "FOREIGN", "DEAD", "NBSP"):
        group = by_class.get(classification, [])
        if not group:
            continue
        print(f"## {classification} ({len(group)})")
        for f in group:
            where = f"{f.directory}/{f.source_file}"
            if f.key is not None:
                print(f"  [{where}] {f.agent_name!r} key {f.key!r} — {f.detail}")
            else:
                print(f"  [{where}] {f.detail}")
        print()


def _print_drift_rows(drifts: list[BuildupDrift]) -> None:
    print(f"  {'agent':16}{'move':46}{'curated':>10}{'db_sum':>10}{'x':>7}  rows mode")
    for d in sorted(drifts, key=lambda d: (d.agent_name, d.key)):
        ratio = "inf" if d.db_sum == 0 else f"{d.ratio:.2f}"
        print(
            f"  {d.agent_name:16}{d.key[:44]:46}{d.spec_buildup:>10}"
            f"{d.db_sum:>10}{ratio:>7}  {d.db_rows:<4} {d.hit_mode}"
        )


def _print_drift_report(drifts: list[BuildupDrift]) -> None:
    if not drifts:
        print("No buildup drift — every curated buildup matches its move's DB row sum.")
        return

    undocumented = [d for d in drifts if d.documented_reason is None]
    documented = [d for d in drifts if d.documented_reason is not None]

    if undocumented:
        print(f"{len(undocumented)} UNDOCUMENTED curated buildup value(s) disagree with")
        print("their DB row sum. INFORMATIONAL — this does not gate (see")
        print("audit_buildup_drift's docstring).\n")
        _print_drift_rows(undocumented)
    else:
        print("No undocumented buildup drift — every curated buildup either matches its")
        print("move's DB row sum or is a listed DOCUMENTED_DEVIATIONS entry.")

    if documented:
        print(f"\n{len(documented)} documented deviation(s) — expected, do NOT 'fix' these:\n")
        _print_drift_rows(documented)
        for d in sorted(documented, key=lambda d: (d.agent_name, d.key)):
            print(f"\n  {d.agent_name} — {d.key}:\n    {d.documented_reason}")


def main() -> None:
    """CLI entry point: run the audit, print or JSON-dump findings, exit non-zero on any."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--buildup",
        action="store_true",
        help=(
            "additionally report curated buildup values that disagree with their move's "
            "DB row sum (informational; does not affect the exit code)"
        ),
    )
    args = parser.parse_args()

    async def _collect() -> tuple[list[Finding], list[BuildupDrift]]:
        # One event loop for both passes: the module-level engine's connection pool
        # binds to the loop that first uses it, so a second asyncio.run() would find
        # its pooled connections attached to a dead loop.
        return (await run_audit(), await audit_buildup_drift() if args.buildup else [])

    findings, drifts = asyncio.run(_collect())

    if args.json:
        payload: dict[str, list[dict]] = {"findings": [asdict(f) for f in findings]}
        if args.buildup:
            # `documented_reason` is a property, so `asdict` drops it — but it is the
            # one field a consumer cannot re-derive from the payload, and without it
            # the machine output cannot make the documented/undocumented split the
            # printed report makes.
            payload["buildup_drift"] = [
                {**asdict(d), "documented_reason": d.documented_reason} for d in drifts
            ]
        print(json.dumps(payload, indent=2))
    else:
        _print_report(findings)
        if args.buildup:
            print()
            _print_drift_report(drifts)

    # Drift is deliberately excluded from the exit code: it is a curation backlog, not
    # a resolution defect, and gating on it would contradict docs/DECISIONS.md.
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
