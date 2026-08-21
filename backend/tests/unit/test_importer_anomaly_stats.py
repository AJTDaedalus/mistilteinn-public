"""Unit tests guarding the AM/AP field mapping in both agent importers.

Anomaly Mastery and Anomaly Proficiency were stored backwards on all 58
agents until 2026-07-25 (`c13695c`) because nanoka's/hakushin's own field
names are counter-intuitive: `element_abnormal_power`/`ElementAbnormalPower`
is Anomaly MASTERY, and `element_mystery`/`ElementMystery` is Anomaly
PROFICIENCY. The swap silently reached production and went undetected for
weeks — see docs/RESEARCH_batch32c_followups.md. Nothing asserted this
mapping before this test existed (`rg` over backend/tests for
`element_abnormal_power` / `element_mystery` returned nothing).

Fixture values must be distinguishable so a re-swap fails the test instead
of passing by coincidence.
"""

from __future__ import annotations

from app.data.importers.hakushin_json_importer import (
    _extract_anomaly_stats as hakushin_extract_anomaly_stats,
)
from app.data.importers.nanoka_importer import (
    _extract_anomaly_stats as nanoka_extract_anomaly_stats,
)


class TestNanokaExtractAnomalyStats:
    def test_mastery_from_abnormal_power_proficiency_from_mystery(self) -> None:
        # Nangong Yu Lv1 (in-game confirmed): AM 90 / AP 93.
        stats = {"element_abnormal_power": 90, "element_mystery": 93}
        anomaly = nanoka_extract_anomaly_stats(stats)
        assert anomaly.mastery == 90
        assert anomaly.proficiency == 93

    def test_missing_fields_default_to_zero(self) -> None:
        assert nanoka_extract_anomaly_stats({}) == (0, 0)


class TestHakushinExtractAnomalyStats:
    def test_mastery_from_abnormal_power_proficiency_from_mystery(self) -> None:
        stats = {"ElementAbnormalPower": 116, "ElementMystery": 148}
        anomaly = hakushin_extract_anomaly_stats(stats)
        assert anomaly.mastery == 116
        assert anomaly.proficiency == 148

    def test_missing_fields_default_to_zero(self) -> None:
        assert hakushin_extract_anomaly_stats({}) == (0, 0)
