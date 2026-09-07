"""The teapot tracker's ranking — `TASKS_account_tracking.md` 3.7."""
from __future__ import annotations

from app.services import teapot
from app.services.teapot import SuiteProgress, progress_for, rank


def suite(sid: str, name: str, favorite: list[str]) -> dict:
    return {"id": sid, "name": name, "icon": "", "placement": "I", "favorite": favorite}


def test_the_three_states_are_exclusive_and_complete() -> None:
    """**Owner's model, 2026-09-03**: a character is available-and-owned, completed-and-owned,
    or available-and-not-owned. Every favouring character is in exactly one."""
    rows = progress_for(
        [suite("s1", "Camp", ["a", "b", "c"])], {"a", "b"}, {("s1", "b")},
    )
    row = rows[0]

    assert row.available == ("a",)          # owned, not yet invited — worth 20
    assert row.completed == ("b",)          # owned, already invited — worth nothing more
    assert row.unowned == ("c",)            # favours it, you do not have them
    assert set(row.available) | set(row.completed) | set(row.unowned) == {"a", "b", "c"}


def test_only_available_owned_characters_are_worth_anything() -> None:
    """The whole reason `builds.owned` exists: a set favoured by three characters you do not
    have is worth nothing to you."""
    rows = progress_for([suite("s1", "Camp", ["a", "b", "c"])], {"a"}, set())

    assert rows[0].available == ("a",)
    assert rows[0].unowned == ("b", "c")
    assert rows[0].remaining == 1


def test_a_set_is_done_only_when_every_owned_favourite_is_invited() -> None:
    both = progress_for(
        [suite("s1", "Camp", ["a", "b"])], {"a", "b"}, {("s1", "a"), ("s1", "b")},
    )
    one = progress_for([suite("s1", "Camp", ["a", "b"])], {"a", "b"}, {("s1", "a")})

    assert both[0].done is True
    assert both[0].remaining == 0
    assert one[0].done is False
    assert one[0].remaining == 1, "the second character is still worth inviting"


def test_a_set_can_be_done_for_you_and_still_list_characters_you_lack() -> None:
    """`done` means nothing left *to claim*, not every favouring character invited."""
    rows = progress_for([suite("s1", "Camp", ["a", "b"])], {"a"}, {("s1", "a")})

    assert rows[0].done is True
    assert rows[0].unowned == ("b",)


def test_inviting_a_character_to_one_set_leaves_their_other_set_owed() -> None:
    """**The bug the per-set key had.** A character favours two sets and each is worth its own
    reward, so a tick on one must not silently finish the other."""
    rows = progress_for(
        [suite("s1", "One", ["a"]), suite("s2", "Two", ["a"])], {"a"}, {("s1", "a")},
    )
    by_name = {row.name: row for row in rows}

    assert by_name["One"].done is True
    assert by_name["Two"].remaining == 1


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
        [suite("s1", "Done", ["a", "b"]), suite("s2", "Todo", ["a"])],
        {"a", "b"},
        {("s1", "a"), ("s1", "b")},
    )

    assert [row.name for row in rows] == ["Todo", "Done"]


def test_ties_break_on_name_so_the_list_does_not_shuffle() -> None:
    """An order that changes between loads is one a reader stops trusting."""
    # Keyword arguments, so the row gaining a field is a compile error in this file rather
    # than a silent reshuffle of what each position means.
    rows = rank([
        SuiteProgress(suite_id="2", nanoka_id="2", name="Beta", icon="", placement="I",
                      available=("a",), completed=(), unowned=()),
        SuiteProgress(suite_id="1", nanoka_id="1", name="Alpha", icon="", placement="I",
                      available=("a",), completed=(), unowned=()),
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
    # Two owned favourites, neither invited: two rewards, because it is per character per set.
    assert rows[0].remaining_primogems == 40


def test_an_invited_character_is_worth_nothing_more() -> None:
    """The reward is once **per character per set**, so a tick removes exactly that
    character's 20 primogems and leaves the rest."""
    rows = progress_for([suite("s1", "Camp", ["a", "b"])], {"a", "b"}, {("s1", "a")})

    assert rows[0].remaining_primogems == 20


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


# ── built is a separate axis from invited ───────────────────────────────────


def test_a_set_can_be_built_with_nobody_invited() -> None:
    """Owner: *"it takes time and effort to build them so that's different from the
    invites."* Building and inviting are separate work and neither implies the other."""
    rows = progress_for([suite("s1", "Camp", ["a"])], {"a"}, set(), {"s1"})

    assert rows[0].built is True
    assert rows[0].remaining == 1, "building it does not invite anybody"


def test_a_set_can_be_fully_invited_without_being_marked_built() -> None:
    """The user may simply not have told us. An inferred `built` would be a claim the data
    does not support."""
    rows = progress_for([suite("s1", "Camp", ["a"])], {"a"}, {("s1", "a")}, set())

    assert rows[0].built is False
    assert rows[0].done is True


def test_at_equal_reward_the_set_already_built_comes_first() -> None:
    """**A real preference, not a tidy-up.** Two sets worth 40 primogems are not equal work
    if one is already standing in your teapot and the other needs materials."""
    rows = progress_for(
        [suite("s1", "Zzz Unbuilt", ["a", "b"]), suite("s2", "Aaa Built", ["a", "b"])],
        {"a", "b"},
        set(),
        {"s2"},
    )

    assert [row.name for row in rows] == ["Aaa Built", "Zzz Unbuilt"]


def test_being_built_never_outranks_a_bigger_reward() -> None:
    """The primary order is still gains for this user; built is only a tie-break."""
    rows = progress_for(
        [suite("s1", "Built But Small", ["a"]), suite("s2", "Unbuilt But Big", ["a", "b"])],
        {"a", "b"},
        set(),
        {"s1"},
    )

    assert [row.name for row in rows] == ["Unbuilt But Big", "Built But Small"]


def test_ordering_counts_only_characters_this_user_owns_and_has_not_invited() -> None:
    """The owner's headline ask: *"ordering by the highest-gains sets for a given user."*

    A set favoured by six characters you do not have ranks below one favoured by a single
    character you do.
    """
    rows = progress_for(
        [
            suite("s1", "Six You Lack", ["p", "q", "r", "s", "t", "u"]),
            suite("s2", "One You Have", ["a"]),
        ],
        {"a"},
        set(),
        set(),
    )

    assert [row.name for row in rows] == ["One You Have", "Six You Lack"]


# ── the capture's own shape ─────────────────────────────────────────────────


def test_every_favouring_character_favours_exactly_two_sets() -> None:
    """**Read off the committed capture, not off a database.**

    The first version of this asked the *test* database, which has no seeded suites — so it
    counted zero characters, found zero violations, and passed by measuring nothing. This repo
    has shipped that exact shape before.

    The invariant belongs to the capture: all 116 characters with a favourite have exactly
    two, which is what the wiki's *"up to 40 Primogems per character"* means and why progress
    is keyed per character per set. A capture that broke this would change what the tracker
    counts.
    """
    import json
    from collections import Counter
    from pathlib import Path

    published = json.loads(
        (Path("app/data/teapot/suite.json")).read_text(encoding="utf-8"),
    )
    per_character = Counter(
        character
        for entry in published.values()
        for character in (entry.get("favorite") or [])
    )

    assert per_character, "the capture names no favourites at all — it is not being read"
    assert len(per_character) == 116
    odd = {c: n for c, n in per_character.items() if n != 2}
    assert not odd, f"these characters favour a number of sets other than two: {odd}"
