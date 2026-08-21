"""Load a Lumiflux agent's coefficients from its kit JSON into a
``LumifluxSpec`` (DESIGN_remielle.md §13.1, Task 28).

Why this is a separate module from ``lumiflux.py``: that one is *mechanism* —
pure, ORM-free, agent-agnostic, and guarded by Task 23's purity test. Kit-JSON
loading is policy. Putting it there would fail that test, and rightly.

Why a cached loader rather than a field on ``BuildSnapshot``: nothing in
``LumifluxSpec`` is build-derived. Live Anomaly Proficiency is deliberately read
at *sim* time (DESIGN §2.1's naming trap), so there is nothing to bake, and
baking would duplicate identical static state across every one of the
optimizer's thousands of per-disc-combination snapshots. The cache is keyed by
agent ``source_id`` (the ``hakushin_id``), process-wide, exactly like
``modifier_loader._cached_find_file``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.lumiflux import LumifluxSpec

logger = logging.getLogger(__name__)

# Same convention as `modifier_loader._DATA_DIR`, deliberately re-derived here
# rather than imported: importing a private name to save one line couples this
# module to that one's internals for no benefit.
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "modifiers"


class LumifluxBlockError(ValueError):
    """A kit JSON carries a `lumiflux` block that cannot become a spec.

    Distinct from "no block at all", which is the ordinary case for every
    non-Lumiflux agent and returns ``None``. A *present but broken* block is
    always a curation bug, and the one thing this module must never do is turn
    a missing coefficient into a zero — a Refringe coefficient of 0 is a
    plausible-looking number that silently deletes the agent's entire kit.
    """


class _LumifluxBlock(BaseModel):
    """Parse model for the kit JSON's `lumiflux` object.

    ``extra="forbid"`` is the point of using Pydantic here at all: an unknown
    key must be an error, not a silent drop (Task 20's lesson, and the same
    reason `validate_kits` L0 checks the key set independently — CI-time and
    runtime defenses, deliberately duplicated).

    Field list mirrors ``LumifluxSpec`` exactly; ``notes`` is the one permitted
    extra, prose for humans and never loaded.
    """

    model_config = ConfigDict(extra="forbid")

    point_cap: int
    voidflare_cap: int
    refringe_ap_ratio_bp: int
    refringe_flat_bonuses: dict[str, int]
    luminize_multipliers: dict[str, int]
    luminize_ap_bonus_bp: int
    phase_flow_tick_s: float
    phase_flow_duration_s: float
    flight_attack_points: tuple[int, ...]
    flight_attack_mv_bp: tuple[int, ...]
    flight_attack_daze_bp: tuple[int, ...]
    notes: str | None = None

    def to_spec(self) -> LumifluxSpec:
        """Build the frozen mechanism-layer spec."""
        data = self.model_dump(exclude={"notes"})
        return LumifluxSpec(**data)


def _find_agent_kit(source_id: str) -> Path | None:
    """The agent kit JSON claiming ``source_id``, or None.

    Sorted glob so the answer does not depend on filesystem enumeration order.
    Unlike ``modifier_loader._find_file_by_source_id`` this does not need to
    handle the multi-match case specially — the kit corpus is guarded against
    duplicate ``(source_type, source_id)`` pairs, and if two files ever did
    claim one id the modifier loader would already have raised long before
    anything asked for a Lumiflux spec.
    """
    agents_dir = _DATA_DIR / "agents"
    if not agents_dir.is_dir():
        return None
    for path in sorted(agents_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("source_id") == source_id:
            return path
    return None


@lru_cache(maxsize=64)
def load_lumiflux_spec(source_id: str) -> LumifluxSpec | None:
    """The ``LumifluxSpec`` for the agent with this ``hakushin_id``, or None.

    ``None`` means "this agent has no Lumiflux block" — the ordinary answer for
    every agent in the game but a Lumiflux one, and for an id no kit JSON
    claims. It is *not* used to signal a broken block: that raises
    ``LumifluxBlockError``, because a partial block means a coefficient is
    missing and the alternative to raising is a silent zero.

    Cached process-wide by ``source_id``. The optimizer calls this once per
    pipeline run rather than once per candidate build, but the cache means even
    a caller that forgets pays a dict lookup rather than a directory scan.
    """
    if not source_id:
        return None
    path = _find_agent_kit(source_id)
    if path is None:
        return None
    try:
        block = json.loads(path.read_text()).get("lumiflux")
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - unreadable kit
        raise LumifluxBlockError(f"{path.name}: kit JSON is unreadable — {exc}") from exc
    if block is None:
        return None
    try:
        return _LumifluxBlock.model_validate(block).to_spec()
    except ValidationError as exc:
        raise LumifluxBlockError(
            f"{path.name}: `lumiflux` block is not a complete LumifluxSpec — {exc}. "
            "A missing coefficient must not become a zero; fix the kit JSON "
            "(validate_kits --level l0 names the offending key)."
        ) from exc
