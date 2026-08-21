"""Tests for Pando node IR.

Nodes are frozen dataclasses describing the DAG. They hold no computed
values — evaluation is the Calculator's job. Tests here verify shape,
immutability, equality semantics, and the ``op`` discriminator.
"""

from __future__ import annotations

import pytest

from app.formula.nodes import (
    Const,
    Custom,
    Lookup,
    Match,
    Max,
    Min,
    Prod,
    Read,
    ReRead,
    Subscript,
    Sum,
    SumFrac,
    TagOverride,
    TagValRead,
    Threshold,
)
from app.formula.tags import Tag


class TestConst:
    def test_number_const(self) -> None:
        n = Const(ex=42)
        assert n.op == "const"
        assert n.ex == 42
        assert n.x == ()

    def test_string_const(self) -> None:
        n = Const(ex="hello")
        assert n.ex == "hello"

    def test_equality(self) -> None:
        assert Const(ex=1) == Const(ex=1)
        assert Const(ex=1) != Const(ex=2)

    def test_frozen(self) -> None:
        n = Const(ex=1)
        with pytest.raises(AttributeError):
            n.ex = 2  # type: ignore[misc]


class TestArithmetic:
    @pytest.mark.parametrize(
        ("cls", "op_name"),
        [(Sum, "sum"), (Prod, "prod"), (Min, "min"), (Max, "max"), (SumFrac, "sumfrac")],
    )
    def test_op_discriminators(self, cls: type, op_name: str) -> None:
        n = cls(x=(Const(ex=1), Const(ex=2)))
        assert n.op == op_name
        assert len(n.x) == 2


class TestBranching:
    def test_threshold_has_br_and_x(self) -> None:
        n = Threshold(
            br=(Const(ex=5), Const(ex=3)),
            x=(Const(ex="high"), Const(ex="low")),
        )
        assert n.op == "thres"
        assert len(n.br) == 2
        assert len(n.x) == 2

    def test_match_op(self) -> None:
        n = Match(
            br=(Const(ex="a"), Const(ex="a")),
            x=(Const(ex=1), Const(ex=0)),
        )
        assert n.op == "match"

    def test_lookup_ex_is_dict(self) -> None:
        table: dict[str, int] = {"fire": 0, "ice": 1}
        n = Lookup(
            br=(Const(ex="fire"),),
            x=(Const(ex=10), Const(ex=20), Const(ex=30)),
            ex=table,
        )
        assert n.op == "lookup"
        assert n.ex == table

    def test_subscript_array(self) -> None:
        n = Subscript(br=(Const(ex=2),), ex=(100, 200, 300))
        assert n.op == "subscript"
        assert n.ex == (100, 200, 300)


class TestTagNodes:
    def test_tag_override(self) -> None:
        tag = Tag.of(src="Anby")
        n = TagOverride(x=(Const(ex=5),), tag=tag)
        assert n.op == "tag"
        assert n.tag == tag

    def test_vtag_reads_category(self) -> None:
        n = TagValRead(ex="src")
        assert n.op == "vtag"
        assert n.ex == "src"


class TestRead:
    def test_read_has_tag_and_accumulator(self) -> None:
        tag = Tag.of(q="atk_")
        n = Read(tag=tag, ex="sum")
        assert n.op == "read"
        assert n.tag == tag
        assert n.ex == "sum"

    def test_read_default_accumulator_is_none(self) -> None:
        n = Read(tag=Tag.of(q="atk"))
        assert n.ex is None  # Calculator infers 'unique' or per-tag default

    def test_reread_forwards_to_tag(self) -> None:
        tag = Tag.of(src="Anby")
        n = ReRead(tag=tag)
        assert n.op == "reread"
        assert n.tag == tag


class TestCustom:
    def test_custom_carries_name(self) -> None:
        n = Custom(x=(Const(ex=1),), ex="floor")
        assert n.op == "custom"
        assert n.ex == "floor"


class TestNodeHashability:
    """Nodes must hash by value so the calculator can memoize on them."""

    def test_identical_consts_hash_equal(self) -> None:
        assert hash(Const(ex=1)) == hash(Const(ex=1))

    def test_identical_sums_hash_equal(self) -> None:
        a = Sum(x=(Const(ex=1), Const(ex=2)))
        b = Sum(x=(Const(ex=1), Const(ex=2)))
        assert hash(a) == hash(b)
