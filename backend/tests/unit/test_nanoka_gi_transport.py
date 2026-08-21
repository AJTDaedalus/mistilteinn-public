"""D.1 — the nanoka GI transport layer: URL grammar, version pinning, retries, dry run.

These pin the shape of the source, which is the part of an importer that breaks without
anyone touching this repo. Nothing here reaches the network: the HTTP tests drive
`httpx.MockTransport`, and the importer tests use `FixtureTransport`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.data.importers.nanoka_gi_importer import (
    ENTITIES,
    USER_AGENT,
    HttpNanokaTransport,
    NanokaGIImporter,
    NanokaImportError,
    _batched,
    _index_keys,
)
from tests.unit.nanoka_transport import FixtureTransport

_MANIFEST = {"gi": {"latest": "7.0.51", "live": "7.0"}}


def _mock_http(handler) -> HttpNanokaTransport:
    """An `HttpNanokaTransport` whose client is backed by `handler` instead of a socket."""
    return HttpNanokaTransport(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_url_grammar_is_manifest_then_index_then_detail():
    """The three URL shapes, spelled out. `en/` is in the detail path only."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/manifest.json":
            return httpx.Response(200, json=_MANIFEST)
        return httpx.Response(200, json={"ok": True})

    transport = _mock_http(handler)
    await transport.fetch_index("character")
    await transport.fetch_detail("character", 10000002)

    assert seen == [
        "https://static.nanoka.cc/manifest.json",
        "https://static.nanoka.cc/gi/7.0.51/character.json",
        "https://static.nanoka.cc/gi/7.0.51/en/character/10000002.json",
    ]


async def test_version_is_pinned_once_for_the_whole_run():
    """One manifest fetch, however many entities — a run must not straddle two patches."""
    manifest_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal manifest_hits
        if request.url.path == "/manifest.json":
            manifest_hits += 1
            return httpx.Response(200, json=_MANIFEST)
        return httpx.Response(200, json={})

    transport = _mock_http(handler)
    for entity in ENTITIES:
        await transport.fetch_index(entity)

    assert manifest_hits == 1


