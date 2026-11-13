# Third-party notices

Mistilteinn is licensed under the GNU Affero General Public License v3.0 or later
(`LICENSE`). It includes, or is built from, the following third-party work: MIT-licensed code
whose licence requires its notice to be kept with copies, and gcsim, which is AGPLv3. This
file is where those notices are kept.

**Not covered by this repository's licence:** Genshin Impact's names, data and art belong to
HoYoverse. The art is not in this repository: `backend/scripts/download_icons.py` fetches it
at deploy time (`docs/DECISIONS.md` §34).

## Data this repository carries, and where it is from

None of the following is licensed by this repository, and none of it is HoYoverse art.

- **Game data**, derived from Genshin Impact and belonging to HoYoverse:
  - `backend/tests/fixtures/nanoka_gi/` holds payloads from nanoka (<https://nanoka.cc>);
  - `backend/app/data/yuanshen/` holds a snapshot from GuraFoundation/YuanShenResources
    (<https://gitlab.com/GuraFoundation/YuanShenResources>), with its pin and provenance in
    `schema/provenance.json`.
- **KeqingMains weapon recommendations** in `backend/app/data/kqm/weapons.json`, cited per
  character to <https://keqingmains.com>, with the retrieval date in the file.
- **Five gcsim configs** in `references/gcsim_db/`, from gcsim's public database
  (<https://gcsim.app/database>), with provenance in `references/gcsim_db/PROVENANCE.md`.

## Genshin Optimizer

`backend/app/pando/` is a port of `libs/pando/engine` from
<https://github.com/frzyc/genshin-optimizer>. The artifact draw weights in
`backend/app/data/external/artifact_draw_model.json` are taken from its
`libs/gi/upopt/src/consts.ts`.

```
MIT License

Copyright (c) 2020-present, frzyc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## gcsim

The browser simulator, `gcsim.wasm`, is built from <https://github.com/genshinsim/gcsim> at
`b107b5dc5cb88977bed5270e5d83e64934730d4d` (release v2.50.0), **unmodified**. Its
Corresponding Source is that commit:
<https://github.com/genshinsim/gcsim/tree/b107b5dc5cb88977bed5270e5d83e64934730d4d>. The build
is `frontend/scripts/build-gcsim-wasm.sh` and `frontend/Dockerfile.prod`, which read the pin
from `docs/CROSSVAL_gcsim.md`; the binary is not vendored here.

**gcsim is licensed under the GNU Affero General Public License v3.0** (or, at your option, any
later version), effective 2026-09-19. This repository pinned past that relicence on
2026-11-13 by the owner's decision (`docs/DECISIONS.md` §37). The production bundle ships
gcsim's full `LICENSE` beside the binary as `gcsim/gcsim.LICENSE.txt`, and the site offers the
source of both gcsim and this repository on every page, as AGPL §13 requires.

gcsim's own notice, from the head of its `LICENSE` at the pin:

```
gcsim
Copyright (c) 2021 The gcsim contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

gcsim is licensed under the AGPLv3 effective 2026-09-19. Released versions up
to and including v2.47.2 were licensed under the MIT License; see LICENSE-MIT.
Code originally contributed under the MIT License remains available under those
terms, and its MIT notice is retained per that license's requirements.
```

**The MIT notice stays**, because code contributed before the relicence carries it and MIT
requires it to be kept. gcsim's `LICENSE-MIT` ships beside the binary as
`gcsim/gcsim-mit.LICENSE.txt`; its licence text is:

```
MIT License

Copyright (c) 2021 genshinsim

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
