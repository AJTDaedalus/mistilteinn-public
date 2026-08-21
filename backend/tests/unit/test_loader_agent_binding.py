"""Unit tests for the moves/agents loader's agent-binding validation (Task 2 of
docs/TASKS_move_key_resolution.md, DESIGN §3 L-A).

Covers: agent_id/agent_name required at load time (though optional on the bare model —
see AgentMovesSpec's docstring, dozens of tests construct it directly as an in-memory
moves_db fixture), agent_id must look like a UUID, and the file stem must cohere with
agent_name. All three are DB-free — whether agent_id/agent_name actually name a real
agent is validate_kits L4's job (Task 3), not this loader's.
"""

import json
from pathlib import Path

import pytest

from app.data.loaders.moves import load_agent_moves
from app.data.loaders.skill_overrides import load_skill_overrides


def _write_move_file(directory: Path, stem: str, data: dict) -> None:
    (directory / f"{stem}.json").write_text(json.dumps(data))


_VALID_MOVE = {
    "agent_id": "019e4c7e-6982-7711-a389-2c3d04c41097",
    "agent_name": "Alice",
    "moves": {},
}


def test_all_shipped_move_files_load_clean() -> None:
    """Regression guard: every real file in app/data/moves/agents/ must load with no error."""
    specs = load_agent_moves()
    # 27 since Task 17d added a PARTIAL norma.json covering one move. A partial file is
    # legitimate — before it, every Norma move took the simulator's tolerant fallback, and
    # covering one improves that move without making any claim about the others.
    assert len(specs) == 27
    assert "norma" in specs
    assert "nangong_yu" in specs
    assert specs["nangong_yu"].agent_id == "019e4c7e-7497-7511-b3a7-310fe5311efc"


def test_stem_disagrees_with_agent_name_raises(tmp_path: Path) -> None:
    _write_move_file(tmp_path, "wrong_stem", _VALID_MOVE)  # agent_name is "Alice"
    with pytest.raises(ValueError, match="disagrees with agent_name"):
        load_agent_moves(tmp_path)


def test_missing_agent_id_raises(tmp_path: Path) -> None:
    data = {**_VALID_MOVE, "agent_id": None}
    _write_move_file(tmp_path, "alice", data)
    with pytest.raises(ValueError, match="missing required 'agent_id'"):
        load_agent_moves(tmp_path)


def test_missing_agent_name_raises(tmp_path: Path) -> None:
    data = {**_VALID_MOVE, "agent_name": None}
    _write_move_file(tmp_path, "alice", data)
    with pytest.raises(ValueError, match="missing required 'agent_name'"):
        load_agent_moves(tmp_path)


def test_non_uuid_agent_id_raises(tmp_path: Path) -> None:
    data = {**_VALID_MOVE, "agent_id": "1511"}
    _write_move_file(tmp_path, "alice", data)
    with pytest.raises(ValueError, match="is not a UUID"):
        load_agent_moves(tmp_path)


def test_ampersand_and_dash_stems_resolve(tmp_path: Path) -> None:
    """The slug rule used by the coherence check must match real shipped conventions."""
    _write_move_file(
        tmp_path,
        "orphie_magus",
        {**_VALID_MOVE, "agent_name": "Orphie & Magus"},
    )
    _write_move_file(
        tmp_path,
        "soldier_0_anby",
        {**_VALID_MOVE, "agent_name": "Soldier 0 - Anby"},
    )
    specs = load_agent_moves(tmp_path)
    assert set(specs) == {"orphie_magus", "soldier_0_anby"}


def test_valid_file_loads_clean(tmp_path: Path) -> None:
    _write_move_file(tmp_path, "alice", _VALID_MOVE)
    specs = load_agent_moves(tmp_path)
    assert specs["alice"].agent_name == "Alice"


def test_skill_override_codename_agent_name_logs_warning_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Norma/Velina class: a codename-shaped agent_name is flagged, not fatal.

    A hard raise here would break load_skill_overrides() on the real directory (and
    therefore seed_db.py and the audit script) until Task 7 fixes those two files —
    see docs/LOG_move_key_resolution.md Task 2 for the reasoning. The DB-backed,
    build-gating check is validate_kits L4 (Task 3).
    """
    (tmp_path / "avatar_female_size99_test.json").write_text(
        json.dumps(
            {
                "agent_name": "Avatar_Female_Size99_Test",
                "moves": {"Some Move": {"hit_mode": "sequential"}},
            }
        )
    )
    with caplog.at_level("WARNING"):
        result = load_skill_overrides(tmp_path)
    assert "avatar_female_size99_test" in result
    assert any("codename" in rec.message for rec in caplog.records)
