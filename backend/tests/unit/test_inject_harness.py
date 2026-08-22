"""The injection harness must not be able to repeat the two mistakes that created it.

Both incidents were the *verification* being wrong rather than the code under test, which is
strictly worse: a broken test tells you nothing, a broken harness tells you something false.
So these are meta-tests — they check that the tool refuses to report, not that it reports
correctly.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from scripts.inject import BACKEND, Injection, Outcome, load_spec, run

if TYPE_CHECKING:
    from pathlib import Path

#: A throwaway module and its test, written per-test into `tests/_inject_tmp/`. Real files,
#: because the harness's whole job is editing files on disk and running pytest over them —
#: mocking that out would test something else.
_TMP = BACKEND / "tests" / "_inject_tmp"


@pytest.fixture
def sandbox() -> Path:
    _TMP.mkdir(exist_ok=True)
    (_TMP / "__init__.py").write_text("")
    (_TMP / "subject.py").write_text(
        "def clamp(value: int) -> int:\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    return value\n"
    )
    (_TMP / "test_subject.py").write_text(
        "from tests._inject_tmp.subject import clamp\n"
        "\n"
        "def test_negatives_clamp():\n"
        "    assert clamp(-5) == 0\n"
        "\n"
        "def test_positives_pass_through():\n"
        "    assert clamp(5) == 5\n"
    )
    yield _TMP
    # rmtree, not unlink: pytest leaves a `__pycache__` directory behind and iterating
    # children blindly raises IsADirectoryError on it.
    shutil.rmtree(_TMP, ignore_errors=True)


def _injection(old: str, new: str) -> Injection:
    return Injection(
        file="tests/_inject_tmp/subject.py",
        old=old,
        new=new,
        tests="tests/_inject_tmp/test_subject.py",
        describe="sandbox",
    )


# ── The refusals: the whole reason this exists ────────────────────────────────


def test_a_target_that_is_not_there_is_an_error_not_a_result(sandbox: Path):
    """Incident two: a drifted target printed a warning and then reported the suite result
    from running the **unmodified** file."""
    result = run(_injection("if value > 1000:", "if False:"))
    assert result.outcome is Outcome.ERROR
    assert "not found" in result.detail
    assert result.failures == ()


def test_an_ambiguous_target_is_an_error(sandbox: Path):
    """Mutating a different occurrence than intended yields a real result about the wrong
    thing, which is the hardest kind of wrong to notice."""
    (sandbox / "subject.py").write_text(
        "def a() -> int:\n    return 1\n\n\ndef b() -> int:\n    return 1\n"
    )
    result = run(_injection("return 1", "return 2"))
    assert result.outcome is Outcome.ERROR
    assert "appears 2 times" in result.detail


def test_a_suite_that_is_already_red_is_an_error(sandbox: Path):
    """Otherwise the injection takes credit for failures it had nothing to do with."""
    (sandbox / "test_subject.py").write_text(
        "def test_already_broken():\n    assert False\n"
    )
    result = run(_injection("if value < 0:", "if False:"))
    assert result.outcome is Outcome.ERROR
    assert "not green before" in result.detail


def test_the_file_is_restored_even_when_the_tests_fail(sandbox: Path):
    """Incident one: a revert that did not run left every later result measured against
    mutated source."""
    before = (sandbox / "subject.py").read_text()
    run(_injection("if value < 0:", "if False:"))
    assert (sandbox / "subject.py").read_text() == before


def test_the_file_is_restored_after_an_error_too(sandbox: Path):
    before = (sandbox / "subject.py").read_text()
    run(_injection("nonexistent", "x"))
    assert (sandbox / "subject.py").read_text() == before


# ── The verdicts ──────────────────────────────────────────────────────────────


def test_a_mutation_the_tests_catch_is_caught(sandbox: Path):
    result = run(_injection("if value < 0:", "if False:"))
    assert result.outcome is Outcome.CAUGHT
    assert any("test_negatives_clamp" in f for f in result.failures)


def test_a_mutation_nothing_notices_is_reported_as_survived(sandbox: Path):
    """The finding that matters: a guard with no test on it.

    Renaming an unused local changes real code and no test can see it — which is correct
    here, and is exactly what SURVIVED is for elsewhere.
    """
    (sandbox / "subject.py").write_text(
        "def clamp(value: int) -> int:\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    unused = 1\n"
        "    return value\n"
    )
    result = run(_injection("unused = 1", "unused = 999"))
    assert result.outcome is Outcome.SURVIVED
    assert result.failures == ()


def test_the_exit_codes_make_a_surviving_mutation_a_failure():
    """Inverted from the usual on purpose: the thing worth failing over is a suite that did
    not notice."""
    assert Outcome.CAUGHT.exit_code == 0
    assert Outcome.SURVIVED.exit_code == 1
    assert Outcome.ERROR.exit_code == 2


# ── Specs ─────────────────────────────────────────────────────────────────────


def test_a_spec_missing_a_field_is_refused(tmp_path: Path):
    spec = tmp_path / "spec.json"
    spec.write_text('[{"file": "a.py", "old": "x", "new": "y"}]')
    with pytest.raises(Exception, match="missing"):
        load_spec(spec)


def test_a_spec_round_trips(tmp_path: Path):
    spec = tmp_path / "spec.json"
    spec.write_text(
        '[{"file": "a.py", "old": "x", "new": "y", "tests": "t", "describe": "d"}]'
    )
    loaded = load_spec(spec)
    assert loaded[0].describe == "d"
    assert loaded[0].tests == "t"
