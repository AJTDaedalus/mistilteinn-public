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

Aesthetic: **inherited from fairy and not yet re-decided for mistilteinn.** The tokens
and effects below are fairy's VHS / video-store / CRT look, derived from an NPC art reference
that did not come along in the fork. Treat the palette and mixins as a working scaffold, not a
brand — mistilteinn's visual identity is an open decision.

Tokens live in `_tokens.scss` — never hardcode colors, type families,
spacing, or radii. Effects (scanlines, halo glow, vhs beam) are
mixins in `_effects.scss`; use sparingly so the chrome stays distinct
rather than noisy. Tabular numerics (damage, stats, percentiles)
should use `class="mono"` or `.stat-value` so they line up.

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
# → http://localhost:4200 (HMR via --poll 1000)

# Direct npm (when iterating without docker):
cd frontend && npm install && npm start  # → http://localhost:4200

npm test                                  # vitest in jsdom
npm run build                             # production bundle
```

### After changing dependencies

The frontend container shadows `node_modules` / `.angular` with anonymous
volumes that **persist across container recreation**. After editing
`package.json` or `package-lock.json`:

```bash
docker compose up -d --build --force-recreate --renew-anon-volumes frontend
```

Plain `--build` rebuilds the image but reuses the stale anonymous
volume — the new deps will be missing inside the running container.
