#!/usr/bin/env bash
# Build gcsim's browser WebAssembly target at the pin, into frontend/gcsim/.
#
# **Not vendored, deliberately.** The artifact is 40 MB (7 MB gzipped) and stripping saves
# 1 MB at a documented performance cost. `backend/tests/fixtures/crossval/PROVENANCE.md`
# already set this precedent for the native binary — "gcsim is not vendored: it is a 35 MB
# Go binary and building it needs a Go toolchain" — and `app/data/yuanshen/` sets it for
# upstream data: gitignore the large artifact, commit the pin and the recipe.
#
# The pin is the single one in docs/CROSSVAL_gcsim.md. A test asserts they agree, because
# two pins that can drift apart is two definitions of what "correct" means.
set -euo pipefail

PIN="$(grep -oP '^\| \*\*Commit\*\* \| `\K[0-9a-f]{40}' ../docs/CROSSVAL_gcsim.md)"
[ -n "$PIN" ] || { echo "could not read the gcsim pin from docs/CROSSVAL_gcsim.md" >&2; exit 1; }

OUT="$(cd "$(dirname "$0")/.." && pwd)/gcsim"
SRC="${GCSIM_SRC:-/tmp/gcsim-build}"

command -v go >/dev/null || { echo "go is required; see the header" >&2; exit 1; }

if [ ! -d "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/genshinsim/gcsim "$SRC"
fi
# **Fetch only when the commit is missing.** `fetch --depth 1` into a clone that already has
# full history writes `.git/shallow` and truncates it at the pin — found at the v2.50.0 re-pin,
# when pointing `GCSIM_SRC` at a working clone left it unable to `git log` past the pin.
if ! git -C "$SRC" cat-file -e "$PIN^{commit}" 2>/dev/null; then
  git -C "$SRC" fetch --depth 1 origin "$PIN" 2>/dev/null || git -C "$SRC" fetch origin
fi
git -C "$SRC" checkout -q "$PIN"

echo "building gcsim browser wasm at $PIN"
( cd "$SRC" && GOOS=js GOARCH=wasm go build -o "$OUT/gcsim.wasm" ./cmd/wasm )
# **The GOROOT of the toolchain that built the wasm, not of whatever `go` is on PATH.** With
# `GOTOOLCHAIN=auto` a host Go older than gcsim's `go.mod` switches toolchains *inside* the
# clone only, so `go env GOROOT` asked from here named the host's 1.23 while the wasm came from
# 1.27 — a loader from one Go release beside a binary from another. Found at the v2.50.0
# re-pin on a host with Go 1.23.4. Asked from inside the clone, both come from one toolchain.
GOROOT_USED="$(cd "$SRC" && go env GOROOT)"
# Go moved this between releases: `misc/wasm/` up to 1.23, `lib/wasm/` from 1.24. Check both
# rather than pinning one — the first version of this script assumed `lib/` and failed on the
# very toolchain it was written with.
EXEC=""
for candidate in "$GOROOT_USED/lib/wasm/wasm_exec.js" "$GOROOT_USED/misc/wasm/wasm_exec.js"; do
  [ -f "$candidate" ] && EXEC="$candidate" && break
done
[ -n "$EXEC" ] || { echo "cannot find wasm_exec.js under $GOROOT_USED" >&2; exit 1; }
cp "$EXEC" "$OUT/wasm_exec.js"
printf '%s\n' "$PIN" > "$OUT/BUILT_FROM"

# The notices travel with the artifacts. We serve both files to every visitor, and both carry
# licences that require their notice to be retained when they are redistributed: gcsim's own
# and Go's (BSD-3-Clause), because `wasm_exec.js` is part of the Go distribution rather than
# anything gcsim or this project wrote.
#
# gcsim's is **two files from v2.50.0 on**: `LICENSE` is the AGPLv3 the project has been under
# since 2026-09-19, and `LICENSE-MIT` is the notice MIT requires to be kept for the code that
# was contributed under it. Both ship; `docs/CROSSVAL_gcsim.md` §The pin says why.
cp "$SRC/LICENSE" "$OUT/gcsim.LICENSE.txt"
cp "$SRC/LICENSE-MIT" "$OUT/gcsim-mit.LICENSE.txt"
cp "$GOROOT_USED/LICENSE" "$OUT/go.LICENSE.txt"

echo "wrote $OUT/gcsim.wasm ($(du -h "$OUT/gcsim.wasm" | cut -f1)) at $PIN"