async def test_an_explicit_version_skips_the_manifest_entirely():
    """`--version 7.0.50` must reproduce an old run, not re-pin to whatever is latest."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path != "/manifest.json"
        return httpx.Response(200, json={})

    transport = HttpNanokaTransport(
        version="7.0.50",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await transport.fetch_index("weapon")

    assert await transport.resolve_version() == "7.0.50"


async def test_a_500_is_retried_and_then_succeeds(monkeypatch):
    """Transient upstream failure must not abort a 1,100-request seed."""
    monkeypatch.setattr("app.data.importers.nanoka_gi_importer.asyncio.sleep", AsyncMock())
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"served": attempts})

    # Version pinned, so `attempts` counts index fetches only and not the manifest.
    transport = HttpNanokaTransport(
        version="7.0.51",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await transport.fetch_index("artifact") == {"served": 2}
    assert attempts == 2


async def test_a_404_is_not_retried(monkeypatch):
    """A 404 is an answer: the index listed an id the detail tree does not serve."""
    sleep = AsyncMock()
    monkeypatch.setattr("app.data.importers.nanoka_gi_importer.asyncio.sleep", sleep)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404)

    transport = HttpNanokaTransport(
        version="7.0.51",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await transport.fetch_detail("monster", 1)

    assert attempts == 1
    sleep.assert_not_awaited()


async def test_retries_are_bounded_and_the_last_error_is_raised(monkeypatch):
    """Three attempts, then give up loudly — never fall through to a half-fetched run."""
    monkeypatch.setattr("app.data.importers.nanoka_gi_importer.asyncio.sleep", AsyncMock())
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    transport = HttpNanokaTransport(
        version="7.0.51",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await transport.fetch_index("character")

    assert attempts == 3


async def test_dry_run_reports_index_counts_and_touches_no_session():
    """The D.1 acceptance criterion: all four indexes, counted, with nothing written."""
    session = MagicMock()
    transport = FixtureTransport(
        indexes={entity: {str(i): {} for i in range(3)} for entity in ENTITIES},
    )
    importer = NanokaGIImporter(session, transport=transport)

    summaries = await importer.dry_run()

    assert sorted(summaries) == sorted(ENTITIES)
    assert all(summary.total == 3 for summary in summaries.values())
    assert [call for call in transport.calls if call[0] == "detail"] == []
    session.assert_not_called()
    assert session.method_calls == []


async def test_dry_run_can_sample_one_detail_per_entity():
    """Index-only would pass against a broken detail URL; the `en/` segment differs."""
    session = MagicMock()
    transport = FixtureTransport.from_committed_fixtures()
    transport.indexes["monster"] = {}
    # Only three detail payloads are committed, and the artifact one (15025) is not the
    # index's lowest id — so trim each index to the entry we can actually serve rather
    # than letting the sample land on a payload nobody captured.
    for entity, key in (("character", "10000002"), ("weapon", "11501"), ("artifact", "15025")):
        transport.indexes[entity] = {key: transport.indexes[entity][key]}
    importer = NanokaGIImporter(session, transport=transport)

    summaries = await importer.dry_run(sample_details=True)

    assert summaries["monster"].total == 0
    # One detail sampled per non-empty index, and none for the empty one.
    assert [call for call in transport.calls if call[0] == "detail"] == [
        ("detail", "character", "10000002"),
        ("detail", "weapon", "11501"),
        ("detail", "artifact", "15025"),
    ]
    assert all(summary.ok for summary in summaries.values())
    assert [summary.sampled for summary in summaries.values()] == [1, 1, 1, 0]
    # A dry run writes nothing, so it must not report anything as imported either.
    assert [summary.imported for summary in summaries.values()] == [0, 0, 0, 0]
    assert session.method_calls == []


async def test_dry_run_records_a_failed_sample_instead_of_raising():
    """A dry run is a report. It says what is broken; it does not abort on the first gap."""
    transport = FixtureTransport(
        indexes={entity: {"7": {}} for entity in ENTITIES},
        details={},
        fail={(entity, "7") for entity in ENTITIES},
    )
    importer = NanokaGIImporter(MagicMock(), transport=transport)

    summaries = await importer.dry_run(sample_details=True)

    assert [summary.failed for summary in summaries.values()] == [["7"]] * len(ENTITIES)
    assert not any(summary.ok for summary in summaries.values())


@pytest.mark.parametrize(
    ("method", "task"),
    [
        ("import_weapons", "D.4"),
        ("import_artifact_sets", "D.5"),
        ("import_enemies", "D.6"),
    ],
)
async def test_unmapped_entity_passes_raise_and_name_their_task(method, task):
    """An unwritten mapping must not report zero rows imported.

    `import_characters` dropped off this list when D.3 wrote it; each of the remaining
    three leaves as its own task lands.
    """
    importer = NanokaGIImporter(MagicMock(), transport=FixtureTransport())

    with pytest.raises(NanokaImportError, match=task):
        await getattr(importer, method)()


async def test_close_releases_the_transport():
    transport = FixtureTransport()
    importer = NanokaGIImporter(MagicMock(), transport=transport)

    await importer.close()

    assert transport.closed


def test_index_keys_sort_numerically_and_keep_the_traveler_variant_suffix():
    """Nanoka's key order is JSON object order; a seed run has to be reproducible.

    The `-N` keys are the four Traveler bodies' seven elemental kits. Plain string order
    would put `10000101` before `10000005-2`, and `int(key)` would raise on it outright.
    """
    index = {
        "10000101": {}, "10000005-8": {}, "10000002": {}, "10000005-2": {}, "10000005": {},
    }

    assert _index_keys(index) == [
        "10000002", "10000005", "10000005-2", "10000005-8", "10000101",
    ]


def test_batched_preserves_order_and_the_final_short_window():
    assert list(_batched(["1", "2", "3", "4", "5"], 2)) == [["1", "2"], ["3", "4"], ["5"]]
    assert list(_batched([], 3)) == []


def test_every_committed_character_index_key_survives_the_sort():
    """No key is dropped or collapsed — 150 in, 150 out, including all 28 Traveler kits."""
    index = FixtureTransport.from_committed_fixtures().indexes["character"]

    keys = _index_keys(index)

    assert len(keys) == len(index) == 150
    assert sum("-" in key for key in keys) == 28


async def test_the_lazily_built_client_identifies_the_project_in_its_user_agent():
    """nanoka 403s urllib's default UA (LOG, C.2's "Operational note for D.1").

    Asserted on the client the transport builds for itself, not on an injected one — the
    injected client is the test seam, and the header has to be on the real path.
    """
    transport = HttpNanokaTransport(version="7.0.51")

    client = await transport._get_client()

    assert client.headers["user-agent"] == USER_AGENT
    await transport.close()
