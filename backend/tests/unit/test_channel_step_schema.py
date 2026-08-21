"""`channel_s` on the combo/simulate step schemas (Task 7 of docs/TASKS_channeled_moves.md).

The field is the third parameterized-mode selector, alongside `variant_label` and
`cycle_position`. It defaults to None so every saved combo round-trips unchanged.
"""

from app.schemas.build import ComboStepInput
from app.schemas.simulate import SimulationStepRequest


def test_combo_step_defaults_channel_s_to_none() -> None:
    """Saved combos predate the field; they must round-trip untouched."""
    step = ComboStepInput(label="EX", move_name="EX Special Attack: Foo")
    assert step.channel_s is None
    assert "channel_s" in step.model_dump()


def test_combo_step_accepts_channel_s() -> None:
    step = ComboStepInput(label="Spray", move_name="EX Special", channel_s=2.5)
    assert step.channel_s == 2.5


def test_simulate_step_defaults_channel_s_to_none() -> None:
    step = SimulationStepRequest(agent_id="dps", move_name="EX Special Attack: Foo")
    assert step.channel_s is None


def test_simulate_step_accepts_channel_s() -> None:
    step = SimulationStepRequest(agent_id="dps", move_name="EX", channel_s=4.0)
    assert step.channel_s == 4.0


def test_channel_s_is_documented_in_openapi() -> None:
    """The field is the whole API surface of the feature -- an undocumented one is
    unusable by any client that is not reading this repo."""
    desc = SimulationStepRequest.model_json_schema()["properties"]["channel_s"]["description"]
    assert "channel" in desc.lower()
    assert "default_s" in desc
