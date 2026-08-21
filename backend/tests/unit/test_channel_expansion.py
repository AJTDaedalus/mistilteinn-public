"""Channel expansion in the combo step resolver — TASKS_channeled_moves.md Task 9.

Covers `_resolve_channel`: entry rows once, tick rows `round(channel_s / tick_s)` times at
the scaled multiplier, release rows once — and the two `tick_mv_basis` readings, which
differ by the whole channel length (DESIGN_channeled_moves.md §4.3).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data.loaders.moves import ChannelSpec, MoveBuildupSpec
from app.models.enums import HitMode
from app.services import combo_step_resolver as csr
from app.services.combo_step_resolver import resolve_combo_sequence

BURNICE_EX = "EX Special Attack: Intense Heat Stirring Method"


def _build(agent_id: str = "agent-1") -> MagicMock:
    b = MagicMock()
    b.potential_rank = 5
    b.agent_id = agent_id
    b.skill_levels = "12,12,12,12,12"
    return b


def _attack(
    *,
    hit_index: int,
    param_name: str,
    name: str = BURNICE_EX,
    skill_key: str = "EXSpecial",
    variant_label: str | None = None,
    damage_base: int = 10_000,
    anomaly_buildup: int = 0,
) -> MagicMock:
    a = MagicMock()
    a.id = f"att-{hit_index}"
    a.hit_index = hit_index
    a.name = name
    a.skill_key = skill_key
    a.hit_mode = HitMode.CHANNEL
    a.variant_label = variant_label
    a.param_name = param_name
    a.element = "fire"
    a.damage_base = damage_base
    a.damage_growth = 0
    a.stun_base = 0
    a.stun_growth = 0
    a.energy_gain = 0
    a.anomaly_buildup = anomaly_buildup
    return a


def _repo_for(attacks: list[MagicMock]) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = attacks
    return repo


def _spec(**over) -> ChannelSpec:
    base = {
        "min_s": 0.0,
        "max_s": 4.0,
        "default_s": 2.0,
        "tick_s": 0.5,
        "tick_mv_basis": "whole_channel",
        "nominal_s": 2.5,
        "roles": {
            "Continuous Spray DMG Multiplier": "tick",
            "Fire Blast DMG Multiplier": "release",
        },
    }
    base.update(over)
    return ChannelSpec(**base)


def _burnice_rows() -> list[MagicMock]:
    return [
        _attack(hit_index=0, param_name="Continuous Spray DMG Multiplier", damage_base=100_000),
        _attack(hit_index=1, param_name="Fire Blast DMG Multiplier", damage_base=30_000),
    ]


@pytest.fixture
def bind_spec(monkeypatch):
    """Bind a channelled move spec for (agent, move) without touching the committed files."""

    def _bind(
        spec: ChannelSpec | None, move_name: str = BURNICE_EX, tail_s: float = 0.0
    ) -> None:
        move = (
            MoveBuildupSpec(duration_s=tail_s, channel=spec) if spec is not None else None
        )

        def fake(agent_id: str, name: str) -> MoveBuildupSpec | None:
            return move if name == move_name else None

        monkeypatch.setattr(csr, "_channel_move_for", fake)

    return _bind


# ---- core expansion -------------------------------------------------------


@pytest.mark.asyncio
async def test_whole_channel_expansion(bind_spec) -> None:
    """2.0s at 0.5s cadence = 4 tick hits + 1 release; ticks scaled tick_s/nominal_s."""
    bind_spec(_spec())
    warnings: list[str] = []
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 2.0}],
        build=_build(),
        attack_repo=_repo_for(_burnice_rows()),
        warnings=warnings,
    )
    assert len(steps) == 5
    ticks = [s for s in steps if s.attack_id == "att-0"]
    release = [s for s in steps if s.attack_id == "att-1"]
    assert len(ticks) == 4
    assert len(release) == 1
    # 100_000 * (0.5 / 2.5) = 20_000 per tick
    assert [s.multiplier for s in ticks] == [20_000] * 4
    # release is untouched by the hold length
    assert release[0].multiplier == 30_000
    assert warnings == []


@pytest.mark.asyncio
async def test_whole_channel_at_nominal_recovers_the_row_total(bind_spec) -> None:
    """Held for exactly nominal_s, the tick rows sum back to the authored figure."""
    bind_spec(_spec())
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 2.5}],
        build=_build(),
        attack_repo=_repo_for(_burnice_rows()),
    )
    ticks = [s for s in steps if s.attack_id == "att-0"]
    assert len(ticks) == 5
    assert sum(s.multiplier for s in ticks) == 100_000


@pytest.mark.asyncio
async def test_per_second_basis_scales_by_tick_length_only(bind_spec) -> None:
    bind_spec(_spec(tick_mv_basis="per_second", nominal_s=None, tick_s=1.0, max_s=6.0))
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 3.0}],
        build=_build(),
        attack_repo=_repo_for(_burnice_rows()),
    )
    ticks = [s for s in steps if s.attack_id == "att-0"]
    assert len(ticks) == 3
    assert [s.multiplier for s in ticks] == [100_000] * 3


@pytest.mark.asyncio
async def test_zero_length_channel_emits_entry_and_release_only(bind_spec) -> None:
    rows = [
        _attack(hit_index=9, param_name="Ignition DMG Multiplier", damage_base=5_000),
        *_burnice_rows(),
    ]
    bind_spec(
        _spec(
            roles={
                "Ignition DMG Multiplier": "entry",
                "Continuous Spray DMG Multiplier": "tick",
                "Fire Blast DMG Multiplier": "release",
            }
        )
    )
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 0.0}],
        build=_build(),
        attack_repo=_repo_for(rows),
    )
    assert [s.attack_id for s in steps] == ["att-9", "att-1"]


@pytest.mark.asyncio
async def test_entry_fires_once_regardless_of_hold(bind_spec) -> None:
    rows = [
        _attack(hit_index=9, param_name="Ignition DMG Multiplier", damage_base=5_000),
        *_burnice_rows(),
    ]
    bind_spec(
        _spec(
            roles={
                "Ignition DMG Multiplier": "entry",
                "Continuous Spray DMG Multiplier": "tick",
                "Fire Blast DMG Multiplier": "release",
            }
        )
    )
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 4.0}],
        build=_build(),
        attack_repo=_repo_for(rows),
    )
    entries = [s for s in steps if s.attack_id == "att-9"]
    assert len(entries) == 1
    assert entries[0].multiplier == 5_000
    # entry first, ticks in the middle, release last
    assert steps[0].attack_id == "att-9"
    assert steps[-1].attack_id == "att-1"
    assert len([s for s in steps if s.attack_id == "att-0"]) == 8


@pytest.mark.asyncio
async def test_tick_buildup_scales_with_the_multiplier(bind_spec) -> None:
    """Gauge must not be applied in full once per tick — that is an n_ticks× over-count."""
    rows = [
        _attack(
            hit_index=0,
            param_name="Continuous Spray DMG Multiplier",
            damage_base=100_000,
            anomaly_buildup=5_000,
        ),
        _attack(hit_index=1, param_name="Fire Blast DMG Multiplier", anomaly_buildup=1_200),
    ]
    bind_spec(_spec())
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 2.5}],
        build=_build(),
        attack_repo=_repo_for(rows),
    )
    ticks = [s for s in steps if s.attack_id == "att-0"]
    assert sum(s.anomaly_buildup for s in ticks) == 5_000
    release = next(s for s in steps if s.attack_id == "att-1")
    assert release.anomaly_buildup == 1_200


# ---- composition with variant --------------------------------------------


@pytest.mark.asyncio
async def test_variant_label_selects_one_warhead(bind_spec) -> None:
    """Norma archetype: the label picks the trio, then the hold scales that trio's tick row."""
    rows = [
        _attack(
            hit_index=0,
            param_name="Continuous Spray DMG Multiplier",
            variant_label="Warhead A",
            damage_base=100_000,
        ),
        _attack(
            hit_index=1,
            param_name="Fire Blast DMG Multiplier",
            variant_label="Warhead A",
            damage_base=30_000,
        ),
        _attack(
            hit_index=2,
            param_name="Continuous Spray DMG Multiplier",
            variant_label="Warhead B",
            damage_base=200_000,
        ),
        _attack(
            hit_index=3,
            param_name="Fire Blast DMG Multiplier",
            variant_label="Warhead B",
            damage_base=60_000,
        ),
    ]
    bind_spec(_spec())
    steps = await resolve_combo_sequence(
        [
            {
                "move_name": BURNICE_EX,
                "label": "EX",
                "channel_s": 2.5,
                "variant_label": "Warhead B",
            }
        ],
        build=_build(),
        attack_repo=_repo_for(rows),
    )
    assert {s.attack_id for s in steps} == {"att-2", "att-3"}
    ticks = [s for s in steps if s.attack_id == "att-2"]
    assert len(ticks) == 5
    assert sum(s.multiplier for s in ticks) == 200_000


