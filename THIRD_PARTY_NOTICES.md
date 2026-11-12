# Third-party notices

Mistilteinn is licensed under the GNU Affero General Public License v3.0 (`LICENSE`). It
includes, or is built from, the following MIT-licensed work. The MIT licence requires its
notice to be kept with copies, which is what this file is for.

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
`caf738dc807a646e2eee7e7b572f225dd6deb510` (v2.47.2), unmodified. The build is
`frontend/scripts/build-gcsim-wasm.sh` and `frontend/Dockerfile.prod`. It is not vendored
here, and the production bundle ships this notice beside the binary as
`gcsim/gcsim.LICENSE.txt`.

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
