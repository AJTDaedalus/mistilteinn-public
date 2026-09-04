# DESIGN — Open Registration: email-verified auto-approval

**Status:** plan, 2026-09-04.
**Owner ask:** *"fairy recently implemented email authentication, can you review and implement
it here so I don't have to manually approve people?"*

**Ported from** `/root/fairy/docs/DESIGN_open_registration.md` (Opus 5, 2026-08-26), which
shipped to fairy's `dev` on 2026-08-28 across PRs #207–#209 and is live: probing
`fairy.aetherus.dev` returns `405` for `auth/verify-email`, `auth/resend-verification` and
`auth/forgot-password` against `404` for a made-up path, which is how a deployed route answers
an OPTIONS it does not implement.

**This is a port, not a copy.** §2 lists what carries over unchanged, and §3 lists the four
places mistilteinn differs enough that copying fairy would be wrong.

---

## Branch policy

- **Branch:** `feat/open-registration`, cut from `dev`.
- **No direct commits to `dev` or `main`.** Pushing `dev` deploys (`docs/DEPLOY.md`), so a
  wrong commit ships. Everything lands here and reaches `dev` only by reviewed PR.
- The phases in §8 are separate commits on one branch; each leaves the gate **shut** except
  the last.
- **Phase 4 changes who can reach the app.** It is a config flip, and it merges only with the
  owner present.
- Branch-setup gate: Task 0 of `docs/TASKS_open_registration.md`.

---

## 1. Problem

`POST /api/v1/auth/register` writes a `User` with `status = PENDING` and nothing else happens.
The user sits on `/pending` until the owner notices and runs `python -m scripts.approve_user`
over SSH. Every account needs a human with shell access to production — a growth ceiling, and
a liveness dependency on one person.

We want: **register → email → click → logged in.**

Removing the human removes the only thing standing between the internet and the `users` table.
So the bot defenses are not bolted on beside the feature; **they are the feature.** Email
verification is the easy half.

---

## 2. What ports over unchanged

Every decision below is fairy's, re-verified against this codebase rather than assumed. The
rationale lives in fairy's document; repeating it here would be a second copy to drift.

| | |
|---|---|
| **D-OR1** | Fix the real client IP first — every IP-keyed defense is decorative until it lands |
| **D-OR2** | Two flags, `REGISTRATION_OPEN` and `AUTO_APPROVE_ON_VERIFY`, not one |
| **D-OR3** | The emailed link opens the **SPA**, which POSTs the token — never a `GET` that consumes |
| **D-OR4** | Resend over `httpx`, behind an `EmailSender` protocol, console sender by default |
| **D-OR5** | Cloudflare Turnstile, verified on `success` **and** `hostname` **and** `action` |
| **D-OR6** | `email_normalized`, gmail-only dot/plus stripping, `UNIQUE` |
| — | `email_verified_at` as a **nullable column**, not a fourth `UserStatus` value |
| — | `auth_tokens` table: `sha256` stored, single use, 24h TTL, issuing invalidates priors |
| — | `202` + identical body for every register outcome; hash **before** the existence branch |
| — | Honeypot field returning the same `202`; disposable-domain blocklist |

**And all four of fairy's current-state defects are present here verbatim** — checked, not
inferred:

| | mistilteinn today |
|---|---|
| §4.1 | `auth.py::_login_ip_key` and `middleware/rate_limit.py::_owner_key` both key on `request.client.host`. Behind nginx that is one bucket for the whole internet. |
| §4.2 | `register` carries **no** `@limiter.limit` at all. |
| §4.3 | `register` returns `409 "Email already registered."` — and returns *before* `hash_password`, so fixing the status alone leaves a ~250 ms bcrypt timing oracle. |
| §4.4 | `Limiter(key_func=_owner_key)` has no `storage_uri`; prod runs `--workers 2`, so every limit is silently doubled. |

**And fairy's #1 pre-merge review finding applies verbatim.** `docker-compose.yml` enumerates
`environment:` explicitly and has **no `env_file:`**; `docker-compose.prod.yml` narrows it
further to two variables. A new setting reaches the container only if someone adds it by hand,
and the failure is silent: mail printed to a container log nobody reads, links pointing at
`localhost:4200`, Turnstile off, and a signup flow that looks like it worked. **Task 1 is the
compose wiring, before any setting exists to forget.**

---

## 3. Where mistilteinn differs, and what changes because of it

### 3.1 The optimizer runs in the browser — fairy's quota chapter does not transfer

Fairy's §6 exists because its optimizer is server-side numba on a 4-core free-tier ARM box:
a few accounts can occupy both workers and deny everyone else the headline feature.

**There is no server-side simulator here.** `rg "subprocess"` over `backend/app` returns
nothing; gcsim is compiled to wasm and every search runs on the user's own CPU. An account
that gets through therefore costs this app *rows*, not cycles, and the honest quota list is
much shorter than fairy's.

### 3.2 …except `POST /rotations/import/link`, which is somebody else's compute

This app has one endpoint fairy has no equivalent of: the gcsim-database importer, which makes
**the only request-time outbound fetch in `app/`**. It is already hardened against
request-forgery — it takes an id, never a URL, and the host is a constant — but that hardening
is about *where* it fetches, not *how often*.

Open registration turns it into a free proxy pointed at gcsim's servers, and the owner has
already ruled on exactly this (2026-09-02): *"I don't want to push our compute load to them."*

