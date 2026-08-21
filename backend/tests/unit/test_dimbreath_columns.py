"""Unit tests for the FileCfg column-triangulation helper (cartography toolkit).

Pure; no network. Guards the triangulation semantics that label hash-obfuscated
columns against trusted anchors (T2.2). The real AvatarSkillTemplateTb map is
re-derived by scripts/dimbreath/build_column_dicts.py against a DB-anchor
snapshot — these tests pin the matcher logic that drives it.
"""

from __future__ import annotations

from scripts.dimbreath import columns

# Synthetic table: key column "ID", a perfect-match column, a one-off-noisy
# column, an unrelated column, an all-zero reserved column, and a list column.
_ROWS = [
    {"ID": 1, "AAA": 100, "BBB": 10, "CCC": 7, "ZZZ": 0, "LLL": []},
    {"ID": 2, "AAA": 200, "BBB": 20, "CCC": 7, "ZZZ": 0, "LLL": [99]},
    {"ID": 3, "AAA": 300, "BBB": 99, "CCC": 7, "ZZZ": 0, "LLL": []},
    {"ID": 4, "AAA": 400, "BBB": 40, "CCC": 7, "ZZZ": 0, "LLL": [5, 6]},
]
_ANCHORS = {
    1: {"dmg": 100, "stun": 10},
    2: {"dmg": 200, "stun": 20},
    3: {"dmg": 300, "stun": 30},
    4: {"dmg": 400, "stun": 40},
}
_FIELDS = ["dmg", "stun"]


def test_value_match_finds_perfect_column():
    report = columns.column_value_match(_ROWS, "ID", _ANCHORS, _FIELDS)
    assert report["AAA"]["best_field"] == "dmg"
    assert report["AAA"]["matches"] == 4
    assert report["AAA"]["ratio"] == 1.0


def test_value_match_reports_partial_ratio():
    # BBB matches stun on 3 of 4 rows (row 3 is 99, not 30).
    report = columns.column_value_match(_ROWS, "ID", _ANCHORS, _FIELDS)
    assert report["BBB"]["best_field"] == "stun"
    assert report["BBB"]["matches"] == 3
    assert report["BBB"]["ratio"] == 0.75


def test_value_match_skips_list_and_key_columns():
    report = columns.column_value_match(_ROWS, "ID", _ANCHORS, _FIELDS)
    assert "LLL" not in report  # list column skipped
    assert "ID" not in report  # key column skipped


def test_confident_map_threshold_excludes_partial():
    report = columns.column_value_match(_ROWS, "ID", _ANCHORS, _FIELDS)
    mapping = columns.confident_map(report, threshold=0.95)
    assert mapping == {"AAA": "dmg"}  # BBB (0.75) excluded


def test_confident_map_one_field_per_column():
    # Two columns both perfectly reproduce "dmg" -> only the first kept, no dup.
    rows = [
        {"ID": 1, "A": 100, "B": 100},
        {"ID": 2, "A": 200, "B": 200},
    ]
    anchors = {1: {"dmg": 100}, 2: {"dmg": 200}}
    report = columns.column_value_match(rows, "ID", anchors, ["dmg"])
    mapping = columns.confident_map(report, threshold=0.95)
    assert list(mapping.values()) == ["dmg"]
    assert len(mapping) == 1


def test_enum_join_maps_value_to_dominant_category():
    # CAT column: value 1 -> "a" (rows 1,2), value 2 -> "b" (rows 3,4).
    rows = [
        {"ID": 1, "CAT": 1},
        {"ID": 2, "CAT": 1},
        {"ID": 3, "CAT": 2},
        {"ID": 4, "CAT": 2},
    ]
    anchors = {
        1: {"kind": "a"}, 2: {"kind": "a"},
        3: {"kind": "b"}, 4: {"kind": "b"},
    }
    res = columns.enum_join(rows, "ID", anchors, "kind")
    assert res["CAT"]["mapping"] == {1: "a", 2: "b"}
    assert res["CAT"]["purity"] == 1.0
    assert res["CAT"]["distinct"] == 2


def test_enum_join_tolerates_one_outlier():
    # value 2 is "b" on 2 rows but one stray "c" -> still maps to dominant "b".
    rows = [
        {"ID": 1, "CAT": 1},
        {"ID": 2, "CAT": 2},
        {"ID": 3, "CAT": 2},
        {"ID": 4, "CAT": 2},
    ]
    anchors = {
        1: {"kind": "a"}, 2: {"kind": "b"},
        3: {"kind": "b"}, 4: {"kind": "c"},
    }
    res = columns.enum_join(rows, "ID", anchors, "kind")
    assert res["CAT"]["mapping"] == {1: "a", 2: "b"}
    assert res["CAT"]["purity"] == 0.75  # 3 of 4 rows match their dominant


def test_profiles_flag_unused_and_resolved_shapes():
    prof = columns.column_profiles(_ROWS, "ID")
    assert prof["ZZZ"]["nonzero"] == 0  # all-zero reserved column
    assert prof["AAA"]["nonzero"] == 4
    assert prof["LLL"]["kind"] == "list"
    assert prof["LLL"]["nonempty"] == 2


