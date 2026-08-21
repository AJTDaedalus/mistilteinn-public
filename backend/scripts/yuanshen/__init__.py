"""YuanShenResources snapshot toolkit (Chunk E).

Ported from fairy's `scripts/dimbreath/` — same three properties that made it
trustworthy (pinned commit SHA, local byte cache, an anchor assertion that fails loudly)
against a different host and a different game's table names.

**Committed snapshots only.** No gate, test or importer may fetch from GitLab at run time;
`tests/unit/test_no_network_at_runtime.py` (E.6) is what enforces that. Regenerating a
snapshot is a manual, reviewed step.
"""