@pytest.mark.asyncio
async def test_missing_variant_label_on_a_channel_defaults_and_warns(bind_spec) -> None:
    rows = [
        _attack(
            hit_index=0,
            param_name="Continuous Spray DMG Multiplier",
            variant_label="Warhead B",
        ),
        _attack(
            hit_index=1,
            param_name="Continuous Spray DMG Multiplier",
            variant_label="Warhead A",
        ),
    ]
    bind_spec(_spec(roles={"Continuous Spray DMG Multiplier": "tick"}))
    warnings: list[str] = []
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 0.5}],
        build=_build(),
        attack_repo=_repo_for(rows),
        warnings=warnings,
    )
    # sorted labels -> "Warhead A" wins the default
    assert {s.attack_id for s in steps} == {"att-1"}
    assert any("variant_label" in w for w in warnings)


# ---- degraded / missing data ---------------------------------------------


@pytest.mark.asyncio
async def test_missing_channel_s_uses_default_and_warns(bind_spec) -> None:
    bind_spec(_spec())
    warnings: list[str] = []
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX"}],
        build=_build(),
        attack_repo=_repo_for(_burnice_rows()),
        warnings=warnings,
    )
    # default_s = 2.0 at 0.5s cadence -> 4 ticks
    assert len([s for s in steps if s.attack_id == "att-0"]) == 4
    assert any("channel_s" in w for w in warnings)