def test_profiles_handle_dict_columns_without_crashing():
    # WeaponTemplateTb stores stats as nested {prop_id, value} dicts — dicts are
    # unhashable, so the profiler must special-case them (regression for T2.2d).
    rows = [
        {"ID": 1, "STAT": {"P": 12101, "V": 32}},
        {"ID": 2, "STAT": {"P": 12101, "V": 48}},
    ]
    prof = columns.column_profiles(rows, "ID")
    assert prof["STAT"]["kind"] == "dict"
    assert prof["STAT"]["nonempty"] == 2
    assert prof["STAT"]["samples"][0] == {"P": 12101, "V": 32}


# ── nested_value_match (WeaponTemplateTb {prop_id, value} blocks, T2.2d) ──────
def test_nested_value_match_finds_value_inner_key():
    # STAT.V reproduces base_atk; STAT.P is the constant prop_id (no field match).
    rows = [
        {"ID": 1, "STAT": {"P": 12101, "V": 32}},
        {"ID": 2, "STAT": {"P": 12101, "V": 48}},
        {"ID": 3, "STAT": {"P": 12101, "V": 60}},
    ]
    anchors = {1: {"base_atk": 32}, 2: {"base_atk": 48}, 3: {"base_atk": 60}}
    res = columns.nested_value_match(rows, "ID", anchors, ["base_atk"], "STAT")
    assert res["V"]["best_field"] == "base_atk"
    assert res["V"]["ratio"] == 1.0
    assert res["P"]["ratio"] == 0.0  # prop_id reproduces nothing


def test_nested_value_match_ignores_unjoined_rows():
    rows = [
        {"ID": 1, "STAT": {"P": 1, "V": 10}},
        {"ID": 2, "STAT": {"P": 1, "V": 20}},
        {"ID": 9, "STAT": {"P": 1, "V": 99}},  # no anchor for id 9
    ]
    anchors = {1: {"val": 10}, 2: {"val": 20}}
    res = columns.nested_value_match(rows, "ID", anchors, ["val"], "STAT")
    assert res["V"]["joined"] == 2
    assert res["V"]["matches"] == 2
    assert res["V"]["ratio"] == 1.0


# ── BuffTemplateTb effect-spec parsing (T2.2c) ───────────────────────────────
def test_parse_spec_splits_effectkey_value_pairs():
    from scripts.dimbreath.build_column_dicts import _parse_spec

    assert _parse_spec("DamagePercentage:7.13") == ("DamagePercentage", "7.13")
    assert _parse_spec("MaxHitNum:16") == ("MaxHitNum", "16")
    assert _parse_spec("DamageValue:-0") == ("DamageValue", "-0")
    # not an effect-spec: attach-point enums, icon names, plain labels
    assert _parse_spec("ElementAbnormalAttachPoint_Default") is None
    assert _parse_spec("MiddlePoint") is None
    assert _parse_spec("") is None


# ── structural derivation: wrapper key + key column (issue #165) ─────────────
# Both were pinned as literal hashes, and both rotate per patch — the wrapper key moved
# `JKMFEMCLDNN` → `MLOEFHJHCID` between the two SHAs this repo has pinned, which made
# every builder die on a KeyError at its own pin. "Regenerate the column dictionary" is
# this toolkit's documented answer to a rotation, so a rotation must not be what stops it.
def test_wrapper_rows_finds_the_only_list_of_rows():
    doc = {"ANYHASHKEY": _ROWS, "version": 3, "tags": ["a", "b"]}
    assert columns.wrapper_rows(doc) is _ROWS


def test_wrapper_rows_refuses_an_ambiguous_shape():
    import pytest

    with pytest.raises(columns.TableShapeError):
        columns.wrapper_rows({"A": _ROWS, "B": [{"ID": 1}]})


def test_unique_key_column_finds_the_id_column():
    rows = [{"ID": 11, "CAT": 0, "NAME": "a"}, {"ID": 12, "CAT": 0, "NAME": "b"}]
    assert columns.unique_key_column(rows) == "ID"


def test_unique_key_column_breaks_a_tie_on_anchor_coverage():
    # Two all-unique int columns: the id, and an id-like sort index. Column order must
    # not decide this — joining on the wrong one poisons every value-match downstream.
    rows = [{"SORT": 1, "ID": 501}, {"SORT": 2, "ID": 502}, {"SORT": 3, "ID": 503}]
    assert columns.unique_key_column(rows, {501: {}, 502: {}, 503: {}}) == "ID"


def test_unique_key_column_refuses_a_tie_it_cannot_break():
    import pytest

    rows = [{"A": 1, "B": 10}, {"A": 2, "B": 20}]
    with pytest.raises(columns.TableShapeError):
        columns.unique_key_column(rows)
    with pytest.raises(columns.TableShapeError):
        columns.unique_key_column(rows, {77: {}})  # anchors join to neither column