**This is mistilteinn's version of fairy's optimizer row**, and it is the one quota that is
about somebody else's bill rather than ours. Shipped as **5/hour per account**; the daily
ceiling the first draft of this section promised is **OQ-OR3**, because counting imports needs
a column distinguishing them from hand-authored rotations and inventing one mid-change was the
wrong trade.

### 3.3 Row quotas, sized to this app's real inventory

Fairy's numbers are for discs. The owner's own account here holds **2,369 artifacts, 75
builds, 87 roster rows** — so a cap has to sit clear of a real player's inventory, and
artifacts arrive in one bulk GOOD import rather than one at a time.

| Resource | Cap | Why that number |
|---|---|---|
| Artifacts per user | 10,000 | 4.2× the owner's real inventory; a GOOD export cannot plausibly exceed it |
| Builds per user | 500 | 6.6× the owner's 75, and above one build per catalogue character |
| Teams per user | 200 | |
| Rotations per user | 500 | |
| `rotations/import/link` | **5/hour per account** | somebody else's servers (§3.2). The daily cap needs a `source` column that does not exist — **OQ-OR3** |
| `POST /sim-runs` | *not capped* | writes a corpus row per search; bounded today by `WRITE_LIMIT` and left there rather than guessed at |

Exceeding one returns `409` naming the limit — a real user hitting a cap deserves to know
which, not a mystery failure.

### 3.4 CSP, and the wasm exception already in it

`frontend/nginx.prod.conf` ships `script-src 'self' 'wasm-unsafe-eval'` **twice** (lines 14
and 119 — the second is inside a location block). Turnstile needs
`https://challenges.cloudflare.com` in `script-src` **and** `frame-src`, and **both copies
must be edited**; editing one leaves the widget working on some paths and silently dead on
others, which is the hardest class of this bug to see.

---

## 4. Account lifecycle

```
register            → status=PENDING,  email_verified_at=NULL
verify (valid link) → email_verified_at=now()
                      └─ if AUTO_APPROVE_ON_VERIFY: status=APPROVED, approved_at=now()
approve_user.py     → status=APPROVED  (unchanged; break-glass and the flag-off path)
abuse               → status=DISABLED  (unchanged)
```

`UserStatus` keeps its triad and every `status == APPROVED` check is untouched. A fourth enum
value would force an audit of every one of those comparisons, and the failure mode of missing
one is an authorization check that silently passes.

**The backfill is not a note, it is the acceptance criterion.** Every existing `APPROVED` user
was approved by hand and never saw a verification email. The migration sets
`email_verified_at = COALESCE(approved_at, created_at)` for them. Skipping it strands the
owner's own account the moment anything requires verification.

---

## 5. Testing

TDD, and **no test may make a network call** — the unit lane already blocks `socket.connect`
(E.6), so a live Resend or Turnstile call fails there loudly rather than flakily.

- **Unit:** client-IP resolution order; gmail normalization (**non-gmail dots preserved** — the
  regression that would silently merge two real users); token mint/hash/expiry/single-use;
  Turnstile success, `hostname` mismatch, `action` mismatch, **network error fails closed**,
  empty secret skips; disposable domains.
- **Integration:** register enumeration — new vs existing must be **byte-identical**; verify
  happy path, expired, reused, forged; auto-approve on and off; `REGISTRATION_OPEN=False` ⇒
  `503`; honeypot ⇒ `202` with **zero rows and zero emails**; each rate limit at its boundary;
  each quota at its boundary; **the migration backfill leaves an existing approved user able
  to log in**.
- **Frontend:** `/verify` POSTs on load and strips the query string; the register form always
  says "check your email" and its 409 branch is gone.
- **Driven:** a real account created end to end through the console sender, which is the
  owner's *"build a dummy account using it"*.

---

## 6. Open questions

**OQ-OR1 — does the owner want a Resend account now, or ship on the console sender?** Every
phase below works with `EMAIL_PROVIDER=console`; only actual delivery to a real inbox needs the
API key and the SPF/DKIM/DMARC records. The code does not care which, and the flag is the seam.

**OQ-OR3 — a `source` column on `Rotation`, so the gcsim import cap can be counted in the
database.** §3.2's cap shipped as a per-account rate limit only. A daily ceiling needs to
count *imports*, and nothing distinguishes an imported rotation from an authored one — so
counting rows created in the last day would cap somebody's own authoring, which is wrong. One
nullable column and a migration; deliberately not folded into this change.

**OQ-OR2 — Turnstile keys.** Same shape: `TURNSTILE_SECRET_KEY=""` skips verification
entirely, so the code ships and the layer switches on when the keys exist.

---

## 7. Phased rollout

**The ordering is the safety property.** Each phase is independently valuable and revertible,
and the gate stays shut until the last.

| Phase | Contents | Gate after |
|---|---|---|
| **0** | compose env wiring, real client IP, register rate limit | closed |
| **1** | `EmailSender`, `auth_tokens`, `email_verified_at` + backfill, verify/resend endpoints, SPA `/verify` | closed |
| **2** | enumeration + timing fix, honeypot, `email_normalized`, disposable domains, Turnstile | closed |
| **3** | quotas (§3.2, §3.3), unverified reaper | closed |
| **4** | `AUTO_APPROVE_ON_VERIFY=true` | **OPEN** |

Phase 4 is a config change. Its rollback is a config change and a restart — no revert, no
redeploy, no migration.
