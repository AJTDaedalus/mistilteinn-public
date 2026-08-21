"""Task 6a acceptance tests — fixture completeness and consistency.

Verifies that the committed optimizer fixtures under
``tests/fixtures/optimizer/`` are present, self-consistent, and match the
locked ground-truth numbers from DESIGN_optimizer_granularity.md.

These tests are DB-free: they only read JSON files.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "optimizer"
_DISCS_FILE = _FIXTURE_DIR / "owner_twst1_discs.json"
_BUCKETS_FILE = _FIXTURE_DIR / "owner_twst1_buckets.json"
_PAYLOAD_FILE = _FIXTURE_DIR / "owner_twst1_payload.json"
_SUBFRAME_FILE = _FIXTURE_DIR / "owner_subframe_small.json"

_FRAME = {32700: 2, 33500: 4}  # 2pc Branch & Blade Song + 4pc White Water Ballad

# Locked ground-truth targets from DESIGN doc
_EXPECTED_N_CANDIDATES = 595
_EXPECTED_EXHAUSTIVE = 12_529_002
_EXPECTED_K7 = 989_898
_EXPECTED_K8 = 1_628_672

# Per DESIGN table:
#   set 32700 (Branch & Blade Song): s1=3, s2=18, s3=19, s4=18, s5=6, s6=12
#   set 33500 (White Water Ballad):  s1=11, s2=7, s3=10, s4=4, s5=7, s6=13
_EXPECTED_BUCKET_COUNTS = {
    (32700, 1): 3,
    (32700, 2): 18,
    (32700, 3): 19,
    (32700, 4): 18,
    (32700, 5): 6,
    (32700, 6): 12,
    (33500, 1): 11,
    (33500, 2): 7,
    (33500, 3): 10,
    (33500, 4): 4,
    (33500, 5): 7,
    (33500, 6): 13,
}

_SUBFRAME_CAP = 6


def _frame_combo_count(
    buckets: dict[tuple[int, int], int],
    cap: int | None = None,
) -> int:
    """Exact frame combo count (same logic as the capture script)."""
    (set_a, _), (set_b, _) = sorted(_FRAME.items(), key=lambda kv: kv[1])
    a = {s: buckets.get((set_a, s), 0) for s in range(1, 7)}
    b = {s: buckets.get((set_b, s), 0) for s in range(1, 7)}
    if cap:
        a = {s: min(v, cap) for s, v in a.items()}
        b = {s: min(v, cap) for s, v in b.items()}
    total = 0
    for two in combinations(range(1, 7), 2):
        prod = a[two[0]] * a[two[1]]
        for s in (s for s in range(1, 7) if s not in two):
            prod *= b[s]
        total += prod
    return total


class TestDiscPoolFixture:
    """owner_twst1_discs.json — basic shape and disc field completeness."""

    @pytest.fixture(scope="class")
    def discs(self) -> list[dict]:
        return json.loads(_DISCS_FILE.read_text())

    def test_file_exists(self):
        assert _DISCS_FILE.exists(), "owner_twst1_discs.json missing"

    def test_candidate_count(self, discs):
        assert len(discs) == _EXPECTED_N_CANDIDATES

    def test_disc_fields_present(self, discs):
        required = {"disc_id", "slot", "set_id", "main_stat_type", "main_stat_value", "substats"}
        for d in discs:
            assert required <= d.keys(), f"Disc {d.get('disc_id')} missing fields"

    def test_slots_range_1_to_6(self, discs):
        slots = {d["slot"] for d in discs}
        assert slots == {1, 2, 3, 4, 5, 6}


class TestBucketsFixture:
    """owner_twst1_buckets.json — match the DESIGN ground-truth table."""

    @pytest.fixture(scope="class")
    def buckets(self) -> dict:
        return json.loads(_BUCKETS_FILE.read_text())

    def test_file_exists(self):
        assert _BUCKETS_FILE.exists(), "owner_twst1_buckets.json missing"

    def test_buckets_match_design(self, buckets):
        """CP1 seed: per-(set_id, slot) counts match the DESIGN locked table."""
        rows = {(r["set_id"], r["slot"]): r["count"] for r in buckets["buckets"]}
        for key, expected in _EXPECTED_BUCKET_COUNTS.items():
            assert rows.get(key, 0) == expected, (
                f"Bucket {key}: expected {expected}, got {rows.get(key, 0)}"
            )

    def test_exhaustive_count_matches_design(self, buckets):
        assert buckets["exhaustive_combos"] == _EXPECTED_EXHAUSTIVE

    def test_bucket_counts_cross_verify_k7(self):
        """Derived from the locked bucket counts: K=7 must give 989,898."""
        counts = dict(_EXPECTED_BUCKET_COUNTS)
        assert _frame_combo_count(counts, cap=7) == _EXPECTED_K7

    def test_bucket_counts_cross_verify_k8(self):
        """Derived from the locked bucket counts: K=8 must give 1,628,672."""
        counts = dict(_EXPECTED_BUCKET_COUNTS)
        assert _frame_combo_count(counts, cap=8) == _EXPECTED_K8


class TestPayloadFixture:
    """owner_twst1_payload.json — schema and required fields."""

    @pytest.fixture(scope="class")
    def payload(self) -> dict:
        return json.loads(_PAYLOAD_FILE.read_text())

    def test_file_exists(self):
        assert _PAYLOAD_FILE.exists(), "owner_twst1_payload.json missing"

    def test_required_keys(self, payload):
        required = {"base_build", "enemy", "combo_steps", "disc_frame", "disc_set_ids"}
        assert required <= payload.keys()

    def test_base_build_keys(self, payload):
        bb = payload["base_build"]
        required_keys = ("agent_base_atk", "wengine_base_atk", "agent_element",
                         "agent_crit_rate", "agent_crit_dmg")
        for key in required_keys:
            assert key in bb, f"base_build missing {key}"

    def test_enemy_keys(self, payload):
        enemy = payload["enemy"]
        for key in ("level", "base_def", "element_res", "stun_dmg_mult"):
            assert key in enemy, f"enemy missing {key}"

    def test_combo_steps_non_empty(self, payload):
        assert len(payload["combo_steps"]) >= 1

    def test_combo_steps_have_required_fields(self, payload):
        for step in payload["combo_steps"]:
            assert "step_type" in step
            assert "label" in step
            if step["step_type"] == "ComboStep":
                for f in ("scope", "multiplier", "element"):
                    assert f in step, f"ComboStep missing {f}"

    def test_disc_frame_matches_frame_constant(self, payload):
        frame = {int(k): v for k, v in payload["disc_frame"].items()}
        assert frame == _FRAME

    def test_physical_element_and_attack_specialty(self, payload):
        assert payload["base_build"]["agent_element"] == "physical"
        assert payload["base_build"].get("agent_specialty") == "attack"


class TestSubframeFixture:
    """owner_subframe_small.json — capped disc pool + tractable combo count."""

    @pytest.fixture(scope="class")
    def subframe(self) -> dict:
        return json.loads(_SUBFRAME_FILE.read_text())

    def test_file_exists(self):
        assert _SUBFRAME_FILE.exists(), "owner_subframe_small.json missing"

    def test_has_discs_field(self, subframe):
        assert "discs" in subframe
        assert len(subframe["discs"]) > 0

    def test_bucket_cap_respected(self, subframe):
        """No (set_id, slot) bucket in the two frame sets exceeds SUBFRAME_CAP."""
        from collections import Counter
        counts = Counter(
            (d["set_id"], d["slot"])
            for d in subframe["discs"]
            if d["set_id"] in _FRAME
        )
        for key, count in counts.items():
            assert count <= _SUBFRAME_CAP, (
                f"Bucket {key} has {count} discs, expected ≤ {_SUBFRAME_CAP}"
            )

    def test_exhaustive_combos_tractable(self, subframe):
        """Subframe must be small enough for exhaustive ground truth (<10M)."""
        assert subframe["exhaustive_combos"] < 10_000_000

    def test_exhaustive_combos_matches_disc_pool(self, subframe):
        """Reported exhaustive count must be reproducible from the disc pool."""
        from collections import Counter
        counts = Counter(
            (d["set_id"], d["slot"])
            for d in subframe["discs"]
            if d["set_id"] in _FRAME
        )
        assert _frame_combo_count(counts) == subframe["exhaustive_combos"]

    def test_inherits_build_and_enemy_from_payload(self, subframe):
        """Subframe includes base_build and enemy (same fields as payload)."""
        for key in ("base_build", "enemy", "combo_steps"):
            assert key in subframe
