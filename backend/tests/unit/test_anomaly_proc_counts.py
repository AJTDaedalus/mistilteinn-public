"""F-02: shock proc count 16 -> 10; single canonical proc-count table."""

from app.services.anomaly_simulator import ANOMALY_PROC_COUNTS
from app.services.damage_calculator import ANOMALY_BASE, AnomalyType, calculate_anomaly_damage


def test_shock_default_proc_count_is_ten():
    _, procs = ANOMALY_BASE[AnomalyType.SHOCK]
    assert procs == 10


def test_shock_total_at_default_procs_equals_ten_times_per_proc():
    result = calculate_anomaly_damage(
        anomaly_type=AnomalyType.SHOCK,
        atk=1000,
        anomaly_proficiency=100,
    )
    assert result.procs == 10
    assert result.total == result.per_proc * 10


def test_simulator_proc_counts_derive_from_canonical_table():
    for anomaly_type, (_, procs) in ANOMALY_BASE.items():
        assert ANOMALY_PROC_COUNTS[anomaly_type] == procs


def test_no_stale_sixteen_proc_literal_remains():
    assert ANOMALY_BASE[AnomalyType.SHOCK][1] != 16
    assert ANOMALY_PROC_COUNTS[AnomalyType.SHOCK] != 16
