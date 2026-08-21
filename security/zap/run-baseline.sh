#!/usr/bin/env bash
#
# ZAP baseline scan — OPT-IN ONLY.
#
# Why the guard exists
# --------------------
# `zap.yaml` targets https://mistilteinn.aetherus.dev. There is no deploy behind it —
# that is Chunk K. A DAST scan pointed at nothing spiders nothing, finds nothing, and
# writes a report full of PASSes, which reads exactly like a clean scan. The repo has
# already lost one artifact to that failure mode: the committed zap-baseline-prod.json,
# deleted in A.3, claimed a clean baseline against this same host.
#
# The pre-flight below checks HTTP, NOT DNS, and that distinction was measured rather
# than guessed. aetherus.dev has WILDCARD DNS onto Cloudflare, so every subdomain
# resolves — `definitely-not-real-xyz123.aetherus.dev` answers just as readily as this
# one. A DNS pre-flight passes and the scan then runs happily against Cloudflare's
# error page: an unguarded run on 2026-08-21 reported "PASS: 59, FAIL-NEW: 0" against a
# host returning 525 with no origin behind it. That report would have been a lie.
#
# So: this script refuses to run unless someone asks for it explicitly, and refuses to
# run against a target that is not actually serving even then. Both refusals **exit
# non-zero**. CLAUDE.md's rule is that a skipped check blocks and is never a pass;
# a guard that exits 0 to mean "did not run" is the bug it is guarding against.
#
#   ZAP_SCAN_ENABLED=1 ./security/zap/run-baseline.sh
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config="${here}/zap.yaml"

target="$(grep -oE 'https?://[A-Za-z0-9.-]+' "${config}" | head -n 1)"
host="${target#*://}"

if [[ "${ZAP_SCAN_ENABLED:-0}" != "1" ]]; then
  echo "SKIPPED: ZAP baseline scan did not run (ZAP_SCAN_ENABLED is not 1)."
  echo "         This is NOT a pass. Nothing was scanned and nothing was proven."
  echo "         Target would have been: ${target}"
  echo "         Enable with: ZAP_SCAN_ENABLED=1 $0"
  exit 78
fi

status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${target}" || echo 000)"
if [[ "${status}" == "000" || "${status}" -ge 500 ]]; then
  echo "BLOCKED: ${target} answered HTTP ${status} — nothing is serving there."
  echo "         (5xx includes Cloudflare's 52x origin errors: the DNS name resolves"
  echo "          via a wildcard, but no origin is behind it.)"
  echo "         Refusing to scan: a scan of a host that is not serving the app"
  echo "         produces an all-PASS report that means nothing. Chunk K stands up"
  echo "         the deploy target; until then this refusal is the correct outcome."
  exit 78
fi

echo "Running ZAP baseline against ${target}"
exec docker run --rm \
  -v "${here}:/zap/wrk/:rw" \
  -t zaproxy/zap-stable \
  zap.sh -cmd -autorun /zap/wrk/zap.yaml
