"""Unit tests for the unseeded-row sweep (issue #180).

Two things are worth testing here and they are not the same thing. The classifier decides
what a row *is*, and its precedence rules are load-bearing — `inert` beating a twin match
is a deliberate choice, not an accident of ordering. The refusals decide whether the script
is allowed to speak at all, and both of their failure modes are silent: an unseeded DB
produces a confidently wrong snapshot, and a rotated column hash produces plausible wrong
numbers. Neither raises on its own; that is why they are asserted here.
"""

from __future__ import annotations

import json

import pytest

from scripts.dimbreath import build_unseeded_rows as sweep


def values(
    dmg: int,
    growth: int = 0,
    *,
    stun: int = 0,
    stun_growth: int = 0,
    energy: int = 0,
    buildup: int = 0,
):
    """One upstream row's six derived values."""
    return {
        "damage_base": dmg,
        "damage_growth": growth,
        "stun_base": stun,
        "stun_growth": stun_growth,
        "energy_gain": energy,
        "anomaly_buildup": buildup,
    }


# ── classifier ─────────────────────────────────────────────────────────────
class TestClassify:
    def test_inert_row_has_no_side_channels(self):
        # Remielle 1581001's shape: damage, no Daze, no energy, no buildup.
        bucket, twin = sweep.classify(values(72520, 6600), [])
        assert (bucket, twin) == ("inert", None)

    def test_inert_beats_a_twin_that_is_also_inert(self):
        """An all-zero signature says something about the row; sharing it says nothing.

        Yuzuha 1411025 is this case against the real corpus. Filing it as a variant of a
        row it merely resembles in having no properties would invent a relationship.
        """
        seeded = [(1411022, values(50000)), (1411023, values(50000))]
        bucket, twin = sweep.classify(values(60000), seeded)
        assert (bucket, twin) == ("inert", None)

    def test_exact_duplicate_names_its_twin(self):
        seeded = [(1341023, values(43750, 1990, stun=4030, stun_growth=190, buildup=3670))]
        bucket, twin = sweep.classify(
            values(43750, 1990, stun=4030, stun_growth=190, buildup=3670), seeded
        )
        assert (bucket, twin) == ("exact_dup_of_seeded", 1341023)

    def test_growth_difference_demotes_a_duplicate_to_a_variant(self):
        """Same base, different growth is a different move at every level but Lv.1."""
        seeded = [(1341023, values(43750, 1990, stun=4030, stun_growth=190))]
        bucket, twin = sweep.classify(values(43750, 2500, stun=4030, stun_growth=190), seeded)
        assert (bucket, twin) == ("variant_of_seeded", 1341023)

    def test_same_side_signature_different_damage_is_a_variant(self):
        seeded = [(1321016, values(60000, 5000, stun=26040, stun_growth=1190, buildup=23670))]
        bucket, twin = sweep.classify(
            values(248570, 22600, stun=26040, stun_growth=1190, buildup=23670), seeded
        )
        assert (bucket, twin) == ("variant_of_seeded", 1321016)

    def test_novel_signature_when_nothing_matches(self):
        seeded = [
            (1311014, values(5500, 500, stun=4840, stun_growth=220, energy=6340, buildup=1759))
        ]
        bucket, twin = sweep.classify(
            values(368140, 33470, stun=77280, stun_growth=3520, buildup=76958), seeded
        )
        assert (bucket, twin) == ("novel_signature", None)

    def test_twin_matching_never_crosses_avatars(self):
        """The caller passes only this avatar's seeded rows; the classifier must rely on it.

        #77's remediation table matched across agents corpus-wide and produced confident
        wrong answers, so this asserts the contract rather than assuming it.
        """
        row = values(43750, 1990, stun=4030, stun_growth=190)
        assert sweep.classify(row, [])[0] == "novel_signature"
        assert sweep.classify(row, [(1341023, dict(row))])[0] == "exact_dup_of_seeded"

    def test_lowest_twin_id_wins_so_output_is_stable(self):
        row = values(1000, 100, stun=50, stun_growth=5)
        seeded = [(1051009, dict(row)), (1051003, dict(row))]
        assert sweep.classify(row, seeded) == ("exact_dup_of_seeded", 1051003)
        assert sweep.classify(row, list(reversed(seeded))) == ("exact_dup_of_seeded", 1051003)


# ── refusal 1: no DB, or a DB with nothing seeded ──────────────────────────
class TestDatabaseRefusal:
    def test_unreachable_db_raises(self, monkeypatch):
        async def boom():
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(sweep, "_load_db_state", boom)
        with pytest.raises(sweep.EmptyRosterError, match="DB not reachable"):
            sweep.load_db_state()

    def test_empty_seeded_set_raises_even_though_the_db_answered(self, monkeypatch):
        """The dangerous case. A reachable-but-unseeded DB raises nowhere on its own —
        it just makes every upstream row look unseeded, and the snapshot would say so."""

        async def empty():
            return {1011: "Anby"}, set()

        monkeypatch.setattr(sweep, "_load_db_state", empty)
        with pytest.raises(
            sweep.EmptyRosterError, match="refusing to sweep against an unseeded DB"
        ):
            sweep.load_db_state()

    def test_refusal_writes_nothing_and_exits_nonzero(self, monkeypatch, tmp_path):
        out = tmp_path / "unseeded_skill_rows.json"
        monkeypatch.setattr(sweep, "OUT_PATH", out)
        def refuse():
            raise sweep.EmptyRosterError("no db")

        monkeypatch.setattr(sweep, "sweep", refuse)
        monkeypatch.setattr("sys.argv", ["build_unseeded_rows"])
        assert sweep.main() == 1
        assert not out.exists()


