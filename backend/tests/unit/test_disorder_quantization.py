"""F-03: burn/corruption disorder+vortex time terms tick-quantize to 0.5s; shock is continuous."""

from app.services.damage_calculator import (
    AnomalyType,
    calculate_disorder_damage,
    calculate_vortex_damage,
)


def _disorder(anomaly_type: AnomalyType, t: float) -> int:
    return calculate_disorder_damage(
        anomaly_type=anomaly_type,
        atk=1000,
        anomaly_proficiency=100,
        attacker_level=60,
        enemy_base_def=0,
        enemy_level=60,
        remaining_duration=t,
        max_duration=10.0,
    ).base_dmg


def test_burn_disorder_quantizes_to_half_second_ticks():
    # t=0.9s -> floor(0.9/0.5) = 1 tick (not 1.8 continuous ticks)
    # mv = 45000 + 1*5000 = 50000, base = 5000
    assert _disorder(AnomalyType.BURN, 0.9) == 5000


def test_burn_disorder_two_ticks_at_one_second():
    # t=1.0s -> floor(1.0/0.5) = 2 ticks
    # mv = 45000 + 2*5000 = 55000, base = 5500
    assert _disorder(AnomalyType.BURN, 1.0) == 5500


def test_corruption_disorder_quantizes_to_half_second_ticks():
    # t=0.9s -> 1 tick; mv = 45000 + 1*6250 = 51250, base = 5125
    assert _disorder(AnomalyType.CORRUPTION, 0.9) == 5125


def test_corruption_disorder_two_ticks_at_one_second():
    # t=1.0s -> 2 ticks; mv = 45000 + 2*6250 = 57500, base = 5750
    assert _disorder(AnomalyType.CORRUPTION, 1.0) == 5750


def test_shock_disorder_stays_continuous():
    # Shock is unbracketed in Leifa: mv = 45000 + t*12500, no tick quantization.
    # t=0.9s -> mv = 45000 + floor(0.9*12500) = 45000+11250 = 56250, base = 5625
    assert _disorder(AnomalyType.SHOCK, 0.9) == 5625


def _vortex(vortex_kind: str, t: float) -> int:
    return calculate_vortex_damage(
        vortex_kind=vortex_kind,
        atk=1000,
        anomaly_proficiency=100,
        attacker_level=60,
        enemy_base_def=0,
        enemy_level=60,
        remaining_duration=t,
        max_duration=10.0,
    ).base_dmg


def test_burn_vortex_quantizes_to_half_second_ticks():
    # t=0.9s -> 1 tick; mv = 90000 + 1*5000 = 95000, base = 9500
    assert _vortex("burn", 0.9) == 9500


def test_corruption_vortex_quantizes_to_half_second_ticks():
    # t=0.9s -> 1 tick; mv = 65000 + 1*6250 = 71250, base = 7125
    assert _vortex("corruption", 0.9) == 7125


def test_shock_vortex_stays_continuous():
    # t=0.9s -> mv = 65000 + floor(0.9*12500) = 65000+11250 = 76250, base = 7625
    assert _vortex("shock", 0.9) == 7625
