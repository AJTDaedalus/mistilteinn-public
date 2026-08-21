# ZAP baseline scan

Dynamic scan of the deployed site. **Not part of CI** and not runnable today.

| File | What |
|---|---|
| `zap.yaml` | ZAP automation-framework plan: spider + passive scan + HTML/JSON report |
| `run-baseline.sh` | The only supported way to invoke it. Opt-in, with two refusals |

## Running it

```bash
ZAP_SCAN_ENABLED=1 ./security/zap/run-baseline.sh
```

Without `ZAP_SCAN_ENABLED=1` the script prints `SKIPPED` and **exits 78**. That is
deliberate. A guard that exits 0 to mean "did not run" is indistinguishable from a
pass, and this repo has already been bitten by that: `zap-baseline-prod.json` was a
committed report claiming a clean baseline against a host that has never existed
(deleted in A.3). Per `CLAUDE.md`, a skipped check blocks — it is never a pass.

The second refusal is an **HTTP** pre-flight, not a DNS one, and the difference is the
whole point.

## Why "the host does not resolve" is wrong

`CLAUDE.md`, `DESIGN §Chunk A` and `TASKS A.11` all say `mistilteinn.aetherus.dev` does
not resolve. Measured on 2026-08-21, it does — **`aetherus.dev` has wildcard DNS onto
Cloudflare**, so every subdomain resolves, including
`definitely-not-real-xyz123.aetherus.dev`. What is missing is an *origin*: the host
answers `525` (Cloudflare SSL handshake failed) where `fairy.aetherus.dev` answers `200`.

A DNS-based guard would therefore have passed, and the scan would have run. It was run
once, unguarded, to find this out. It reported:

```
FAIL-NEW: 0   WARN-NEW: 2   PASS: 59
```

59 passing rules against a Cloudflare error page. That is precisely the false all-clear
this gate exists to prevent, and it is why the pre-flight checks whether the target is
actually *serving* (`HTTP < 500`) rather than whether its name resolves.

## Why it cannot pass yet

The deploy target, tunnel, and origin are **Chunk K**. Until then every invocation is
expected to exit 78, and that is the correct outcome.

## Known issue for Chunk K

In that unguarded run the ZAP container could not write its reports:
`AccessDeniedException /zap/wrk/zap-baseline-prod.html`. The image runs as uid 1000 and
this directory is root-owned. Not fixed here — it cannot be verified without a real
target, and guessing at a `--user` flag risks breaking ZAP's own home directory. Fix it
when the scan can actually run.

## Reports

`zap.yaml` writes `zap-baseline-prod.{html,json}` into this directory. Those are
scan *output*, not source — regenerate them, do not hand-edit, and think hard before
committing one, since a committed report is a claim about a specific host at a
specific moment.
