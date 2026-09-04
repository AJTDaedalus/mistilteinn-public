# TASKS — Open Registration

Reads `docs/DESIGN_open_registration.md`. Ported from fairy's shipped implementation.

**Status: phases 0-3 complete. Phase 4 — flipping `AUTO_APPROVE_ON_VERIFY` in production —
is the owner's, and is a config change rather than a deploy.**

| task | phase | state |
|---|---|---|
| 0. Branch | — | done — `feat/open-registration` |
| 1. Compose carries every setting | 0 | done — 34 tests; defect planted and caught |
| 2. Real client IP | 0 | done — mutation-tested |
| 3. Rate-limit `register` | 0 | done — `3/hour`, `10/day` per IP |
| 4. `email_verified_at` + backfill | 1 | done — 3 of 3 existing users backfilled |
| 5. `auth_tokens` + repository | 1 | done |
| 6. `EmailSender` protocol | 1 | done — console default, no network in any test |
| 7. `/verify-email`, `/resend-verification` | 1 | done |
| 8. SPA `/verify` route | 1 | done |
| 9. Enumeration + timing fix | 2 | done — identical 202, hash before the branch |
| 10. Honeypot | 2 | done — driven, confirmed invisible |
| 11. `email_normalized` | 2 | done — derived in the model |
| 12. Disposable domains | 2 | done — 8,368 committed with provenance |
| 13. Turnstile + CSP | 2 | done — both copies of the policy |
| 14. Quotas | 3 | done, **with one gap recorded as OQ-OR3** |
| 15. Unverified reaper | 3 | done — in the startup sweep |
| 16. Drive it: a real account | — | done — see below |

## What was driven, 2026-09-04

Through the real UI at `localhost:4201`, in a real browser:

```
register through the form   → "check your email"          ✓
honeypot present, visible=False                            ✓
link read out of the container log                         ✓
open it → lands at "/", token stripped from the URL        ✓
full nav rendered, "Brand New User" signed in              ✓
console errors                                             none
```

And through the API, both sides of the switch:

| account | what happened | result |
|---|---|---|
| `dummy.account` | registered, never clicked | pending, unverified |
| `dummy.tester` | clicked, `AUTO_APPROVE_ON_VERIFY=false` | verified, still pending |
| `real.signup` | clicked, flag `true` | approved, session issued, `/auth/me` 200 |

Re-clicking a spent link returns `already_used`; a forged token returns `invalid`.
**Nobody ran `approve_user`.**

---

## 0. Branch

`git switch -c feat/open-registration dev`. Confirm with `git branch --show-current`.

## 1. Compose carries every setting — **first, before any setting exists**

`docker-compose.yml` enumerates `environment:` and has no `env_file:`; the prod override
narrows it to two variables. This was fairy's **#1 pre-merge review finding**: no new setting
reached the container, and the failure was silent.

Add every new setting to **both** compose files with a default, and say in `docs/DEPLOY.md`
that omitting one fails silently rather than loudly.

**Acceptance:** a test reads `docker-compose.yml` and asserts that every non-default field on
`Settings` added by this design appears in the backend service's `environment:`. That test is
the thing that would have caught fairy's defect.

## 2. Real client IP

`app/middleware/client_ip.py::get_client_ip` — `CF-Connecting-IP` → leftmost
`X-Forwarded-For` → `request.client.host`. Used by `_owner_key`, `_login_ip_key` and every new
limiter, so the logic exists once.

`--forwarded-allow-ips` in the prod compose, with a comment saying `*` is safe **only** while
the backend publishes no host port.

**Acceptance:** unit tests for the order; a spoofed `X-Forwarded-For` loses to `CF-Connecting-IP`.

## 3. Rate-limit `register`

`3/hour` and `10/day` per IP. Per-email comes in Task 11, keyed on the **normalized** address —
fairy's finding 4 was that keying the raw address let rotating Gmail dots buy unlimited budget.

## 4. `email_verified_at` + backfill

Nullable column. One migration, and the backfill
`email_verified_at = COALESCE(approved_at, created_at) WHERE status = 'approved'` is in it.

**Acceptance:** an integration test proves a pre-existing approved user is not locked out.

## 5. `auth_tokens`

`(id, user_id, purpose, token_hash, expires_at, consumed_at)`. `sha256` only, single use, 24h,
issuing invalidates priors for the same `(user_id, purpose)`. Purged in the existing lifespan
sweep beside `SessionRepository.delete_expired()`.

## 6. `EmailSender`

`app/services/email/` — `base.py` (Protocol), `console.py` (default), `resend.py`, and a
recording sender for tests. `templates.py` for the three messages: verify, already-registered
notice, and (later) reset.

**No test may make a network call.**

## 7. Endpoints

`POST /auth/verify-email` — `{token}` → `verified | expired | already_used | invalid`. On
success with the flag on, mint a session and return it in the same response.
`POST /auth/resend-verification` — `3/hour` per email and per IP.

## 8. SPA `/verify`

Route posts the token on load and clears the query string with `history.replaceState`.
The `expired` outcome renders a working resend button — fairy's finding 7 was that
`resendVerification` had no caller, so an expired link was a dead end.

## 9. Enumeration + timing

`202` with an identical body for every outcome. `hash_password()` **unconditionally, before**
the existence branch. Delete the frontend's 409 branch rather than leaving it.

**Acceptance:** an integration test asserts new and existing addresses return byte-identical
status and body.

## 10. Honeypot

A `website` field. Non-empty ⇒ the same `202`, zero rows, zero emails, log at INFO.

## 11. `email_normalized`

Lowercase everywhere; strip dots and `+…` for gmail/googlemail only. `UNIQUE`. **Every
identity lookup — login, resend, reset, register — resolves on it**; fairy's `0d5a0ba` was an
account made unreachable because registration used the normalized column and login the raw one,
and anti-enumeration made it unrecoverable.

## 12. Disposable domains

Committed JSON under `app/data/validation/`, refreshed by a script. Rejected **visibly** — it
is also the message a confused legitimate user needs.

## 13. Turnstile + CSP

Verify `success`, `hostname` **and** `action`. **Fail closed** on register, and never send the
`"unknown"` IP sentinel as `remoteip`. Empty secret ⇒ skipped.

**Both copies of the CSP** in `nginx.prod.conf` (lines 14 and 119) gain
`https://challenges.cloudflare.com` in `script-src` and `frame-src`.

## 14. Quotas

DESIGN §3.2 and §3.3. The `rotations/import/link` cap is the one that matters — it is somebody
else's servers.

## 15. Reaper

Startup sweep deletes `PENDING` + unverified users older than 30 days.

## 16. Drive it

Owner: *"build a dummy account using it."* Register through the real UI, read the link out of
the console sender, click it, and land logged in. Then re-click it and get `already_used`.
