"""Unit tests for combo_step_resolver — T-B1: step_type discriminator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.combo_step_resolver import resolve_combo_step
from app.services.combo_types import ComboStep, StunEndStep, StunTriggerStep
from app.services.modifiers import AttackScope


def _build(agent_id: str = "agent-1", skill_levels: str = "12,12,12,12,12"):
    from unittest.mock import MagicMock

    b = MagicMock()
    b.agent_id = agent_id
    b.skill_levels = skill_levels
    # A real int: PotentialVariant.for_rank compares it (#90), and a MagicMock
    # would raise rather than select a variant.
    b.potential_rank = 5
    return b


def _attack(
    id: str = "att-1",
    name: str = "Basic Attack 1",
    skill_key: str = "Basic",
    element: str = "ice",
):
    from unittest.mock import MagicMock

    a = MagicMock()
    a.id = id
    a.name = name
    a.skill_key = skill_key
    a.element = element
    a.damage_growth = []
    return a


class TestStepTypeDiscriminator:
    """T-B1: new step_type field routes raw entries to correct step types."""

    @pytest.mark.asyncio
    async def test_missing_step_type_defaults_to_attack(self):
        """Existing row format (no step_type) resolves identically to before."""
        raw = {"attack_id": "att-1", "label": "BA1"}
        attack = _attack()
        repo = AsyncMock()
        repo.get_by_id.return_value = attack
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert len(result) == 1
        assert isinstance(result[0], ComboStep)
        assert result[0].label == "BA1"
        assert result[0].attack_id == "att-1"

    @pytest.mark.asyncio
    async def test_explicit_attack_step_type(self):
        """step_type='attack' is the same as the legacy format."""
        raw = {"step_type": "attack", "attack_id": "att-1", "label": "BA1"}
        attack = _attack()
        repo = AsyncMock()
        repo.get_by_id.return_value = attack
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert len(result) == 1
        assert isinstance(result[0], ComboStep)

    @pytest.mark.asyncio
    async def test_stun_trigger_step_type(self):
        """step_type='stun_trigger' returns a StunTriggerStep without DB lookup."""
        raw = {"step_type": "stun_trigger", "label": "Stun"}
        repo = AsyncMock()
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert len(result) == 1
        assert isinstance(result[0], StunTriggerStep)
        assert result[0].label == "Stun"
        repo.get_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_stun_trigger_default_label(self):
        """step_type='stun_trigger' with no label uses default."""
        raw = {"step_type": "stun_trigger"}
        repo = AsyncMock()
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert isinstance(result[0], StunTriggerStep)
        assert result[0].label == "Stun"

    @pytest.mark.asyncio
    async def test_stun_end_step_type(self):
        """step_type='stun_end' returns a StunEndStep without DB lookup."""
        raw = {"step_type": "stun_end", "label": "Stun End"}
        repo = AsyncMock()
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert len(result) == 1
        assert isinstance(result[0], StunEndStep)
        assert result[0].label == "Stun End"
        repo.get_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_stun_end_default_label(self):
        raw = {"step_type": "stun_end"}
        repo = AsyncMock()
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert isinstance(result[0], StunEndStep)
        assert result[0].label == "Stun End"

    @pytest.mark.asyncio
    async def test_resolve_sequence_mixed(self):
        """resolve_combo_sequence handles a mixed sequence end-to-end."""
        from app.services.combo_step_resolver import resolve_combo_sequence

        raw_seq = [
            {"attack_id": "att-1", "label": "BA1"},
            {"step_type": "stun_trigger"},
            {"attack_id": "att-1", "label": "Chain"},
            {"step_type": "stun_end"},
        ]
        attack = _attack()
        repo = AsyncMock()
        repo.get_by_id.return_value = attack
        result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
        assert len(result) == 4
        assert isinstance(result[0], ComboStep)
        assert isinstance(result[1], StunTriggerStep)
        assert isinstance(result[2], ComboStep)
        assert isinstance(result[3], StunEndStep)


class TestResolverState:
    """T-B2: _ResolverState dataclass and sequence walker."""

    def test_resolver_state_defaults(self):
        from app.services.combo_step_resolver import _ResolverState

        state = _ResolverState()
        assert state.prev_attack_key is None
        assert state.prev_was_single_tap is False
        assert state.prev_cycle_position == -1

    @pytest.mark.asyncio
    async def test_atomic_step_resets_state(self):
        """After an atomic move step, prev_attack_key should be None."""
        from app.models.enums import HitMode
        from app.services.combo_step_resolver import _resolve_one, _ResolverState

        raw = {"move_name": "Basic Attack", "label": "B1"}
        attack = _attack(name="Basic Attack")
        attack.hit_mode = HitMode.ATOMIC
        attack.variant_label = None
        repo = AsyncMock()
        repo.get_by_agent_and_name.return_value = [attack]
        _, state = await _resolve_one(
            raw, state=_ResolverState(), build=_build(), attack_repo=repo
        )
        assert state.prev_attack_key is None

    @pytest.mark.asyncio
    async def test_marker_does_not_change_state(self):
        """stun_trigger marker step must not reset prev_attack_key."""
        from app.services.combo_step_resolver import _resolve_one, _ResolverState

        initial_state = _ResolverState(
            prev_attack_key=("Basic", "Basic Attack: Swiftedge"),
            prev_was_single_tap=True,
            prev_cycle_position=1,
        )
        raw = {"step_type": "stun_trigger", "label": "Stun"}
        repo = AsyncMock()
        _, state = await _resolve_one(raw, state=initial_state, build=_build(), attack_repo=repo)
        assert state.prev_attack_key == ("Basic", "Basic Attack: Swiftedge")
        assert state.prev_was_single_tap is True
        assert state.prev_cycle_position == 1


class TestPerOwnerAgentId:
    """T-B3: agent_id threaded through ComboStep; per-owner sequential state."""

    @pytest.mark.asyncio
    async def test_default_step_carries_dps_agent_id(self):
        """A step with no agent_id field produces ComboStep.agent_id == 'dps'."""
        raw = {"attack_id": "att-1", "label": "BA"}
        attack = _attack()
        repo = AsyncMock()
        repo.get_by_id.return_value = attack
        result = await resolve_combo_step(raw, build=_build(), attack_repo=repo)
        assert isinstance(result[0], ComboStep)
        assert result[0].agent_id == "dps"

    @pytest.mark.asyncio
    async def test_support1_step_carries_support1_agent_id(self):
        """A step with agent_id='support1' produces ComboStep.agent_id == 'support1'."""
        from app.services.combo_step_resolver import resolve_combo_sequence

        support_build = _build(agent_id="support-agent-99")
        raw_seq = [{"attack_id": "att-sup", "label": "Sup", "agent_id": "support1"}]
        attack = _attack(id="att-sup")
        repo = AsyncMock()
        repo.get_by_id.return_value = attack
        result = await resolve_combo_sequence(
            raw_seq,
            build=_build(),
            attack_repo=repo,
            member_builds={"support1": support_build},
        )
        assert len(result) == 1
        assert isinstance(result[0], ComboStep)
        assert result[0].agent_id == "support1"

    @pytest.mark.asyncio
    async def test_uuid_owned_move_step_resolves_against_owner_build(self):
        """A step tagged with a member build UUID resolves its move on that
        member's agent — not the primary build's agent.

        Regression: the team /calculate path passes member_builds keyed by build
        UUID. Resolving a support-owned move against the primary agent used to
        404 because the move only exists on the support's agent.
        """
        from app.models.enums import HitMode
        from app.services.combo_step_resolver import resolve_combo_sequence

        sup_uuid = "sup-build-uuid"
        primary_build = _build(agent_id="primary-agent")
        support_build = _build(agent_id="support-agent")

        sup_attack = _attack(id="sup-att", name="SupportSkill")
        sup_attack.hit_mode = HitMode.ATOMIC
        sup_attack.variant_label = None

        repo = AsyncMock()

        async def _get_by_agent_and_name(agent_id, name, variant):
            # SupportSkill only exists on the support's agent.
            if agent_id == "support-agent" and name == "SupportSkill":
                return [sup_attack]
            return []

        repo.get_by_agent_and_name.side_effect = _get_by_agent_and_name

        raw_seq = [{"move_name": "SupportSkill", "label": "S1", "agent_id": sup_uuid}]
        result = await resolve_combo_sequence(
            raw_seq,
            build=primary_build,
            attack_repo=repo,
            member_builds={sup_uuid: support_build},
        )
        assert len(result) == 1
        assert isinstance(result[0], ComboStep)
        assert result[0].attack_id == "sup-att"
        assert result[0].agent_id == sup_uuid

    @pytest.mark.asyncio
    async def test_sequential_per_owner_state_not_reset_by_foreign_step(self):
        """A's sequential cycle is NOT reset when B's atomic step is interleaved.

        Sequence:
          Step 1 — A presses sequential move (pos=0)
          Step 2 — B presses an atomic step (would reset state in old code)
          Step 3 — A presses sequential move again → should be pos=1, not pos=0
        """
        from app.models.enums import HitMode
        from app.services.combo_step_resolver import resolve_combo_sequence

        # Two sequential hits for agent A: hit_index 0 and 1
        seq_hit0 = _attack(id="seq-0", name="Swiftedge")
        seq_hit0.hit_mode = HitMode.SEQUENTIAL
        seq_hit0.hit_index = 0
        seq_hit0.variant_label = None

        seq_hit1 = _attack(id="seq-1", name="Swiftedge")
        seq_hit1.hit_mode = HitMode.SEQUENTIAL
        seq_hit1.hit_index = 1
        seq_hit1.variant_label = None

        # Atomic step for agent B
        atomic_hit = _attack(id="b-atk", name="Support Skill")
        atomic_hit.hit_mode = HitMode.ATOMIC
        atomic_hit.variant_label = None

        support_build = _build(agent_id="support-b")

        repo = AsyncMock()

        async def _get_by_agent_and_name(agent_id, name, variant):
            if name == "Swiftedge":
                return [seq_hit0, seq_hit1]
            return [atomic_hit]

        repo.get_by_agent_and_name.side_effect = _get_by_agent_and_name

        raw_seq = [
            {"move_name": "Swiftedge", "label": "A1"},           # A: pos=0
            {"move_name": "Support Skill", "label": "B1", "agent_id": "support1"},  # B: atomic
            {"move_name": "Swiftedge", "label": "A2"},           # A: pos=1 (not reset)
        ]
        result = await resolve_combo_sequence(
            raw_seq,
            build=_build(),
            attack_repo=repo,
            member_builds={"support1": support_build},
        )
        # All 3 raw steps resolve to 1 ComboStep each
        assert len(result) == 3
        # A's first press → seq_hit0 (hit_index=0)
        assert result[0].attack_id == "seq-0"
        # B's atomic step → atomic_hit
        assert result[1].attack_id == "b-atk"
        assert result[1].agent_id == "support1"
        # A's second press → seq_hit1 (hit_index=1), cycle advanced
        assert result[2].attack_id == "seq-1"
        assert result[2].agent_id == "dps"


class TestEXSpecialUltimateScope:
    """T-13.5b: EXSpecial and Ultimate skill_key resolve to the correct AttackScope.

    Pin test: once 13.5a reclassifies DB rows, the stateless path must route
    EXSpecial attacks to AttackScope.EX_SPECIAL so scope-gated modifiers (e.g.
    Yanagi M6 +80% DMG on EX) are not silently dropped.
    """

    def test_exspecial_maps_to_ex_special_scope(self):
        from app.services.combo_step_resolver import _SKILL_KEY_TO_SCOPE

        assert _SKILL_KEY_TO_SCOPE["EXSpecial"] == AttackScope.EX_SPECIAL

    def test_ultimate_maps_to_ultimate_scope(self):
        from app.services.combo_step_resolver import _SKILL_KEY_TO_SCOPE

        assert _SKILL_KEY_TO_SCOPE["Ultimate"] == AttackScope.ULTIMATE

    def test_special_still_maps_to_special_scope(self):
        from app.services.combo_step_resolver import _SKILL_KEY_TO_SCOPE

        assert _SKILL_KEY_TO_SCOPE["Special"] == AttackScope.SPECIAL

    def test_exspecial_modifier_applied_at_ex_special_scope(self):
        """A modifier scoped to ex_special is included when attack_scope=EX_SPECIAL,
        and excluded when attack_scope=SPECIAL — locks the M6 regression fix."""
        from app.services.buff_resolver import resolve_modifiers
        from app.services.modifiers import (
            ActiveConditions,
            Condition,
            Modifier,
            ModifierSource,
            ModifierTarget,
        )

        m6_mod = Modifier(
            stat="dmg_bonus",
            value=8000,  # 4 stacks × 2000bp = 80%
            source=ModifierSource.MINDSCAPE,
            source_label="M6: EX Special DMG stacks",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.EX_SPECIAL,),
        )
        conditions = ActiveConditions(active={Condition.ALWAYS})

        # With EX_SPECIAL scope — modifier must be applied
        result_ex = resolve_modifiers(
            [m6_mod],
            conditions,
            attack_scope=AttackScope.EX_SPECIAL,
        )
        assert sum(result_ex.dmg_bonuses) == 8000

        # With SPECIAL scope — modifier must be excluded (old folding bug)
        result_sp = resolve_modifiers(
            [m6_mod],
            conditions,
            attack_scope=AttackScope.SPECIAL,
        )
        assert sum(result_sp.dmg_bonuses) == 0


class TestDashVsDodgeCounterScope:
    """Task 17 Batch 6 audit finding: the DB has one skill_key ("Dodge") for
    both Dash Attack and Dodge Counter — they were only ever distinguishable
    by name prefix, and the resolver used to hand both AttackScope.DODGE_COUNTER
    unconditionally, making every dash-scoped modifier corpus-wide unreachable
    via this path."""

    def test_dodge_counter_prefix_maps_to_dodge_counter_scope(self):
        from app.services.combo_step_resolver import scope_for_skill_key

        assert (
            scope_for_skill_key("Dodge", "Dodge Counter: Ceremony of Swordlight")
            == AttackScope.DODGE_COUNTER
        )

    def test_dash_attack_prefix_maps_to_dash_scope(self):
        from app.services.combo_step_resolver import scope_for_skill_key

        assert scope_for_skill_key("Dodge", "Dash Attack: Taser Blast") == AttackScope.DASH

    def test_unprefixed_dodge_skill_key_defaults_to_dash(self):
        # Harumasa's "Chasing Thunder" carries neither prefix but is a Dash
        # Attack per ZO char/util.ts:271.
        from app.services.combo_step_resolver import scope_for_skill_key

        assert scope_for_skill_key("Dodge", "Chasing Thunder") == AttackScope.DASH

    def test_attack_to_step_resolves_dash_scope(self):
        attack = _attack(name="Dash Attack: Taser Blast", skill_key="Dodge")
        from app.services.combo_step_resolver import _attack_to_step

        step = _attack_to_step(attack, build=_build(), label="dash")
        assert step.scope == AttackScope.DASH
