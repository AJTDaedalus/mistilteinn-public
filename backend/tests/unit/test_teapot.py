"""The teapot tracker's ranking — `TASKS_account_tracking.md` 3.7."""
from __future__ import annotations

from app.services import teapot
from app.services.teapot import SuiteProgress, progress_for, rank


def suite(sid: str, name: str, favorite: list[str]) -> dict:
    return {"id": sid, "name": name, "icon": "", "placement": "I", "favorite": favorite}


def test_only_owned_characters_count_toward_a_set() -> None:
    """The whole reason `builds.owned` exists: a set favoured by three characters you do not
    have is worth nothing to you."""
    rows = progress_for([suite("s1", "Camp", ["a", "b", "c"])], {"a"}, set())

    assert rows[0].owned_favorites == ("a",)
    assert rows[0].unowned_favorites == ("b", "c")
    assert rows[0].remaining == 1


def test_a_finished_set_has_nothing_remaining() -> None:
    rows = progress_for([suite("s1", "Camp", ["a", "b"])], {"a", "b"}, {"s1"})

    assert rows[0].done is True
    assert rows[0].remaining == 0


def test_the_most_worth_doing_comes_first() -> None:
    rows = progress_for(
        [suite("s1", "One", ["a"]), suite("s2", "Two", ["a", "b", "c"])],
        {"a", "b", "c"},
        set(),
    )

    assert [row.name for row in rows] == ["Two", "One"]


def test_finished_sets_sink_rather_than_disappear() -> None:
    """Seelie's affordance is *mark it off*, not *delete it* — a user has to be able to see
    what they have done, and unmark one they ticked by mistake."""
    rows = progress_for(
        [suite("s1", "Done", ["a", "b"]), suite("s2", "Todo", ["a"])], {"a", "b"}, {"s1"},
    )

    assert [row.name for row in rows] == ["Todo", "Done"]


def test_ties_break_on_name_so_the_list_does_not_shuffle() -> None:
    """An order that changes between loads is one a reader stops trusting."""
    rows = rank([
        SuiteProgress("2", "Beta", "", "I", ("a",), (), False),
        SuiteProgress("1", "Alpha", "", "I", ("a",), (), False),
    ])

    assert [row.name for row in rows] == ["Alpha", "Beta"]


def test_the_reward_is_twenty_primogems_per_character() -> None:
    """**Cited, not remembered** (OQ-A4). Two independent sources agree that inviting a
    companion to a set they favour gives 20 Primogems, once per set — GameWith and the
    Genshin Impact Wiki, both linked at the constant.

    Pinned here so a later edit has to disagree with a test rather than with a comment.
    """
    rows = progress_for([suite("s1", "Camp", ["a", "b"])], {"a", "b"}, set())

    assert teapot.REWARD_PER_CHARACTER == 20
    assert rows[0].remaining_primogems == 40


def test_a_finished_set_is_worth_nothing_more() -> None:
    """The reward is **one-time per set**, which is what makes `teapot_progress` a done flag
    rather than a cooldown."""
    rows = progress_for([suite("s1", "Camp", ["a"])], {"a"}, {"s1"})

    assert rows[0].remaining_primogems == 0


def test_the_order_is_the_same_one_the_reward_would_give(monkeypatch) -> None:
    """**The sort does not wait on the citation.**

    The reward is one constant for every character, so `reward × remaining` and `remaining`
    order identically — a positive constant multiplier cannot change a ranking. When the
    constant arrives it changes the number on screen and not one row's position.
    """
    catalogue = [
        suite("s1", "One", ["a"]),
        suite("s2", "Two", ["a", "b"]),
        suite("s3", "Three", ["a", "b", "c"]),
    ]
    without = [row.suite_id for row in progress_for(catalogue, {"a", "b", "c"}, set())]

    monkeypatch.setattr(teapot, "REWARD_PER_CHARACTER", 999)
    rows = progress_for(catalogue, {"a", "b", "c"}, set())

    assert [row.suite_id for row in rows] == without
    assert rows[0].remaining_primogems == 3 * 999
