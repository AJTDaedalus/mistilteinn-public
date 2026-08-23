"""mistilteinn and fairy share a host. These are the properties that make that safe.

Owner ruling (2026-08-22): deploy alongside fairy, as `mistilteinn.aetherus.dev` and
`fairy.aetherus.dev`. Co-existence is not automatic, and one of its failure modes already
happened here once.

**The recorded hazard.** Chunk A joined fairy's compose network to reach its Postgres, which
registered this backend under the alias `backend` on `fairy_default` — where fairy's own
`backend` service already lives. fairy's tunnel then intermittently served mistilteinn's API.
Both projects name a service `backend`, so the collision is guaranteed rather than unlucky,
and **nothing fails**: traffic simply reaches the wrong application.

A comment saying "do not join that network" is what the repo had. This is the executable
version, because the whole session's pattern is that an instruction nobody can run is an
instruction that eventually is not followed.

Read through `docker compose config`, which is what the daemon actually sees — the merged
result of the base and prod files, with `!reset` applied. Parsing the YAML by hand would
check a document Docker never uses.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

REPO = __import__("pathlib").Path(__file__).resolve().parents[3]

#: Placeholders. `docker compose config` interpolates before it validates, and an unset
#: variable is a warning plus an empty string — which would make these assertions pass for
#: the wrong reason.
ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/mistilteinn",
    "TEST_DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/mistilteinn_test",
    "CLOUDFLARE_TUNNEL_TOKEN": "placeholder",
    "POSTGRES_USER": "mistilteinn",
    "POSTGRES_PASSWORD": "placeholder",
    "POSTGRES_DB": "mistilteinn",
}


def _config() -> dict:
    import os

    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [
            shutil.which("docker") or "docker", "compose",
            "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
            "config", "--format", "json",
        ],
        cwd=REPO, capture_output=True, text=True, check=False,
        env={**os.environ, **ENV},
    )
    if result.returncode != 0:
        pytest.fail(f"`docker compose config` failed:\n{result.stderr}")
    return json.loads(result.stdout)


pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker is not installed on this machine",
)


def test_the_prod_stack_publishes_no_host_ports():
    """Nothing on the host means nothing to collide with fairy over.

    The dev ports (8001/4201) were chosen so both stacks run at once locally. In prod
    neither publishes anything and cloudflared reaches nginx over the project network, so
    the question does not arise — provided it stays that way.
    """
    published = {
        name: service["ports"]
        for name, service in _config()["services"].items()
        if service.get("ports")
    }
    assert not published, (
        f"these services publish host ports in production: {published}. Prod reaches nginx "
        f"through its own cloudflared over the project network; a host port is both "
        f"unnecessary and a way to collide with the other stack on this box."
    )


def test_the_stack_joins_no_external_network():
    """The recorded hazard, as a check.

    An `external: true` network here would almost certainly be fairy's, and the alias
    collision on `backend` follows immediately.
    """
    external = {
        name: net
        for name, net in (_config().get("networks") or {}).items()
        if net and net.get("external")
    }
    assert not external, (
        f"the prod stack joins external network(s) {sorted(external)}. Chunk A did this to "
        f"reach fairy's Postgres and fairy's tunnel began serving mistilteinn's API, "
        f"because both projects name a service `backend`. Nothing errors when that happens."
    )


def test_every_network_belongs_to_this_project():
    networks = (_config().get("networks") or {})
    for name, net in networks.items():
        actual = (net or {}).get("name", name)
        assert actual.startswith("mistilteinn"), (
            f"network {name!r} resolves to {actual!r}, which is not this project's. Sharing "
            f"a network with the other stack on this box is how the two get confused."
        )


def test_prod_owns_its_database_rather_than_reaching_for_a_host_port():
    """fairy's prod publishes no 5432, so the dev arrangement cannot work there.

    Carrying `host.docker.internal` into prod would either fail to connect or — worse —
    connect to whatever else is listening on the host's 5432.
    """
    services = _config()["services"]
    assert "db" in services, "the prod stack has no database of its own"

    backend = services["backend"]
    assert not backend.get("extra_hosts"), (
        f"backend still maps {backend.get('extra_hosts')} in production. In dev that reaches "
        f"fairy's Postgres over the host gateway; in prod it would let a dev `.env` resolve "
        f"to whatever is listening on the host instead of failing loudly."
    )


def test_every_service_survives_a_host_reboot():
    """fairy learned this on 2026-07-28: with a policy only on cloudflared, a reboot brought
    the tunnel back while the app stayed down, so the site answered 502 rather than failing
    obviously."""
    without = [
        name for name, service in _config()["services"].items()
        if service.get("restart") != "unless-stopped"
    ]
    assert not without, f"these services have no restart policy: {without}"
