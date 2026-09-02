"""The gcsim share-link importer: what it accepts, what it refuses, and what it fetches.

Every test here runs in the unit lane, where `socket.connect` is blocked — so a transport that
reached the network would fail rather than pass slowly.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.gcsim_share import (
    MAX_BYTES,
    GcsimShareError,
    HttpShareTransport,
    fetch_config,
    share_id,
)

CONFIG = 'skirk char lvl=90/90;\nskirk attack;\n'


class _Fixture:
    """A transport that serves one payload, and records what it was asked for."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.asked: list[str] = []

    async def fetch(self, entry_id: str) -> dict[str, object]:
        self.asked.append(entry_id)
        return self.payload


@pytest.mark.parametrize("text", [
    "https://gcsim.app/db/kDHmWKmfgqtF",
    "http://gcsim.app/db/kDHmWKmfgqtF",
    "https://www.gcsim.app/db/kDHmWKmfgqtF",
    "gcsim.app/db/kDHmWKmfgqtF",
    "https://gcsim.app/sh/kDHmWKmfgqtF",
    "https://gcsim.app/db/kDHmWKmfgqtF/",
    "https://gcsim.app/db/kDHmWKmfgqtF?utm=x",
    "kDHmWKmfgqtF",
])
def test_the_forms_of_link_a_user_actually_has_to_hand(text: str) -> None:
    """A viewer link, its short form, a trailing slash, tracking junk, or the bare id."""
    assert share_id(text) == "kDHmWKmfgqtF"


@pytest.mark.parametrize("text", [
    "https://evil.example/db/kDHmWKmfgqtF",
    # **The one worth naming.** A host that merely *starts* with gcsim.app is a different host,
    # and an unanchored match would have fetched from it.
    "http://gcsim.app.evil.example/db/kDHmWKmfgqtF",
    "https://notgcsim.app/db/kDHmWKmfgqtF",
    "https://gcsim.app/db/../../etc/passwd",
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
    "",
    "   ",
])
def test_anything_that_is_not_a_gcsim_link_is_refused(text: str) -> None:
    """The safety argument is that only a share id ever reaches an HTTP client."""
    with pytest.raises(GcsimShareError):
        share_id(text)


async def test_the_config_comes_back_verbatim() -> None:
    """`config_file` is exactly what the paste box takes, so it is handed over untouched."""
    transport = _Fixture({"config_file": CONFIG, "statistics": {"dps": {"mean": 1}}})

    assert await fetch_config("https://gcsim.app/db/kDHmWKmfgqtF", transport) == CONFIG
    assert transport.asked == ["kDHmWKmfgqtF"]


async def test_an_entry_with_no_config_is_refused_rather_than_returned_empty() -> None:
    """An empty string would reach the parser and be refused there, naming nothing useful."""
    with pytest.raises(GcsimShareError, match="carries no config"):
        await fetch_config("kDHmWKmfgqtF", _Fixture({"statistics": {}}))


async def test_a_config_that_is_not_a_string_is_refused() -> None:
    """The endpoint is undocumented, so its shape is checked rather than assumed."""
    with pytest.raises(GcsimShareError, match="carries no config"):
        await fetch_config("kDHmWKmfgqtF", _Fixture({"config_file": {"nested": True}}))


async def test_the_transport_builds_its_own_url_from_a_constant_host() -> None:
    """The whole request-forgery argument, asserted rather than described.

    Nothing a user types reaches the client: the id is all that survives parsing, and the
    host comes from a constant in the module.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"config_file": CONFIG})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpShareTransport(client=client)

    assert await fetch_config("https://gcsim.app/db/kDHmWKmfgqtF", transport) == CONFIG
    assert seen == ["https://gcsim.app/api/share/db/kDHmWKmfgqtF"]
    await client.aclose()


async def test_a_missing_entry_says_so_rather_than_failing_generically() -> None:
    """404 is the case a user can act on: wrong link, or an unpublished run."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, text="not found")),
    )
    with pytest.raises(GcsimShareError, match="no database entry"):
        await fetch_config("kDHmWKmfgqtF", HttpShareTransport(client=client))
    await client.aclose()


async def test_a_body_past_the_ceiling_is_refused_before_it_is_parsed() -> None:
    """A ceiling against a surprise. The owner's reference entry is 206 KB."""
    body = "x" * (MAX_BYTES + 1)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)),
    )
    with pytest.raises(GcsimShareError, match="ceiling"):
        await fetch_config("kDHmWKmfgqtF", HttpShareTransport(client=client))
    await client.aclose()


async def test_a_network_failure_names_gcsim_rather_than_leaking_httpx() -> None:
    """"Could not reach gcsim.app" is actionable; a ConnectError traceback is not."""
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(GcsimShareError, match=r"Could not reach gcsim\.app"):
        await fetch_config("kDHmWKmfgqtF", HttpShareTransport(client=client))
    await client.aclose()
