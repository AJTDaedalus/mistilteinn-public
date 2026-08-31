"""An empty `ids` list means *no artifacts*, and must never read as *no filter*.

This lives at the repository layer because that is the only place the distinction is
expressible: over HTTP, `?ids=` binds to `[""]` and omitting it binds to `None`, so a caller
cannot hand the route a literal `[]`. Python callers can, and `if ids:` would have answered
"give me none of them" with the entire inventory.

No database: the assertion is about the SQL that gets built, so compiling the statement is
both sufficient and faster than a fixture.
"""

from __future__ import annotations

from app.repositories.artifact import ArtifactRepository


def _where(ids: list[str] | None) -> str:
    repo = ArtifactRepository.__new__(ArtifactRepository)
    repo.owner_id = None
    stmt = repo._filtered(slot=None, set_id=None, equipped=None, ids=ids)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_an_empty_id_list_still_constrains_the_query() -> None:
    assert "WHERE" in _where([])


def test_a_missing_id_list_does_not_constrain_the_query() -> None:
    # The other half. Without it, "always add the clause" would pass the test above and break
    # every unfiltered listing.
    assert "WHERE" not in _where(None)


def test_named_ids_are_matched_by_id() -> None:
    built = _where(["a", "b"])

    assert "artifacts.id IN" in built
    assert "'a'" in built
    assert "'b'" in built
