"""The CSP lets gcsim run in its Web Worker — in **every** copy of the policy.

gcsim runs in a dedicated worker (`frontend/src/app/sim/gcsim.worker.ts`) so a simulation that
can never finish can be killed with `terminate()`. Three things in `nginx.prod.conf` have to
hold for that worker to work in production, and none of them is visible in dev, which has no
nginx at all:

1. **The worker chunk may be created.** With no `worker-src`, CSP falls back to `script-src`
   (then `default-src`), so `'self'` there is what allows `new Worker('/worker-….js')`. A
   `worker-src` added later without `'self'` would block it silently — the page would render
   and every simulation would fail.
2. **The worker may load `wasm_exec.js`** by dynamic `import()` from `/gcsim/`, which is
   `script-src 'self'` again.
3. **The worker may compile the wasm.** A worker is governed by the CSP delivered *with its
   own script*, not the page's — so the response for `/worker-….js` must carry
   `'wasm-unsafe-eval'`. It is served by `location /`, which inherits the server-level
   headers only while it adds none of its own (`add_header` in a location *replaces* the
   inherited set, the trap this file's `/index.html` block documents).
"""

from __future__ import annotations

import re
from pathlib import Path

NGINX = Path(__file__).resolve().parents[3] / "frontend" / "nginx.prod.conf"


def _policies() -> list[str]:
    return re.findall(r"Content-Security-Policy\s+\"([^\"]+)\"", NGINX.read_text())


def _directive(policy: str, name: str) -> list[str] | None:
    for part in policy.split(";"):
        tokens = part.split()
        if tokens and tokens[0] == name:
            return tokens[1:]
    return None


def test_the_policy_is_found_at_all() -> None:
    """Guards the guard: a restructured file with no match would make every loop below pass."""
    assert len(_policies()) >= 2


def test_every_copy_lets_the_page_start_a_same_origin_worker() -> None:
    for policy in _policies():
        governing = (
            _directive(policy, "worker-src")
            or _directive(policy, "child-src")
            or _directive(policy, "script-src")
            or _directive(policy, "default-src")
        )
        assert governing is not None, f"no directive governs workers in: {policy[:80]}…"
        assert "'self'" in governing, f"workers are not allowed from 'self' in: {policy[:80]}…"


def test_every_copy_lets_the_worker_import_the_go_shim_and_compile_the_wasm() -> None:
    for policy in _policies():
        scripts = _directive(policy, "script-src") or _directive(policy, "default-src") or []
        assert "'self'" in scripts
        assert "'wasm-unsafe-eval'" in scripts


def test_the_worker_chunk_inherits_the_server_level_policy() -> None:
    """The worker chunk is served by `location / { … }`. One `add_header` there would drop the
    server-level CSP for that response, and the worker would run with **no** policy carrying
    `'wasm-unsafe-eval'` — or, worse, with whatever partial set was added."""
    text = NGINX.read_text()
    match = re.search(r"location / \{(.*?)\n    \}", text, re.DOTALL)
    assert match is not None, "could not find `location /` in nginx.prod.conf"
    assert "add_header" not in match.group(1)
