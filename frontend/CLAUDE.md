# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the frontend.

## Stack

- **Angular 21** (latest LTS), standalone components, signals + computed
- **No NgRx** — signals + small per-feature service singletons handle all state
- **SCSS** with design tokens in `src/styles/_tokens.scss`
- **Vitest** for unit tests (replaces Karma; `jsdom` environment)
- **Bebas Neue** (display) + **IBM Plex Mono** (numeric) loaded from Google Fonts in `index.html`
- **openapi-typescript** + **openapi-fetch** for typed backend access — no Angular `HttpClient`

## API Client

Backend types are generated from a checked-in `openapi.json` snapshot.

```bash
npm run openapi:fetch   # snapshot live backend → frontend/openapi.json
npm run codegen         # openapi.json → src/app/api/api.types.ts (gitignored)
```

Both run automatically via `prestart` / `prebuild`. From a service:

```ts
import { Injectable } from '@angular/core';
import { injectApi } from '../api/api.client';

@Injectable({ providedIn: 'root' })
export class BuildsService {
  private api = injectApi();

  async list() {
    const { data, error } = await this.api.GET('/api/v1/builds');
    if (error) throw error;
    return data;
  }
}
```

`injectApi()` is a tiny factory that calls `createClient<paths>()`. Override
the base URL in tests by providing `API_BASE_URL`.

## Layout

```
src/
  app/
    api/
      api.client.ts      — typed fetch client + DI token
      api.types.ts       — generated, gitignored
    pages/
      <feature>/         — route-level smart components
    shared/              — dumb / cross-feature components (TBD)
    app.{ts,html,scss}   — shell: brand bar + nav + router-outlet
    app.routes.ts        — top-level routes (lazy-loaded)
  styles/
    _tokens.scss         — palette, type, spacing, motion
    _typography.scss     — h1-h6, .eyebrow, .mono, .stat-value
    _effects.scss        — scanlines, halo-border, vhs-beam mixins
  styles.scss            — global reset + base element styles
  index.html
```

## Design System

Aesthetic: **the Mitya palette, decided in Chunk J (#46).** The paragraph that stood here
called the look "inherited from fairy and not yet re-decided" long after it had been —
`_tokens.scss` is sampled from `references/mitya.png` and `references/mitya_ornament.png`,
and the emblem is his ornament. The character himself is deliberately absent: his colours
and his patterns are the brand, he is not, and there is no portrait anywhere in the app.

The structure is **two-accent**, which is the part worth knowing before adding anything:
warm brass for identity and action, cool mint/azure for data and state. Keeping them apart
is what stops the palette reading as generic fantasy-purple, and it maps onto something
real — a damage number and a button are different kinds of thing.

Tokens live in `_tokens.scss` — never hardcode colors, type families, spacing, or radii.
That rule was broken in nine stylesheets at once: `.muted`, `.hint`, `.error` and `.warn`
were each redefined per page with `#ff8080` and `#ffc966` written out by hand, so the two
colours the app uses to say *something is wrong* were the only ones nobody could restyle.
They are global now, on `--danger` and `--warning`. The **element** colours
(`--element-pyro` and friends) are the one place a colour is chosen rather than sampled —
they are a design decision, not game data, and the token block says so at length.

Effects (scanlines, halo glow, vhs beam) are mixins in `_effects.scss`; use sparingly so the
chrome stays distinct rather than noisy. Tabular numerics (damage, stats, percentiles)
should use `class="mono"` or `.stat-value` so they line up.

### Catalogue art

`frontend/public/icons/` is **gitignored**. The art is HoYoverse's (`docs/DECISIONS.md` §34).
A fresh clone has none. Fill it with `cd backend && python -m scripts.download_icons`; prod's
deploy runs the same script and mounts the result into nginx. Three components consume it, and a new
surface should reach for one rather than writing an `<img>`:

- `shared/icon` — `<catalogue-icon [icon] [alt] [size]>`, the raw image. Renders nothing for
  a null basename and hides itself on a failed load.
- `shared/token` — `<entity-token [icon] [name] [meta]>`, art beside a name. What most
  surfaces want.
- `shared/element` — `<element-chip [element]>`, a vision as a coloured pill. Colour is a
  second channel on a label that still says "Electro"; it is never the only one.

An `<option>` cannot contain an `<img>`, so a `<select>` gets its art as an adornment beside
the control (`teams`, `rotations`) or is replaced by `shared/combobox`, which takes an
optional `icon` per option (`compare`).

## Conventions

- One feature per `pages/<name>/` directory: `name.ts`, `name.html`,
  `name.scss` (no separate module file — standalone components)
- Lazy-load every page route via `loadComponent: () => import(...)`
- Inject services via `inject()`, not constructor params
- Async API calls return Promises; bind to component-local signals
- SCSS in components is component-scoped automatically; reference
  global mixins via `@use '../../../styles/effects' as fx;`

## Frontend Dev Loop

```bash
docker compose up -d                     # full stack incl. frontend
# → http://localhost:4201 (HMR via --poll 1000; container serves 4200)

# Direct npm (when iterating without docker):
cd frontend && npm install && npm start  # → http://localhost:4200 (no docker)

npm run verify                            # typecheck + lint + test — what CI runs
npm test                                  # vitest in jsdom (the inner loop)
npm run build                             # production bundle
```

**`npm test` is not the gate; `npm run verify` is.** CI runs typecheck, lint and tests as
three separate steps, and only the third is what a dev loop usually invokes — so `ng lint`
was routinely skipped locally. It is not cosmetic: it caught a real accessibility bug on
#131 (a `<label>` wrapping a component associates with nothing, and the combobox inside had
no accessible name at all), and it caught it in `ci_local` rather than during development,
which is the wrong end of the loop.

`cd backend && python -m scripts.ci_local --job frontend` is still the authority — it reads
the workflow file, so it cannot drift. `verify` is the fast approximation.

### After changing dependencies

The frontend container shadows `node_modules` / `.angular` with anonymous
volumes that **persist across container recreation**. After editing
`package.json` or `package-lock.json`:

```bash
docker compose up -d --build --force-recreate --renew-anon-volumes frontend
```

Plain `--build` rebuilds the image but reuses the stale anonymous
volume — the new deps will be missing inside the running container.
