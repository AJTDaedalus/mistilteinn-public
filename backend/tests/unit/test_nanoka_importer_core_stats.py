"""Unit tests for importing `core_stats` from nanoka's `extra_level` dict.

nanoka's `character/<id>.json` `extra_level` dict carries the per-tier Core
Skill stat bonuses (1-indexed tiers "1".."6" = ranks A..F); the model's
`core_stats` column is a 0-indexed list of ZO-shaped rows. Previously this
block was never imported, leaving `core_stats` NULL unless the separate
`scripts/backfill_core_stats.py` was run against a ZO snapshot — which lagged
behind nanoka and had no data at all for newer agents.

The subtle part is flat-vs-percent: nanoka reuses the label "HP" for both
(flat for Yixuan, percent for Manato), so the entry's `format` string is the
only discriminator. Percent values arrive as basis points; Energy Regen is
neither flat nor basis points but hundredths.
"""

from __future__ import annotations

from app.data.importers.nanoka_importer import _extract_core_stats


def _tiers(*per_tier: list[tuple[str, float, str]]) -> dict:
    """Build a nanoka `extra_level` dict from (name, value, format) triples."""
    return {
        str(i): {
            "extra": {
                str(n): {"name": name, "value": value, "format": fmt}
                for n, (name, value, fmt) in enumerate(entries)
            }
        }
        for i, entries in enumerate(per_tier, start=1)
    }


# Real nanoka `character/1091.json` (Miyabi), fetched 2026-07-25 — flat anomProf.
_MIYABI = _tiers(
    *[
        [("Anomaly Proficiency", ap, "{0:0}"), ("Base ATK", atk, "{0:0.#}")]
        for ap, atk in ((30, 0), (30, 25), (60, 25), (60, 50), (90, 50), (90, 75))
    ]
)

# Real nanoka `character/1381.json` (Yixuan) — percent CRIT Rate, FLAT hp.
_YIXUAN = _tiers(
    *[
        [("CRIT Rate", cr, "{0:0.#%}"), ("HP", hp, "{0:0}")]
        for cr, hp in ((480, 0), (480, 140), (960, 140), (960, 280), (1440, 280), (1440, 420))
    ]
)

# Real nanoka (Manato) — same "HP" label, but PERCENT via the format string.
_MANATO = _tiers(
    *[
        [("HP", hp, "{0:0.#%}"), ("Base ATK", atk, "{0:0.#}")]
        for hp, atk in ((600, 0), (600, 25), (1200, 25), (1200, 50), (1800, 50), (1800, 75))
    ]
)

# Real nanoka (Astra Yao) — Energy Regen is hundredths, and carries no "%".
_ASTRA = _tiers(
    *[
        [("Base Energy Regen", er, "{0:0.##}"), ("Base ATK", atk, "{0:0.#}")]
        for er, atk in ((12, 0), (12, 25), (24, 25), (24, 50), (36, 50), (36, 75))
    ]
)


class TestExtractCoreStats:
    def test_returns_none_for_missing_block(self) -> None:
        assert _extract_core_stats({}) is None
        assert _extract_core_stats(None) is None  # type: ignore[arg-type]

    def test_emits_six_tiers(self) -> None:
        assert len(_extract_core_stats(_MIYABI)) == 6

    def test_flat_stats_pass_through_unscaled(self) -> None:
        rows = _extract_core_stats(_MIYABI)
        assert rows[0] == {"anomProf": 30, "atk": 0}
        assert rows[5] == {"anomProf": 90, "atk": 75}

    def test_percent_stats_scale_from_basis_points(self) -> None:
        rows = _extract_core_stats(_YIXUAN)
        assert rows[0]["crit_"] == 0.048
        assert rows[5]["crit_"] == 0.144

    def test_hp_label_is_flat_when_format_has_no_percent(self) -> None:
        rows = _extract_core_stats(_YIXUAN)
        assert rows[5]["hp"] == 420
        assert "hp_" not in rows[5]

    def test_hp_label_is_percent_when_format_has_percent(self) -> None:
        """Same "HP" label as Yixuan — only `format` distinguishes them."""
        rows = _extract_core_stats(_MANATO)
        assert rows[5]["hp_"] == 0.18
        assert "hp" not in rows[5]

    def test_energy_regen_scales_by_hundred_not_ten_thousand(self) -> None:
        rows = _extract_core_stats(_ASTRA)
        assert rows[0]["enerRegen"] == 0.12
        assert rows[5]["enerRegen"] == 0.36

    def test_unknown_labels_are_skipped_not_crashed(self) -> None:
        rows = _extract_core_stats(_tiers([("Some New Stat", 5, "{0:0}")]))
        assert rows[0] == {}
        assert len(rows) == 6

    def test_missing_tiers_yield_empty_rows(self) -> None:
        rows = _extract_core_stats({"1": {"extra": {}}})
        assert rows == [{}] * 6
