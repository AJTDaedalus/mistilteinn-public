#!/usr/bin/env bash
# Runs npm audit and fails only on a GHSA advisory not already reviewed in
# audit-allowlist.txt, or an allowlist entry npm audit no longer reports
# (stale — remove it). See audit-allowlist.txt for format and reasoning.
set -uo pipefail

cd "$(dirname "$0")/.."

ALLOWLIST="audit-allowlist.txt"
AUDIT_OUTPUT=$(npm audit 2>&1)
echo "$AUDIT_OUTPUT"

found=$(grep -oE 'GHSA-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+' <<< "$AUDIT_OUTPUT" | sort -u)
allowed=$(grep -oE '^GHSA-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+' "$ALLOWLIST" | sort -u)

new=$(comm -23 <(printf '%s\n' "$found") <(printf '%s\n' "$allowed") | grep -v '^$')
stale=$(comm -13 <(printf '%s\n' "$found") <(printf '%s\n' "$allowed") | grep -v '^$')

status=0
if [ -n "$new" ]; then
  echo
  echo "NEW, unreviewed advisories (add to $ALLOWLIST with a reason, or fix the dependency):"
  echo "$new"
  status=1
fi
if [ -n "$stale" ]; then
  echo
  echo "STALE allowlist entries (npm audit no longer reports these — remove them from $ALLOWLIST):"
  echo "$stale"
  status=1
fi
if [ "$status" -eq 0 ]; then
  echo
  echo "All allowlisted advisories are current. No new findings."
fi
exit "$status"
