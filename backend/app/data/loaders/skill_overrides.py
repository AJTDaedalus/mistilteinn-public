"""Loader for skill-override JSON files (sequential / variant curation)."""

import json
import logging
from pathlib import Path

from pydantic import BaseModel, model_validator

from app.models.enums import HitMode, RowCondition

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent / "skill_overrides"


class SyntheticFields(BaseModel):
    """Explicit column values for a variant row that nanoka does not import.

    Required: damage_base, damage_growth.
    Optional: stun_base, stun_growth, energy_gain, anomaly_buildup (default 0).
    All other fields (agent_id, name, skill_key, element, hakushin_skill_id)
    are cloned from the first existing Attack row for that move.
    """

    damage_base: int
    damage_growth: int
    stun_base: int = 0
    stun_growth: int = 0
    energy_gain: int = 0
    anomaly_buildup: int = 0


class VariantSpec(BaseModel):
    """One context-variant within a VARIANT move.

    Exactly one of ``hit_indices`` or ``fields`` must be provided:
    - ``hit_indices``: indices into the existing (imported) Attack rows to
      assign to this variant label.
    - ``fields``: explicit column values for a synthetic row that the importer
      does not produce (e.g. a sub-maximum sword-count variant whose multiplier
      is absent from the source API).
    """

    label: str
    hit_indices: list[int] | None = None
    fields: SyntheticFields | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> "VariantSpec":
        """Reject specs that give both or neither of ``hit_indices``/``fields``."""
        has_indices = self.hit_indices is not None and len(self.hit_indices) > 0
        has_fields = self.fields is not None
        if has_indices == has_fields:
            raise ValueError(
                "VariantSpec must have exactly one of 'hit_indices' or 'fields',"
                " not both or neither"
            )
        return self


class MoveOverride(BaseModel):
    """Curation override for one agent move: hit-grouping mode plus optional variants."""

    hit_mode: HitMode
    variants: list[VariantSpec] | None = None
    # Per-row runtime gates (D-CH5): ``param_name`` -> :class:`RowCondition` value. Keyed by
    # `param_name`, not `hit_index`, for the same reason `ChannelSpec.roles` is: row counts and
    # orderings move across re-seeds -- this repo's own move files carry notes documenting exactly
    # that drift -- while the label is the stable semantic handle. Rows not listed stay
    # unconditional, so an absent entry can never *hide* a row; the failure mode of a typo is a
    # row that keeps firing, which LCH catches, rather than a row that silently vanishes.
    row_conditions: dict[str, RowCondition] | None = None
    # Rows to lift OUT of this move into a move of their own (D-CH6): ``param_name`` -> new
    # move name. For a row whose trigger the engine cannot evaluate at all -- Trigger's
    # ``Counter``, which fires on an automatic Perfect Dodge, i.e. on the ENEMY attacking --
    # so it is neither a channel role nor a `select_when` state, but something the player
    # knows and can put in a rotation deliberately.
    #
    # This is the only override that mutates ``attacks.name``, and a move name is what L4
    # validates and what saved combos reference. Hence the validator below: a split must
    # produce a distinct name, and must not collide with the move it is split from.
    split_moves: dict[str, str] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_split_moves(self) -> "MoveOverride":
        """A split must rename to something distinct, and not to two different rows' targets."""
        if not self.split_moves:
            return self
        targets = list(self.split_moves.values())
        for target in targets:
            if not target or not target.strip():
                raise ValueError("split_moves target name must be non-empty")
        if len(set(targets)) != len(targets):
            raise ValueError(
                f"split_moves sends two rows to the same move name ({sorted(targets)}) — "
                "that silently merges them; give each split its own name"
            )
        return self

    @model_validator(mode="after")
    def validate_variant_spec(self) -> "MoveOverride":
        """Require variants for VARIANT mode, with no ``hit_index`` reused across variants."""
        if self.hit_mode == HitMode.VARIANT:
            if not self.variants:
                raise ValueError("variant move must declare at least one variant")
            all_indices: list[int] = []
            for spec in self.variants:
                for idx in spec.hit_indices or []:
                    if idx in all_indices:
                        raise ValueError(f"hit_index {idx} appears in more than one variant spec")
                    all_indices.append(idx)
        return self


class AgentOverride(BaseModel):
    """Top-level skill-override document for one agent: move key to :class:`MoveOverride` map."""

    agent_name: str
    moves: dict[str, MoveOverride]


def _looks_like_codename(agent_name: str) -> bool:
    """Heuristic, DB-free proxy for "is this a raw Dimbreath internal codename?".

    Unlike ``moves/agents/``, the filename stem here is legitimately a codename
    (e.g. ``avatar_female_size01_norma.json``) — that is not the binding key.
    ``agent_name`` is: ``apply_skill_overrides`` resolves it against ``agents.name``
    at seed time, and a codename value binds to nothing there. Every one of the 51
    correctly-bound display names in this directory uses spaces/hyphens, never an
    underscore — the same signal a Dimbreath codename (``Avatar_Female_Size01_Norma``)
    always carries. This is only a heuristic: the authoritative, DB-backed check
    ("does this resolve to a real ``agents.name``?") is validate_kits L4.
    """
    return "_" in agent_name


def load_skill_overrides(
    directory: Path | None = None,
) -> dict[str, AgentOverride]:
    """Load all skill-override JSON files from *directory* (defaults to app/data/skill_overrides/).

    Returns a dict keyed by lowercase filename stem (e.g. "ye_shunguang").

    Logs (does not raise) when ``agent_name`` looks like a Dimbreath codename rather
    than a display name — the loader stays tolerant of currently-known-bad files
    (tracked as branch debt in ``known_issues.json``, gated by validate_kits L4) so it
    keeps working for tooling that reads every file, e.g. the audit script and
    ``seed_db.py``, while those files are fixed.
    """
    directory = directory or _DEFAULT_DIR
    result: dict[str, AgentOverride] = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        override = AgentOverride.model_validate(data)
        if _looks_like_codename(override.agent_name):
            logger.warning(
                "%s: agent_name %r looks like a Dimbreath internal codename, not a "
                "display name. It must match agents.name exactly (e.g. 'Norma', not "
                "'Avatar_Female_Size01_Norma') or apply_skill_overrides will silently "
                "skip it at seed time.",
                path.name,
                override.agent_name,
            )
        result[path.stem.lower()] = override
    return result
