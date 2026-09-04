"""Every setting this feature added is actually delivered to the running app.

**This test exists because the equivalent change in fairy shipped without it and broke.**
Its pre-merge review's first finding: no new setting reached the container. The backend
service enumerates its `environment:` and has no `env_file:`, so a setting absent from that
list is invisible to the app whatever `.env` holds — and invisible *silently*. On the first
production deploy that means verification mail printed to a container log nobody reads,
escaped links pointing at `localhost`, and Turnstile off, while signup looks like it worked.

`.env.example` and the deploy runbook had both been written. Neither was checked against the
delivery path, because nothing checked it.

So this reads the compose files as text and asserts the wiring. It needs no database, no
container, and no network — it is a string comparison nobody was making.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[3]
DEV = ROOT / "docker-compose.yml"
PROD = ROOT / "docker-compose.prod.yml"

#: The settings `DESIGN_open_registration.md` introduces. Named explicitly rather than
#: diffed against a baseline: the point is to state what must be delivered, so that adding a
#: setting and forgetting the compose file fails here rather than in production.
REQUIRED = (
    "EMAIL_PROVIDER",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "PUBLIC_BASE_URL",
    "REGISTRATION_OPEN",
    "AUTO_APPROVE_ON_VERIFY",
    "EMAIL_VERIFY_TTL_SECONDS",
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_EXPECTED_HOSTNAME",
    "MAX_ARTIFACTS_PER_USER",
    "MAX_BUILDS_PER_USER",
    "MAX_TEAMS_PER_USER",
    "MAX_ROTATIONS_PER_USER",
    "MAX_GCSIM_IMPORTS_PER_DAY",
    "MAX_SIM_RUNS_PER_DAY",
    "UNVERIFIED_REAP_DAYS",
)


def _backend_environment(path: Path) -> str:
    """The `environment:` block of the backend service, as text.

    Parsed by slicing rather than with a YAML loader, because the prod file uses compose's
    `!reset` tag, which `yaml.safe_load` refuses.
    """
    text = path.read_text()
    start = text.index("  backend:")
    # The next top-level service, or end of file.
    rest = text[start + 1 :]
    match = re.search(r"\n  [a-z][a-z0-9_-]*:\n", rest)
    return rest[: match.start()] if match else rest


@pytest.mark.parametrize("setting", REQUIRED)
def test_the_dev_compose_delivers_the_setting(setting: str) -> None:
    assert f"{setting}:" in _backend_environment(DEV), (
        f"{setting} is not in docker-compose.yml's backend environment, so the app cannot "
        f"see it. This service has no `env_file:` — putting it in `.env` is not enough."
    )


@pytest.mark.parametrize("setting", REQUIRED)
def test_the_prod_compose_delivers_the_setting(setting: str) -> None:
    assert f"{setting}:" in _backend_environment(PROD), (
        f"{setting} is not in docker-compose.prod.yml's backend environment. The prod "
        f"override narrows the environment, so a setting present only in the dev file is "
        f"absent in production — which is where it matters."
    )


def test_every_required_setting_is_a_real_setting() -> None:
    """The list above cannot drift into naming things that do not exist.

    Without this, deleting a setting from `Settings` leaves a compose entry and a passing
    test asserting a variable nothing reads — which is the same class of lie as a documented
    control that does nothing.
    """
    unknown = [name for name in REQUIRED if name not in Settings.model_fields]

    assert unknown == []


def test_uvicorn_is_told_to_trust_the_proxy() -> None:
    """Without `--forwarded-allow-ips`, every per-IP rate limit is one global bucket.

    uvicorn ignores `X-Forwarded-For` unless the immediate peer is trusted, and the peer in
    production is the nginx *container*, not 127.0.0.1. `DESIGN_open_registration.md` §2
    calls this the highest-value item in the plan: every IP-keyed defense is decorative
    until it lands.
    """
    assert "--forwarded-allow-ips" in PROD.read_text()
