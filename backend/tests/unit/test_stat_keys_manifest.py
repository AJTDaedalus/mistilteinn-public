"""The L3 manifest must stay in sync with the corpus — Task 11.

`frontend/src/app/shared/stat-keys.generated.ts` is the list of stat keys the frontend's
L3 spec checks STAT_META against. If a kit gains a new stat key and nobody regenerates the
manifest, the frontend check keeps passing against a stale list and the unmapped key ships
as a raw `FINAL_ATK_PCT +1000` chip — exactly issue #62. This test closes that loop from
the backend side, where the corpus actually lives.
"""

from __future__ import annotations

from scripts.refresh_kit_refs import (
    STAT_KEYS_TS_PATH,
    collect_stat_keys,
    render_stat_keys_module,
)


def test_generated_stat_key_manifest_is_current() -> None:
    assert STAT_KEYS_TS_PATH.is_file(), f"missing generated manifest: {STAT_KEYS_TS_PATH}"
    assert STAT_KEYS_TS_PATH.read_text() == render_stat_keys_module(collect_stat_keys()), (
        "stat-keys.generated.ts is stale — a modifier JSON uses a stat key the manifest "
        "does not list (or vice versa). Regenerate it:\n"
        "    cd backend && python -m scripts.refresh_kit_refs --only stats"
    )


def test_manifest_covers_the_corpus() -> None:
    keys = collect_stat_keys()
    assert len(keys) > 40
    assert "final_atk_pct" in keys  # the key that made issue #62 visible
