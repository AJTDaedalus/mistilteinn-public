"""Source too deeply nested to parse safely is refused before the parser recurses into it.

Security audit F4: `/rotations/validate` parses on every keystroke, and deep input drove the
recursive parser into `RecursionError` (a 500) or a response the serializer could not write.
"""

from __future__ import annotations

import pytest

from app.services.rotation_diagnostics import validate_rotation
from app.services.source_limits import (
    MAX_NESTING,
    MAX_OPERATORS_PER_STATEMENT,
    nesting_refusal,
)

HOSTILE = {
    "operator chain": "if " + "1+" * 5000 + "1 { }\n",
    "parentheses": "x = " + "(" * 500 + "1" + ")" * 500 + ";\n",
    "blocks": "if 1 {" * 500 + "}" * 500 + "\n",
    "unary chain": "x = " + "-" * 1000 + "1;\n",
    "unclosed": "(" * 5000,
}


@pytest.mark.parametrize("source", HOSTILE.values(), ids=HOSTILE.keys())
def test_deep_input_is_refused_by_name(source: str) -> None:
    assert nesting_refusal(source) is not None


@pytest.mark.parametrize(
    "source",
    [
        "",
        "barbara skill;",
        "if .x.burst.rea",
        (
            "while 1 {\n  if .noelle.energy >= 40 && .noelle.burst.ready {\n    noelle burst;\n"
            "  }\n  noelle attack:3;\n}\n"
        ),
        "x = " + "(" * (MAX_NESTING - 1) + "1" + ")" * (MAX_NESTING - 1) + ";\n",
        "x = " + "1+" * (MAX_OPERATORS_PER_STATEMENT - 1) + "1;\n",
        # Operators are counted per statement, so many short ones are fine.
        "x = 1 + 2;\n" * 2000,
    ],
)
def test_real_shaped_input_passes(source: str) -> None:
    assert nesting_refusal(source) is None


@pytest.mark.parametrize(
    "source",
    [
        "x = " + "(" * MAX_NESTING + "1" + ")" * MAX_NESTING + ";\n",
        "x = " + "1+" * MAX_OPERATORS_PER_STATEMENT + "1;\n",
    ],
)
def test_whatever_passes_the_check_parses_without_recursing_too_far(source: str) -> None:
    """The bounds are set where the parser and serializer are still comfortably safe."""
    if nesting_refusal(source) is None:
        tree, _ = validate_rotation(source, {})
        tree.model_dump_json()


def test_untokenizable_input_is_left_to_the_validator() -> None:
    """An unterminated string is a diagnostic for the editor, not a refusal from this check."""
    assert nesting_refusal('x = "unterminated') is None


def test_the_limits_from_real_configs_hold() -> None:
    """Every committed real config passes, so the bound costs no real rotation."""
    from pathlib import Path

    from app.services.gcsim_parser import split_config

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    configs = [p for p in fixtures.rglob("*.txt") if "gcsim" in str(p).lower()]
    for path in configs:
        _, source = split_config(path.read_text())
        assert nesting_refusal(source) is None, path
