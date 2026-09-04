# DESIGN — a character as your avatar

**Status:** design + implementation, one chunk. Owner asked for it directly on 2026-09-04:
*"users can select a character as their avatar, and their headshot becomes their user avatar."*

## Branch policy

Work happens on **`feat/user-avatar`**, branched from `dev`. No direct commits to `dev` or
`main`; `dev` is updated by PR only. There are no parallel tracks — one branch, one PR. The
branch-setup gate is §7 Task 0 below.

## 1. What this is

An account carries a chosen character. Their headshot — the same `UI_AvatarIcon_*` art the
catalogue already draws — is shown wherever the app names the user, which today is the
identity chip in the header and, from this chunk, an account page.

Two owner rulings, taken as answers before implementation:

* **The picker lives on a new `/account` page**, not in a header popover. There is no account
  surface today, so the header chip's only affordance is *Sign out*. A 150-card grid in a
  dropdown is also the wrong container for a grid that already has search and filter chips.
* **Any catalogue character may be chosen**, not only ones on the roster. It is decoration.
  Gating it on the roster gives a new user — who has not imported a GOOD export yet — an empty
  picker on the one page whose whole purpose is to pick something.

## 2. Non-goals

* **Uploaded images.** An avatar the user supplies is a file store, a content-moderation
  question and an image pipeline; a character id is a foreign key. The ask was a character.
* **Showing the avatar to other people.** The rotation library publishes rotations without any
  author identity at all (`LibraryRotationRead` has no author field), so there is nowhere for
  someone else's avatar to appear. If author attribution is added later, this column is what it
  would read.
* **Per-character or per-build avatars.** One account, one avatar.

## 3. Storage: a foreign key, not a basename

`users.avatar_character_id` → `characters.id`, nullable, **`ON DELETE SET NULL`**.

* **Not the icon basename.** Storing `UI_AvatarIcon_Ayaka` puts an unvalidated string in the
  users table that no constraint keeps true. Art basenames are nanoka's and have changed before
  (`ae4b7f29b90e` added per-slot artifact icons); a stored copy is the one that goes stale, and
  the failure mode is silent — `CatalogueIcon` hides an image that 404s, so a stale avatar looks
  like no avatar. The FK means the picture always comes from a real catalogue row.
* **`SET NULL`, where `builds.character_id` is `CASCADE`.** A build *is about* its character and
  is meaningless without it. An avatar is decoration on an account, and an account must never be
  reachable by a `DELETE` on the catalogue. Deleting a character should cost a user their
  picture, not their login.
* **Character ids survive a re-seed.** This rests on the same assumption `builds` and
  `character_roster` already rest on: `seed_db` upserts by `nanoka_id` and keeps the row's `id`.
  If that ever stopped being true, three features would break together and this would be the
  least of them.

Nullable is the honest default. Nobody has an avatar until they pick one, and "no avatar" is a
state the header must render anyway (every account that exists today is in it).

## 4. API

`GET /auth/me` grows one field:

```
avatar: { character_id, name, icon } | null
```

**Nested rather than three flat nullable fields.** `avatar_character_id`, `avatar_name` and
`avatar_icon` side by side is three things that can disagree; one optional object is either
there or it is not. The client needs `icon` to draw and `name` for the `alt` text and the
"currently: Ayaka" line — a bare id would force the account page to fetch the whole catalogue
before it could name what it was already displaying.

`PUT /auth/me/avatar`, body `{ "character_id": str | null }`:

* an id that names a character → 200, the updated `MeResponse`;
* `null` → 200, avatar cleared (this is the *Clear* button, not a `DELETE` route, so setting and
  unsetting are one code path with one test);
* an id that names nothing → **404**, and the column is not touched. A silent no-op here would
  leave the page showing the old avatar after a "successful" save.

**`PUT`, and it requires an approved user** (`CurrentUser`), unlike `GET /auth/me` which serves
any status. Reading your own status is what a pending user does while waiting; setting a picture
is app usage.

## 5. Frontend

* **`/account`** (`canMatch: [requireApproved]`) — email, label, status, the current avatar, and
  the `CardPicker` grid behind a *Change* button, reusing the character options and the
  vision/weapon filter chips exactly as `builds` builds them. A *Clear* button beside it, shown
  only when there is something to clear.
* **The header identity chip** draws the avatar through `CatalogueIcon` and becomes a link to
  `/account`. `CatalogueIcon` already hides itself when art is missing, so an account with no
  avatar, and one whose art failed to load, both degrade to the name alone — which is what the
  chip shows today.
* **`AuthService.setAvatar()`** calls the endpoint and writes the returned `MeResponse` into the
  existing `me` signal, so the header updates without a reload. The signal is already the single
  source for the chip; nothing new needs to subscribe.

## 6. What could go wrong, and what catches it

| risk | catch |
|---|---|
| Migration and model drift apart | `tests/integration/test_migrations_match_models.py` already compares them |
| A lazy load on a new relationship | Avoided entirely — no ORM relationship is added; the endpoint fetches the character through `CharacterRepository`. `test_lazy_loads_are_refused.py` stays true by construction |
| The contract goes stale | `test_openapi_contract_is_current.py`; `npm run codegen` regenerates `api.types.ts` |
| A green suite over a feature nobody drove | The repo's standing lesson (`CLAUDE.md`: *drive the feature*). Rendering the page is the check — `scripts/shoot.py` |

## 7. Tasks

0. **Branch setup** — `feat/user-avatar` off `dev`. (done)
1. Model column + hand-written migration off head `8fb4f2a3b44f`.
2. `MeResponse.avatar` + `AvatarRead`; `PUT /auth/me/avatar`.
3. Backend tests: set, clear, unknown id 404, unauthenticated 401, `/me` reflects it.
4. `npm run codegen`; `AuthService.setAvatar`; account page + route; header chip.
5. Frontend tests: service, page, chip.
6. Run both suites and `npm run check:tokens`; drive the page in a browser.
