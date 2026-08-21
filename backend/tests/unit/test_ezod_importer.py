"""Unit tests for ezod_importer — parse_ezod_payload, key resolvers, build draft."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.data.importers.ezod_importer import (
    _AGENT_ALIASES,
    _WENGINE_ALIASES,
    MAX_CHAR_COUNT,
    MAX_DISC_COUNT,
    MAX_WEAPON_COUNT,
    BuildDraft,
    _normalize_key,
    build_draft_from_character,
    disc_slots_for_character,
    parse_ezod_payload,
    resolve_agent_key,
    resolve_wengine_key,
)


def _ezod(**kw) -> dict:
    base: dict = {
        "format": "eZOD",
        "version": 1,
        "source": "Youkai",
        "characters": [],
        "weapons": [],
        "discs": [],
    }
    base.update(kw)
    return base


# ---- parse_ezod_payload -------------------------------------------------------


class TestParseEzodPayload:
    def test_accepts_valid_ezod(self):
        data = parse_ezod_payload(_ezod())
        assert data["format"] == "eZOD"
        assert data["characters"] == []
        assert data["discs"] == []

    def test_accepts_string_payload(self):
        data = parse_ezod_payload(json.dumps(_ezod()))
        assert data["format"] == "eZOD"

    def test_accepts_bytes_payload(self):
        data = parse_ezod_payload(json.dumps(_ezod()).encode())
        assert data["format"] == "eZOD"

    def test_rejects_zod_format(self):
        with pytest.raises(ValueError, match="Expected format=eZOD"):
            parse_ezod_payload({"format": "ZOD", "characters": [], "weapons": [], "discs": []})

    def test_rejects_good_format(self):
        with pytest.raises(ValueError, match="Expected format=eZOD"):
            parse_ezod_payload({"format": "GOOD", "characters": [], "weapons": [], "discs": []})

    def test_rejects_no_format(self):
        with pytest.raises(ValueError, match="Expected format=eZOD"):
            parse_ezod_payload({"characters": [], "weapons": [], "discs": []})

    def test_rejects_non_dict_top_level(self):
        with pytest.raises(TypeError, match="JSON object"):
            parse_ezod_payload([])

    def test_rejects_non_dict_from_json_array(self):
        with pytest.raises(TypeError, match="JSON object"):
            parse_ezod_payload("[]")

    def test_rejects_malformed_json_string(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_ezod_payload("{not valid json")

    def test_rejects_malformed_json_bytes(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_ezod_payload(b"{bad}")

    def test_rejects_missing_characters(self):
        with pytest.raises(ValueError, match="'characters'"):
            parse_ezod_payload({"format": "eZOD", "weapons": [], "discs": []})

    def test_rejects_missing_weapons(self):
        with pytest.raises(ValueError, match="'weapons'"):
            parse_ezod_payload({"format": "eZOD", "characters": [], "discs": []})

    def test_rejects_missing_discs(self):
        with pytest.raises(ValueError, match="'discs'"):
            parse_ezod_payload({"format": "eZOD", "characters": [], "weapons": []})

    def test_rejects_characters_not_list(self):
        with pytest.raises(ValueError, match="'characters'"):
            parse_ezod_payload(_ezod(characters={}))

    def test_rejects_too_many_characters(self):
        with pytest.raises(ValueError, match="characters"):
            parse_ezod_payload(_ezod(characters=[{}] * (MAX_CHAR_COUNT + 1)))

    def test_rejects_too_many_weapons(self):
        with pytest.raises(ValueError, match="weapons"):
            parse_ezod_payload(_ezod(weapons=[{}] * (MAX_WEAPON_COUNT + 1)))

    def test_rejects_too_many_discs(self):
        with pytest.raises(ValueError, match="discs"):
            parse_ezod_payload(_ezod(discs=[{}] * (MAX_DISC_COUNT + 1)))

    def test_accepts_exactly_max_counts(self):
        data = parse_ezod_payload(
            _ezod(
                characters=[{}] * MAX_CHAR_COUNT,
                weapons=[{}] * MAX_WEAPON_COUNT,
                discs=[{}] * MAX_DISC_COUNT,
            )
        )
        assert len(data["characters"]) == MAX_CHAR_COUNT
        assert len(data["weapons"]) == MAX_WEAPON_COUNT
        assert len(data["discs"]) == MAX_DISC_COUNT


# ---- _normalize_key ----------------------------------------------------------


class TestNormalizeKey:
    def test_strips_spaces_and_lowercases(self):
        assert _normalize_key("Astra Yao") == "astrayao"

    def test_strips_hyphen_and_lowercases(self):
        assert _normalize_key("Peacekeeper - Specialized") == "peacekeeperspecialized"

    def test_pascalcase_unchanged_except_lower(self):
        assert _normalize_key("BashfulDemon") == "bashfuldemon"

    def test_apostrophe_stripped(self):
        assert _normalize_key("Phaethon's Melody") == "phaethonsmelody"


# ---- resolve_agent_key -------------------------------------------------------


def _mock_agent(name: str, agent_id: str = "agent-1") -> SimpleNamespace:
    return SimpleNamespace(id=agent_id, name=name)


def _agent_lookup(*agents: SimpleNamespace) -> dict[str, SimpleNamespace]:
    """Build lookup the same way build_agent_lookup would."""
    lookup = {_normalize_key(a.name): a for a in agents}
    for alias_norm, target_norm in _AGENT_ALIASES.items():
        if target_norm in lookup:
            lookup[alias_norm] = lookup[target_norm]
    return lookup


class TestResolveAgentKey:
    def setup_method(self):
        self.lookup = _agent_lookup(
            _mock_agent("Astra Yao", "agent-ay"),
            _mock_agent("Rina", "agent-ri"),
            _mock_agent("Anby", "agent-an"),
        )

    def test_direct_match_exact_case(self):
        result = resolve_agent_key("Rina", self.lookup)
        assert result.id == "agent-ri"

    def test_direct_match_different_case(self):
        # "RINA" normalizes to "rina" → same key
        result = resolve_agent_key("RINA", self.lookup)
        assert result.id == "agent-ri"

    def test_alias_astra_resolves_to_astra_yao(self):
        result = resolve_agent_key("Astra", self.lookup)
        assert result.name == "Astra Yao"

    def test_unknown_key_returns_skip_reason(self):
        outcome = resolve_agent_key("NotAnAgent", self.lookup)
        assert isinstance(outcome, tuple)
        _, reason = outcome
        assert "unknown agent key" in reason
        assert "NotAnAgent" in reason

    def test_empty_string_returns_skip_reason(self):
        outcome = resolve_agent_key("", self.lookup)
        assert isinstance(outcome, tuple)


# ---- resolve_wengine_key -----------------------------------------------------


def _mock_engine(name: str, eng_id: str = "eng-1") -> SimpleNamespace:
    return SimpleNamespace(id=eng_id, name=name)


def _wengine_lookup(*engines: SimpleNamespace) -> dict[str, SimpleNamespace]:
    lookup = {_normalize_key(e.name): e for e in engines}
    for alias_norm, target_norm in _WENGINE_ALIASES.items():
        if target_norm in lookup:
            lookup[alias_norm] = lookup[target_norm]
    return lookup


class TestResolveWEngineKey:
    def setup_method(self):
        self.lookup = _wengine_lookup(
            _mock_engine("Peacekeeper - Specialized", "eng-pk"),
            _mock_engine("BashfulDemon", "eng-bd"),
        )

    def test_direct_match(self):
        result = resolve_wengine_key("BashfulDemon", self.lookup)
        assert result.id == "eng-bd"

    def test_alias_peacekeeper_resolves_to_specialized(self):
        result = resolve_wengine_key("Peacekeeper", self.lookup)
        assert result.name == "Peacekeeper - Specialized"

    def test_unknown_key_returns_skip_reason(self):
        outcome = resolve_wengine_key("MadeUpGun", self.lookup)
        assert isinstance(outcome, tuple)
        _, reason = outcome
        assert "unknown w-engine key" in reason
        assert "MadeUpGun" in reason

    def test_empty_string_returns_skip_reason(self):
        outcome = resolve_wengine_key("", self.lookup)
        assert isinstance(outcome, tuple)


# ---- build_draft_from_character -----------------------------------------------

# Shared test data modelled on the ezod_small.json fixture.

_RINA_CHAR = {
    "key": "Rina",
    "level": 60,
    "constellation": 6,
    "ascension": 6,
    "talent": {"basic": 12, "dodge": 12, "assist": 11, "special": 12, "chain": 12, "core": 6},
}
_ANBY_CHAR = {
    "key": "Anby",
    "level": 50,
    "constellation": 2,
    "ascension": 4,
    "talent": {"basic": 10, "dodge": 10, "assist": 8, "special": 10, "chain": 10, "core": 4},
}
_LUCY_CHAR = {
    "key": "Lucy",
    "level": 40,
    "constellation": 0,
    "ascension": 3,
    "talent": {"basic": 6, "dodge": 6, "assist": 5, "special": 6, "chain": 6, "core": 0},
}

_BASHFUL_DEMON_RAW = {
    "key": "BashfulDemon", "level": 60, "ascension": 5, "refinement": 1, "location": "Rina"
}


class TestBuildDraftFromCharacterFull:
    """Rina: full character — all talents maxed, engine equipped, core=6 (F)."""

    def setup_method(self):
        self.agent = _mock_agent("Rina", "agent-ri")
        self.engine = _mock_engine("BashfulDemon", "eng-bd")
        self.draft: BuildDraft = build_draft_from_character(
            _RINA_CHAR, self.agent, weapon=self.engine, weapon_raw=_BASHFUL_DEMON_RAW
        )

    def test_returns_build_draft(self):
        assert isinstance(self.draft, BuildDraft)

    def test_agent_id(self):
        assert self.draft.agent_id == "agent-ri"

    def test_agent_level(self):
        assert self.draft.agent_level == 60

    def test_mindscape_from_constellation(self):
        assert self.draft.mindscape_level == 6

    def test_skill_levels_format(self):
        # basic,dodge,special,chain,core_attack — assist dropped
        assert self.draft.skill_levels == "12,12,12,12,6"

    def test_core_skill_level_f_tier(self):
        # core=6 (F) → core_skill_level = 6-1 = 5
        assert self.draft.core_skill_level == 5

    def test_w_engine_id(self):
        assert self.draft.w_engine_id == "eng-bd"

    def test_w_engine_level(self):
        assert self.draft.w_engine_level == 60

    def test_w_engine_refinement(self):
        assert self.draft.w_engine_refinement == 1


class TestBuildDraftFromCharacterNoEngine:
    """Anby: no engine equipped — w_engine fields should be None/defaults."""

    def setup_method(self):
        self.agent = _mock_agent("Anby", "agent-an")
        self.draft: BuildDraft = build_draft_from_character(_ANBY_CHAR, self.agent)

    def test_agent_level(self):
        assert self.draft.agent_level == 50

    def test_mindscape_level(self):
        assert self.draft.mindscape_level == 2

    def test_skill_levels(self):
        assert self.draft.skill_levels == "10,10,10,10,4"

    def test_core_skill_level_d_tier(self):
        # core=4 (D) → core_skill_level = 4-1 = 3
        assert self.draft.core_skill_level == 3

    def test_w_engine_id_none(self):
        assert self.draft.w_engine_id is None

    def test_w_engine_level_default(self):
        assert self.draft.w_engine_level == 60

    def test_w_engine_refinement_default(self):
        assert self.draft.w_engine_refinement == 1


class TestBuildDraftFromCharacterCoreZero:
    """Lucy: core=0 (uninvested) — core_attack floors to 1, core_skill_level=0."""

    def setup_method(self):
        self.agent = _mock_agent("Lucy", "agent-lu")
        self.draft: BuildDraft = build_draft_from_character(_LUCY_CHAR, self.agent)

    def test_skill_levels_core_attack_floored_to_one(self):
        # talent.core=0 → max(1,0)=1 for core attack slot
        assert self.draft.skill_levels == "6,6,6,6,1"

    def test_core_skill_level_zero(self):
        # core=0 → clamp(0-1,0,5)=0
        assert self.draft.core_skill_level == 0

    def test_mindscape_zero(self):
        assert self.draft.mindscape_level == 0

    def test_no_engine(self):
        assert self.draft.w_engine_id is None


class TestBuildDraftCoreMath:
    """Parameterised checks for the core tier mapping edge cases."""

    def _draft(self, core_val: int) -> BuildDraft:
        agent = _mock_agent("Test", "agent-t")
        char = {
            "key": "Test",
            "level": 60,
            "constellation": 0,
            "talent": {"basic": 1, "dodge": 1, "special": 1, "chain": 1, "core": core_val},
        }
        return build_draft_from_character(char, agent)

    def test_core_0_attack_floor(self):
        d = self._draft(0)
        assert d.skill_levels.split(",")[4] == "1"
        assert d.core_skill_level == 0

    def test_core_1_a_tier(self):
        d = self._draft(1)
        assert d.skill_levels.split(",")[4] == "1"
        assert d.core_skill_level == 0

    def test_core_3_c_tier(self):
        d = self._draft(3)
        assert d.skill_levels.split(",")[4] == "3"
        assert d.core_skill_level == 2

    def test_core_6_f_tier(self):
        d = self._draft(6)
        assert d.skill_levels.split(",")[4] == "6"
        assert d.core_skill_level == 5

    def test_assist_not_in_skill_levels(self):
        # skill_levels has exactly 5 entries (no assist)
        d = self._draft(4)
        parts = d.skill_levels.split(",")
        assert len(parts) == 5


# ---- disc_slots_for_character -------------------------------------------------


class TestDiscSlotsForCharacter:
    def _disc(self, slot: int, location: str) -> dict:
        return {"slotKey": str(slot), "location": location, "setKey": "SomeSet", "rarity": 4}

    def test_full_six_discs(self):
        discs = [self._disc(i, "Rina") for i in range(1, 7)]
        result = disc_slots_for_character("Rina", discs)
        assert set(result.keys()) == {1, 2, 3, 4, 5, 6}

    def test_partial_discs_only_matching_location(self):
        discs = [
            self._disc(1, "Anby"),
            self._disc(2, "Anby"),
            self._disc(3, "Rina"),  # different character
            self._disc(4, "Anby"),
        ]
        result = disc_slots_for_character("Anby", discs)
        assert set(result.keys()) == {1, 2, 4}

    def test_no_discs_returns_empty(self):
        discs = [self._disc(i, "Rina") for i in range(1, 7)]
        result = disc_slots_for_character("Lucy", discs)
        assert result == {}

    def test_unequipped_disc_excluded(self):
        discs = [{"slotKey": "1", "location": "", "setKey": "X", "rarity": 4}]
        result = disc_slots_for_character("Rina", discs)
        assert result == {}

    def test_non_dict_entry_skipped(self):
        discs = ["not a dict", self._disc(2, "Rina")]
        result = disc_slots_for_character("Rina", discs)
        assert result == {2: discs[1]}

    def test_missing_slot_key_skipped(self):
        discs = [{"location": "Rina", "setKey": "X"}]
        result = disc_slots_for_character("Rina", discs)
        assert result == {}

    def test_invalid_slot_key_skipped(self):
        discs = [{"slotKey": "bad", "location": "Rina", "setKey": "X"}]
        result = disc_slots_for_character("Rina", discs)
        assert result == {}

    def test_slot_out_of_range_skipped(self):
        discs = [{"slotKey": "7", "location": "Rina", "setKey": "X"}]
        result = disc_slots_for_character("Rina", discs)
        assert result == {}

    def test_returns_disc_raw_for_each_slot(self):
        disc = self._disc(3, "Anby")
        result = disc_slots_for_character("Anby", [disc])
        assert result[3] is disc


class TestSkillLevelsConsistencyOnImport:
    """The schema validator does not reach this path (#156).

    `BuildCreate`/`BuildUpdate` gained a `skill_levels` vs `mindscape_level` check,
    but the importer builds `Build(**kwargs)` straight from a `BuildDraft` dataclass
    and never touches those schemas — so imports could still write the exact
    self-contradicting rows the validator exists to stop (Anby and Nicole are live
    examples: mindscape 0 with skills of 13 and 15).

    `skill_levels` stores the EFFECTIVE level, mindscape bonus included (#153,
    established from a real scanner export), so the legal ceiling is
    `12 + (4 if mc>=5 else 2 if mc>=3 else 0)`.
    """

    @staticmethod
    def _char(constellation: int, basic: int) -> dict:
        return {
            "key": "Jane",
            "level": 60,
            "constellation": constellation,
            "talent": {
                "basic": basic,
                "dodge": 12,
                "assist": 12,
                "special": 12,
                "chain": 12,
                "core": 6,
            },
        }

    def test_consistent_character_reports_no_problem(self):
        from app.data.importers.ezod_importer import skill_levels_problem

        # M6 allows up to 16; 15 is Anton's real shape.
        assert skill_levels_problem(self._char(6, 15)) is None
        assert skill_levels_problem(self._char(0, 12)) is None

    def test_skill_above_the_mindscape_ceiling_is_reported(self):
        from app.data.importers.ezod_importer import skill_levels_problem

        problem = skill_levels_problem(self._char(0, 13))

        assert problem is not None
        assert "mindscape" in problem.lower()

    def test_m3_allows_14_but_not_15(self):
        from app.data.importers.ezod_importer import skill_levels_problem

        assert skill_levels_problem(self._char(3, 14)) is None
        assert skill_levels_problem(self._char(3, 15)) is not None

    def test_anbys_real_export_shape_is_accepted(self):
        """Her live scanner row is M6 with a 13 — legal. The validator must flag the
        stale DB row, not the correct export."""
        from app.data.importers.ezod_importer import skill_levels_problem

        assert skill_levels_problem(self._char(6, 13)) is None


class TestSkipReportsMindscapeDrift:
    """`skip` leaves a build alone — but silently (#156).

    That silence is how 16 of 39 live builds ended up below the scanner's mindscape,
    every one an understatement, each quietly dropping the kit rows gated on
    `min_mindscape`. Anby sat at M0 against a real M6, missing all six.

    Skipping is still the right action — the caller asked for it — but it must say so.
    """

    @staticmethod
    def _char(constellation: int) -> dict:
        return {
            "key": "Jane",
            "level": 60,
            "constellation": constellation,
            "talent": {"basic": 12, "dodge": 12, "assist": 12,
                       "special": 12, "chain": 12, "core": 6},
        }

    def test_drift_is_reported_with_both_values_and_the_remedy(self):
        from app.data.importers.ezod_importer import mindscape_drift_problem

        problem = mindscape_drift_problem(self._char(6), stored_mindscape=0)

        assert problem is not None
        assert "M0" in problem
        assert "M6" in problem
        assert "overwrite" in problem  # the caller is told how to fix it

    def test_no_drift_when_they_agree(self):
        from app.data.importers.ezod_importer import mindscape_drift_problem

        assert mindscape_drift_problem(self._char(2), stored_mindscape=2) is None

    def test_stored_ahead_of_the_scan_is_not_reported(self):
        """Mindscapes only increase, so DB > scan means the payload is old, not the
        build. Reporting that would train people to ignore the message."""
        from app.data.importers.ezod_importer import mindscape_drift_problem

        assert mindscape_drift_problem(self._char(1), stored_mindscape=4) is None


class TestSkipProtectsEquippedDiscs:
    """`skip` must protect the whole build, equipment included (#144).

    `claimed_rows` only tracked rows claimed *during a run*, so a disc already
    attached to a skipped build was never claimed and a later character equipping a
    content-identical disc could take the row — dropping the skipped build from 6
    discs to 5, silently.

    The issue names two defensible readings. This picks "skip protects the build
    wholly": `skip` reads as "leave this build exactly as it is", and having its gear
    moved contradicts that. The other reading (payload is authoritative about current
    equipment) is defensible, but under it the name is misleading AND the user is
    still not told — so it fails the acceptance criterion either way unless reported.
    Here the later character simply finds no free row, and that IS reported.
    """

    def test_preclaimed_ids_block_a_later_claim(self):
        from app.data.importers.ezod_importer import claim_ids_for_skipped_build

        class _Row:
            pass

        a, b = _Row(), _Row()
        claimed: set[int] = set()

        claim_ids_for_skipped_build([a, b], claimed)

        assert id(a) in claimed
        assert id(b) in claimed

    def test_claiming_is_additive_and_never_drops_existing_claims(self):
        from app.data.importers.ezod_importer import claim_ids_for_skipped_build

        class _Row:
            pass

        a, b = _Row(), _Row()
        claimed = {id(a)}

        claim_ids_for_skipped_build([b], claimed)

        assert claimed == {id(a), id(b)}

    def test_no_discs_is_a_no_op(self):
        from app.data.importers.ezod_importer import claim_ids_for_skipped_build

        claimed: set[int] = set()
        claim_ids_for_skipped_build([], claimed)
        assert claimed == set()