# ── refusal 2: a column map that cannot reproduce its anchors ──────────────
class TestColumnMapRefusal:
    def test_unreproducible_columns_raise(self):
        rows = [{"KEY": 1011001, "AAA": 7, "BBB": 8}, {"KEY": 1011002, "AAA": 9, "BBB": 10}]
        anchors = {
            1011001: {f: 100 + i for i, f in enumerate(sweep.VALUE_FIELDS)},
            1011002: {f: 200 + i for i, f in enumerate(sweep.VALUE_FIELDS)},
        }
        with pytest.raises(sweep.ColumnMapError, match="refusing to write a snapshot"):
            sweep.derive_columns(rows, anchors)

    def test_reproducible_columns_are_accepted(self):
        rows = [
            {"KEY": 1011001, **{f"C{i}": 100 + i for i in range(len(sweep.VALUE_FIELDS))}},
            {"KEY": 1011002, **{f"C{i}": 200 + i for i in range(len(sweep.VALUE_FIELDS))}},
        ]
        anchors = {
            1011001: {f: 100 + i for i, f in enumerate(sweep.VALUE_FIELDS)},
            1011002: {f: 200 + i for i, f in enumerate(sweep.VALUE_FIELDS)},
        }
        key_col, cols, ratios = sweep.derive_columns(rows, anchors)
        assert key_col == "KEY"
        assert set(cols) == set(sweep.VALUE_FIELDS)
        assert all(r == 1.0 for r in ratios.values())


# ── ability membership signal ──────────────────────────────────────────────
class TestAbilitySignal:
    def test_returns_none_when_no_column_references_skill_ids(self, monkeypatch):
        """The real shape at pin 475dd0195645: ability ids plus name strings, no references.

        `null` is the answer, and it must arrive as a derived negative rather than as a
        guess — the value of the field is that a future pin adding a reference column
        starts populating it without anyone noticing the table changed.
        """
        table = {
            "rows": [{"KEY": 1339701 + i, "NAME": f"AbyssS2_Artifact_{i}"} for i in range(30)]
        }
        monkeypatch.setattr(sweep, "fetch_json", lambda _t: table)
        ids, note = sweep.ability_reference_ids({1581001, 1581025})
        assert ids is None
        assert "not derivable" in note

    def test_derives_the_column_when_one_actually_references_skills(self, monkeypatch):
        seeded = {1011000 + i for i in range(30)}
        table = {
            "rows": [
                {"KEY": 9000 + i, "SKILL": 1011000 + (i % 25), "NOISE": 42} for i in range(30)
            ]
        }
        monkeypatch.setattr(sweep, "fetch_json", lambda _t: table)
        ids, note = sweep.ability_reference_ids(seeded)
        assert ids is not None
        assert 1011005 in ids
        assert "SKILL" in note

    def test_a_few_coincidental_ids_do_not_count_as_a_reference(self, monkeypatch):
        seeded = {1011000 + i for i in range(30)}
        table = {"rows": [{"KEY": 9000 + i, "MOSTLY_OTHER": 1011000 + (i % 2)} for i in range(3)]}
        monkeypatch.setattr(sweep, "fetch_json", lambda _t: table)
        assert sweep.ability_reference_ids(seeded)[0] is None


# ── --check ────────────────────────────────────────────────────────────────
class TestCheckMode:
    def _doc(self, rows):
        """A minimal snapshot document — only the fields `_check` reads."""
        return {"_meta": {"pinned_sha": "abc123", "buckets": {}}, "rows": rows}

    def test_missing_snapshot_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sweep, "OUT_PATH", tmp_path / "absent.json")
        assert sweep._check(self._doc({})) == 1

    def test_identical_snapshot_passes(self, monkeypatch, tmp_path):
        out = tmp_path / "snap.json"
        doc = self._doc({"1581001": {"bucket": "inert"}})
        out.write_text(json.dumps(doc))
        monkeypatch.setattr(sweep, "OUT_PATH", out)
        assert sweep._check(doc) == 0

    def test_new_upstream_row_fails(self, monkeypatch, tmp_path, capsys):
        out = tmp_path / "snap.json"
        out.write_text(json.dumps(self._doc({"1581001": {"bucket": "inert"}})))
        monkeypatch.setattr(sweep, "OUT_PATH", out)
        fresh = self._doc(
            {"1581001": {"bucket": "inert"}, "1581026": {"bucket": "novel_signature"}}
        )
        assert sweep._check(fresh) == 1
        assert "1581026" in capsys.readouterr().err

    def test_changed_values_fail(self, monkeypatch, tmp_path, capsys):
        out = tmp_path / "snap.json"
        out.write_text(json.dumps(self._doc({"1581001": {"damage_base": 72520}})))
        monkeypatch.setattr(sweep, "OUT_PATH", out)
        assert sweep._check(self._doc({"1581001": {"damage_base": 72521}})) == 1
        assert "changed: 1581001" in capsys.readouterr().err
