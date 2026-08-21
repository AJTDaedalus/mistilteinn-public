"""Validate the curated modifier JSONs. Trust lives here, not in prompts.

An LLM (curator or auditor) may write `confidence: draft` / `audited`. Only this
harness may promote a kit to `verified` — see `docs/DESIGN_kit_validation.md`.

Layers (each is independent; run one or all):

  L0  executability — can the modifier physically reach the damage calc?
      Needs no fixture, no DB, no ZO clone. Catches the silent-no-op class:
      a `scaling_stat` the snapshot builder never dispatches on, a `stat` no
      consumer reads, a modifier that bakes to 0, incoherent scale fields.

  L1  description cross-check — does every number a modifier asserts actually appear
      in that modifier's own in-game description text? Kills the fabrication class
      (a value from nowhere) and off-by-10x slips. Reads only the committed
      `kit_descriptions.json` fixture. Blind to a right number wired to the wrong
      stat — that is shape, and shape is the auditor's job (D-KV6).

  L2  ZO citation check — does the ZO symbol a modifier cites actually exist, for *this*
      agent? A citation naming a symbol ZO does not have is a hard failure, however
      confident the prose around it. Resolves against two per-character namespaces: the
      sheet's registered buff ids and the `dm.*` constants. Cannot verify formula shape
      (D-KV6) — a real symbol with the right number can still be wired to the wrong stat.

  L3  display coverage         — frontend, `stat-meta.spec.ts` (Task 11)

  L4  per-agent move-key resolution — does every attack-name key in every per-agent JSON
      under `app/data/moves/agents/` and `app/data/skill_overrides/` resolve to an attack
      *owned by that agent*? Per-agent scoped, not global — a global match would pass
      Grace's `Basic Attack: Swiftedge`, which is a real attack name, just not hers
      (docs/DESIGN_move_key_resolution.md). Normalises Unicode whitespace (NBSP) on both
      sides. Needs the real seeded app DB — skips cleanly (no findings, a stderr note)
      when it can't connect or the DB has no agents, matching the other integration tests
      that require a seeded DB (`test_zo_crossval.py`, `test_abloom_crossval.py`). Reuses
      `scripts.audit_agent_data_binding`'s classification rather than re-deriving it.

  L6  upstream multiplier cross-check — does every hand-transcribed upstream multiplier
      still equal what upstream says? L4/L5 ask "does this move key resolve to a DB
      row?", which no check can answer for a move that **has no DB row**: nanoka seeds
      only the moves the in-game skill panel lists, so a damage channel built on an
      unlisted skill passes the entire gate untouched (issue #165 — Remielle's Phase
      Flow flight attacks, whose three multipliers are a hand-copy of upstream rows
      1581022-24). Each `upstream_mv_checks` entry in a kit names the path, the upstream
      skill ids, and the skill level it was frozen at; L6 rebuilds
      `base + growth * (level - 1)` from `app/data/validation/upstream_skill_mv.json`
      and diffs. A kit key shaped like a copied tuple (`*_mv_bp`, `*_daze_bp`) with no
      declaration fails too — otherwise the level could only ever check what someone
      remembered to enrol.

      Offline by construction: it reads a committed snapshot, never the network and
      never the DB, so — unlike L4/L5 — it has no way to skip. A missing snapshot is a
      finding. Regenerate the snapshot (network, manual) with
      `python -m scripts.dimbreath.build_upstream_mv`; the fetch is kept out of the gate
      so the gate cannot go flaky, which is the failure mode that trains reviewers to
      wave a red run through.

  LR  roster coverage — does every DB entity (agent, W-Engine, disc set) have a kit
      JSON under `app/data/modifiers/`, or a deliberate, owner-authorized entry in
      `app/data/validation/coverage_ledger.json`? Every other level iterates the files
      that exist, so a wholly missing kit is invisible to all of them by construction —
      the Norma/Pyrois signature-engine gap (DESIGN_kit_accuracy_gate.md D7) sat
      undetected until branch archaeology found it. Needs the real seeded app DB (the
      roster IS the DB) and skips cleanly without one, exactly as L4/L5 do; `--require-db`
      turns that skip into a failure. Gaps are ranked via
      `app/data/validation/signature_map.json`: an uncurated signature engine of an
      already-curated agent outranks a generic gap. `--roster` prints the coverage
      report on its own.

  LU  unseeded upstream damage rows — every damage-bearing `AvatarSkillTemplateTb` row
      with no seeded `attacks` row must carry an owner-authorized entry in
      `app/data/validation/unseeded_row_ledger.json`. L6 watches the upstream
      multipliers a kit has already hand-copied; LU watches the population those copies
      were drawn from (issue #180: 126 rows across 41 agents). nanoka publishes only
      panel-listed moves, so these rows have no DB row at all, and L4/L5 — which both
      ask "does this key resolve to a DB row?" — are structurally unable to see them.
      The load-bearing finding is `unseeded_row_unledgered`: a new row appearing
      upstream fails the build instead of arriving invisibly.

      Offline by construction, exactly as L6 is: it reads
      `app/data/validation/unseeded_skill_rows.json` plus the ledger, never the DB and
      never the network, so it cannot skip. Regenerate the snapshot (DB + network,
      manual) with `python -m scripts.dimbreath.build_unseeded_rows`, which refuses to
      write without a seeded DB — a DB-less sweep sees no seeded ids and would call
      every upstream row unseeded.

      Class entries bundle rows that are the same issue, and LU RE-DERIVES each class's
      membership predicate rather than trusting its id list (D-KV27). A row satisfying a
      predicate but absent from the list still fails: no implicit membership.

Open issues live in `app/data/validation/known_issues.json` (D-KV7). A listed finding does
not fail the build while it is open; a **new** finding does; a waiver that no longer fires
is itself an error, so an entry cannot outlive the defect it describes.

Every waiver carries a `class`. `branch_debt` is a defect this branch retires, and is what
the merge gate counts — `--gate` exits non-zero while any remains. `upstream_blocked` is a
finding that is correct and understood but not retirable here because it waits on a third
party (D-KV22: an agent whose ZO sheet is an unimplemented stub cites no ZO symbol because
none exists). Those are expected to survive the merge, so counting them in the gate would
only pressure someone into inventing a citation — the exact failure this harness exists to
catch. They still go stale, and still fail, the moment their `retire_when` condition is met.

  LC  confidence ladder — does `confidence: "verified"` carry a harness stamp that
      matches the kit's current content? (Task 18). This is the layer that makes the
      trust model real: a curator may write `draft`, an auditor `audited`, but
      `verified` requires `verified_stamp`, and only `--promote` below computes one.

  LD  ledger consistency — the two halves of "what does `confidence` mean?" that live in
      the ledger rather than in a kit. (a) Every kit still at `confidence: "draft"` must
      say *why* in `draft_blockers`, not only inside its own `notes` string: a draft kit
      with no entry fails as `undocumented_draft`, and an entry naming a kit that is no
      longer draft is stale and fails too. (b) A kit carrying an *open waiver* may not sit
      above `draft` (`waived_finding_above_draft`) — D-KV22 says so and nothing enforced
      it, which is the general form of issue #88's complaint that `audited` does not
      guarantee the absence of known defects. Not a merge gate: `draft` is a tracked
      state, not debt the open branch owes. Runs on the ledger, not on a layer, so it
      runs under `--level` too (under-reporting (b), never over-reporting it). Every run
      prints the resulting draft report.

L4 and L5 need the real seeded app DB, and are proven by the **pre-merge agent review**
rather than by CI (issue #114). CI still dispatches every level and lets those two skip —
that is load-bearing, not an oversight, because the stale-waiver check is gated on
`set(levels) == set(LEVELS)` and narrowing the dispatch would switch staleness off for
L0–L2 as well.

Which leaves the reviewer holding a gate whose two most defect-prone levels **skip silently
when their DB is missing**, and a skip is indistinguishable from a pass. `--require-db`
closes that: it turns "could not check" into a hard failure. It is mandatory in the review
gate — `CLAUDE.md`'s gate paragraph is the authority — and is what makes that document's
"a skipped level BLOCKS, it is never a pass" rule enforced by the tool rather than
remembered by the reader. See `docs/DECISIONS.md`, "L4/L5 move to the pre-merge agent".

Usage:
    python -m scripts.validate_kits              # all implemented layers
    python -m scripts.validate_kits --level l0
    python -m scripts.validate_kits --no-waivers # show the full debt, exit 1
    python -m scripts.validate_kits --json       # machine-readable findings
    python -m scripts.validate_kits --gate       # fail while any branch_debt waiver is open
    python -m scripts.validate_kits --gate --require-db
                                                 # the review gate: also fail if L4/L5
                                                 # could not check (needs a seeded DB)
    python -m scripts.validate_kits --promote    # stamp clean `audited` kits `verified`
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import operator
import re
import sys
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database import async_session_factory, engine
from app.services.buff_resolver import (
    _COMBAT_STATS,
    _DMG_BONUS_STATS,
    _STAT_TO_INPUT,
    ELEMENT_SCOPE_HONORED_STATS,
)
from app.services.kit_formulas import UnknownFormulaOpError, validate_kit_formula
from app.services.lumiflux import LumifluxSpec
from app.services.snapshot_builder import _SCALING_BAKERS
from scripts.audit_agent_data_binding import (
    DatabaseNotSeededError,
    run_audit,
)
from scripts.audit_agent_data_binding import (
    # Aliased deliberately: this module defines its own `Finding`, and the audit
    # module's is a different dataclass. Importing it bare would shadow ours.
    Finding as BindingFinding,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MODIFIERS_DIR = BACKEND_ROOT / "app" / "data" / "modifiers"
MOVES_DIR = BACKEND_ROOT / "app" / "data" / "moves" / "agents"
VALIDATION_DIR = BACKEND_ROOT / "app" / "data" / "validation"
KNOWN_ISSUES_PATH = VALIDATION_DIR / "known_issues.json"
KIT_DESCRIPTIONS_PATH = VALIDATION_DIR / "kit_descriptions.json"
COVERAGE_LEDGER_PATH = VALIDATION_DIR / "coverage_ledger.json"
SIGNATURE_MAP_PATH = VALIDATION_DIR / "signature_map.json"
ZO_CONSTANTS_PATH = VALIDATION_DIR / "zo_constants.json"
UPSTREAM_MV_PATH = VALIDATION_DIR / "upstream_skill_mv.json"
UNSEEDED_ROWS_PATH = VALIDATION_DIR / "unseeded_skill_rows.json"
UNSEEDED_LEDGER_PATH = VALIDATION_DIR / "unseeded_row_ledger.json"
DIMBREATH_PROVENANCE_PATH = (
    BACKEND_ROOT / "app" / "data" / "dimbreath" / "schema" / "provenance.json"
)
_UPSTREAM_MV_REL = "validation/upstream_skill_mv.json"
_UNSEEDED_ROWS_REL = "validation/unseeded_skill_rows.json"
_UNSEEDED_LEDGER_REL = "validation/unseeded_row_ledger.json"
STAT_META_TS = BACKEND_ROOT.parent / "frontend" / "src" / "app" / "shared" / "stat-meta.ts"

# Stats any consumer actually reads. Imported from buff_resolver rather than
# restated: a stat outside these three buckets falls through to the `else` branch
# of resolve_modifiers(), which marks it is_modeled=False — the buff is loaded,
# displayed, and then silently ignored by the calc.
RESOLVABLE_STATS: frozenset[str] = frozenset(
    set(_STAT_TO_INPUT) | set(_DMG_BONUS_STATS) | set(_COMBAT_STATS)
)

# Inner-bracket ("Initial Stat") percentage keys, mapped to their outer-bracket
# ("combat") counterparts. The ATK chain is
#     ((agent_base + wengine_base) × (1 + atk_pct) + flat_atk) × (1 + final_atk_pct)
# (`stat_calculator.py:147`), so an agent-kit buff routed through the inner bracket
# multiplies against the bare base instead of the equipment-inclusive total. That is a
# silently *wrong magnitude* rather than a no-op — the modifier does reach the calc,
# which is exactly why nothing else catches it.
#
# Not importable from a pairing table because none exists: `stat_calculator` holds the
# two keys as independent fields, and the inner/outer split is a curation rule. It maps
# onto ZO's buff zones — `initial.*` inner, `combat.*` outer — which ZO's own disc tests
# pin directly: `libs/zzz/formula/src/data/disc/disc.test.ts:189-190` asserts the 2pc
# passive lands in `initial.atk_` and the 4pc in `combat.atk_`, and no character sheet
# under `data/char/sheets/` touches `initial.atk_` at all. `docs/DESIGN_kit_validation.md`
# Finding 1 supplies the semantics underneath that (ZO's `initial.atk` is
# equipment-inclusive but pre-combat-buff, ≡ fairy's `_support_total_atk`); the bracket
# split follows from it rather than being stated there. Also confirmed against an in-game
# screenshot audit in `docs/LOG_ysg3_stat_audit.md`. Restated here deliberately, with that
# provenance.
_INNER_TO_OUTER_BRACKET: dict[str, str] = {
    "atk_pct": "final_atk_pct",
    "hp_pct": "final_hp_pct",
    "def_pct": "final_def_pct",
}


def baked_scaling_stats() -> frozenset[str]:
    """The scaling_stat values snapshot_builder actually dispatches on.

    Read straight off the dispatch table, the same way this module imports
    `_STAT_TO_INPUT` and `ELEMENT_SCOPE_HONORED_STATS` rather than restating them.
    Until Task 13 (C1) landed `_SCALING_BAKERS` there was no table to import, so this
    regex-scraped `snapshot_builder.py` as text — which also matched any
    `mod.scaling_stat == "..."` written inside a comment or docstring, and `sys.exit`ed
    whenever the code shape moved. Importing removes both failure modes: adding a basis
    to the builder now updates L0 with no second edit, and deleting one is a hard
    ImportError instead of a quietly-shorter set.
    """
    return frozenset(_SCALING_BAKERS)


@dataclass(frozen=True)
class Finding:
    """One validation failure, addressed to a specific modifier."""

    level: str  # "L0" | "L1" | "L2"
    code: str  # stable slug — waivers key off this
    source_file: str  # e.g. "agents/ben.json"
    source_name: str  # e.g. "Ben"
    index: int  # modifier index within the file
    label: str  # modifier source_label
    message: str

    @property
    def key(self) -> str:
        """Stable identity for waiver matching."""
        return f"{self.code}|{self.source_file}|{self.index}"


def iter_kits() -> list[tuple[Path, dict[str, Any]]]:
    """Every curated modifier JSON: agents, W-Engines, disc sets."""
    return [(path, json.loads(path.read_text())) for path in sorted(MODIFIERS_DIR.rglob("*.json"))]


def _rel(path: Path) -> str:
    """Path as `agents/ben.json`. Already-relative paths (tests) pass through."""
    try:
        return str(path.relative_to(MODIFIERS_DIR))
    except ValueError:
        return str(path)


def _effective_value(mod: dict[str, Any]) -> int:
    """The value the loader will actually hand the calc.

    W-Engine modifiers carry `value_r1`/`value_r5` instead of `value`; the loader
    interpolates by refinement and passes it as `value_override`
    (`modifier_loader.wengine_value_at_refinement`). Treating a missing `value` as
    inert would false-flag every W-Engine row.
    """
    if "value" in mod:
        return mod.get("value") or 0
    return (mod.get("value_r1") or 0) or (mod.get("value_r5") or 0)


def _check_formulas(path: Path, kit: dict[str, Any], name: str) -> list[Finding]:
    """Rule 5 — every `formulas[]` entry must be executable by the C3 consumer.

    Before Task 21 this rule flagged every entry unconditionally: no loader, service,
    or frontend path read the key, so all 21 custom damage instances were authored,
    ZO-cited, and dropped (D-KV8).

    Now the rule *runs* the consumer. `validate_kit_formula` walks the whole multiplier
    tree and then resolves it through the same code `snapshot_builder` calls, raising on
    any op, read target, scope, quantity, or scaling stat the engine does not implement
    — so an unimplementable formula fails the build here rather than silently
    contributing zero at damage time. Exercising the real code path, rather than
    restating its grammar, is what keeps the harness and the engine from drifting apart.
    """
    findings: list[Finding] = []
    for j, formula in enumerate(kit.get("formulas", [])):
        try:
            validate_kit_formula(formula)
        except (UnknownFormulaOpError, KeyError, TypeError, IndexError) as exc:
            findings.append(
                Finding(
                    level="L0",
                    code="unexecutable_formula",
                    source_file=_rel(path),
                    source_name=name,
                    index=j,
                    label=formula.get("name", ""),
                    message=(
                        f"kit `formulas[]` entry does not evaluate — {type(exc).__name__}: {exc}"
                    ),
                )
            )
    return findings


def _scale_coherence_problems(mod: dict[str, Any]) -> list[tuple[str, str]]:
    """Rule 4 — scale fields must be internally coherent.

    Extracted from `check_l0` because the flat_addend check (C8 / D-KV20) pushed
    the loop body over Ruff's `PLR0912` branch-count limit — the same pressure
    C7's `element_scope` gate hit in `buff_resolver.resolve_modifiers` (see
    `_gated_out`).
    """
    scaling_stat = mod.get("scaling_stat")
    scaling_ratio = mod.get("scaling_ratio", 0) or 0
    atk_ratio = mod.get("atk_scale_ratio", 0) or 0
    flat_addend = mod.get("flat_addend", 0) or 0
    hp_per_unit = mod.get("hp_scale_per_unit", 0) or 0
    hp_unit = mod.get("hp_scale_unit", 0) or 0
    hp_base = mod.get("hp_scale_base", 0) or 0
    value = _effective_value(mod)

    problems: list[tuple[str, str]] = []

    if scaling_stat == "base_atk" and scaling_ratio <= 0:
        problems.append(
            (
                "incoherent_scale",
                (
                    "scaling_stat 'base_atk' requires scaling_ratio > 0 to dispatch "
                    "(snapshot_builder gates on it) — never baked"
                ),
            )
        )
    if scaling_ratio and not scaling_stat:
        problems.append(
            (
                "incoherent_scale",
                f"scaling_ratio {scaling_ratio} is set but scaling_stat is null — never baked",
            )
        )
    if atk_ratio and value <= 0:
        problems.append(
            (
                "incoherent_scale",
                (
                    "atk_scale_ratio is set, so `value` is the cap and must be > 0 "
                    "(min(value, ATK*ratio) would clamp to 0)"
                ),
            )
        )
    if flat_addend and not atk_ratio:
        problems.append(
            (
                "incoherent_scale",
                (
                    "flat_addend is set but atk_scale_ratio is 0 — flat_addend only "
                    "bakes alongside atk_scale_ratio (min(cap, ATK*ratio + flat_addend)); "
                    "on its own it is a second, uncapped way to author a flat buff"
                ),
            )
        )
    if hp_per_unit and not hp_unit:
        problems.append(
            (
                "incoherent_scale",
                "hp_scale_per_unit is set but hp_scale_unit is 0 — scaling adds nothing",
            )
        )
    if hp_unit and not hp_per_unit:
        problems.append(
            (
                "incoherent_scale",
                "hp_scale_unit is set but hp_scale_per_unit is 0 — the HP bake never triggers",
            )
        )
    if hp_per_unit and value <= 0 and hp_base <= 0:
        problems.append(
            (
                "incoherent_scale",
                "hp-scaled modifier has neither a cap (`value`) nor an hp_scale_base",
            )
        )
    return problems


# --------------------------------------------------------------------------
# L0 — the `lumiflux` kit block (Task 27, DESIGN_remielle.md §13.1)
# --------------------------------------------------------------------------

# Keys the block may carry that are not `LumifluxSpec` fields. `notes` is prose
# for humans and is deliberately not loaded.
LUMIFLUX_EXTRA_KEYS: frozenset[str] = frozenset({"notes"})

# The three per-flight-attack tuples are read slot-wise (`flight_attack_points[i]`
# describes the same attack as `flight_attack_mv_bp[i]`), so unequal lengths mean
# `phase_flow_expected_value` averages over a different attack set per quantity.
LUMIFLUX_PARALLEL_TUPLES = ("flight_attack_points", "flight_attack_mv_bp", "flight_attack_daze_bp")


def lumiflux_spec_keys() -> frozenset[str]:
    """Every field `LumifluxSpec` requires, read off the dataclass itself.

    Same reasoning as `baked_scaling_stats()`: importing the real definition
    rather than restating it means adding a coefficient to the spec
    automatically requires it in every Lumiflux kit JSON, and deleting one is
    a hard ImportError rather than a quietly-stale key list. `LumifluxSpec`
    carries no defaults on purpose (a default would be a hardcoded constant for
    whichever agent was authored first), so *every* field is required here.
    """
    return frozenset(f.name for f in fields(LumifluxSpec))


def _is_lumiflux_agent(path: Path) -> bool:
    """Whether this agent kit belongs to a Lumiflux-element agent.

    L0 needs no DB and no fixture, so the element cannot be read from
    `agents.element`. The offline stand-in is the agent's own committed move
    data: `app/data/moves/agents/<slug>.json` shares the kit file's slug, and
    every move row carries an `element`.

    Known limitation, stated rather than hidden: a Lumiflux agent with **no**
    moves file is invisible to this check and will not be required to carry a
    `lumiflux` block. That is the same blind spot every offline layer has, and
    it fails safe — the loader (Task 28) still raises on a partial block, and
    the assembler (Task 29) logs a warning for a Lumiflux agent with no spec.
    """
    moves_path = MOVES_DIR / path.name
    if not moves_path.is_file():
        return False
    try:
        moves = json.loads(moves_path.read_text()).get("moves", {})
    except (OSError, json.JSONDecodeError):
        return False
    return any(move.get("element") == "lumiflux" for move in moves.values())


def _check_lumiflux_block(path: Path, kit: dict[str, Any], name: str) -> list[Finding]:
    """Rule 7 — a Lumiflux agent's kit must carry a complete `lumiflux` block.

    Two failure shapes, both silent without this check and both the exact class
    L0 exists for:

    * a **missing or partial** block — the coefficients then live nowhere a
      loader can reach, which is how the whole subsystem shipped inert
      (escalation E-5, `docs/LOG_remielle.md`);
    * an **unknown key** — Task 20's lesson verbatim: a key the loader's model
      does not know is a number the curator believes is live and the engine
      never reads. The loader parses with ``extra="forbid"`` for the same
      reason; validating in both places is deliberate, not redundant.
    """
    block = kit.get("lumiflux")
    required = lumiflux_spec_keys()

    if block is None:
        if not _is_lumiflux_agent(path):
            return []
        return [
            Finding(
                level="L0",
                code="missing_lumiflux_block",
                source_file=_rel(path),
                source_name=name,
                index=-1,
                label="lumiflux",
                message=(
                    "agent has Lumiflux-element moves but the kit JSON carries no "
                    f"top-level `lumiflux` block — every LumifluxSpec coefficient "
                    f"({', '.join(sorted(required))}) would be unloadable and the "
                    "Refringe/Voidflare/Luminize/Phase Flow subsystem inert for this agent"
                ),
            )
        ]

    problems: list[tuple[str, str]] = []

    if not isinstance(block, dict):
        problems.append(("malformed_lumiflux_block", "`lumiflux` must be a JSON object"))
        block = {}

    present = set(block)
    problems.extend(
        (
            "incomplete_lumiflux_block",
            (
                f"`lumiflux` is missing required key {key!r} — LumifluxSpec has no "
                f"default for it, so the loader raises rather than substituting a zero"
            ),
        )
        for key in sorted(required - present)
    )
    problems.extend(
        (
            "unknown_lumiflux_key",
            (
                f"`lumiflux` carries unknown key {key!r} — no LumifluxSpec field reads it, "
                f"so it is authored, committed, and silently dropped (known keys: "
                f"{', '.join(sorted(required | LUMIFLUX_EXTRA_KEYS))})"
            ),
        )
        for key in sorted(present - required - LUMIFLUX_EXTRA_KEYS)
    )
    problems.extend(
        (
            "incomplete_lumiflux_block",
            (
                f"`lumiflux` key {key!r} is null — a coefficient must be a value, "
                f"not an absence the loader would have to guess at"
            ),
        )
        for key in sorted(required & present)
        if block[key] is None
    )

    lengths = {
        key: len(block[key])
        for key in LUMIFLUX_PARALLEL_TUPLES
        if isinstance(block.get(key), list)
    }
    if len(set(lengths.values())) > 1:
        problems.append(
            (
                "incoherent_lumiflux_block",
                (
                    f"the per-flight-attack tuples must be the same length, got "
                    f"{', '.join(f'{k}={v}' for k, v in sorted(lengths.items()))} — they are "
                    f"read slot-wise, so a mismatch silently averages different attack sets"
                ),
            )
        )

    return [
        Finding(
            level="L0",
            code=code,
            source_file=_rel(path),
            source_name=name,
            index=-1,
            label="lumiflux",
            message=message,
        )
        for code, message in problems
    ]


def _check_duplicate_source_ids(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """Rule 8 — `(source_type, source_id)` must be unique across the whole corpus.

    Two files claiming one id means `modifier_loader`'s answer depends on
    directory glob order — the silent-wrong-data class L0 exists to kill. Found
    live: Velina's fabricated `poem_of_the_empty_feather_return.json` claimed
    14158, which is Remielle's "Ode of Resurrected Wings", so prod served her
    invented buffs for a real equippable item (docs/TASKS_wengine_id_collision.md).

    Deliberately source-type agnostic: L1/L2 gate on `source_type == "agent"`,
    which is exactly why CI never saw that W-Engine collision. Corpus-level, so
    it does not fit the per-modifier loop; `index=-1` marks a file-level finding
    (same convention as `_check_formulas`' per-entry index not applying).
    """
    by_id: dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for path, kit in kits:
        source_id = kit.get("source_id")
        if source_id is None:
            continue
        key = (kit.get("source_type", ""), str(source_id))
        by_id.setdefault(key, []).append((path, kit))

    findings: list[Finding] = []
    for (source_type, source_id), group in by_id.items():
        if len(group) == 1:
            continue
        members = sorted(_rel(path) for path, _ in group)
        for path, kit in group:
            others = ", ".join(m for m in members if m != _rel(path))
            findings.append(
                Finding(
                    level="L0",
                    code="duplicate_source_id",
                    source_file=_rel(path),
                    source_name=kit.get("source_name", path.stem),
                    index=-1,
                    label="",
                    message=(
                        f"({source_type}, {source_id}) is also claimed by {others} — "
                        f"the loader's winner depends on directory order; exactly one "
                        f"file may own an id"
                    ),
                )
            )
    return findings


# Agents with a Potential tree (#90). Read from the seeded-DB snapshot rather than
# hardcoded, so a patch that grants Potential to a new agent widens the rule by
# regenerating `potential_deltas.json` — not by someone remembering to edit a list here.
# Falls back to an empty set if the snapshot is missing, which makes the rule inert
# rather than making it fail an unrelated run.
@lru_cache(maxsize=1)
def _potential_agent_stems() -> frozenset[str]:
    snapshot = BACKEND_ROOT / "app" / "data" / "validation" / "potential_deltas.json"
    try:
        data = json.loads(snapshot.read_text())
    except (OSError, ValueError):
        return frozenset()
    return frozenset(
        name.lower().replace(" - ", "_").replace(" ", "_").replace("-", "_")
        for name in data.get("agents", {})
    )


# Rule 8c's index check is DB-backed, but it lives in L0 — the tier CI runs HERMETICALLY,
# with no database. So it must not fail on a missing DB: that would make a hermetic level
# depend on one, and CI would go red for an absence rather than a defect. It degrades to
# "cannot check" instead, exactly as L4/L5/LR do, and `--require-db` turns that into a
# block so the manually-confirmed gate still proves it. `bound_rows_seen` keeps the skip
# silent on runs where no kit binds a ramp at all.
L0_POTENTIAL_STATUS: dict[str, bool] = {"ramps_available": True, "bound_rows_seen": False}


@lru_cache(maxsize=1)
def _potential_ramp_counts() -> dict[str, int]:
    """{kit stem: number of Potential ramps} from the seeded DB, or {} when unavailable.

    Read live rather than snapshotted, because the ramp COUNT is what an index is checked
    against and a patch can change it. An unreachable or un-re-seeded DB yields {}, which
    An unreachable or un-re-seeded DB yields {}, which makes Rule 8c degrade to "cannot
    check" — reported via L0_POTENTIAL_STATUS and blocked by `--require-db`, NOT emitted
    as a finding. L0 is the hermetic tier CI runs without a database, so a finding here
    would turn an absence into a red build.
    """
    # Deferred, like the other DB-touching levels in this file: validate_kits must import
    # and run its offline levels with no database and no app config present.
    try:
        import asyncio  # noqa: PLC0415

        from sqlalchemy import select  # noqa: PLC0415

        from app.database import async_session_factory, engine  # noqa: PLC0415
        from app.models.agent import Agent  # noqa: PLC0415

        async def _load() -> dict[str, int]:
            # Hand the pool back INSIDE this loop. `asyncio.run` closes the loop when it
            # returns, and any pooled asyncpg connection left bound to it raises
            # "attached to a different loop" the next time the shared engine is used —
            # which is L4, running later in the same process. That is not hypothetical:
            # this helper caused exactly that, and `--require-db` turned the resulting
            # "L4 skipped" into a non-zero exit rather than a quiet pass. Same discipline
            # as `_load_sequential_rows` and `_run_audit_and_release`.
            try:
                async with async_session_factory() as session:
                    rows = (
                        await session.execute(
                            select(Agent.name, Agent.potential_params).where(
                                Agent.potential_params.is_not(None)
                            )
                        )
                    ).all()
            finally:
                await engine.dispose()
            return {
                name.lower().replace(" - ", "_").replace(" ", "_").replace("-", "_"): len(ramps)
                for name, ramps in rows
            }

        return asyncio.run(_load())
    except Exception:  # unreachable DB, no event loop, pre-Track-2 schema
        return {}


def _agent_has_potential(path: Path) -> bool:
    """True when *path* is an agent kit for an agent that has a Potential tree."""
    return "agents" in path.parts and path.stem in _potential_agent_stems()


def _check_potential_rules(path: Path, mod: dict[str, Any]) -> list[tuple[str, str]]:
    """L0 rules 8 and 8c — Potential state, and ramp binding (#90).

    Split out of :func:`check_l0` to keep its branch count inside the lint budget. The
    logic and the finding codes are unchanged.
    """
    problems: list[tuple[str, str]] = []

    # Rule 8c (#90 Track 2) — a ramp-bound value must name a ramp that exists.
    # `bind_potential_param` resolves a bad index to 0 rather than raising, which is the
    # right runtime behaviour (inert beats wrong) but makes a typo invisible — the row
    # simply contributes nothing, forever. Author time is where an index should be
    # checked, so this is that check.
    potential_param = mod.get("potential_param")
    if potential_param is not None:
        L0_POTENTIAL_STATUS["bound_rows_seen"] = True
        known = _potential_ramp_counts()
        if not known:
            # No reachable/seeded DB — CANNOT CHECK, which is not a finding. L0 is the
            # hermetic tier that CI runs without a database, so failing here would turn
            # an absence into a red build. `--require-db` blocks on it instead, via
            # L0_POTENTIAL_STATUS, exactly as it does for L4/L5/LR.
            L0_POTENTIAL_STATUS["ramps_available"] = False
        else:
            ramps = known.get(path.stem)
            if ramps is None:
                problems.append((
                    "potential_param_unknown_agent",
                    (
                        f"row binds potential_param {potential_param} but this agent has "
                        f"no Potential ramps at all — it has no Potential tree, so no "
                        f"index is valid here"
                    ),
                ))
            elif not 0 <= potential_param < ramps:
                problems.append((
                    "potential_param_out_of_range",
                    (
                        f"potential_param {potential_param} is out of range: this agent "
                        f"has {ramps} ramp(s), so valid indices are 0..{ramps - 1}. The "
                        f"index is positional — nanoka's numbers carry no labels — so an "
                        f"off-by-one binds the row to a different mechanic entirely"
                    ),
                ))

    # Rule 8 — Potential gating (#90). On an agent that HAS a Potential tree,
    # every row must state `requires_potential` explicitly. Mandatory rather
    # than opt-in, and only for these agents, because an absent key is
    # indistinguishable from a key nobody thought about: kit JSONs were all
    # authored between #85 and #90, when fairy imported ONLY the unlocked kit,
    # so every row in the corpus was written against unlocked text. An opt-in
    # marker therefore fails in the silent direction — the row a curator forgot
    # stays wrongly active for a locked build, which is the exact defect #90
    # exists to fix. The other ~49 agents are untouched and the key stays absent
    # there.
    if _agent_has_potential(path) and "potential" not in mod:
        problems.append(
            (
        "potential_unstated",
        (
            "this agent has a Potential tree, so every modifier must say "
            "which Potential state its mechanic belongs to: add "
            "`potential: \"base\"|\"unlocked\"|null`. An absent key cannot be "
            "distinguished from an unconsidered one — every kit in this "
            "corpus was authored against Potential-unlocked text (#85), "
            "so silence here means the row is still wrongly active for a "
            "build that has not unlocked Potential"
        ),
            )
        )

    return problems


def check_l0(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L0 — executability. Can this modifier physically reach the calc?"""
    baked = baked_scaling_stats()
    findings: list[Finding] = []

    findings.extend(_check_duplicate_source_ids(kits))

    for path, kit in kits:
        name = kit.get("source_name", path.stem)

        findings.extend(_check_formulas(path, kit, name))

        # Rule 8b (#90) — same mandate as Rule 8 below, for `formulas[]`. A formula
        # instance can be Potential-gated exactly as a modifier can (Burnice's
        # unlocked-only free Afterburn proc is one), so leaving them out would make
        # Rule 8's "every row states its state" claim false in a place nobody looks.
        if _agent_has_potential(path):
            for fi, formula in enumerate(kit.get("formulas", []) or []):
                if "potential" in formula:
                    continue
                findings.append(
                    Finding(
                        level="L0",
                        code="potential_unstated",
                        source_file=_rel(path),
                        source_name=name,
                        index=fi,
                        label=formula.get("name", "") or f"formulas[{fi}]",
                        message=(
                            "this agent has a Potential tree, so every formula must say "
                            "which Potential state it belongs to: add "
                            '`potential: "base"|"unlocked"|null`'
                        ),
                    )
                )
        findings.extend(_check_lumiflux_block(path, kit, name))

        for i, mod in enumerate(kit.get("modifiers", [])):
            label = mod.get("source_label", "")
            stat = mod.get("stat", "")
            value = _effective_value(mod)
            scaling_stat = mod.get("scaling_stat")
            atk_ratio = mod.get("atk_scale_ratio", 0) or 0
            hp_per_unit = mod.get("hp_scale_per_unit", 0) or 0

            problems: list[tuple[str, str]] = []

            # Rule 1 — scaling_stat must be one the builder dispatches on, or the
            # value is never baked and the modifier contributes literally nothing.
            if scaling_stat and scaling_stat not in baked:
                problems.append(
                    (
                        "unbaked_scaling_stat",
                        (
                            f"scaling_stat {scaling_stat!r} is never baked by snapshot_builder "
                            f"(dispatches on: {', '.join(sorted(baked))}) — "
                            f"modifier is a silent no-op"
                        ),
                    )
                )

            # Rule 2 — stat must be readable by some consumer.
            if stat not in RESOLVABLE_STATS:
                problems.append(
                    (
                        "unresolvable_stat",
                        (
                            f"stat {stat!r} resolves in no buff_resolver bucket — "
                            f"buff_resolver marks it is_modeled=False and the calc ignores it"
                        ),
                    )
                )

            # Rule 3 — inert: nothing to contribute and nothing to fill it in.
            #
            # `potential_param` joined this list for #90 Track 2 and is the reason the rule
            # is worded as "value-supplying mechanism" rather than "scale field": a
            # ramp-bound row carries `value: 0` BY CONTRACT, because its value comes from
            # `agents.potential_params[index][rank]` at snapshot time. Without this it
            # reported every such row as dead — which is what a curator hit on Ellen's
            # first two bindings.
            supplies_value = bool(
                scaling_stat or atk_ratio or hp_per_unit or mod.get("potential_param") is not None
            )
            if not value and not supplies_value:
                problems.append(
                    (
                        "inert_modifier",
                        (
                            "value is 0 and nothing supplies one (no scale field, no "
                            "potential_param) — bakes to 0, contributes nothing"
                        ),
                    )
                )

            # Rule 4 — scale fields must be internally coherent.
            problems.extend(_scale_coherence_problems(mod))

            # Rule 6 — element_scope (C7 / D-KV16) is a filter only res_reduction /
            # res_ignore honor. On any other stat it silently does nothing —
            # exactly the no-op class this layer exists to kill.
            element_scope = mod.get("element_scope")
            if element_scope and stat not in ELEMENT_SCOPE_HONORED_STATS:
                problems.append(
                    (
                        "unhonored_element_scope",
                        (
                            f"element_scope is set but stat {stat!r} has no consumer that "
                            f"honors it (honored: "
                            f"{', '.join(sorted(ELEMENT_SCOPE_HONORED_STATS))}) "
                            f"— the scope is silently ignored"
                        ),
                    )
                )

            # Rule 7 — bracket routing. Agent kits buff *combat* ATK/HP/DEF, which is
            # the outer bracket; the inner bracket is reserved for disc / W-Engine
            # Initial Stats. Scoped to `agents/` because disc sets legitimately use
            # both (a 2pc base bonus is an Initial Stat, a conditional 4pc is not).
            # Pulchra's M2 row was fixed once (8c747da), silently reverted by an
            # uncommitted draft, and fixed again (2c7c1d4) with nothing to catch a
            # third revert — this rule is that catch. Waivable like any finding, so a
            # genuine inner-bracket agent buff can be recorded rather than argued.
            # `parts`, not `parent.name`: `iter_kits` walks with `rglob`, so a future
            # `agents/<subdir>/foo.json` would otherwise slip the rule silently.
            if "agents" in path.parts and stat in _INNER_TO_OUTER_BRACKET:
                problems.append(
                    (
                        "wrong_stat_bracket",
                        (
                            f"stat {stat!r} is the INNER (Initial Stat) bracket, reserved for "
                            f"disc / W-Engine stats; a kit-sourced buff belongs in "
                            f"{_INNER_TO_OUTER_BRACKET[stat]!r} (OUTER/combat bracket) — "
                            f"the value reaches the calc but multiplies the bare base "
                            f"instead of the equipment-inclusive total"
                        ),
                    )
                )

            problems.extend(_check_potential_rules(path, mod))

            findings.extend(
                Finding(
                    level="L0",
                    code=code,
                    source_file=_rel(path),
                    source_name=name,
                    index=i,
                    label=label,
                    message=message,
                )
                for code, message in problems
            )

    return findings


# --------------------------------------------------------------------------
# L1 — description cross-check
# --------------------------------------------------------------------------

# In-game descriptions carry unevaluated templates. A skill that reads "increases all
# squad members' DMG by {CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}%" states 20.00% at max
# skill level, once the template is evaluated. Without expanding
# these, every level-scaled buff in the corpus would false-flag. The grammar is closed:
# arithmetic over literals plus one function, AvatarSkillLevel(i).
_CAL_RE = re.compile(r"\{CAL:([^,}]+),\s*([0-9.]+)\s*,\s*(\d+)\}")
_SKILL_LEVEL_RE = re.compile(r"AvatarSkillLevel\(\s*\d+\s*\)")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Skill levels are pinned at max (D-KV4), so any AvatarSkillLevel(i) resolves to 12.
MAX_SKILL_LEVEL = 12

# A value matches the text if it lands within this much of a number in it. Descriptions
# round (35% of ATK, "up to a maximum of 1,200"), so exact equality is too strict.
MATCH_EPSILON = 0.011

# A cited constant must equal ZO's to within float noise — nothing looser.
ZO_VALUE_EPSILON = 1e-6


def _safe_arith(expr: str) -> float | None:
    """Evaluate a CAL arithmetic expression without eval().

    Only literals and + - * / and unary minus are permitted; anything else returns None
    and the template is left unexpanded (which is visible, rather than silently wrong).
    """
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(f"unsupported expression node: {ast.dump(node)}")

    try:
        return walk(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError):
        return None


def expand_cal(text: str) -> str:
    """Replace {CAL:...} templates with their value at max skill level."""

    def replace(match: re.Match[str]) -> str:
        expr, scale, precision = match.group(1), float(match.group(2)), int(match.group(3))
        value = _safe_arith(_SKILL_LEVEL_RE.sub(str(MAX_SKILL_LEVEL), expr))
        if value is None:
            return match.group(0)
        return f"{value * scale:.{precision}f}"

    return _CAL_RE.sub(replace, text)


def load_stat_units() -> dict[str, str]:
    """`{stat_key: 'bp'|'raw'}`, parsed from the frontend's STAT_META.

    STAT_META is the one place a stat's unit is declared, and L3 (Task 11) enforces that
    it covers every key in the corpus — so it is the honest source of truth here too,
    rather than a second list in Python that can drift from it.
    """
    pattern = re.compile(r"^\s*([a-z_0-9]+):\s*\{[^}]*unit:\s*'(bp|raw)'", re.MULTILINE)
    return dict(pattern.findall(STAT_META_TS.read_text()))


def _numbers_in(text: str) -> set[float]:
    """Every number in the text, comma separators removed ("1,200" → 1200.0)."""
    return {float(raw.replace(",", "")) for raw in _NUMBER_RE.findall(text)}


def _own_text(agent: dict[str, Any], source: str) -> str:
    """The text belonging to `source` itself — no fallback pooling.

    Used to detect a **seeding gap**: an agent whose core (or mindscape) text is missing
    from the DB entirely. Velina and Norma were the live case — nanoka.cc served both a
    literal `" | "` for every `core_skills` row (Task 23) — and without this distinction
    their unverifiable core modifiers would be reported as if a curator had invented them.
    """
    key = "mindscapes" if source == "mindscape" else "core_skills"
    return " \n".join(r["description"] for rows in agent[key].values() for r in rows)


def _description_pool(agent: dict[str, Any], source: str) -> str:
    """The description text a modifier of this `source` must be justified by.

    `core_skill` pools the core levels **and** the skills: the in-game "Additional
    Ability" has no row of its own, so e.g. Astra's team DMG%/CRIT DMG buffs are tagged
    `core_skill` in the kit but described in the Special skill's text.
    """
    parts = [_own_text(agent, source)]
    if source != "mindscape":
        parts += [s["description"] for s in agent["skills"]]
    return expand_cal(" \n".join(parts))


def _claimed_values(mod: dict[str, Any], units: dict[str, str]) -> list[tuple[str, float]]:
    """The numbers this modifier asserts, in the form the description would state them."""
    claims: list[tuple[str, float]] = []
    stat = mod.get("stat", "")
    value = _effective_value(mod)
    unit = units.get(stat)

    if value and unit:
        # bp are stated as a percentage in text: 2500 → "25%". raw are stated as-is.
        claims.append(("value", abs(value) / 100 if unit == "bp" else abs(value)))
    if mod.get("atk_scale_ratio"):
        claims.append(("atk_scale_ratio", mod["atk_scale_ratio"] / 100))
    if mod.get("scaling_stat") == "base_atk" and mod.get("scaling_ratio"):
        claims.append(("scaling_ratio", mod["scaling_ratio"] / 100))
    return claims


def check_l1(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L1 — every value a modifier asserts must appear in its own description text.

    A containment check, deliberately not a parse of game grammar: it asks "is this number
    present?", never "does this sentence mean what the modifier does". It kills the
    fabrication class (a number from nowhere) and off-by-10× errors. It cannot catch a
    right number wired to the wrong stat — that is D-KV6's blind spot, and it is the
    auditor's job, not CI's.

    Scope: **agents only.** W-Engine and disc-set descriptions are not in the fixture, so
    their values are unchecked by L1 today (their own L1 needs a `w_engines` /`disc_sets`
    description pool — worth doing, not in Task 9).
    """
    descriptions = json.loads(KIT_DESCRIPTIONS_PATH.read_text())["agents"]
    units = load_stat_units()
    findings: list[Finding] = []

    for path, kit in kits:
        if kit.get("source_type") != "agent":
            continue
        agent = descriptions.get(str(kit.get("source_id")))
        name = kit.get("source_name", path.stem)
        if agent is None:
            findings.append(
                Finding(
                    level="L1",
                    code="no_description_source",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label="",
                    message=(
                        f"source_id {kit.get('source_id')!r} is in no DB agent — "
                        f"L1 cannot check any of this kit's values"
                    ),
                )
            )
            continue

        sources = ("core_skill", "mindscape")
        texts = {source: _description_pool(agent, source) for source in sources}
        pools = {source: _numbers_in(text) for source, text in texts.items()}

        # A source whose description text is empty in the DB cannot justify anything.
        # Report that once, as a seeding gap — never as N "value not in description"
        # findings, which would blame the curator for missing data. (Velina and Norma
        # hit this for real — nanoka.cc served both an empty Core Passive/Additional
        # Ability description; Task 23's HakushinCoreDescriptionPatchImporter backfills
        # it, but the corpus can hit this again for a future agent nanoka is slow on.)
        blank = {source for source in texts if not _NUMBER_RE.search(_own_text(agent, source))}
        for source in sorted(blank):
            if not any(m.get("source") == source for m in kit.get("modifiers", [])):
                continue
            findings.append(
                Finding(
                    level="L1",
                    code="no_description_text",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label=source,
                    message=(
                        f"the DB has no {source} description text for this agent, so none "
                        f"of its {source} modifiers can be cross-checked — a seeding gap, "
                        f"not a curation error"
                    ),
                )
            )

        for i, mod in enumerate(kit.get("modifiers", [])):
            if mod.get("override_reason"):
                continue  # explicit, reviewed escape hatch
            source = mod.get("source", "core_skill")
            if source in blank:
                continue  # already reported as a seeding gap
            numbers = pools.get(source, pools["core_skill"])
            for field, claimed in _claimed_values(mod, units):
                if any(abs(claimed - n) <= MATCH_EPSILON for n in numbers):
                    continue
                findings.append(
                    Finding(
                        level="L1",
                        code="value_not_in_description",
                        source_file=_rel(path),
                        source_name=name,
                        index=i,
                        label=mod.get("source_label", ""),
                        message=(
                            f"{field}={mod.get(field, _effective_value(mod))} reads as "
                            f"{claimed:g} for stat {mod.get('stat')!r}, which appears "
                            f"nowhere in the agent's {mod.get('source')} description text"
                        ),
                    )
                )

    return findings


# --------------------------------------------------------------------------
# L2 — ZO citation check
# --------------------------------------------------------------------------

# What a kit `notes` field actually cites, in the three shapes the corpus uses:
#   "ZO: m1_resRed_ = prod(attack_hits, 0.06)"        → a sheet buff id, group-prefixed
#   "coreParams[0][6] = 0.35 (max core level)"        → a raw index path
#   "ZO: registerBuff('common_dmg_', ...)"            → a bare, unprefixed sheet buff id
#     (ZO registers some buffs — e.g. `common_dmg_`, `crit_dmg_`, `basic_electric_dmg_` —
#     under engine-shared or per-attack-type ids with no core/ability/mN prefix; D-KV15.
#     Recognised only via exact membership in *this agent's* `buff_names`, below —
#     see `_bare_buff_citations`.)
_CITED_SYMBOL_RE = re.compile(r"\b(core|ability|m[1-6])[._]([A-Za-z][A-Za-z0-9_]*)")
_CITED_PATH_RE = re.compile(
    r"\b(coreParams|abilityParams|mindscapeParams|potentialParams)((?:\[\d+\])+)\s*(?:=|→|->)?\s*"
    r"(-?\d+(?:\.\d+)?)?"
)

# `db:"<quoted DB fragment>"` (D-KV21) — the citation shape for stats that are pure
# fairy-internal extensions with no ZO symbol to name (e.g. `frostbite_frost_variant`,
# added for Miyabi). L1 still verifies the modifier's *value* against the DB description
# text; this only lets L2 accept the citation instead of flagging it uncited.
_DB_CITATION_RE = re.compile(r"\bdb:\s*[\"“]([^\"”]+)[\"”]")

# Stats a `db:` citation is allowed to resolve. Deliberately small and explicit: growing
# it requires a D-KV entry (see D-KV21 in docs/DECISIONS.md) — without that gate, `db:`
# becomes a second, untethered way to claim a value is cited, re-opening the exact
# fabrication hole L2 exists to close.
FAIRY_INTERNAL_STATS: frozenset[str] = frozenset({"frostbite_frost_variant"})

# `guide(vX.Y.Z)` (Task 22, Remielle #84) — the citation shape for an agent with
# *no ZO sheet at all* (`zo_agents` NULL — Remielle's own case). Modeled on
# D-KV21's `db:` fragment: gated to exactly one condition (see `check_l2`'s
# `zo_key is None` branch, which is the only place this citation is ever
# consulted) rather than a free-form escape any kit could reach for. A `db:`
# quoted-DB-text citation is accepted under the same gate — it is at least as
# strong a citation as the guide for an agent this codebase can't cross-check
# against ZO at all, and is not restricted to `FAIRY_INTERNAL_STATS` here
# (that allowlist only bounds `db:`'s use when a *real* ZO citation was the
# alternative; there is no such alternative for a ZO-absent agent).
_GUIDE_CITATION_RE = re.compile(r"\bguide\(v[\d.]+\)")

# Provenance tags this corpus's authoring convention uses in a modifier's
# `notes` (DESIGN_remielle.md §9.2): `db | guide(vX.Y.Z) | beta |
# user-relayed(Leifa) | estimated`. Only `estimated` needs its own scan --
# the other four are already citation forms L1/L2 parse structurally; this
# one exists purely for `find_estimated_values` for report (non-blocking).
_ESTIMATED_TAG_RE = re.compile(r"\bestimated\b")


def _norm_slug(name: str) -> str:
    """`soldier_11` and ZO's `Soldier11` are the same agent — normalise both sides.

    A CamelCase→snake_case slug does not insert a separator before a digit run, so an
    exact-string join drops Soldier 11 and Soldier 0 - Anby.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _zo_index_map(zo: dict[str, Any]) -> dict[str, str]:
    """`{normalised fairy slug: ZO character key}`."""
    return {_norm_slug(entry["fairy_slug"]): key for key, entry in zo.items()}


def _citation_resolves(token: str, group: str, symbol: str, entry: dict[str, Any]) -> bool:
    """Does this cited token name something ZO actually has *for this character*?

    Two answer keys, because citations use both. `buff_names` are the sheet's own buff ids
    (`registerBuff('m1_defIgn_', ...)`) — the form most of the corpus cites. `symbols` are
    the `dm.*` constants. A trailing underscore is ZO's percent marker and is written
    inconsistently in the notes, so it is tolerated on lookup — but nothing else is.
    """
    if token in entry["buff_names"]:
        return True
    bare = symbol.rstrip("_")
    return any(
        f"{group}.{candidate}" in entry["symbols"] for candidate in (symbol, bare, f"{bare}_")
    )


def _bare_buff_citations(notes: str, entry: dict[str, Any]) -> set[str]:
    """Bare, unprefixed ZO buff ids literally present in `notes` (D-KV15).

    `_CITED_SYMBOL_RE` only recognises `core.`/`ability.`/`m[1-6].`-prefixed citations, but
    ZO registers some buffs (`common_dmg_`, `crit_dmg_`, `basic_electric_dmg_`, …) under
    bare ids with no such prefix. Resolving those requires the opposite search direction:
    instead of extracting a candidate token from prose and checking it, walk *this agent's
    own* `buff_names` — already a small, per-character set — and check literal presence.

    This is deliberately not a general identifier scan. A trailing-underscore-tolerant
    fuzzy match, or a global (cross-character) namespace, would let a fabricated bare id
    slip through if it happened to resemble a real one for a *different* agent — the exact
    anti-fabrication property `_citation_resolves` already protects must hold here too.
    """
    hits: set[str] = set()
    for buff_id in entry["buff_names"]:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(buff_id)}(?![A-Za-z0-9_])")
        if pattern.search(notes):
            hits.add(buff_id)
    return hits


def _check_l2_no_zo_reference(path: Path, kit: dict[str, Any], name: str) -> list[Finding]:
    """L2 for a kit whose slug maps to no ZO character at all.

    Gated escape (Task 22, D-KV21-style): an agent genuinely absent from
    zo_constants.json has no ZO leg to cross-check against, so a
    per-modifier `guide(vX.Y.Z)` or `db:"..."` citation is accepted in its
    place — gated to exactly this function, never a free-form escape any
    kit could reach for regardless of ZO coverage (an agent that DOES have
    a zo_key never calls this).
    """
    findings: list[Finding] = []
    for i, mod in enumerate(kit.get("modifiers", [])):
        label = mod.get("source_label", "")
        notes = f"{mod.get('notes') or ''} {mod.get('_comment') or ''}"
        if _GUIDE_CITATION_RE.search(notes) or _DB_CITATION_RE.search(notes):
            continue
        findings.append(
            Finding(
                level="L2",
                code="no_zo_reference",
                source_file=_rel(path),
                source_name=name,
                index=i,
                label=label,
                message=(
                    f"no ZO character maps to kit slug {path.stem!r}, and this "
                    f"modifier cites neither a guide(vX.Y.Z) provenance tag nor a "
                    f'db:"..." DB-text fragment — the gated escape for agents '
                    f"absent from zo_constants.json requires one"
                ),
            )
        )
    return findings


def check_l2(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L2 — every value must trace to a ZO symbol that exists, for *this* agent.

    This is the layer that kills the fabrication class outright: Nicole's `m1_defRed_` names
    a symbol ZO does not have, and no amount of confident prose around it changes that.

    What L2 **cannot** do is verify *shape*, and that limit is load-bearing (D-KV6). A
    citation can name a real symbol, carry the right number, and still be wired to the wrong
    stat — ZO applies Nicole's `ability_ether_dmg_` as generic `common_dmg_`, while fairy
    encodes it as Ether-only. L2 passes that row. The auditor exists for exactly this, and a
    green harness is necessary, never sufficient.
    """
    zo = json.loads(ZO_CONSTANTS_PATH.read_text())["agents"]
    slug_to_zo = _zo_index_map(zo)
    findings: list[Finding] = []

    for path, kit in kits:
        if kit.get("source_type") != "agent":
            continue  # W-Engine / disc-set sheets are a separate ZO namespace
        name = kit.get("source_name", path.stem)
        zo_key = slug_to_zo.get(_norm_slug(path.stem))
        if zo_key is None:
            findings.extend(_check_l2_no_zo_reference(path, kit, name))
            continue
        entry = zo[zo_key]

        for i, mod in enumerate(kit.get("modifiers", [])):
            label = mod.get("source_label", "")
            stat = mod.get("stat", "")
            notes = f"{mod.get('notes') or ''} {mod.get('_comment') or ''}"
            symbols = _CITED_SYMBOL_RE.findall(notes)
            paths = _CITED_PATH_RE.findall(notes)
            bare = _bare_buff_citations(notes, entry)
            db_citations = _DB_CITATION_RE.findall(notes)

            def add(
                code: str,
                message: str,
                *,
                _i: int = i,
                _l: str = label,
                _p: Path = path,
                _n: str = name,
            ) -> None:
                findings.append(
                    Finding(
                        level="L2",
                        code=code,
                        source_file=_rel(_p),
                        source_name=_n,
                        index=_i,
                        label=_l,
                        message=message,
                    )
                )

            if db_citations and stat not in FAIRY_INTERNAL_STATS:
                add(
                    "db_citation_not_allowlisted",
                    f"cites a `db:` citation, but stat {stat!r} is not in "
                    f"FAIRY_INTERNAL_STATS — `db:` citations are only accepted for "
                    f"fairy-internal stats with no ZO equivalent (D-KV21); growing the "
                    f"allowlist requires a D-KV entry",
                )
                continue

            # A `db:` citation for an allowlisted fairy-internal stat satisfies L2 on its
            # own — `db_citations` being non-empty here means it already passed the gate
            # above, so it short-circuits this guard exactly like a resolved ZO citation.
            if not symbols and not paths and not bare and not db_citations:
                add(
                    "no_zo_citation",
                    "no ZO symbol or param path cited in `notes` — the value traces to "
                    "nothing and cannot be verified",
                )
                continue

            # `notes` and `_comment` often repeat the same citation — report it once.
            for group, symbol in dict.fromkeys(symbols):
                token = f"{group}_{symbol}"
                if not _citation_resolves(token, group, symbol, entry):
                    add(
                        "nonexistent_zo_symbol",
                        f"cites ZO symbol {token!r}, which does not exist for {zo_key} "
                        f"(neither a registered buff nor a dm constant) — the value is "
                        f"unverifiable, and may be attributed to the wrong skill entirely",
                    )

            for root, index_path, stated in paths:
                if not stated:
                    continue
                resolved = _resolve_param_path(entry["params"].get(root), index_path)
                if resolved is None:
                    add(
                        "nonexistent_zo_symbol",
                        f"cites {root}{index_path}, which does not exist for {zo_key}",
                    )
                elif abs(float(resolved) - float(stated)) > ZO_VALUE_EPSILON:
                    add(
                        "zo_value_mismatch",
                        f"cites {root}{index_path} = {stated}, but ZO has {resolved} "
                        f"(a wrong index reads the wrong level — DESIGN Finding 4)",
                    )

    return findings


def find_estimated_values(kits: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    """Every modifier tagged `estimated` in its provenance citation (Task 22,
    DESIGN_remielle.md §9.2), across the whole corpus.

    Non-blocking by design: `estimated` is one of five recognized provenance
    tags (`db | guide(vX.Y.Z) | beta | user-relayed(Leifa) | estimated`) a
    curator may cite — flagging a value as a placeholder is meant to be
    reportable without failing L0-L2, so a kit under active development
    doesn't have to hide its own known gaps to stay green. Returns plain
    description strings (not `Finding`s) since this never gates the run —
    `main()` prints the list purely as a report.
    """
    reports: list[str] = []
    for path, kit in kits:
        for i, mod in enumerate(kit.get("modifiers", [])):
            notes = f"{mod.get('notes') or ''} {mod.get('_comment') or ''}"
            if _ESTIMATED_TAG_RE.search(notes):
                label = mod.get("source_label", "") or mod.get("stat", "")
                reports.append(f"{_rel(path)} [{i}] {label}")
    return reports


# --------------------------------------------------------------------------
# L4 — per-agent move-key resolution
# --------------------------------------------------------------------------

# Maps scripts.audit_agent_data_binding's classification to a stable waiver code.
_L4_CODE_BY_CLASSIFICATION: dict[str, str] = {
    "BIND": "unbound_agent_name",
    "FOREIGN": "foreign_move_key",
    "DEAD": "dead_move_key",
    "NBSP": "nbsp_move_key",
}

# Mutated by check_l4 after each run so main() (and tests) can tell "L4 found nothing
# to report" apart from "L4 could not run" when deciding whether a waiver looks stale
# (see main()). A dict, not a plain module global, so check_l4 mutates it in place
# rather than rebinding the module attribute (avoids `global`).
L4_STATUS: dict[str, bool] = {"db_reachable": True}


async def _run_audit_and_release() -> list[BindingFinding]:
    """`run_audit()`, then hand the pool's connections back inside THIS loop.

    L4 and L5 share one module-level `engine` (both reach it through
    `app.database.async_session_factory`), and each runs under its own
    `asyncio.run(...)`. Without this, L4's loop closes while the pool still
    holds live asyncpg connections bound to it; L5 then inherits a pool of
    connections whose loop is dead. Its own `engine.dispose()` tries to close
    them *gracefully*, from a different loop, which raises "got Future attached
    to a different loop" and dumps a full traceback to stderr on an otherwise
    clean run — noise in a gate whose enforcement depends on reviewers actually
    reading its output.

    Disposing here, inside the loop that opened them, is the root fix: no
    connection outlives the loop it belongs to, so L5 never meets a stale one.
    `finally`, so a failed audit cleans up too — an exception on the way out is
    exactly when the pool is most likely to be holding something.
    """
    try:
        return await run_audit()
    finally:
        await engine.dispose()


def check_l4(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L4 — every attack-name key in moves/agents/ and skill_overrides/ resolves,
    per-agent-scoped, to a real attack owned by that agent.

    Ignores *kits* — L4's universe is moves/agents/ and skill_overrides/, not
    modifiers/, but every LEVELS entry shares the same (kits) -> list[Finding] shape so
    main() can dispatch uniformly. Needs the real seeded app DB; skips cleanly (empty
    result, a stderr note, and L4_STATUS["db_reachable"] set False) when it can't
    connect or the DB has no agents — see the module docstring's L4 section.
    """
    del kits
    try:
        binding_findings = asyncio.run(_run_audit_and_release())
    except DatabaseNotSeededError as exc:
        L4_STATUS["db_reachable"] = False
        print(f"L4 skipped: {exc}", file=sys.stderr)
        return []
    L4_STATUS["db_reachable"] = True

    findings: list[Finding] = []
    per_file_index: dict[str, int] = {}
    for bf in binding_findings:
        source_file = f"{bf.directory}/{bf.source_file}"
        index = per_file_index.get(source_file, 0)
        per_file_index[source_file] = index + 1
        findings.append(
            Finding(
                level="L4",
                code=_L4_CODE_BY_CLASSIFICATION[bf.classification],
                source_file=source_file,
                source_name=bf.agent_name or "",
                index=index,
                label=bf.key or "",
                message=bf.detail,
            )
        )
    return findings


def _resolve_param_path(params: Any, index_path: str) -> float | None:
    """Index `[0][6]` into a param array; None if it does not resolve to a number."""
    node = params
    for raw in re.findall(r"\[(\d+)\]", index_path):
        if not isinstance(node, list) or int(raw) >= len(node):
            return None
        node = node[int(raw)]
    return float(node) if isinstance(node, int | float) else None


# --------------------------------------------------------------------------
# L5 — sequential plausibility (docs/TASKS_sequential_variant.md Task 25)
# --------------------------------------------------------------------------

# Patterns in a `param_name` that mean "this row is a variant of another row, or a rider
# on one" rather than "this row is its own button press". Drawn from the moves audited on
# fix/sequential-variant-cycle: Soldier 11's `Enhanced Basic Attack 5th-Hit`, Caesar's and
# Lucy's `3rd-Hit (ALT)`, Alice's `One-/Two-/Three-Staged`, Yidhari's `Level-N`, Lighter's
# `L-Form Thundering Fist` set.
_L5_VARIANT_LABEL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bEnhanced\b", "Enhanced"),
    (r"\(ALT\)", "(ALT)"),
    (r"\bMin\b|\bMax\b", "Min/Max"),
    (r"\(Coordinated\)", "(Coordinated)"),
    (r"\bCharge Level\s*(?:\d+|One|Two|Three|Four|Five)\b", "Charge Level N"),
    (r"\bLevel-\d+", "Level-N"),
    (r"\b(?:One|Two|Three|Four|Five)-Staged\b", "N-Staged"),
)

# Mutated by check_l5, exactly as L4_STATUS is, so main() and the tests can tell "L5 found
# nothing" apart from "L5 could not run". `param_name_populated` is the second half of
# that: a DB migrated but never re-seeded has the column all-NULL, and reading all-NULL as
# "no variant labels, therefore clean" is the `ex_energy_cost` failure shape
# (DESIGN_sequential_variant.md §5.4). All-NULL means *cannot check*.
L5_STATUS: dict[str, bool] = {"db_reachable": True, "param_name_populated": True}

# Every code check_l5 can emit. Exported so the stale-waiver check can exclude L5 entries
# when L5 could not run — "couldn't check" is not "confirmed gone" — exactly as
# `_L4_CODE_BY_CLASSIFICATION` does for L4. Defined here, next to the emitting code, so
# adding a signal without updating the guard is not possible without noticing.
L5_CODES: frozenset[str] = frozenset({
    "seq_rider_row",
    "seq_duplicate_param_name",
    "seq_variant_label",
    "seq_qualified_duplicate",
    "seq_identical_rows",
    "seq_leading_qualifier",
})

# Signal 6's two guards. Both were derived by running the rule against the live corpus
# before shipping it: without them it fires on 4 moves that are genuine press chains.
#
# `_L5_ORDINAL` marks a word that *orders* a chain rather than qualifying one press of it.
# It is tested against the words that DIFFER between two labels, not against the words
# they share — `1st-Hit Charged Attack` vs `2nd-Hit Charged Attack` differ only in the
# ordinal, which is what a real chain looks like, whereas `Standing Fire` vs `Crouching
# Fire` differ in a state word. Testing the shared tail instead flags Lycaon's whole
# 5-press Moon Hunter and Manato's Blazing Wind Slash.
_L5_ORDINAL = re.compile(r"^\d+(?:st|nd|rd|th)\b|^(?:First|Second|Third|Fourth|Fifth)\b", re.I)

# A tail every row of every move ends with carries no information, so two rows "sharing"
# it are not related. Without this, Yixuan's bare `DMG Multiplier` row pairs with every
# other row of the move.
#
# Kept deliberately short. `Attack DMG Multiplier` was in an earlier draft and was
# removed: it suppressed Aria's genuine `Charge Level One/Two/Three Attack` trio, and for
# a flag-only lint an extra waiver is cheaper than a stoplist entry that hides a real
# finding. Add to this set only for a tail that is *always* boilerplate.
_L5_GENERIC_TAILS: frozenset[str] = frozenset({
    "dmg multiplier",
    "dmg",
    "multiplier",
    "total dmg multiplier",
})


def _l5_leading_qualifier_pairs(names: list[str]) -> list[tuple[str, str, str]]:
    """Pairs of labels related by a leading qualifier over a shared, meaningful tail.

    Two shapes, both meaning "one press in two forms" rather than two presses:

    * one label is a **suffix** of the other — `Shot DMG Multiplier` inside
      `Charged Shot DMG Multiplier` (Hugo);
    * both end in the same tail behind **different** leading words —
      `Standing Fire DMG Multiplier` / `Crouching Fire DMG Multiplier` (Billy).

    Returns `(shorter-or-first, other, shared tail)`, deduplicated and ordered.
    """
    uniq = sorted({re.sub(r"\s+", " ", n).strip() for n in names if n})
    pairs: list[tuple[str, str, str]] = []
    for i, a in enumerate(uniq):
        for b in uniq[i + 1 :]:
            wa, wb = a.split(), b.split()
            shared = 0
            while shared < min(len(wa), len(wb)) and wa[-1 - shared] == wb[-1 - shared]:
                shared += 1
            if shared == 0:
                continue
            tail = " ".join(wa[len(wa) - shared :])
            if tail.lower() in _L5_GENERIC_TAILS:
                continue
            # The words that distinguish the two labels. An ordinal here means a chain.
            head_a, head_b = " ".join(wa[: len(wa) - shared]), " ".join(wb[: len(wb) - shared])
            if _L5_ORDINAL.search(head_a) or _L5_ORDINAL.search(head_b):
                continue
            if not head_a and not head_b:
                continue
            pairs.append((a, b, tail))
    return pairs


@dataclass(frozen=True)
class _SeqRow:
    """One DB attack row of a move declared `sequential`."""

    hit_index: int
    param_name: str | None
    damage_base: int
    damage_growth: int
    stun_base: int
    anomaly_buildup: int
    # Which Potential state this row belongs to (#90); None = both. Load-bearing for
    # signal 2: a base/Potential pair shares a param_name and a hit_index legitimately.
    potential: str | None = None


def _l5_signals(rows: list[_SeqRow]) -> list[tuple[str, str]]:
    """Return (code, message) for every implausibility in one declared-sequential move.

    Flags only. It never decides what the move *is* — a rider, a variant and a genuine
    press can all produce the same signal, and telling them apart needs the skill text and
    nanoka's input notation, i.e. a human with sources. Auto-fixing any of these would
    rebuild the generator this branch just retired.
    """
    signals: list[tuple[str, str]] = []
    ordered = sorted(rows, key=lambda r: r.hit_index)

    # 1. Rider signature: a non-first row that lands no daze and no gauge. A button press
    #    that contributes neither is not a press (Promeia's `Cloak Slash DMG Per Second`,
    #    Soldier 11's `5th-Hit Additional`).
    riders = [r for r in ordered[1:] if r.stun_base == 0 and r.anomaly_buildup == 0]
    if riders:
        signals.append((
            "seq_rider_row",
            (
                "non-first row(s) at hit_index "
                f"{[r.hit_index for r in riders]} carry stun_base=0 and "
                "anomaly_buildup=0 — rider/DoT signature, not a press"
            ),
        ))

    # 2. Duplicate param_name within the move: one nanoka `param` expanded into several
    #    rows, which is how a variant pair reaches the DB (Miyabi's two `Slash` rows).
    #
    #    Grouped by (param_name, potential) since #90. A base/Potential pair is the SAME
    #    press described twice -- once per kit -- not two presses, so the two rows share
    #    a param_name legitimately and land on the same hit_index. Soldier 0 - Anby's
    #    `3rd-Hit DMG Multiplier` is the live case: skill 1381003 (base) and 1381022
    #    (Potential) both sit at hit_index 2, and each kit sees exactly one of them.
    #    Grouping on param_name alone reads that as a duplicated press and flags a move
    #    that is correct in both states.
    labelled = [r for r in ordered if r.param_name]
    seen: dict[tuple[str, str | None], list[int]] = {}
    for r in labelled:
        seen.setdefault((r.param_name or "", r.potential), []).append(r.hit_index)
    dupes = {name: idxs for (name, _tag), idxs in seen.items() if len(idxs) > 1}
    if dupes:
        signals.append((
            "seq_duplicate_param_name",
            (
                "param_name repeated within the move: "
                + "; ".join(f"{name!r} at {idxs}" for name, idxs in sorted(dupes.items()))
            ),
        ))

    # 3. Variant-pattern labels.
    hits = [
        f"{human!r} in {r.param_name!r} (hit_index {r.hit_index})"
        for r in labelled
        for pattern, human in _L5_VARIANT_LABEL_PATTERNS
        if re.search(pattern, r.param_name or "")
    ]
    if hits:
        signals.append((
            "seq_variant_label",
            "variant-pattern label(s): " + "; ".join(hits),
        ))

    # 5. A parenthesised qualifier whose stem is itself another row's label. This is the
    #    general form of signal 3 and does not need the state to be named in advance:
    #    Lighter's `5th-Hit Startup DMG Multiplier (Morale Burst)` sits beside a plain
    #    `5th-Hit Startup DMG Multiplier`, so the pair is one press in two states, not two
    #    presses. Catches Qingyi's `(ALT)` and Aria's `(Coordinated)` too, without an
    #    enumeration that goes stale every patch.
    stems = {r.param_name for r in labelled}
    qualified = [
        f"{r.param_name!r} (hit_index {r.hit_index}) qualifies {stem!r}"
        for r, stem in (
            (r, re.sub(r"\s*\([^)]*\)\s*$", "", r.param_name or "").strip()) for r in labelled
        )
        if stem and stem != r.param_name and stem in stems
    ]
    if qualified:
        signals.append((
            "seq_qualified_duplicate",
            (
                "parenthesised state qualifier over an existing row label: "
                + "; ".join(qualified)
            ),
        ))

    # 4. A row numerically identical to an earlier one. Two presses of a chain do not
    #    normally land the same four numbers; a re-statement of one press does.
    by_tuple: dict[tuple[int, int, int, int], list[int]] = {}
    for r in ordered:
        by_tuple.setdefault(
            (r.damage_base, r.damage_growth, r.stun_base, r.anomaly_buildup), []
        ).append(r.hit_index)
    identical = {t: idxs for t, idxs in by_tuple.items() if len(idxs) > 1}
    if identical:
        signals.append((
            "seq_identical_rows",
            (
                "row(s) identical in "
                "(damage_base, damage_growth, stun_base, anomaly_buildup): "
                + "; ".join(f"{t} at {idxs}" for t, idxs in sorted(identical.items()))
            ),
        ))

    # Emitted LAST, deliberately. `known_issues.json` waiver keys are
    # `code|file|ordinal`, where the ordinal is the finding's position within the
    # file — so inserting a signal anywhere but the end renumbers every later
    # finding and silently invalidates its waiver. Adding this one in the middle
    # broke Soldier 11's `seq_identical_rows|soldier_11.json|2` on the first run.
    # 6. A leading qualifier over a shared tail — signal 5's shape without the
    #    parentheses, which is the only reason Hugo's `Shot` / `Charged Shot` and Billy's
    #    `Standing Fire` / `Crouching Fire` were invisible to L5 while being exactly the
    #    "one press in two forms" case it exists to find. Both guards are in
    #    `_l5_leading_qualifier_pairs`; see its docstring.
    lq = _l5_leading_qualifier_pairs([r.param_name or "" for r in labelled])
    if lq:
        signals.append((
            "seq_leading_qualifier",
            (
                "leading qualifier over a shared row-label tail: "
                + "; ".join(f"{a!r} / {b!r} (shared tail {tail!r})" for a, b, tail in lq)
            ),
        ))

    return signals


async def _load_sequential_rows() -> dict[tuple[str, str], list[_SeqRow]]:
    """(agent_name, move name) -> its rows, for every move whose rows say `sequential`."""
    from app.models.agent import Agent, Attack  # noqa: PLC0415

    # L4 runs first in a full-harness run and closes its own event loop. Any pooled
    # connection left bound to that dead loop raises "attached to a different loop" when
    # reused here, which the skip contract below would report as "DB not reachable" — so
    # L5 would silently no-op in exactly the run that matters while looking green.
    # `_run_audit_and_release` now empties the pool inside L4's own loop, so in the full
    # run there is nothing stale left to meet; this stays as the guard for every other
    # entry order (`--level l5` alone, or after some other DB work in-process), where
    # nothing has taken that responsibility. Cheap, and the failure it prevents is silent.
    await engine.dispose()

    try:
        async with async_session_factory() as session:
            agents = (await session.execute(select(Agent))).scalars().all()
            attacks = (await session.execute(select(Attack))).scalars().all()
    finally:
        # Symmetric to the L4 side: hand the connections back before this loop
        # closes, rather than leaving them for whatever runs next.
        await engine.dispose()

    if not agents:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    id_to_name = {a.id: a.name for a in agents}
    out: dict[tuple[str, str], list[_SeqRow]] = {}
    for at in attacks:
        mode = getattr(at.hit_mode, "value", at.hit_mode)
        if mode != "sequential":
            continue
        key = (id_to_name.get(at.agent_id, at.agent_id), at.name)
        out.setdefault(key, []).append(
            _SeqRow(
                hit_index=at.hit_index,
                param_name=at.param_name,
                damage_base=at.damage_base,
                damage_growth=at.damage_growth,
                stun_base=at.stun_base,
                anomaly_buildup=at.anomaly_buildup,
                potential=getattr(at.potential, "value", at.potential),
            )
        )
    return out


# ---------------------------------------------------------------------------
# LCH — channel binding (DB-backed, DESIGN_channeled_moves.md §9)
# ---------------------------------------------------------------------------

# Mutated by check_lch exactly as L4_STATUS/L5_STATUS/LR_STATUS are, so main() and the tests
# can tell "LCH found nothing" from "LCH could not look" — the distinction --require-db turns
# into an exit code. `param_name` is the field LCH keys roles by and is populated by the
# nanoka importer alone, so a migrated-but-not-re-seeded DB is exactly the state that must
# block rather than read as clean.
LCH_STATUS: dict[str, bool] = {"db_reachable": True, "param_name_populated": True}

# Every code check_lch can emit, so the stale-waiver check can reason about LCH entries
# without importing the function.
LCH_CODES: tuple[str, ...] = (
    "channel_role_key_unresolved",
    "channel_row_unclassified",
    "channel_basis_nominal_mismatch",
    "channel_per_sec_label_mismatch",
    "channel_cost_key_unresolved",
    "channel_cost_key_per_sec_mismatch",
    "channel_era_basis_mismatch",
    "channel_move_no_db_rows",
    "channel_row_condition_unknown",
    "channel_role_empty_in_state",
    "channel_era_exemption_unauthorized",
    "channel_era_exemption_stale",
)

# §4.3.1 / D-CH1. Below the lower bound the game quotes whole-duration totals; at or above the
# upper bound it quotes per-second rates and says so in `param_name`. The gap between them is
# where no channel has shipped, so nothing is asserted there. These are DATA, not knobs: an
# agent that violates the boundary means HoYo shifted convention, which must fail the build
# rather than arrive silently. Widening either bound needs an owner ruling in DECISIONS.md.
_CHANNEL_ERA_WHOLE_MAX = 1371
_CHANNEL_ERA_PER_SEC_MIN = 1541

_PER_SEC_LABEL = re.compile(r"Per Sec(ond)?\b", re.IGNORECASE)


@dataclass(frozen=True)
class _ChannelRow:
    """One DB `attacks` row belonging to a move whose rows say `channel`."""

    hit_index: int
    param_name: str | None
    select_when: str | None = None


@dataclass(frozen=True)
class _ChannelAgent:
    """What LCH needs to know about one agent that owns at least one channel move."""

    name: str
    hakushin_id: int | None
    rows_by_move: dict[str, list[_ChannelRow]]
    cost_keys: dict[str, bool]  # cost_key -> per_sec


async def _load_channel_rows() -> dict[str, _ChannelAgent]:
    """Agent name -> its channel rows and resource-cost keys, straight from the DB.

    Keyed and scoped **per agent** deliberately: LCH rule 1 asks whether a role key names a
    row *this* agent owns, and a global `param_name` set would answer "yes" for a key that
    belongs to somebody else entirely. That is the #77 per-agent-scoping trap, which this
    repo has already fallen into once inside #77's own remediation table.
    """
    from app.models.agent import Agent, AgentResourceCost, Attack  # noqa: PLC0415

    # Same dead-loop guard as `_load_sequential_rows` — see its docstring. A pooled
    # connection bound to an earlier level's closed loop would surface here as "DB not
    # reachable", i.e. a silent skip in precisely the run that matters.
    await engine.dispose()

    try:
        async with async_session_factory() as session:
            agents = (await session.execute(select(Agent))).scalars().all()
            attacks = (await session.execute(select(Attack))).scalars().all()
            costs = (await session.execute(select(AgentResourceCost))).scalars().all()
    finally:
        await engine.dispose()

    if not agents:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    by_agent: dict[str, _ChannelAgent] = {}
    rows_acc: dict[str, dict[str, list[_ChannelRow]]] = {}
    costs_acc: dict[str, dict[str, bool]] = {}
    id_to_name = {a.id: a.name for a in agents}

    for at in attacks:
        mode = getattr(at.hit_mode, "value", at.hit_mode)
        if mode != "channel":
            continue
        name = id_to_name.get(at.agent_id, str(at.agent_id))
        rows_acc.setdefault(name, {}).setdefault(at.name, []).append(
            _ChannelRow(
                hit_index=at.hit_index,
                param_name=at.param_name,
                select_when=getattr(at.select_when, "value", at.select_when),
            )
        )
    for rc in costs:
        name = id_to_name.get(rc.agent_id, str(rc.agent_id))
        costs_acc.setdefault(name, {})[rc.cost_key] = bool(rc.per_sec)

    for agent in agents:
        if agent.name not in rows_acc:
            continue
        by_agent[agent.name] = _ChannelAgent(
            name=agent.name,
            hakushin_id=getattr(agent, "hakushin_id", None),
            rows_by_move=rows_acc[agent.name],
            cost_keys=costs_acc.get(agent.name, {}),
        )
    return by_agent


def _lch_rule_roles_resolve(
    agent: _ChannelAgent, rows: list[_ChannelRow], channel: Any
) -> list[tuple[str, str]]:
    """Rule 1 — every authored role key names a row THIS agent owns.

    Scoped per agent deliberately: a global `param_name` set would answer "resolves" for a
    key belonging to somebody else entirely, which is the #77 per-agent-scoping trap this
    repo has already fallen into once inside #77's own remediation table.
    """
    owned = sorted({r.param_name for r in rows if r.param_name})
    return [
        (
            "channel_role_key_unresolved",
            (
                f"channel role key {key!r} matches no attacks.param_name owned by "
                f"{agent.name!r} on this move (owned: {owned})"
            ),
        )
        for key in sorted(channel.roles)
        if key not in set(owned)
    ]


def _lch_rule_rows_classified(
    rows: list[_ChannelRow], channel: Any
) -> list[tuple[str, str]]:
    """Rule 2 — and every row has a role.

    An unclassified row takes `build_channel_plan`'s fallback (fired once, unscaled). That
    is a defensible *runtime* behaviour and an indefensible *authoring* state, so it warns
    at request time and fails here.
    """
    return [
        (
            "channel_row_unclassified",
            (
                f"row {row.hit_index} ({row.param_name!r}) has no authored channel role; "
                "it would fire once, unscaled by the hold length"
            ),
        )
        for row in sorted(rows, key=lambda r: r.hit_index)
        if row.param_name and row.param_name not in channel.roles
    ]


def _lch_rule_basis(channel: Any) -> list[tuple[str, str]]:
    """Rule 3 — exactly one basis, `nominal_s` present iff `whole_channel`.

    The loader rejects the inverse already; this catches a spec constructed past it in code,
    and states the consequence rather than the schema violation.
    """
    out: list[tuple[str, str]] = []
    if channel.tick_mv_basis == "whole_channel" and not channel.nominal_s:
        out.append(
            (
                "channel_basis_nominal_mismatch",
                (
                    "tick_mv_basis is 'whole_channel' but nominal_s is unset — every tick "
                    "would scale against a missing denominator"
                ),
            )
        )
    if channel.tick_mv_basis == "per_second" and channel.nominal_s is not None:
        out.append(
            (
                "channel_basis_nominal_mismatch",
                (
                    "tick_mv_basis is 'per_second' but nominal_s is set — the row is already "
                    "a rate, so the field is silently ignored"
                ),
            )
        )
    return out


def _lch_rule_per_sec_label(
    rows: list[_ChannelRow], channel: Any
) -> list[tuple[str, str]]:
    """Rule 4 — the game's own label polices the curator's role map.

    A row the game labels a rate must be a `tick` read as `per_second`, and nothing without
    that label may claim the basis. §4.3.1 is what makes this an assertion rather than a
    style check: the label tracks a real authoring convention, verified against release order.
    """
    out: list[tuple[str, str]] = []
    for row in sorted(rows, key=lambda r: r.hit_index):
        if not row.param_name:
            continue
        labelled = bool(_PER_SEC_LABEL.search(row.param_name))
        role = channel.roles.get(row.param_name)
        rate_read = role == "tick" and channel.tick_mv_basis == "per_second"
        if labelled and not rate_read:
            out.append(
                (
                    "channel_per_sec_label_mismatch",
                    (
                        f"row {row.hit_index} ({row.param_name!r}) carries the game's own "
                        f"'Per Sec' label but is authored role={role!r} "
                        f"basis={channel.tick_mv_basis!r}; expected role='tick' "
                        "basis='per_second'"
                    ),
                )
            )
        elif rate_read and not labelled:
            out.append(
                (
                    "channel_per_sec_label_mismatch",
                    (
                        f"row {row.hit_index} ({row.param_name!r}) is read as a per-second "
                        "rate but carries no 'Per Sec' label upstream"
                    ),
                )
            )
    return out


def _lch_rule_cost_keys(agent: _ChannelAgent, channel: Any) -> list[tuple[str, str]]:
    """Rule 5 — cost keys resolve for this agent, and only the drain is per-second.

    A drain bound to a flat row bills a whole hold as one payment; an entry bound to a
    per-sec row bills the activation over and over. Both leave a plausible-looking total.
    """
    out: list[tuple[str, str]] = []
    for field, expect_per_sec in (
        ("entry_cost_key", False),
        ("drain_cost_key", True),
        ("release_cost_key", False),
    ):
        key = getattr(channel, field, None)
        if not key:
            continue
        if key not in agent.cost_keys:
            out.append(
                (
                    "channel_cost_key_unresolved",
                    (
                        f"{field}={key!r} matches no agent_resource_costs row owned by "
                        f"{agent.name!r}"
                    ),
                )
            )
        elif agent.cost_keys[key] is not expect_per_sec:
            out.append(
                (
                    "channel_cost_key_per_sec_mismatch",
                    (
                        f"{field}={key!r} has per_sec={agent.cost_keys[key]}, expected "
                        f"{expect_per_sec}"
                    ),
                )
            )
    return out




_ERA_EXEMPTIONS_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "validation"
    / "channel_era_exemptions.json"
)


@lru_cache(maxsize=1)
def _era_exemptions() -> dict[tuple[str, str], dict[str, Any]]:
    """(agent, move) -> exemption record for LCH rule 6 (Task 19b).

    Rule 6 catches a real convention shift and must keep doing so. D-CH1a showed it can also be
    *wrong*: it was expressed as an avatar_id RANGE when what separates the cohorts is aggregate
    language in ``param_name``, so an agent can sit inside the range and outside the reason.

    An exemption is therefore a recorded decision, not a suppression — same contract as
    ``coverage_ledger.json``: a curator records it, only the owner may authorize it, and an
    unauthorized entry still fails.
    """
    if not _ERA_EXEMPTIONS_PATH.exists():
        return {}
    raw = json.loads(_ERA_EXEMPTIONS_PATH.read_text())
    return {
        (e["agent"], e["move"]): e
        for e in raw.get("exemptions", [])
        if e.get("agent") and e.get("move")
    }


def _lch_check_era_exemption(exemption: dict[str, Any], channel: Any) -> list[tuple[str, str]]:
    """Validate an era exemption rather than trusting it (Task 19b).

    Two ways an exemption is itself a defect: nobody authorized it, or it no longer describes
    the move it exempts. The second matters because rule 6 is a convention tripwire — an
    exemption left behind after a re-author would widen the rule by attrition, silently.
    """
    out: list[tuple[str, str]] = []
    if not exemption.get("authorized_by"):
        out.append(
            (
                "channel_era_exemption_unauthorized",
                (
                    "an LCH rule-6 exemption is recorded for this move but authorized_by is "
                    "null — a curator records, only the owner authorizes "
                    "(channel_era_exemptions.json)"
                ),
            )
        )
    expected = exemption.get("expected_basis")
    if expected and channel.tick_mv_basis != expected:
        out.append(
            (
                "channel_era_exemption_stale",
                (
                    f"the exemption is written for tick_mv_basis={expected!r} but the move is "
                    f"authored {channel.tick_mv_basis!r} — an exemption that no longer describes "
                    "the move it exempts is a hole, not a decision"
                ),
            )
        )
    return out


def _lch_rule_era(
    agent: _ChannelAgent, channel: Any, move_name: str = ""
) -> list[tuple[str, str]]:
    """Rule 6 — the era check (D-CH1), with the D-CH1a exemption ledger (Task 19b).

    The boundary is data, not a knob. A *new* agent that violates it means HoYo shifted
    convention again, which is exactly the event that must fail the build rather than arrive
    silently. Widening either bound needs an owner ruling in DECISIONS.md.

    An exempt move skips the check — but the exemption itself is then checked: unauthorized
    fails, and an exemption whose move no longer violates the rule is stale and fails, so the
    ledger cannot quietly accumulate entries that widen rule 6 by attrition.
    """
    exemption = _era_exemptions().get((agent.name, move_name))
    if exemption is not None:
        return _lch_check_era_exemption(exemption, channel)

    aid = agent.hakushin_id
    if aid is None:
        return []
    if aid <= _CHANNEL_ERA_WHOLE_MAX and channel.tick_mv_basis != "whole_channel":
        return [
            (
                "channel_era_basis_mismatch",
                (
                    f"avatar_id {aid} <= {_CHANNEL_ERA_WHOLE_MAX} is in the whole-duration "
                    f"cohort but the basis is {channel.tick_mv_basis!r} (D-CH1)"
                ),
            )
        ]
    if aid >= _CHANNEL_ERA_PER_SEC_MIN and channel.tick_mv_basis != "per_second":
        return [
            (
                "channel_era_basis_mismatch",
                (
                    f"avatar_id {aid} >= {_CHANNEL_ERA_PER_SEC_MIN} is in the per-second "
                    f"cohort but the basis is {channel.tick_mv_basis!r} (D-CH1)"
                ),
            )
        ]
    return []




_KNOWN_ROW_CONDITIONS = frozenset({"enemy_stunned", "enemy_not_stunned"})

# The states a `select_when` gate can be evaluated in. Named rather than inlined so rule 8
# reads as "every state keeps every role alive" rather than as a boolean pair.
_ROW_CONDITION_STATES: tuple[tuple[str, bool], ...] = (
    ("enemy not stunned", False),
    ("enemy stunned", True),
)


def _row_live_in(row: _ChannelRow, *, is_stunned: bool) -> bool:
    """Mirror of `anomaly_simulator._row_is_live`, over the harness's own row shape."""
    if row.select_when is None:
        return True
    if row.select_when == "enemy_stunned":
        return is_stunned
    if row.select_when == "enemy_not_stunned":
        return not is_stunned
    return True


def _lch_rule_row_conditions(
    rows: list[_ChannelRow], channel: Any
) -> list[tuple[str, str]]:
    """Rules 7 and 8 — the row gates are known, and no state starves a role (D-CH5).

    Rule 7 catches a DB holding a condition this build does not know: the loader rejects
    unknown values at author time, so one reaching the DB means a downgrade or rows seeded
    from a newer branch. The simulator fails *open* there, which keeps the damage rather than
    deleting a hit; that is the right runtime call and the wrong thing to stay quiet about.

    Rule 8 is the one worth having. Gating is the only mechanism here that can make a role
    produce **nothing** in some state — author both warheads as `enemy_stunned` and the move
    silently deals no entry damage whenever the target is not stunned. The output is a
    smaller number, not an error, which is exactly the class of defect this harness exists
    for.
    """
    out: list[tuple[str, str]] = [
        (
            "channel_row_condition_unknown",
            (
                f"row {row.hit_index} ({row.param_name!r}) has select_when="
                f"{row.select_when!r}, which is not a known condition "
                f"({sorted(_KNOWN_ROW_CONDITIONS)}) — the simulator fails open and fires it"
            ),
        )
        for row in sorted(rows, key=lambda r: r.hit_index)
        if row.select_when is not None and row.select_when not in _KNOWN_ROW_CONDITIONS
    ]

    if not any(r.select_when for r in rows):
        return out

    roles_present = {
        channel.roles.get(r.param_name) for r in rows if r.param_name in channel.roles
    }
    for state_name, is_stunned in _ROW_CONDITION_STATES:
        for role in sorted(x for x in roles_present if x):
            live = [
                r
                for r in rows
                if channel.roles.get(r.param_name) == role
                and _row_live_in(r, is_stunned=is_stunned)
            ]
            if not live:
                out.append(
                    (
                        "channel_role_empty_in_state",
                        (
                            f"with {state_name}, no {role!r} row is live — the move would "
                            "deal nothing for that role in that state, and report a smaller "
                            "number rather than an error"
                        ),
                    )
                )
    return out


def _lch_signals(agent: _ChannelAgent, move_name: str, channel: Any) -> list[tuple[str, str]]:
    """Every LCH rule for one (agent, move), as ``(code, message)`` pairs.

    Split from :func:`check_lch` so the six rules can be exercised against hand-built
    violations without Postgres — the Task 13 acceptance is "LCH catches each of six", and a
    rule reachable only through a live DB tends not to get tested at all.
    """
    rows = agent.rows_by_move.get(move_name, [])
    return [
        *_lch_rule_roles_resolve(agent, rows, channel),
        *_lch_rule_rows_classified(rows, channel),
        *_lch_rule_basis(channel),
        *_lch_rule_per_sec_label(rows, channel),
        *_lch_rule_cost_keys(agent, channel),
        *_lch_rule_era(agent, channel, move_name),
        *_lch_rule_row_conditions(rows, channel),
    ]


def check_lch(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """LCH — a move file's `channel` block that does not bind to the DB it describes.

    Ignores *kits*: LCH's universe is `moves/agents/` crossed with the DB, not
    `modifiers/`. Every LEVELS entry shares the `(kits) -> list[Finding]` shape.

    DB-backed under the same contract as L4/L5/LR: it **skips** without a reachable seeded
    DB and `--require-db` turns that skip into a blocking exit. Doubly load-bearing here —
    `attacks.param_name`, which every role key is matched against, is populated by the
    nanoka importer alone, so a migrated-but-not-re-seeded DB has NULLs everywhere and
    "no role keys failed to resolve" would be a lie rather than a pass.
    """
    del kits
    from app.data.loaders.moves import load_agent_moves  # noqa: PLC0415

    try:
        by_agent = asyncio.run(_load_channel_rows())
    except DatabaseNotSeededError as exc:
        LCH_STATUS["db_reachable"] = False
        LCH_STATUS["param_name_populated"] = False
        print(f"LCH skipped: {exc}", file=sys.stderr)
        return []
    except Exception as exc:
        LCH_STATUS["db_reachable"] = False
        LCH_STATUS["param_name_populated"] = False
        print(f"LCH skipped: DB not reachable: {exc}", file=sys.stderr)
        return []

    LCH_STATUS["db_reachable"] = True

    all_rows = [r for a in by_agent.values() for rows in a.rows_by_move.values() for r in rows]
    if all_rows and not any(r.param_name for r in all_rows):
        LCH_STATUS["param_name_populated"] = False
        print(
            "LCH skipped: attacks.param_name is NULL on every channel row — the DB was "
            "migrated but not re-seeded, so role keys cannot be resolved. Run "
            "`python -m scripts.seed_db`.",
            file=sys.stderr,
        )
        return []
    LCH_STATUS["param_name_populated"] = True

    specs = load_agent_moves()
    findings: list[Finding] = []
    per_agent_index: dict[str, int] = {}
    for stem, spec in sorted(specs.items()):
        agent = by_agent.get(spec.agent_name)
        for move_name, move in sorted(spec.moves.items()):
            if move.channel is None:
                continue
            source_file = f"{stem}.json"
            if agent is None or move_name not in agent.rows_by_move:
                # The move file describes a channel the DB does not have. Usually a
                # skill_overrides entry that never landed — the exact silent drop that
                # shipped Burnice's first re-tag as a no-op.
                index = per_agent_index.get(source_file, 0)
                per_agent_index[source_file] = index + 1
                findings.append(
                    Finding(
                        level="LCH",
                        code="channel_move_no_db_rows",
                        source_file=source_file,
                        source_name=spec.agent_name,
                        index=index,
                        label=move_name,
                        message=(
                            f"{move_name}: authors a `channel` block but no DB row for this "
                            "move says hit_mode='channel' — check "
                            "app/data/skill_overrides/ and re-seed"
                        ),
                    )
                )
                continue
            for code, message in _lch_signals(agent, move_name, move.channel):
                index = per_agent_index.get(source_file, 0)
                per_agent_index[source_file] = index + 1
                findings.append(
                    Finding(
                        level="LCH",
                        code=code,
                        source_file=source_file,
                        source_name=spec.agent_name,
                        index=index,
                        label=move_name,
                        message=f"{move_name}: {message}",
                    )
                )
    return findings


def check_l5(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L5 — a move declared `sequential` whose DB rows do not look like a press chain.

    Ignores *kits*: L5's universe is the DB, not `modifiers/`. Every LEVELS entry shares
    the `(kits) -> list[Finding]` shape so `main()` can dispatch uniformly.

    Needs the real seeded app DB and **skips cleanly** when it can't reach one — CI has no
    Postgres and runs `--gate`, exactly as L4 does. It also skips when `param_name` is
    NULL on every row, which is what a migrated-but-not-re-seeded DB looks like: treating
    that as "no variant labels found, therefore clean" would be the `ex_energy_cost`
    mistake (DESIGN_sequential_variant.md §5.4). Isolated NULLs are fine and expected —
    a synthetic variant row minted from an override's `fields` block has no upstream
    nanoka param and so legitimately has no label.

    **It flags; it never classifies, and no finding may be auto-fixed.** Deciding whether
    a flagged row is a rider, a variant or a real press needs the skill text and nanoka's
    input notation. A tool that decided for itself is the generator this branch retired.
    """
    del kits
    try:
        by_move = asyncio.run(_load_sequential_rows())
    except DatabaseNotSeededError as exc:
        L5_STATUS["db_reachable"] = False
        L5_STATUS["param_name_populated"] = False
        print(f"L5 skipped: {exc}", file=sys.stderr)
        return []
    except Exception as exc:
        L5_STATUS["db_reachable"] = False
        L5_STATUS["param_name_populated"] = False
        print(f"L5 skipped: DB not reachable: {exc}", file=sys.stderr)
        return []

    L5_STATUS["db_reachable"] = True

    all_rows = [r for rows in by_move.values() for r in rows]
    if all_rows and not any(r.param_name for r in all_rows):
        L5_STATUS["param_name_populated"] = False
        print(
            "L5 skipped: attacks.param_name is NULL on every sequential row — the DB was "
            "migrated but not re-seeded, so label signals cannot be checked. Run "
            "`python -m scripts.seed_db`.",
            file=sys.stderr,
        )
        return []
    L5_STATUS["param_name_populated"] = True

    findings: list[Finding] = []
    per_agent_index: dict[str, int] = {}
    for (agent_name, move_name), rows in sorted(by_move.items()):
        for code, message in _l5_signals(rows):
            source_file = f"{_agent_stem(agent_name)}.json"
            index = per_agent_index.get(source_file, 0)
            per_agent_index[source_file] = index + 1
            findings.append(
                Finding(
                    level="L5",
                    code=code,
                    source_file=source_file,
                    source_name=agent_name,
                    index=index,
                    label=move_name,
                    message=f"{move_name}: {message}",
                )
            )
    return findings


def _agent_stem(agent_name: str) -> str:
    """`Soldier 0 - Anby` -> `soldier_0_anby`, matching the data files' naming."""
    return agent_name.lower().replace(" - ", "_").replace(" ", "_").replace("'", "")


# --------------------------------------------------------------------------
# L6 — upstream multiplier cross-check (issue #165)
# --------------------------------------------------------------------------

# `{quantity: (base_field, growth_field)}` — the two upstream fields a declared quantity
# is rebuilt from. A skill's value at level N is `base + growth * (N - 1)`; that linear
# form is the whole of ZZZ's skill scaling and is what every hand-copied tuple in a kit
# is a frozen evaluation of.
_L6_QUANTITY_FIELDS: dict[str, tuple[str, str]] = {
    "damage": ("damage_base", "damage_growth"),
    "daze": ("stun_base", "stun_growth"),
}

# Key suffixes that mean "this list is copied upstream multipliers". A kit key shaped
# like this and *not* covered by a declaration is the exact defect #165 reports — an
# unchecked hand-transcription — so the naming convention is enforced rather than
# trusted. It is the only way this level can grow itself: nothing else in the repo knows
# that a new `*_mv_bp` key is a transcription rather than a curated constant.
_L6_HAND_COPY_SUFFIXES: tuple[str, ...] = ("_mv_bp", "_daze_bp")

L6_CODES: frozenset[str] = frozenset({
    "upstream_mv_mismatch",
    "upstream_mv_unknown_skill",
    "upstream_mv_bad_declaration",
    "upstream_mv_undeclared",
    "upstream_mv_snapshot_missing",
    "upstream_mv_snapshot_stale",
})


def _resolve_dotted(node: Any, path: str) -> Any:
    """`a.b.c` into nested dicts; None if any hop is missing."""
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _hand_copy_paths(node: Any, prefix: str = "") -> list[str]:
    """Every dotted path under `node` whose key looks like a copied multiplier tuple."""
    found: list[str] = []
    if not isinstance(node, dict):
        return found
    for key, value in node.items():
        path = f"{prefix}{key}"
        if key.endswith(_L6_HAND_COPY_SUFFIXES) and isinstance(value, list):
            found.append(path)
        elif isinstance(value, dict):
            found.extend(_hand_copy_paths(value, f"{path}."))
    return found


def _load_upstream_snapshot() -> dict[str, Any] | None:
    if not UPSTREAM_MV_PATH.is_file():
        return None
    return json.loads(UPSTREAM_MV_PATH.read_text())


def _snapshot_findings(snapshot: dict[str, Any]) -> list[Finding]:
    """Is the committed snapshot still the pin the rest of the toolkit reads?

    Bumping `provenance.json` without regenerating leaves L6 diffing today's kits
    against yesterday's upstream — a check that still passes, still prints green, and no
    longer means anything. Same family as a stale waiver: the failure mode of a
    verification artifact is silence, so it has to be made loud.
    """
    pinned = json.loads(DIMBREATH_PROVENANCE_PATH.read_text())["pinned_commit_sha"]
    snapshot_sha = snapshot.get("_meta", {}).get("pinned_sha")
    if snapshot_sha == pinned:
        return []
    return [
        Finding(
            level="L6",
            code="upstream_mv_snapshot_stale",
            source_file=_UPSTREAM_MV_REL,
            source_name="",
            index=0,
            label="upstream snapshot",
            message=(
                f"snapshot was built at Dimbreath {snapshot_sha}, but provenance.json now "
                f"pins {pinned}. Regenerate: "
                "`python -m scripts.dimbreath.build_upstream_mv`"
            ),
        )
    ]


def _check_declaration(
    rel: str, name: str, index: int, check: dict[str, Any], kit: dict[str, Any], skills: dict
) -> list[Finding]:
    """One `upstream_mv_checks` entry: rebuild the tuple upstream and diff it."""

    def finding(code: str, message: str) -> Finding:
        return Finding(
            level="L6",
            code=code,
            source_file=rel,
            source_name=name,
            index=index,
            label=str(check.get("path", "<no path>")),
            message=message,
        )

    path = check.get("path")
    quantity = check.get("quantity")
    level = check.get("skill_level")
    skill_ids = check.get("skill_ids") or []
    if not isinstance(path, str) or quantity not in _L6_QUANTITY_FIELDS:
        return [
            finding(
                "upstream_mv_bad_declaration",
                f"needs a `path` and a `quantity` in "
                f"{sorted(_L6_QUANTITY_FIELDS)}; got path={path!r} quantity={quantity!r}",
            )
        ]
    if not isinstance(level, int) or level < 1:
        return [
            finding("upstream_mv_bad_declaration", f"`skill_level` must be >= 1, got {level!r}")
        ]

    authored = _resolve_dotted(kit, path)
    if not isinstance(authored, list) or not all(isinstance(v, int) for v in authored):
        return [
            finding(
                "upstream_mv_bad_declaration",
                f"`{path}` does not resolve to a list of ints in this kit (got "
                f"{type(authored).__name__})",
            )
        ]
    if len(authored) != len(skill_ids):
        return [
            finding(
                "upstream_mv_bad_declaration",
                f"`{path}` has {len(authored)} value(s) but the declaration cites "
                f"{len(skill_ids)} skill id(s) — the two must line up positionally",
            )
        ]

    base_field, growth_field = _L6_QUANTITY_FIELDS[quantity]
    findings: list[Finding] = []
    for pos, (sid, value) in enumerate(zip(skill_ids, authored, strict=True)):
        row = skills.get(str(sid))
        if row is None:
            findings.append(
                finding(
                    "upstream_mv_unknown_skill",
                    f"skill_id {sid} (`{path}`[{pos}]) is not in the upstream snapshot, so "
                    "this value could not be checked. Regenerate: "
                    "`python -m scripts.dimbreath.build_upstream_mv`",
                )
            )
            continue
        expected = row[base_field] + row[growth_field] * (level - 1)
        if expected != value:
            findings.append(
                finding(
                    "upstream_mv_mismatch",
                    f"`{path}`[{pos}] is {value}, but skill_id {sid} at Lv.{level} is "
                    f"{expected} upstream ({row[base_field]} + {row[growth_field]}*"
                    f"{level - 1}, {quantity})",
                )
            )
    return findings


def check_l6(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """L6 — does every hand-transcribed upstream multiplier still match upstream?

    L4 and L5 answer "does this move key resolve to a DB row?", which is unanswerable for
    a move that has **no DB row**: nanoka seeds only the moves the in-game skill panel
    lists, so a damage channel built on an unlisted skill (Remielle's Phase Flow flight
    attacks, issue #165) passes the whole gate without a single check ever touching it.
    The kit's own numbers are then a hand-copy of upstream with nothing watching them.

    L6 watches them. Each `upstream_mv_checks` entry names a kit path, the upstream skill
    ids it was copied from, and the skill level it was frozen at; this rebuilds
    `base + growth * (level - 1)` from the committed Dimbreath snapshot and diffs.

    Offline by construction — it reads a committed artifact, never the network and never
    the DB, so unlike L4/L5 it cannot "skip". A missing snapshot is a **finding**, not a
    silent pass; that is the whole point of putting the fetch in a separate generator.
    """
    snapshot = _load_upstream_snapshot()
    declared_paths = {
        (_rel(path), check.get("path"))
        for path, kit in kits
        for check in (kit.get("upstream_mv_checks") or [])
    }

    findings: list[Finding] = []
    # Undeclared hand-copies are reported whether or not the snapshot exists — the defect
    # is the missing declaration, and it is knowable without any upstream data.
    for path, kit in kits:
        rel = _rel(path)
        name = kit.get("source_name", "")
        for i, copied in enumerate(sorted(_hand_copy_paths(kit))):
            if (rel, copied) in declared_paths:
                continue
            findings.append(
                Finding(
                    level="L6",
                    code="upstream_mv_undeclared",
                    source_file=rel,
                    source_name=name,
                    index=i,
                    label=copied,
                    message=(
                        f"`{copied}` is shaped like a hand-copied upstream multiplier tuple "
                        f"but no `upstream_mv_checks` entry cites where it came from, so "
                        "nothing can tell whether it has drifted (issue #165)"
                    ),
                )
            )

    if snapshot is None:
        if declared_paths:
            findings.append(
                Finding(
                    level="L6",
                    code="upstream_mv_snapshot_missing",
                    source_file=_UPSTREAM_MV_REL,
                    source_name="",
                    index=0,
                    label="upstream snapshot",
                    message=(
                        f"{len(declared_paths)} kit declaration(s) cite upstream skill rows, "
                        f"but {_UPSTREAM_MV_REL} does not exist, so none of them could be "
                        "checked. Generate it: "
                        "`python -m scripts.dimbreath.build_upstream_mv`"
                    ),
                )
            )
        return findings

    findings.extend(_snapshot_findings(snapshot))
    skills = snapshot.get("skills", {})
    for path, kit in kits:
        rel = _rel(path)
        name = kit.get("source_name", "")
        for index, check in enumerate(kit.get("upstream_mv_checks") or []):
            findings.extend(_check_declaration(rel, name, index, check, kit, skills))
    return findings


# --------------------------------------------------------------------------
# LC — confidence ladder (Task 18)
# --------------------------------------------------------------------------

# unverified (Task 15's demotion default) -> draft (curator) -> audited (auditor
# subagent) -> verified (harness only). See DESIGN "Confidence ladder" and the
# module docstring — no LLM may write "verified".
CONFIDENCE_LADDER: tuple[str, ...] = ("unverified", "draft", "audited", "verified")

_STAMP_PREFIX = "sha256:"


def _confidence_stamp(kit: dict[str, Any]) -> str:
    """The harness's own signature over a kit's checkable content.

    Only `modifiers[]` and `formulas[]` are hashed — the fields L0-L2 actually
    verify. Editing `notes`, `version`, or other metadata does not invalidate an
    existing stamp; changing a value, condition, citation, or any other field
    inside a modifier or formula does.
    """
    payload = json.dumps(
        {"modifiers": kit.get("modifiers", []), "formulas": kit.get("formulas", [])},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _STAMP_PREFIX + hashlib.sha256(payload.encode()).hexdigest()


def check_confidence(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """LC — enforce the ladder itself, not what it rates.

    `verified` may only appear alongside a `verified_stamp` that matches the kit's
    current `modifiers[]`/`formulas[]`. A hand edit setting `confidence: "verified"`
    has no way to also produce the matching stamp (only `--promote` computes one),
    so it fails here regardless of whether L0-L2 would otherwise pass the kit clean
    — this is what makes DESIGN's trust model ("the harness is the only writer of
    `verified`") an enforced property instead of a convention.

    LC also enforces the #180 cap: an agent with an `undetermined` unseeded upstream row
    may not declare a confidence above `draft`, unless the owner authorized a
    `ceiling_override` naming a higher one (never `verified`). Same principle as the
    stamp rule — a kit does not get to advertise more certainty than the corpus can
    support — applied to a row that is not in the kit but is about the same agent.
    """
    findings: list[Finding] = []
    caps = unseeded_confidence_caps()
    for path, kit in kits:
        name = kit.get("source_name", path.stem)
        confidence = kit.get("confidence")

        if confidence not in CONFIDENCE_LADDER:
            findings.append(
                Finding(
                    level="LC",
                    code="invalid_confidence",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label="",
                    message=(
                        f"confidence {confidence!r} is not one of {CONFIDENCE_LADDER} "
                        f"— likely a typo; the ladder only recognises these four rungs"
                    ),
                )
            )
            continue

        cap = caps.get(str(kit.get("source_id"))) if kit.get("source_type") == "agent" else None
        if cap and CONFIDENCE_LADDER.index(confidence) > CONFIDENCE_LADDER.index(cap):
            findings.append(
                Finding(
                    level="LC",
                    code="unseeded_undetermined_caps_confidence",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label="",
                    message=(
                        f"confidence is {confidence!r} but this agent has an `undetermined` "
                        f"unseeded upstream row, which caps the kit at {cap!r} — a damage-"
                        "bearing row nobody could identify is not allowed to be invisible "
                        "in what the kit advertises (issue #180). Either finish the triage, "
                        "or have the owner authorize a `ceiling_override` in "
                        "unseeded_row_ledger.json"
                    ),
                )
            )

        if confidence != "verified":
            continue

        stamp = kit.get("verified_stamp")
        if not stamp:
            findings.append(
                Finding(
                    level="LC",
                    code="unstamped_verified",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label="",
                    message=(
                        "confidence is 'verified' but there is no `verified_stamp` — "
                        "only `validate_kits.py --promote` may write 'verified', and "
                        "it always writes the stamp alongside it; this can only be a "
                        "hand edit"
                    ),
                )
            )
            continue

        expected = _confidence_stamp(kit)
        if stamp != expected:
            findings.append(
                Finding(
                    level="LC",
                    code="stamp_mismatch",
                    source_file=_rel(path),
                    source_name=name,
                    index=-1,
                    label="",
                    message=(
                        f"`verified_stamp` does not match the kit's current "
                        f"modifiers/formulas (expected {expected}, found {stamp!r}) — "
                        f"either hand-edited after stamping, or the stamp itself was "
                        f"hand-written"
                    ),
                )
            )

    return findings


def promote_kits(kits: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    """Advance every clean `audited` kit to `verified`, in place.

    "Clean" means zero L0-L2 findings for that kit — waived or not (L1/L2 apply to
    agents only; W-Engine/disc-set kits are judged on L0 alone). A waived finding is
    still open debt; promoting past it would make `verified` mean less than it says.

    Mutates the kit dicts in `kits` and returns the relative paths promoted; writing
    the files back to disk is the caller's job (`--promote` in `main()`), so this
    stays pure and unit-testable without touching the filesystem.
    """
    dirty = {f.source_file for f in check_l0(kits) + check_l1(kits) + check_l2(kits)}
    promoted: list[str] = []
    for path, kit in kits:
        rel = _rel(path)
        if kit.get("confidence") != "audited" or rel in dirty:
            continue
        kit["confidence"] = "verified"
        kit["verified_stamp"] = _confidence_stamp(kit)
        promoted.append(rel)
    return promoted


# --------------------------------------------------------------------------
# LR — roster coverage (docs/DESIGN_kit_accuracy_gate.md D7, TASKS Track D)
# --------------------------------------------------------------------------

# Mutated by check_lr exactly as L4_STATUS/L5_STATUS are, so main() and the tests can
# tell "LR found nothing" apart from "LR could not run". The roster lives in the DB, so
# no DB means no universe to check against — a skip, never a pass.
LR_STATUS: dict[str, bool] = {"db_reachable": True}

# Coverage counts per entity type, filled by check_lr for the `--roster` report:
# {entity_type: {"db": n, "covered": n, "ledgered": n, "gaps": n}}.
LR_SUMMARY: dict[str, dict[str, int]] = {}

# Every code check_lr can emit, exported for the stale-waiver exclusion exactly as
# L5_CODES is: when LR could not run, a waiver on one of these codes is "couldn't
# check", not "confirmed gone".
LR_CODES: frozenset[str] = frozenset({
    "roster_uncovered",
    "roster_unauthorized_ledger",
    "roster_stale_ledger",
    "roster_ledger_unknown_entity",
    "roster_sigmap_error",
})

# entity_type (as kits' `source_type` and the DB use it) -> corpus subdirectory.
_LR_DIRS: dict[str, str] = {"agent": "agents", "w_engine": "w_engines", "disc_set": "disc_sets"}


class MalformedCoverageLedgerError(ValueError):
    """A `coverage_ledger.json` entry is missing a required field.

    Raised, never skipped-over: a malformed entry that parsed leniently could
    suppress a roster gap while saying nothing anyone reviews — the unclassified-waiver
    failure shape, one file over.
    """


_LR_LEDGER_FIELDS = ("entity_type", "source_id", "name", "reason", "recorded_by", "date")


def load_coverage_ledger() -> list[dict[str, Any]]:
    """Entries of `coverage_ledger.json`, validated for shape.

    `authorized_by` is deliberately NOT in the required list — `null` is a legal,
    meaningful state (recorded by a curator, awaiting the owner) — but the key itself
    must be present, so "forgot the field" cannot read as "pending review".
    """
    if not COVERAGE_LEDGER_PATH.exists():
        return []
    entries = json.loads(COVERAGE_LEDGER_PATH.read_text()).get("entries", [])
    for i, entry in enumerate(entries):
        missing = [f for f in (*_LR_LEDGER_FIELDS, "authorized_by") if f not in entry]
        if missing:
            raise MalformedCoverageLedgerError(
                f"coverage_ledger.json entries[{i}] is missing {missing}"
            )
        if entry["entity_type"] not in _LR_DIRS:
            raise MalformedCoverageLedgerError(
                f"coverage_ledger.json entries[{i}]: unknown entity_type "
                f"{entry['entity_type']!r} (expected one of {sorted(_LR_DIRS)})"
            )
    return entries


def load_signature_map() -> dict[str, dict[str, Any]]:
    """`signature_map.json`'s engines block: {engine hakushin id: {agent_source_id, ...}}."""
    if not SIGNATURE_MAP_PATH.exists():
        return {}
    return json.loads(SIGNATURE_MAP_PATH.read_text()).get("engines", {})


async def _load_roster() -> dict[str, dict[str, dict[str, Any]]]:
    """{entity_type: {hakushin id (str): {name, rarity, specialty}}} from the app DB."""
    from app.models.agent import Agent  # noqa: PLC0415
    from app.models.disc import DiscSet  # noqa: PLC0415
    from app.models.w_engine import WEngine  # noqa: PLC0415

    # Same guard as _load_sequential_rows: an earlier level's loop may have owned the
    # pool; meeting one of its connections here would read as "DB not reachable".
    await engine.dispose()
    try:
        async with async_session_factory() as session:
            agents = (await session.execute(select(Agent))).scalars().all()
            engines = (await session.execute(select(WEngine))).scalars().all()
            disc_sets = (await session.execute(select(DiscSet))).scalars().all()
    finally:
        await engine.dispose()

    if not agents:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    def _val(x: Any) -> str:
        return str(getattr(x, "value", x))

    return {
        "agent": {
            str(a.hakushin_id): {"name": a.name, "rarity": _val(a.rarity), "specialty": ""}
            for a in agents
        },
        "w_engine": {
            str(w.hakushin_id): {
                "name": w.name,
                "rarity": _val(w.rarity),
                "specialty": _val(w.specialty),
            }
            for w in engines
        },
        "disc_set": {
            str(d.hakushin_id): {"name": d.name, "rarity": "", "specialty": ""}
            for d in disc_sets
        },
    }


def _roster_findings(
    roster: dict[str, dict[str, dict[str, Any]]],
    corpus_ids: dict[str, set[str]],
    ledger_entries: list[dict[str, Any]],
    signature_map: dict[str, dict[str, Any]],
) -> list[Finding]:
    """Pure diff: DB roster vs corpus vs ledger vs signature map.

    Split from :func:`check_lr` so the logic is unit-testable without a DB — the same
    split every DB-backed level here uses. Returns findings sorted most-urgent first:
    signature engines of curated agents, then S-rank gaps, then the rest, then
    ledger/map hygiene.
    """
    ledger_by_key = {(e["entity_type"], str(e["source_id"])): e for e in ledger_entries}
    ranked: list[tuple[int, Finding]] = []

    for etype, subdir in _LR_DIRS.items():
        for sid, info in sorted(roster.get(etype, {}).items()):
            if sid in corpus_ids.get(etype, set()):
                continue
            entry = ledger_by_key.get((etype, sid))
            if entry is not None:
                if entry.get("authorized_by"):
                    continue  # deliberate, owner-authorized non-coverage
                ranked.append((
                    3,
                    Finding(
                        level="LR",
                        code="roster_unauthorized_ledger",
                        source_file=f"{subdir}/{sid}",
                        source_name=info["name"],
                        index=0,
                        label=info["name"],
                        message=(
                            f"{etype} {sid} ({info['name']}) is ledgered by "
                            f"{entry['recorded_by']!r} but authorized_by is null — a "
                            "curator records, only the owner authorizes "
                            "(coverage_ledger.json)"
                        ),
                    ),
                ))
                continue

            sig = signature_map.get(sid) if etype == "w_engine" else None
            ranked.append(_gap_finding(etype, subdir, sid, info, sig, corpus_ids))

    ranked.extend(_ledger_hygiene_findings(roster, corpus_ids, ledger_entries))
    ranked.extend(_sigmap_findings(roster, signature_map))
    ranked.sort(key=lambda pair: (pair[0], pair[1].source_file))
    return [f for _prio, f in ranked]


def _gap_finding(
    etype: str,
    subdir: str,
    sid: str,
    info: dict[str, Any],
    sig: dict[str, Any] | None,
    corpus_ids: dict[str, set[str]],
) -> tuple[int, Finding]:
    """One uncovered-entity finding, ranked: sig-of-curated-agent, then S-rank, then rest."""
    if sig and str(sig.get("agent_source_id")) in corpus_ids.get("agent", set()):
        priority = 0
        headline = (
            f"SIGNATURE ENGINE of curated agent {sig.get('agent_name', '?')} — "
            "highest-priority gap: "
        )
    elif sig:
        priority = 1
        headline = f"signature engine of uncurated agent {sig.get('agent_name', '?')}: "
    else:
        priority = 1 if info.get("rarity") == "S" else 2
        headline = ""
    tags = [t for t in (info.get("rarity"), info.get("specialty")) if t]
    return (
        priority,
        Finding(
            level="LR",
            code="roster_uncovered",
            source_file=f"{subdir}/{sid}",
            source_name=info["name"],
            index=0,
            label=info["name"],
            message=(
                f"{headline}{etype} {sid} ({info['name']}"
                f"{', ' + '/'.join(tags) if tags else ''}) is in the DB but has "
                f"no kit JSON under modifiers/{subdir}/ and no coverage_ledger "
                "entry — curate it, or record + owner-authorize the omission"
            ),
        ),
    )


def _ledger_hygiene_findings(
    roster: dict[str, dict[str, dict[str, Any]]],
    corpus_ids: dict[str, set[str]],
    ledger_entries: list[dict[str, Any]],
) -> list[tuple[int, Finding]]:
    """Stale and unresolvable coverage-ledger entries — the checks that stop the
    ledger rotting into a list nobody can trust (the D-KV7 property, one file over)."""
    ranked: list[tuple[int, Finding]] = []
    for entry in ledger_entries:
        etype, sid = entry["entity_type"], str(entry["source_id"])
        subdir = _LR_DIRS[etype]
        if sid not in roster.get(etype, {}):
            ranked.append((
                3,
                Finding(
                    level="LR",
                    code="roster_ledger_unknown_entity",
                    source_file=f"{subdir}/{sid}",
                    source_name=entry["name"],
                    index=0,
                    label=entry["name"],
                    message=(
                        f"coverage_ledger.json names {etype} {sid} ({entry['name']}) but "
                        "no such DB row exists — a typo here authorizes nothing; fix or "
                        "remove the entry"
                    ),
                ),
            ))
        elif sid in corpus_ids.get(etype, set()):
            ranked.append((
                3,
                Finding(
                    level="LR",
                    code="roster_stale_ledger",
                    source_file=f"{subdir}/{sid}",
                    source_name=entry["name"],
                    index=0,
                    label=entry["name"],
                    message=(
                        f"coverage_ledger.json still lists {etype} {sid} ({entry['name']}) "
                        "but a kit JSON now exists — the entry is stale, remove it"
                    ),
                ),
            ))
    return ranked


def _sigmap_findings(
    roster: dict[str, dict[str, dict[str, Any]]],
    signature_map: dict[str, dict[str, Any]],
) -> list[tuple[int, Finding]]:
    """Signature-map entries that do not resolve against the DB."""
    ranked: list[tuple[int, Finding]] = []
    for eng_id, sig in sorted(signature_map.items()):
        problems = []
        if eng_id not in roster.get("w_engine", {}):
            problems.append(f"engine {eng_id} is not a DB w_engine")
        if str(sig.get("agent_source_id")) not in roster.get("agent", {}):
            problems.append(f"agent {sig.get('agent_source_id')} is not a DB agent")
        if problems:
            ranked.append((
                3,
                Finding(
                    level="LR",
                    code="roster_sigmap_error",
                    source_file=f"w_engines/{eng_id}",
                    source_name=sig.get("agent_name", ""),
                    index=0,
                    label=sig.get("agent_name", ""),
                    message=(
                        f"signature_map.json entry {eng_id!r}: {'; '.join(problems)} — "
                        "the map must resolve against the DB, never against numerology"
                    ),
                ),
            ))
    return ranked


def check_lr(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """LR — every DB entity is either curated or deliberately, verifiably not.

    The corpus side comes from *kits* (their `source_type`/`source_id`); the roster
    side is the DB, so this level skips cleanly without one — CI has no Postgres and
    runs `--gate`, exactly as L4/L5 do — and `--require-db` turns that skip into a
    failure. See the module docstring's LR section.
    """
    corpus_ids: dict[str, set[str]] = {etype: set() for etype in _LR_DIRS}
    for _path, kit in kits:
        etype = kit.get("source_type")
        if etype in corpus_ids and kit.get("source_id") is not None:
            corpus_ids[etype].add(str(kit["source_id"]))

    try:
        roster = asyncio.run(_load_roster())
    except DatabaseNotSeededError as exc:
        LR_STATUS["db_reachable"] = False
        print(f"LR skipped: {exc}", file=sys.stderr)
        return []
    except Exception as exc:
        LR_STATUS["db_reachable"] = False
        print(f"LR skipped: DB not reachable: {exc}", file=sys.stderr)
        return []
    LR_STATUS["db_reachable"] = True

    ledger_entries = load_coverage_ledger()
    signature_map = load_signature_map()
    findings = _roster_findings(roster, corpus_ids, ledger_entries, signature_map)

    ledgered = {
        (e["entity_type"], str(e["source_id"])) for e in ledger_entries if e.get("authorized_by")
    }
    LR_SUMMARY.clear()
    for etype in _LR_DIRS:
        db_ids = set(roster.get(etype, {}))
        covered = db_ids & corpus_ids[etype]
        auth = {sid for (et, sid) in ledgered if et == etype and sid in db_ids}
        LR_SUMMARY[etype] = {
            "db": len(db_ids),
            "covered": len(covered),
            "ledgered": len(auth),
            "gaps": len(db_ids - covered - auth),
        }
    return findings


# --------------------------------------------------------------------------
# LU — unseeded upstream damage rows (issue #180)
# --------------------------------------------------------------------------

# What a disposition may say, and the extra field each one must carry.
#
# `issue` is required-present (it may be null) on the two non-terminal dispositions for
# the same reason `authorized_by` is on the coverage ledger: "forgot the field" must not
# read as "nothing to track here".
UNSEEDED_DISPOSITIONS: dict[str, tuple[str, ...]] = {
    "not_a_move": (),
    "duplicate_of_modelled": ("twin_skill_id",),
    "modelled_in_kit": ("kit", "multiplier_bp"),
    "not_described_anywhere": (),
    "real_move_unmodelled": ("issue",),
    "undetermined": ("issue",),
}

# Class authorization is available only where LU can RE-DERIVE the membership predicate
# from the committed snapshot (owner ruling, 2026-08-14 — DESIGN §8a). `real_move_unmodelled`
# and `undetermined` are per-row stories, and a class would be a way of not telling them.
CLASS_ELIGIBLE_DISPOSITIONS = frozenset(
    {"not_a_move", "duplicate_of_modelled", "not_described_anywhere"}
)

_UNSEEDED_REQUIRED = ("disposition", "reason", "recorded_by", "authorized_by", "date")
_OVERRIDE_REQUIRED = ("ceiling", "retire_when", "decision", "authorized_by")
_UNSEEDED_SIDE_FIELDS = ("stun_base", "stun_growth", "energy_gain", "anomaly_buildup")

# Where a kit keeps a *damage* number, as opposed to a percentage bonus. Checking only
# these positions is the difference between evidence and a coincidence: `1000` in a kit is
# far more often "+10% DMG" than "1000% of ATK", and a naive whole-file scan says the row
# is explained when it is not (Ye Shunguang 1431036 and Cissia 1521021 both look explained
# under a naive scan and are not).
_KIT_MV_SUFFIXES = ("_mv_bp", "_daze_bp")

# Skill levels a description can be quoting. Kits cap at 12 today; the extra rungs cost
# nothing and stop a future level cap from silently narrowing the predicate.
_DESCRIPTION_LEVELS = range(1, 17)

# Descriptions comma-group at four digits ("1,600%"), so a percentage at or above this
# has two written forms and both have to be searched.
_COMMA_GROUPED_FROM = 1000
_UNSEEDED_VALUE_FIELDS = ("damage_base", "damage_growth", *_UNSEEDED_SIDE_FIELDS)


class MalformedUnseededLedgerError(ValueError):
    """An `unseeded_row_ledger.json` entry is structurally invalid.

    Raised rather than reported, on the `load_waivers` / `load_draft_blockers` precedent:
    an entry that parses leniently silences the row it covers while explaining nothing,
    which is strictly worse than the row not being listed at all.
    """


def _validate_override(where: str, override: dict[str, Any]) -> None:
    """A `ceiling_override` must name what it permits, when it retires, and who decided.

    `verified` is refused outright. That rung means the harness proved the kit, and an
    unidentified damage-bearing row upstream is the harness saying it cannot — no
    authorization makes that true (DESIGN §8b).
    """
    missing = [f for f in _OVERRIDE_REQUIRED if f not in override]
    if missing:
        raise MalformedUnseededLedgerError(f"{where}: ceiling_override is missing {missing}")
    ceiling = override["ceiling"]
    if ceiling not in CONFIDENCE_LADDER:
        raise MalformedUnseededLedgerError(
            f"{where}: ceiling_override.ceiling {ceiling!r} is not a rung of {CONFIDENCE_LADDER}"
        )
    if ceiling == "verified":
        raise MalformedUnseededLedgerError(
            f"{where}: ceiling_override.ceiling may not be 'verified' — an undetermined "
            "upstream row is the harness saying it could not prove the agent's damage, "
            "and no authorization converts that into proof (DESIGN §8b)"
        )


def _validate_unseeded_entry(where: str, entry: dict[str, Any]) -> list[str]:
    """Validate one ledger entry and return the skill ids it covers, as strings."""
    kind = entry.get("kind")
    if kind not in ("row", "class"):
        raise MalformedUnseededLedgerError(f"{where}: kind {kind!r} is not 'row' or 'class'")

    missing = [f for f in _UNSEEDED_REQUIRED if f not in entry]
    if missing:
        raise MalformedUnseededLedgerError(f"{where}: missing {missing}")

    disposition = entry["disposition"]
    if disposition not in UNSEEDED_DISPOSITIONS:
        raise MalformedUnseededLedgerError(
            f"{where}: disposition {disposition!r} is not one of {sorted(UNSEEDED_DISPOSITIONS)}"
        )

    if entry.get("ceiling_override") is not None:
        _validate_override(where, entry["ceiling_override"])

    if kind == "class":
        if disposition not in CLASS_ELIGIBLE_DISPOSITIONS:
            raise MalformedUnseededLedgerError(
                f"{where}: {disposition!r} may not be bundled as a class — LU cannot "
                "re-derive a membership predicate for it, so the class would be a list "
                f"nobody checks (class-eligible: {sorted(CLASS_ELIGIBLE_DISPOSITIONS)})"
            )
        ids = entry.get("skill_ids")
        if not isinstance(ids, list) or not ids:
            raise MalformedUnseededLedgerError(f"{where}: class entry needs a non-empty skill_ids")
        return [str(sid) for sid in ids]

    extra = [f for f in UNSEEDED_DISPOSITIONS[disposition] if f not in entry]
    if extra:
        raise MalformedUnseededLedgerError(
            f"{where}: disposition {disposition!r} must also carry {extra}"
        )
    if "skill_id" not in entry:
        raise MalformedUnseededLedgerError(f"{where}: row entry needs a skill_id")
    return [str(entry["skill_id"])]


def load_unseeded_ledger() -> list[dict[str, Any]]:
    """Entries of `unseeded_row_ledger.json`, validated for shape.

    Two entry shapes. A `row` entry is one row's story. A `class` entry covers several
    rows that are the same issue and lists every id it covers — explicitly, because
    implicit membership would let a new upstream row join an already-authorized class
    without anyone deciding that it should (DESIGN §8a).

    Malformed entries raise rather than report, on the `load_waivers` /
    `load_draft_blockers` precedent: an entry that parses leniently silences the row it
    covers while explaining nothing, which is worse than the row not being listed at all.
    """
    if not UNSEEDED_LEDGER_PATH.is_file():
        return []
    entries = json.loads(UNSEEDED_LEDGER_PATH.read_text()).get("entries", [])
    seen: dict[str, str] = {}
    for i, entry in enumerate(entries):
        where = f"unseeded_row_ledger.json entries[{i}]"
        for sid in _validate_unseeded_entry(where, entry):
            if sid in seen:
                raise MalformedUnseededLedgerError(
                    f"{where}: skill {sid} is already covered by {seen[sid]} — two entries "
                    "claiming one row makes it ambiguous which disposition and which "
                    "authorization apply to it"
                )
            seen[sid] = where
    return entries


def unseeded_coverage(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`{skill id: the entry covering it}` — row entries and class members alike."""
    coverage: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("kind") == "class":
            for sid in entry.get("skill_ids", []):
                coverage[str(sid)] = entry
        elif "skill_id" in entry:
            coverage[str(entry["skill_id"])] = entry
    return coverage


def _load_unseeded_snapshot() -> dict[str, Any] | None:
    if not UNSEEDED_ROWS_PATH.is_file():
        return None
    return json.loads(UNSEEDED_ROWS_PATH.read_text())


@lru_cache(maxsize=1)
def _load_kit_descriptions() -> dict[str, Any]:
    """The committed description corpus. Cached — LU asks it once per row."""
    if not KIT_DESCRIPTIONS_PATH.is_file():
        return {}
    return json.loads(KIT_DESCRIPTIONS_PATH.read_text())


def _description_blob(avatar_id: int) -> str | None:
    """This agent's committed skill / core / mindscape text, as one searchable string.

    `kit_descriptions.json` is a committed artifact, which is what lets the
    `not_described_anywhere` predicate be re-derived offline like every other class
    predicate. Returns None when the agent is absent from it — the predicate then cannot
    be evaluated, and an unevaluable predicate is a violation rather than a pass.
    """
    doc = _load_kit_descriptions()
    agent = (doc.get("agents") or {}).get(str(avatar_id))
    if agent is None:
        return None
    return json.dumps(agent, ensure_ascii=False)


def _percentage_written(blob: str, value_bp: int) -> str | None:
    """Is this exact percentage written in the text, and not part of a longer number?

    The boundary check is the whole of it. A naive substring search matches "600%" inside
    Jane's "1,600%" and calls the row identified — the exact failure mode this predicate
    exists to avoid, since a false "described" reading would eject a row from the class
    for no reason, and a false "undescribed" one would sweep a described move into it.
    """
    value = value_bp / 100
    forms = {f"{value:g}"}
    if value >= _COMMA_GROUPED_FROM and value == int(value):
        forms.add(f"{int(value):,}")
    for form in forms:
        for match in re.finditer(re.escape(form) + "%", blob):
            before = blob[match.start() - 1] if match.start() else " "
            if not (before.isdigit() or before in ",."):
                return form + "%"
    return None


def _described_at_any_level(row: dict[str, Any]) -> str | None:
    """The percentage form this row's damage takes in the agent's prose, if any."""
    blob = _description_blob(int(row["avatar_id"]))
    if blob is None:
        return None
    base, growth = int(row["damage_base"]), int(row["damage_growth"])
    for level in _DESCRIPTION_LEVELS:
        written = _percentage_written(blob, base + growth * (level - 1))
        if written:
            return written
    return None


def _class_predicate_violation(disposition: str, row: dict[str, Any]) -> str | None:
    """Re-derive a class's membership predicate for one row. `None` means it still holds.

    This is what makes a class an assertion the harness checks rather than a list it
    trusts: if the row's numbers move, it stops satisfying the predicate and falls out of
    the class instead of quietly keeping its authorization.
    """
    if disposition == "not_described_anywhere":
        return _undescribed_violation(row)
    if disposition == "not_a_move":
        return _inert_violation(row)
    return _duplicate_violation(row)


def _undescribed_violation(row: dict[str, Any]) -> str | None:
    if _description_blob(int(row["avatar_id"])) is None:
        return (
            f"has no entry in {KIT_DESCRIPTIONS_PATH.name} for avatar "
            f"{row['avatar_id']}, so the predicate cannot be evaluated — and an "
            "unevaluable predicate is not a satisfied one"
        )
    written = _described_at_any_level(row)
    if written:
        return (
            f"IS described: {written} appears in the agent's skill/core/mindscape text "
            "at some skill level, so the class's premise no longer holds for it. "
            "Re-triage it on its own — a described damage instance is the shape the "
            "three confirmed unmodelled moves in #180 had"
        )
    return None


def _inert_violation(row: dict[str, Any]) -> str | None:
    live = {f: row.get(f) for f in _UNSEEDED_SIDE_FIELDS if row.get(f)}
    if live:
        return (
            f"carries {live} — the inert class means no Daze, no energy and no anomaly "
            "buildup, which is the whole of its evidence"
        )
    return None


def _duplicate_violation(row: dict[str, Any]) -> str | None:
    twin, twin_values = row.get("twin_skill_id"), row.get("twin_values")
    if twin is None or twin_values is None:
        return "the snapshot records no seeded twin for it, so it duplicates nothing"
    diff = {
        f: (row.get(f), twin_values.get(f))
        for f in _UNSEEDED_VALUE_FIELDS
        if row.get(f) != twin_values.get(f)
    }
    if diff:
        return f"no longer matches seeded twin {twin} on {sorted(diff)} (row vs twin: {diff})"
    return None


def kit_damage_multipliers(kit: dict[str, Any]) -> set[int]:
    """Every number a kit uses as a damage multiplier: formula multipliers and mv/daze tuples."""
    values: set[int] = set()
    for formula in kit.get("formulas", []):
        multiplier = formula.get("multiplier")
        if isinstance(multiplier, dict) and isinstance(multiplier.get("value"), (int, float)):
            values.add(int(multiplier["value"]))

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            if path.endswith(_KIT_MV_SUFFIXES) and all(isinstance(x, (int, float)) for x in node):
                values.update(int(x) for x in node)
            else:
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

    walk(kit, "")
    return values


def _modelling_findings(
    entry: dict[str, Any],
    sid: str,
    row: dict[str, Any],
    kits: list[tuple[Path, dict[str, Any]]],
) -> list[Finding]:
    """`modelled_in_kit` is checked, not asserted: the kit must still carry the number.

    The disposition says "this row is real and we already model it" — Vivian's Prophecy
    instance and Remielle's flight attacks are both this. That claim rots the moment
    someone edits the multiplier out, and the row would then be silently unmodelled again
    while its ledger entry still says otherwise. So the entry names the kit and the value,
    and LU re-derives that the pairing is still true.
    """
    kit_rel, expected = entry["kit"], int(entry["multiplier_bp"])
    kit = next((k for path, k in kits if _rel(path) == kit_rel), None)
    if kit is None:
        message = f"names kit {kit_rel!r}, which does not exist in the corpus"
    elif expected not in kit_damage_multipliers(kit):
        message = (
            f"claims {kit_rel} models it as {expected} bp, but no damage multiplier in "
            "that kit carries that value any more — either the kit changed and the row "
            "is unmodelled again, or the entry was wrong when it was written"
        )
    else:
        return []
    return [
        Finding(
            level="LU",
            code="unseeded_row_modelling_lost",
            source_file=_UNSEEDED_LEDGER_REL,
            source_name=str(row.get("agent_name", "")),
            index=int(sid),
            label=sid,
            message=f"skill {sid} is ledgered as `modelled_in_kit` but {message}",
        )
    ]


def check_lu(kits: list[tuple[Path, dict[str, Any]]]) -> list[Finding]:
    """LU — every unseeded upstream damage row is a decision, not an absence (issue #180).

    nanoka publishes only panel-listed moves, so a damage-bearing `AvatarSkillTemplateTb`
    row with no panel entry gets no `attacks` row — and L4/L5, which both ask "does this
    key resolve to a DB row?", are structurally unable to see it. #165 shipped L6 for the
    rows a kit had already hand-copied; this level watches the population those copies
    were drawn from: 126 rows across 41 agents that nothing else looks at.

    Offline by construction — it reads two committed files, never the DB and never the
    network — so, like L6, it **cannot skip**, and it belongs on CI's side of the gate
    split. Registration in `LEVELS` is also what keeps the stale-waiver guarantee whole:
    that check is gated on `set(levels) == set(LEVELS)`, so a level outside the registry
    would silently narrow it.

    The load-bearing finding is `unseeded_row_unledgered`. Everything else here protects
    it: a new row appearing upstream must fail the build rather than arrive invisibly,
    which is the exact failure #180 was filed to end.
    """
    snapshot = _load_unseeded_snapshot()
    if snapshot is None:
        return [
            Finding(
                level="LU",
                code="unseeded_snapshot_missing",
                source_file=_UNSEEDED_ROWS_REL,
                source_name="",
                index=0,
                label="unseeded snapshot",
                message=(
                    f"{_UNSEEDED_ROWS_REL} does not exist, so no unseeded upstream row "
                    "could be checked at all. Generate it against a seeded DB: "
                    "`python -m scripts.dimbreath.build_unseeded_rows`"
                ),
            )
        ]

    findings: list[Finding] = []
    rows: dict[str, Any] = snapshot.get("rows", {})

    pinned = json.loads(DIMBREATH_PROVENANCE_PATH.read_text())["pinned_commit_sha"]
    snapshot_sha = snapshot.get("_meta", {}).get("pinned_sha")
    if snapshot_sha != pinned:
        findings.append(
            Finding(
                level="LU",
                code="unseeded_snapshot_stale_pin",
                source_file=_UNSEEDED_ROWS_REL,
                source_name="",
                index=0,
                label="unseeded snapshot",
                message=(
                    f"snapshot was swept at Dimbreath {snapshot_sha}, but provenance.json "
                    f"now pins {pinned} — a patch may have added or changed rows nobody "
                    "has looked at. Re-sweep against a seeded DB: "
                    "`python -m scripts.dimbreath.build_unseeded_rows`"
                ),
            )
        )

    entries = load_unseeded_ledger()
    coverage = unseeded_coverage(entries)

    for sid in sorted(coverage, key=int):
        entry = coverage[sid]
        row = rows.get(sid)
        if row is None:
            findings.append(
                Finding(
                    level="LU",
                    code="unseeded_row_stale_ledger",
                    source_file=_UNSEEDED_LEDGER_REL,
                    source_name=str(entry.get("agent_name", "")),
                    index=int(sid),
                    label=sid,
                    message=(
                        f"ledger covers skill {sid}, which the current snapshot does not "
                        "list — either it is seeded now (so the entry has outlived its "
                        "row) or the id is a typo, and a typo must not silently authorize "
                        "nothing"
                    ),
                )
            )
            continue

        declared_avatar = entry.get("avatar_id")
        if declared_avatar is not None and int(declared_avatar) != int(row["avatar_id"]):
            findings.append(
                Finding(
                    level="LU",
                    code="unseeded_row_entity_mismatch",
                    source_file=_UNSEEDED_LEDGER_REL,
                    source_name=str(entry.get("agent_name", "")),
                    index=int(sid),
                    label=sid,
                    message=(
                        f"ledger files skill {sid} under avatar {declared_avatar}, but the "
                        f"snapshot has it under {row['avatar_id']} ({row['agent_name']}) — "
                        "the entry is about a different agent than it says it is"
                    ),
                )
            )

        if entry["disposition"] == "modelled_in_kit":
            findings.extend(_modelling_findings(entry, sid, row, kits))

        if entry.get("kind") == "class":
            violation = _class_predicate_violation(entry["disposition"], row)
            if violation:
                findings.append(
                    Finding(
                        level="LU",
                        code="unseeded_class_predicate_violated",
                        source_file=_UNSEEDED_LEDGER_REL,
                        source_name=str(row.get("agent_name", "")),
                        index=int(sid),
                        label=sid,
                        message=(
                            f"class {entry.get('class_id', '<unnamed>')!r} "
                            f"({entry['disposition']}) lists skill {sid}, but it {violation}. "
                            "A class authorizes what its predicate still covers, never what "
                            "its list asserts"
                        ),
                    )
                )

    for sid in sorted(rows, key=int):
        row = rows[sid]
        entry = coverage.get(sid)
        if entry is None:
            findings.append(
                Finding(
                    level="LU",
                    code="unseeded_row_unledgered",
                    source_file=_UNSEEDED_ROWS_REL,
                    source_name=str(row.get("agent_name", "")),
                    index=int(sid),
                    label=sid,
                    message=(
                        f"{row['agent_name']} skill {sid} deals damage upstream "
                        f"({row['damage_base']} bp at Lv.1, bucket {row['bucket']}) but is "
                        "never seeded and has no ledger entry — nothing distinguishes "
                        "'correctly ignored' from 'silently missing damage' (issue #180)"
                    ),
                )
            )
        elif not entry.get("authorized_by"):
            findings.append(
                Finding(
                    level="LU",
                    code="unseeded_row_unauthorized",
                    source_file=_UNSEEDED_LEDGER_REL,
                    source_name=str(row.get("agent_name", "")),
                    index=int(sid),
                    label=sid,
                    message=(
                        f"skill {sid} is recorded as {entry['disposition']!r} but "
                        "`authorized_by` is null — a curator records an entry and may never "
                        "authorize it; this is a review queue, not a suppression"
                    ),
                )
            )

    return findings


def unseeded_confidence_caps() -> dict[str, str]:
    """`{avatar id: the highest rung its kit may declare}`, from `undetermined` rows.

    The owner's 2026-08-14 ruling: an unresolved unknown about an agent's damage is not
    allowed to be invisible in what its kit advertises. The cap is `draft` by default and
    lifts only to an authorized `ceiling_override.ceiling` — never to `verified`.
    """
    caps: dict[str, str] = {}
    for entry in load_unseeded_ledger():
        if entry.get("disposition") != "undetermined" or entry.get("avatar_id") is None:
            continue
        override = entry.get("ceiling_override") or {}
        ceiling = override["ceiling"] if override.get("authorized_by") else "draft"
        avatar = str(entry["avatar_id"])
        current = caps.get(avatar)
        if current is None or CONFIDENCE_LADDER.index(ceiling) < CONFIDENCE_LADDER.index(current):
            caps[avatar] = ceiling
    return caps


LEVELS = {
    "l0": check_l0,
    "l1": check_l1,
    "l2": check_l2,
    "l4": check_l4,
    "l5": check_l5,
    "l6": check_l6,
    "lc": check_confidence,
    "lch": check_lch,
    "lr": check_lr,
    "lu": check_lu,
}


# The two waiver classes and the fields each one must carry to be well-formed. Checked
# rather than trusted: a `class` nobody validates is documentation, and the whole point of
# splitting the ledger is that the merge gate can count one class and not the other.
WAIVER_CLASSES: dict[str, tuple[str, ...]] = {
    "branch_debt": ("owner_task",),
    "upstream_blocked": ("retire_when", "decision"),
}

GATED_WAIVER_CLASS = "branch_debt"


class MalformedWaiverError(ValueError):
    """A `known_issues.json` entry is missing its class or that class's required fields."""


def load_waivers() -> dict[str, dict[str, Any]]:
    """Open-issue ledger: {finding.key: waiver}.

    Raises :class:`MalformedWaiverError` on an entry without a recognised `class`, or
    without the fields that class requires. An unclassified waiver would otherwise
    silently escape the merge gate — it would suppress its finding while counting toward
    neither class, which is strictly worse than not being listed at all.
    """
    if not KNOWN_ISSUES_PATH.is_file():
        return {}
    raw = json.loads(KNOWN_ISSUES_PATH.read_text())
    waivers: dict[str, dict[str, Any]] = {}
    for entry in raw.get("waivers", []):
        key = entry.get("key", "<no key>")
        cls = entry.get("class")
        if cls not in WAIVER_CLASSES:
            raise MalformedWaiverError(
                f"waiver {key!r} has class {cls!r}; expected one of "
                f"{', '.join(sorted(WAIVER_CLASSES))}"
            )
        missing = [field for field in WAIVER_CLASSES[cls] if not entry.get(field)]
        if missing:
            raise MalformedWaiverError(
                f"waiver {key!r} is class {cls!r} and must carry: {', '.join(missing)}"
            )
        waivers[entry["key"]] = entry
    return waivers


# --------------------------------------------------------------------------
# LD — draft blockers (issue #88)
# --------------------------------------------------------------------------

# Each draft-blocker class and the fields it must carry. `curation_pending` is the only
# class anyone can close by working on the kit itself, so it is the only one that names an
# `owner_task`; every other class names the external condition that retires it instead,
# because there is no task to name — pretending otherwise is how a blocker rots into
# "someone should look at this sometime". See known_issues.json `_meta` for what each
# class means and which D-KV licenses it.
DRAFT_BLOCKER_CLASSES: dict[str, tuple[str, ...]] = {
    "curation_pending": ("owner_task",),
    "schema_gap": ("retire_when",),
    "approximation_ceiling": ("retire_when", "decision"),
    "upstream_blocked": ("retire_when", "decision"),
}


class MalformedDraftBlockerError(ValueError):
    """A `known_issues.json` draft_blockers entry is missing a required field."""


def load_draft_blockers() -> dict[str, dict[str, Any]]:
    """The draft-blocker ledger: {entry key: entry}.

    Raises :class:`MalformedDraftBlockerError` on an entry without a `key`, without a
    recognised `class`, without that class's required fields, or without the `kit`/`reason`
    every class needs. Validated rather than trusted for the same reason waivers are: an
    entry that does not say what retires it silences the `undocumented_draft` check while
    explaining nothing, which is worse than the kit not being listed at all.

    Keys must be present and unique — a missing one cannot be uniquely referred to and a
    duplicate would let one entry shadow another, and the whole point of keying on
    `<file>#<slug>` rather than on the file is that one kit can be stuck for several
    unrelated reasons at once (Nekomata is).
    """
    if not KNOWN_ISSUES_PATH.is_file():
        return {}
    raw = json.loads(KNOWN_ISSUES_PATH.read_text())
    blockers: dict[str, dict[str, Any]] = {}
    for entry in raw.get("draft_blockers", []):
        key = entry.get("key")
        if not key:
            raise MalformedDraftBlockerError(
                f"draft blocker entry has no `key` (expected `<kit>#<slug>`): {entry!r}"
            )
        if key in blockers:
            raise MalformedDraftBlockerError(f"duplicate draft blocker key {key!r}")
        cls = entry.get("class")
        if cls not in DRAFT_BLOCKER_CLASSES:
            raise MalformedDraftBlockerError(
                f"draft blocker {key!r} has class {cls!r}; expected one of "
                f"{', '.join(sorted(DRAFT_BLOCKER_CLASSES))}"
            )
        required = ("kit", "reason", *DRAFT_BLOCKER_CLASSES[cls])
        missing = [field for field in required if not entry.get(field)]
        if missing:
            raise MalformedDraftBlockerError(
                f"draft blocker {key!r} is class {cls!r} and must carry: {', '.join(missing)}"
            )
        blockers[key] = entry
    return blockers


def _draft_kits(kits: list[tuple[Path, dict[str, Any]]]) -> dict[str, str]:
    """{relative path: source_name} for every kit currently at `confidence: "draft"`."""
    return {
        _rel(path): kit.get("source_name", path.stem)
        for path, kit in kits
        if kit.get("confidence") == "draft"
    }


def check_draft_blockers(
    kits: list[tuple[Path, dict[str, Any]]], blockers: dict[str, dict[str, Any]]
) -> list[Finding]:
    """LD — every `draft` kit must have a ledger entry saying why.

    Deliberately *not* a judgement on whether the blocker is a good one: it asks only
    whether the reason exists somewhere a reader can find without opening the kit. Task 32
    closed with four draft kits carrying four unrelated blockers, each recorded solely in
    its own `notes` string, and nothing anywhere reported that state (issue #88).
    """
    documented = {entry["kit"] for entry in blockers.values()}
    return [
        Finding(
            level="LD",
            code="undocumented_draft",
            source_file=rel,
            source_name=name,
            index=-1,
            label="",
            message=(
                f"confidence is 'draft' but no `draft_blockers` entry in "
                f"{KNOWN_ISSUES_PATH.name} names {rel} — add one saying what is blocking "
                f"the kit and what retires it, or promote the kit"
            ),
        )
        for rel, name in sorted(_draft_kits(kits).items())
        if rel not in documented
    ]


def stale_draft_blockers(
    kits: list[tuple[Path, dict[str, Any]]], blockers: dict[str, dict[str, Any]]
) -> list[str]:
    """Entries naming a kit that is no longer `draft` (or no longer exists).

    The mirror of the stale-waiver rule, and there for the same reason: an entry that
    outlives its blocker turns the ledger back into prose nobody trusts.
    """
    drafts = _draft_kits(kits)
    return sorted(key for key, entry in blockers.items() if entry["kit"] not in drafts)


def check_confidence_caps(
    kits: list[tuple[Path, dict[str, Any]]], waived: list[Finding]
) -> list[Finding]:
    """LD — a kit carrying an open waiver may not sit above `draft`.

    D-KV22 states this ("the affected kit's confidence caps at `draft` regardless of how
    clean the rest of the file is"), and until now nothing enforced it. That is the general
    form of issue #88's headline complaint: `audited` is supposed to mean "no known
    defects", and a waived finding is a known defect that merely does not fail the build.
    Both waiver classes cap — `branch_debt` because the defect is real and ours,
    `upstream_blocked` because an unverifiable row is exactly what `audited` must not
    silently absorb.

    Takes the already-waived findings rather than re-deriving them, so it can only fire on
    a finding that actually fires today. It therefore *under*-reports when `--level`
    narrows the run or L4 skips for want of a DB — the same direction the stale-waiver
    check errs in, and the safe one.
    """
    confidences = {_rel(path): kit.get("confidence") for path, kit in kits}
    draft_rung = CONFIDENCE_LADDER.index("draft")
    findings: list[Finding] = []
    for finding in waived:
        confidence = confidences.get(finding.source_file)
        if confidence not in CONFIDENCE_LADDER:
            continue  # LC already reports an unrecognised rung; don't double-report
        if CONFIDENCE_LADDER.index(confidence) <= draft_rung:
            continue
        findings.append(
            Finding(
                level="LD",
                code="waived_finding_above_draft",
                source_file=finding.source_file,
                source_name=finding.source_name,
                index=finding.index,
                label=finding.label,
                message=(
                    f"confidence is {confidence!r} but this kit still carries an open "
                    f"waiver ({finding.key}) — a waived finding is a known defect, so "
                    f"D-KV22 caps the kit at 'draft' until the waiver is retired"
                ),
            )
        )
    return findings


def format_draft_report(
    kits: list[tuple[Path, dict[str, Any]]], blockers: dict[str, dict[str, Any]]
) -> list[str]:
    """The draft/blocker report, one line per kit plus one per blocker (issue #88, item 4).

    Grouped by kit because a kit can carry several blockers, and "how many kits are stuck"
    is a different number from "how many things are keeping them stuck".
    """
    drafts = _draft_kits(kits)
    if not drafts:
        return ["No kits at `confidence: draft`."]

    by_kit: dict[str, list[dict[str, Any]]] = {rel: [] for rel in drafts}
    for entry in blockers.values():
        if entry["kit"] in by_kit:
            by_kit[entry["kit"]].append(entry)

    lines = [f"Draft kits ({len(drafts)}) — blockers from {KNOWN_ISSUES_PATH.name}:"]
    for rel in sorted(by_kit):
        lines.append(f"  {rel}")
        if not by_kit[rel]:
            lines.append("      (no ledger entry — see the undocumented_draft finding above)")
        for entry in sorted(by_kit[rel], key=lambda e: e["key"]):
            retires = entry.get("owner_task") or entry.get("retire_when", "")
            lines.append(f"      {entry['class']:<22} {entry['key'].split('#', 1)[-1]}")
            lines.append(f"          retired by: {retires}")
    return lines


def unrunnable_levels(levels: list[str]) -> list[str]:
    """Requested DB-backed layers that could not actually check anything.

    The two ways a layer ends up here are the two ways :func:`check_l4` and
    :func:`check_l5` skip: the app DB is unreachable, or (L5 only) the DB was
    migrated but never re-seeded, leaving ``attacks.param_name`` NULL on every row.

    A skip prints to stderr and otherwise looks exactly like a pass. That is
    tolerable where the run is advisory and something else is the gate; it is not
    tolerable where the run *is* the gate, which is what ``--require-db`` is for.
    """
    unrunnable = []
    if "l4" in levels and not L4_STATUS["db_reachable"]:
        unrunnable.append("l4")
    if "l5" in levels and not (L5_STATUS["db_reachable"] and L5_STATUS["param_name_populated"]):
        unrunnable.append("l5")
    if "lr" in levels and not LR_STATUS["db_reachable"]:
        unrunnable.append("lr")
    if "lch" in levels and not (
        LCH_STATUS["db_reachable"] and LCH_STATUS["param_name_populated"]
    ):
        unrunnable.append("lch")
    # L0 is hermetic APART FROM Rule 8c's ramp-index check (#90 Track 2), which needs the
    # seeded DB to know how many ramps an agent has. Only unrunnable when a kit actually
    # binds one — otherwise every DB-less run over an unaffected corpus would report a
    # skip nobody can act on.
    if (
        "l0" in levels
        and L0_POTENTIAL_STATUS["bound_rows_seen"]
        and not L0_POTENTIAL_STATUS["ramps_available"]
    ):
        unrunnable.append("l0")
    return unrunnable


def _report_unrunnable(could_not_check: list[str]) -> None:
    """Explain a ``--require-db`` failure, and say exactly how to satisfy it.

    A gate that fails without naming the remedy gets bypassed, which for this one means
    dropping the flag — reopening the hole it exists to close.
    """
    if not could_not_check:
        return
    print(
        "\nMERGE GATE: --require-db was passed and "
        f"{', '.join(lvl.upper() for lvl in could_not_check)} could not check anything. "
        "A skip here is indistinguishable from a pass, so this run proves nothing about "
        "the levels most likely to catch a curation defect.\n"
        "Seed a real DB and re-run:\n"
        "    docker compose up -d db\n"
        "    python -m scripts.seed_db --skip-icons\n"
        "    python -m scripts.validate_kits --gate --require-db",
        file=sys.stderr,
    )


def _unrunnable_waiver_codes(levels: list[str]) -> set[str]:
    """Waiver codes whose level could not actually check anything on this run.

    A waiver for such a code must not be called stale: "couldn't check" is not
    "confirmed gone". L4 and L5 both need the real seeded app DB and skip cleanly
    without one; L5 has a second way of being unable to check, `attacks.param_name`
    NULL on every row, i.e. a DB migrated but never re-seeded (see :func:`check_l5`).

    Per-code rather than a blanket "switch the stale check off", so staleness stays
    enforced for every level that *did* run.

    Derived from :func:`unrunnable_levels` rather than restating the same two
    conditions, so "this is empty" and "that is empty" cannot drift apart.
    ``--require-db``'s reason for **not** switching this exemption off depends on
    exactly that equivalence: a *passing* ``--require-db`` run is one where
    :func:`unrunnable_levels` was empty, and therefore one where nothing here is
    exempt and staleness is fully enforced. Pinned by
    ``test_the_exemption_is_empty_exactly_when_require_db_would_pass``.
    """
    codes: set[str] = set()
    for level in unrunnable_levels(levels):
        if level == "l4":
            codes |= set(_L4_CODE_BY_CLASSIFICATION.values())
        elif level == "l5":
            codes |= L5_CODES
        elif level == "lr":
            codes |= LR_CODES
    return codes


def _print_lr_summary() -> None:
    """Coverage counts per entity type, when LR ran — the `--roster` report body."""
    if not LR_SUMMARY:
        return
    print("\nRoster coverage (LR):")
    for etype, s in LR_SUMMARY.items():
        print(
            f"  {etype}: {s['covered']}/{s['db']} curated, "
            f"{s['ledgered']} authorized not-modeled, {s['gaps']} gap(s)"
        )


def _parse_args() -> argparse.Namespace:
    """CLI surface, split from main() so the dispatch logic stays readable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--level",
        action="append",
        choices=sorted(LEVELS),
        help="layer(s) to run (default: all implemented)",
    )
    parser.add_argument(
        "--no-waivers",
        action="store_true",
        help="report known-issue waivers as failures too (shows the full debt)",
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument(
        "--gate",
        action="store_true",
        help=(
            "merge gate: also fail while any `branch_debt` waiver is open "
            "(upstream_blocked entries are expected to survive — see known_issues.json)"
        ),
    )
    parser.add_argument(
        "--require-db",
        action="store_true",
        help=(
            "fail instead of skipping when a DB-backed layer (L4/L5) cannot check; "
            "use wherever the run IS the gate, so 'could not check' can never read as a pass"
        ),
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="advance every clean 'audited' kit to 'verified' and write it back to disk",
    )
    parser.add_argument(
        "--roster",
        action="store_true",
        help=(
            "run only LR and print the roster coverage report — the post-reseed "
            "discovery step (DESIGN_kit_accuracy_gate.md D7); implies --require-db, "
            "because a coverage report against no DB reports nothing"
        ),
    )
    args = parser.parse_args()

    if args.roster:
        args.level = ["lr"]
        args.require_db = True
    return args


def main() -> int:
    """Run the requested validation layers over every curated modifier JSON."""
    args = _parse_args()

    kits = iter_kits()

    if args.promote:
        promoted = promote_kits(kits)
        by_path = {_rel(path): (path, kit) for path, kit in kits}
        for rel in promoted:
            path, kit = by_path[rel]
            path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n")
        print(
            f"Promoted {len(promoted)} kit(s) to 'verified'"
            + (f": {', '.join(sorted(promoted))}" if promoted else "")
        )
        return 0

    levels = args.level or sorted(LEVELS)
    findings: list[Finding] = []
    for level in levels:
        findings.extend(LEVELS[level](kits))

    waivers = {} if args.no_waivers else load_waivers()
    unwaived = [f for f in findings if f.key not in waivers]
    waived = [f for f in findings if f.key in waivers]

    # LD runs off the ledger rather than off a layer, so it is independent of `--level`.
    # `--no-waivers` drops the draft ledger too, on the same "show the full debt" reading:
    # with no entries, every draft kit reports as undocumented.
    blockers = {} if args.no_waivers else load_draft_blockers()
    draft_findings = check_draft_blockers(kits, blockers) + check_confidence_caps(kits, waived)
    stale_blockers = stale_draft_blockers(kits, blockers)
    unwaived += draft_findings

    # A waiver that no longer fires is stale — fail, so the list can't rot. Only
    # meaningful for a layer that actually ran: under `--level l0` the L1 entries
    # legitimately do not fire, and calling them stale would be a lie.
    #
    # L4 and L5 both need the real seeded app DB and skip cleanly without one, so their
    # waivers cannot fire either — and that absence is "couldn't check", not "resolved".
    # L5 has a second way of being unable to check: `param_name` NULL on every row, i.e.
    # a DB migrated but never re-seeded (see check_l5).
    #
    # The exclusion is per-code rather than a blanket switch-off of the whole check,
    # which is what this did before: a DB-less run reported *nothing* stale, so a stale
    # L0/L1/L2 waiver was invisible in exactly the CI lane meant to catch it. Narrowing
    # it keeps staleness enforced for every layer that did run.
    # `tests/unit/test_validate_kits_l0.py::test_no_stale_waivers` computes the same
    # exclusion against the same corpus, and test_validate_kits_l5 pins this branch.
    fired = {f.key for f in findings}
    # NOT switched off under --require-db, deliberately. The exemption and the flag reach
    # the same guarantee from opposite ends: --require-db fails the run outright when a
    # level could not check, so a *passing* --require-db run is one where every level ran
    # and the exemption is empty anyway — staleness is fully enforced exactly when it can
    # be. Dropping the exemption would only change what a *failing* run prints, and what
    # it would print is "STALE WAIVER (no longer fires, remove it)" for the ledger the
    # operator must not delete — the misleading advice 96d8f3a fixed.
    could_not_check = unrunnable_levels(levels)
    unrunnable_codes = _unrunnable_waiver_codes(levels)
    stale = (
        [
            key
            for key in waivers
            if key not in fired and key.split("|", 1)[0] not in unrunnable_codes
        ]
        if set(levels) == set(LEVELS)
        else []
    )

    # The merge gate counts only branch debt — see the module docstring and
    # known_issues.json's `classes` block for why upstream_blocked is excluded.
    open_debt = sorted(
        key
        for key, waiver in waivers.items()
        if waiver.get("class") == GATED_WAIVER_CLASS and key in fired
    )

    if args.json:
        print(
            json.dumps(
                {
                    "unwaived": [asdict(f) for f in unwaived],
                    "waived": [asdict(f) for f in waived],
                    "stale_waivers": stale,
                    "open_branch_debt": open_debt,
                    "estimated_values": find_estimated_values(kits),
                    "draft_kits": sorted(_draft_kits(kits)),
                    "draft_blockers": [blockers[key] for key in sorted(blockers)],
                    "stale_draft_blockers": stale_blockers,
                },
                indent=2,
            )
        )
    else:
        for finding in unwaived:
            print(
                f"{finding.level} {finding.code}: {finding.source_name} "
                f"[{finding.index}] {finding.label or finding.code}\n"
                f"    {finding.message}\n"
                f"    → {finding.source_file}"
            )
        _print_lr_summary()
        print(
            f"\n{len(kits)} kits checked ({', '.join(levels)}). "
            f"{len(unwaived)} failing, {len(waived)} waived "
            f"({len(open_debt)} open branch debt)."
        )
        estimated = find_estimated_values(kits)
        print(
            f"{len(estimated)} modifier(s) tagged 'estimated' (non-blocking, "
            f"DESIGN_remielle.md §9.2):"
        )
        for report in estimated:
            print(f"  {report}")
        print()
        for line in format_draft_report(kits, blockers):
            print(line)
        for key in stale:
            print(f"STALE WAIVER (no longer fires, remove it): {key}", file=sys.stderr)
        for key in stale_blockers:
            print(
                f"STALE DRAFT BLOCKER (kit is no longer 'draft', remove it): {key}",
                file=sys.stderr,
            )
        if args.gate and open_debt:
            print(
                "\nMERGE GATE: branch debt is still open — retire these before merging "
                "to dev (see known_issues.json):",
                file=sys.stderr,
            )
            for key in open_debt:
                print(f"  {key}", file=sys.stderr)

    _report_unrunnable(could_not_check if args.require_db else [])

    return (
        1
        if unwaived
        or stale
        or stale_blockers
        or (args.gate and open_debt)
        or (args.require_db and could_not_check)
        else 0
    )


if __name__ == "__main__":
    sys.exit(main())