@pytest.mark.asyncio
async def test_unauthored_channel_spec_degrades_to_atomic_and_warns(bind_spec) -> None:
    """hit_mode='channel' in the DB with no authored spec: fire each row once, loudly."""
    bind_spec(None)
    warnings: list[str] = []
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 2.0}],
        build=_build(),
        attack_repo=_repo_for(_burnice_rows()),
        warnings=warnings,
    )
    assert [s.attack_id for s in steps] == ["att-0", "att-1"]
    assert any("no channel spec" in w for w in warnings)


@pytest.mark.asyncio
async def test_unmapped_param_name_fires_once_and_warns(bind_spec) -> None:
    rows = [
        *_burnice_rows(),
        _attack(hit_index=2, param_name="Mystery DMG Multiplier", damage_base=7_000),
    ]
    bind_spec(_spec())
    warnings: list[str] = []
    steps = await resolve_combo_sequence(
        [{"move_name": BURNICE_EX, "label": "EX", "channel_s": 0.5}],
        build=_build(),
        attack_repo=_repo_for(rows),
        warnings=warnings,
    )
    mystery = [s for s in steps if s.attack_id == "att-2"]
    assert len(mystery) == 1
    assert mystery[0].multiplier == 7_000
    assert any("Mystery DMG Multiplier" in w for w in warnings)


@pytest.mark.asyncio
async def test_channel_step_does_not_disturb_sequential_state(bind_spec) -> None:
    """A channel press is a move press: it must reset another move's sequential cycle."""
    bind_spec(_spec())
    seq = [
        _attack(hit_index=i, param_name=f"p{i}", name="Basic Attack: Swiftedge", skill_key="Basic")
        for i in range(3)
    ]
    for a in seq:
        a.hit_mode = HitMode.SEQUENTIAL

    repo = AsyncMock()

    async def by_name(agent_id, name, potential):
        return seq if name == "Basic Attack: Swiftedge" else _burnice_rows()

    repo.get_by_agent_and_name.side_effect = by_name
    steps = await resolve_combo_sequence(
        [
            {"move_name": "Basic Attack: Swiftedge", "label": "B1"},
            {"move_name": BURNICE_EX, "label": "EX", "channel_s": 0.5},
            {"move_name": "Basic Attack: Swiftedge", "label": "B2"},
        ],
        build=_build(),
        attack_repo=repo,
    )
    basics = [s for s in steps if s.attack_name == "Basic Attack: Swiftedge"]
    assert [s.attack_id for s in basics] == ["att-0", "att-0"]
