"""Every action gcsim defines is either authorable here or reviewed as not a move.

Owner ruling, 2026-09-19: *we need to make sure we support all moves gcsim does; if the new
special attack isn't supported, we can't just ignore it.*

The gap this closes is narrow and was live. `authorable_actions()` used to derive from
gcsim's action **enum** (`astr` in `pkg/core/action/action.go`), on the assumption that the
enum and the config vocabulary were the same list. They are not: gcsim `1de5a4243` added
`special_skill` to the enum and **not** to the tokenizer's table
(`pkg/gcs/ast/keys.go`), so a re-pin would have offered every character an action that
gcsim's own parser then refuses with `unexpected token`.

Filtering it out silently would have been the other failure — the next enum entry might be a
real move, and nothing would have said so. So the rule is a partition: authorable, or listed
with a reason.
"""

from __future__ import annotations

import pytest

from app.services import gcsim_keys
from app.services.gcsim_keys import (
    authorable_actions,
    gcsim_actions,
    parser_actions,
    unauthorable_actions,
)


def test_the_partition_is_total():
    """No enum entry is unaccounted for.

    This is the test a future gcsim action trips. It fails on the *new* name, which is what
    sends a reader to gcsim's source to decide whether it is a move.
    """
    unaccounted = set(gcsim_actions()) - set(parser_actions()) - set(unauthorable_actions())

    assert not unaccounted, (
        f"gcsim's action enum gained {sorted(unaccounted)}, which its parser does not accept "
        f"and nothing here has ruled on. Read the kit that uses it: if a config can name it, "
        f"it belongs in the parser's table (and this test will pass once the snapshot is "
        f"rebuilt); if it is internal bookkeeping, add it to `_NOT_A_MOVE` with the reason."
    )


def test_the_partition_is_exclusive():
    """Nothing is both authorable and excused, which would make the reason a lie."""
    both = set(parser_actions()) & set(unauthorable_actions())

    assert not both, f"{sorted(both)} is in the parser's table and on the not-a-move list"


def test_every_offered_action_is_one_the_parser_accepts():
    """The direction that matters: we never offer what gcsim would reject."""
    assert set(authorable_actions()) <= set(parser_actions())


def test_special_skill_is_excused_rather_than_merely_absent():
    """The case that prompted the rule, asserted so it holds on both sides of the re-pin.

    `special_skill` is a cooldown bucket. Varka's Four Winds is authored as `charge` and
    Odette's recast as `skill`; both dispatch internally, and neither needs a new action.

    It entered gcsim's enum in `1de5a4243`, which is **after the pin this test was written
    at**. So the ruling is asserted here (it is excused, and never offered) rather than its
    presence in the enum — which `test_the_partition_is_total` covers the moment the pin
    moves and the snapshot carries it.
    """
    assert "special_skill" not in parser_actions(), "gcsim's tokenizer has no such token"
    assert "special_skill" not in authorable_actions()
    assert "cooldown bucket" in unauthorable_actions()["special_skill"]


@pytest.mark.parametrize("reason", unauthorable_actions().values())
def test_each_excuse_says_something(reason: str):
    """A reason short enough to be a label is a reason nobody had to think about."""
    assert len(reason) > 40


def test_a_new_enum_action_fails_the_partition(monkeypatch: pytest.MonkeyPatch):
    """Plant the failure and run **the real check** against it.

    Without this, `test_the_partition_is_total` passes on every input it can currently be
    given — and a check that can only return one answer is not a check. Note what is
    patched: the snapshot itself, so the assertion under test runs through the same
    `gcsim_actions()` it always does. Re-implementing the set arithmetic here would prove
    only that subtraction works.
    """
    planted = dict(gcsim_keys._snapshot())
    planted["actions"] = [*planted["actions"], "relic_skill"]
    monkeypatch.setattr(gcsim_keys, "_snapshot", lambda: planted)

    assert "relic_skill" in gcsim_actions(), "the plant did not reach the function under test"

    with pytest.raises(AssertionError, match="relic_skill"):
        test_the_partition_is_total()
