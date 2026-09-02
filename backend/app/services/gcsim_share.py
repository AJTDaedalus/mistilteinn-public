"""Fetch a gcsim database entry's config, given the share link a user pastes.

## Why this exists

The importer already reads a pasted gcsim config into steps. The owner asked for the *link*
instead — `https://gcsim.app/db/kDHmWKmfgqtF` — because copying a config out of gcsim's viewer
is the tedious half of importing someone else's rotation.

## Why it is a server-side fetch and not a browser one

`https://gcsim.app/api/share/db/<id>` answers `200 application/json` with the whole run,
including `config_file` — the exact text the paste box takes. It sends **no
`Access-Control-Allow-Origin` header**, so a browser fetch from this app's origin is blocked.
The request has to be made by something that is not a browser.

## Why an id and never a URL

This takes an **id**, and builds the URL itself from a constant host. A service that fetches a
URL a user supplies is a request forgery primitive pointed at whatever this backend can reach —
its own database included. Parsing the link happens here too, so the only thing that ever
reaches an HTTP client is a string matching `SHARE_ID`.

## What it is not

**Not a simulation.** The owner's standing ruling is that this project does not push compute
to gcsim; this is one GET of a stored document per import, and the result is saved as steps in
this database, so nothing depends on gcsim after the import returns.

**Not a stable contract.** `/api/share/db/` is the route gcsim's own single-page app calls,
read out of its published bundle. It is undocumented and may change. That is survivable
precisely because the import is a one-time write: a break costs new imports, never saved ones,
and the paste box it sits beside is the fallback.
"""

from __future__ import annotations

import re
from typing import Protocol

import httpx

#: The host, as a constant. Never taken from the user — see the module docstring.
SHARE_HOST = "https://gcsim.app"

#: A share id as gcsim mints them. Anchored, because the whole safety argument is that nothing
#: but this shape reaches an HTTP client.
SHARE_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

#: The forms of link a user actually has to hand: the viewer, the short link, and the bare id.
_LINK = re.compile(
    r"^(?:https?://)?(?:www\.)?gcsim\.app/(?:db|sh)/(?P<id>[A-Za-z0-9_-]{6,64})/?(?:[?#].*)?$",
)

USER_AGENT = "mistilteinn/0.1 (+https://github.com/AJTDaedalus/mistilteinn) httpx"

#: A gcsim run is a few hundred KB — the owner's reference entry is 206 KB. This is a ceiling
#: against a surprise, not a limit anyone should meet.
MAX_BYTES = 8 * 1024 * 1024


class GcsimShareError(RuntimeError):
    """The link could not be turned into a config, with a reason a user can act on."""


def share_id(text: str) -> str:
    """The id inside whatever the user pasted — a link, a short link, or the id itself.

    Refuses anything else rather than guessing. A link to another host is the case worth
    naming: silently fetching gcsim's copy of an id scraped out of someone else's URL would be
    answering a question nobody asked.
    """
    candidate = text.strip()
    if not candidate:
        raise GcsimShareError("Paste a gcsim link, for example https://gcsim.app/db/kDHmWKmfgqtF")
    match = _LINK.match(candidate)
    if match:
        return match.group("id")
    if SHARE_ID.match(candidate):
        return candidate
    raise GcsimShareError(
        f"{candidate!r} is not a gcsim database link. It should look like "
        f"https://gcsim.app/db/kDHmWKmfgqtF, or be the id on the end of one.",
    )


class ShareTransport(Protocol):
    """How this reaches gcsim. A protocol so tests serve fixtures rather than the network."""

    async def fetch(self, entry_id: str) -> dict[str, object]:
        """The stored run for one share id."""
        ...


class HttpShareTransport:
    """The live transport: httpx against gcsim.app."""

    def __init__(self, *, timeout: float = 20.0, client: httpx.AsyncClient | None = None) -> None:
        self._timeout = timeout
        #: Injectable so a transport test can drive `httpx.MockTransport` rather than reach in
        #: and rebind a private attribute.
        self._client = client

    async def fetch(self, entry_id: str) -> dict[str, object]:
        """The stored run for one share id, refusing anything that is not one."""
        if not SHARE_ID.match(entry_id):
            raise GcsimShareError(f"{entry_id!r} is not a share id.")
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout, headers={"User-Agent": USER_AGENT},
        )
        try:
            response = await client.get(f"{SHARE_HOST}/api/share/db/{entry_id}")
        except httpx.HTTPError as exc:
            raise GcsimShareError(f"Could not reach gcsim.app: {exc}") from exc
        if response.status_code == httpx.codes.NOT_FOUND:
            raise GcsimShareError(
                f"gcsim has no database entry {entry_id!r}. Check the link is a /db/ one and "
                f"that the run is still published.",
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise GcsimShareError(
                f"gcsim answered {response.status_code} for {entry_id!r}.",
            )
        if len(response.content) > MAX_BYTES:
            raise GcsimShareError(
                f"gcsim's answer for {entry_id!r} is {len(response.content)} bytes, past the "
                f"{MAX_BYTES}-byte ceiling this fetch will hold.",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise GcsimShareError(
                f"gcsim's answer for {entry_id!r} was not JSON. The endpoint this reads is the "
                f"one its own app calls and is undocumented; paste the config instead.",
            ) from exc
        if not isinstance(body, dict):
            raise GcsimShareError(f"gcsim's answer for {entry_id!r} was not an object.")
        return body


async def fetch_config(text: str, transport: ShareTransport) -> str:
    """The gcsim config behind a share link, ready for the importer that already exists.

    Returns the `config_file` verbatim. Everything else in the payload — the statistics, the
    sample, the target details — is gcsim's answer to a question this app asks for itself.
    """
    entry_id = share_id(text)
    body = await transport.fetch(entry_id)
    config = body.get("config_file")
    if not isinstance(config, str) or not config.strip():
        raise GcsimShareError(
            f"gcsim's entry {entry_id!r} carries no config. Nothing here can be imported from "
            f"it; paste the config instead.",
        )
    return config
