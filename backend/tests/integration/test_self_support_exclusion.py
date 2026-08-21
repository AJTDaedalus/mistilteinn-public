"""A build occupying two team slots must not become its own support (issue #133).

The structural half of #133 lives in `tests/unit/test_no_index_only_support_selection.py`
— it fails if any call site re-derives the support list by slot index alone. This is the
behavioural half: proof that `select_support_members` is genuinely *wired into* the
pipelines rather than merely imported next to the old code.

**The team row has to be forged.** `TeamCreate`/`TeamUpdate` reject a duplicated build
(`assert_slots_distinct`, PR #125), which is exactly why this defect is latent — the only
rows that can reach it are ones written before that validation existed. So these tests
seed a valid team through the API and then rewrite `build2_id` directly, reproducing a
legacy row rather than pretending the API would produce one.

**The probe is `BuildSnapshot.folded_supports`**, added by #121: it records which builds
were folded into a snapshot. If the target is folded into its own scoring snapshot, its
own build id appears there — a direct, kit-independent assertion that does not depend on
which agent happens to own a `target=team` modifier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from tests.integration.test_rank_support_snapshot import (
    _optimize_payload,
    _patched_loaders,
    _rank_payload,
    _seed,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _duplicate_the_primary_into_slot_2(db: AsyncSession, seed: dict) -> None:
    """Forge the legacy row: the same build in slots 1 and 2.

    Raw UPDATE deliberately — going through the API is impossible by design since #125,
    and going through the ORM would still be a legitimate write path this test must not
    imply exists.
    """
    await db.execute(
        text("UPDATE teams SET build2_id = :bid WHERE id = :tid"),
        {"bid": seed["dps_build_id"], "tid": seed["team_id"]},
    )
    await db.flush()


def _folded_ids(snapshot) -> list[str]:
    return [build_id for build_id, _agent_name in snapshot.folded_supports]


async def test_rank_does_not_fold_the_primary_into_its_own_scoring_snapshot(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """`rank_pipeline`'s `_ctx_support_builds` — one of the seven original sites."""
    seed = await _seed(authed_client, db_session)
    await _duplicate_the_primary_into_slot_2(db_session, seed)

    with _patched_loaders():
        payload = await _rank_payload(db_session, seed)

    ctx = payload.contexts[0]
    assert seed["dps_build_id"] not in _folded_ids(ctx.scoring_base), (
        "the primary was folded into its own scoring snapshot as a support — its own "
        "target=team kit modifiers now count twice (issue #133)"
    )


async def test_optimizer_does_not_fold_the_primary_into_its_own_scoring_snapshot(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """`optimizer_pipeline`'s team_id branch — the site that has carried this longest."""
    seed = await _seed(authed_client, db_session)
    await _duplicate_the_primary_into_slot_2(db_session, seed)

    with _patched_loaders():
        payload = await _optimize_payload(db_session, seed)

    assert seed["dps_build_id"] not in _folded_ids(payload.scoring_snap)
    assert seed["dps_build_id"] not in _folded_ids(payload.scoring_base)


async def test_a_real_support_is_still_folded_in(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The must-not-over-exclude control.

    Without this, a helper that returned `[]` unconditionally would pass both tests
    above — and would silently reintroduce #121's defect 2 (supports dropped entirely).
    """
    seed = await _seed(authed_client, db_session)

    with _patched_loaders():
        payload = await _rank_payload(db_session, seed)

    folded = _folded_ids(payload.contexts[0].scoring_base)
    assert seed["support_build_id"] in folded, (
        "the genuine support stopped being folded in — over-exclusion reintroduces #121"
    )
    assert seed["dps_build_id"] not in folded


async def test_the_third_slot_survives_the_duplicate(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Excluding the self-duplicate must not take a legitimate teammate with it."""
    seed = await _seed(authed_client, db_session, with_second_support=True)
    await _duplicate_the_primary_into_slot_2(db_session, seed)

    with _patched_loaders():
        payload = await _rank_payload(db_session, seed)

    folded = _folded_ids(payload.contexts[0].scoring_base)
    assert seed["dps_build_id"] not in folded
    assert seed["support2_build_id"] in folded, (
        "slot 3 was dropped along with the duplicated slot 2"
    )
