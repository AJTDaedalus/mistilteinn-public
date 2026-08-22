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
git -C "$SRC" fetch --depth 1 origin "$PIN" 2>/dev/null || git -C "$SRC" fetch origin
git -C "$SRC" checkout -q "$PIN"

echo "building gcsim browser wasm at $PIN"
( cd "$SRC" && GOOS=js GOARCH=wasm go build -o "$OUT/gcsim.wasm" ./cmd/wasm )
# Go moved this between releases: `misc/wasm/` up to 1.23, `lib/wasm/` from 1.24. Check both
# rather than pinning one — the first version of this script assumed `lib/` and failed on the
# very toolchain it was written with.
EXEC=""
for candidate in "$(go env GOROOT)/lib/wasm/wasm_exec.js" "$(go env GOROOT)/misc/wasm/wasm_exec.js"; do
  [ -f "$candidate" ] && EXEC="$candidate" && break
done
[ -n "$EXEC" ] || { echo "cannot find wasm_exec.js under $(go env GOROOT)" >&2; exit 1; }
cp "$EXEC" "$OUT/wasm_exec.js"
printf '%s\n' "$PIN" > "$OUT/BUILT_FROM"

echo "wrote $OUT/gcsim.wasm ($(du -h "$OUT/gcsim.wasm" | cut -f1)) at $PIN"
