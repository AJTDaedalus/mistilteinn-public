"""`builds.owned` — Track 1 of `TASKS_account_tracking.md`.

Owner: *"Builds should have a 'owned' boolean … when imported they default to owned=True.
This way we know which units they actually have on their account and which they've just made
to test."*
"""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.build import BuildCreate, BuildRead, BuildUpdate
from app.services.good_build_service import _new_build


def _create(**over) -> BuildCreate:
    base = {"character_id": "01a00000-0000-7000-8000-000000000001"}
    return BuildCreate(**{**base, **over})


def test_a_build_is_owned_unless_the_user_says_otherwise() -> None:
    """A GOOD export is a record of gear the player has, and that is how nearly every build
    arrives. A build made to try something out is the case a user opts *into*."""
    assert _create().owned is True


def test_a_test_build_can_say_so_at_creation() -> None:
    assert _create(owned=False).owned is False


def test_update_leaves_ownership_alone_unless_it_is_sent() -> None:
    """`None` means "not mentioned" — a PATCH that omits it must not reclassify the build."""
    assert BuildUpdate().owned is None


def test_update_can_toggle_it() -> None:
    assert BuildUpdate(owned=False).owned is False


def test_a_read_always_carries_it() -> None:
    """The build page needs it on every row to draw the toggle; a missing key would read as
    "we did not look" rather than "this is owned"."""
    assert "owned" in BuildRead.model_fields


def test_an_imported_build_is_owned() -> None:
    """**Asserted on the object the importer builds, not on the schema default.**

    A later change to the column default must not silently reclassify every imported build.
    An imported build is owned because a GOOD export records gear the player actually has —
    a fact about this code path rather than about the schema, so it is tested here.
    """
    character = SimpleNamespace(id="c1", name="Noelle", element="geo")
    build = _new_build(
        owner_id="u1", character=character, entry=None, weapon=None, wielded=None,
        source="a GOOD export", ambiguous=False,
    )

    assert build.owned is True
