"""A GOOD export's `lock` reaches the database — `DESIGN_account_tracking.md` X.1.

**Parsed since the importer was written, and dropped until now.** An optimizer that builds
around a piece somebody has locked for another character gives advice they cannot take, which
is worse than not knowing: the recommendation looks actionable.
"""
from __future__ import annotations

from app.data.importers.good_importer import ParsedArtifact
from app.models.artifact import Artifact


def test_the_model_has_somewhere_to_put_it() -> None:
    assert "locked" in Artifact.__table__.c


def test_an_unlocked_piece_defaults_to_unlocked() -> None:
    assert ParsedArtifact.__dataclass_fields__["lock"].default is False


# The behavioural half — that a locked piece arrives locked and an unlocked one does not —
# is `tests/integration/test_good_import_keeps_equipment.py`, because it takes a real import
# through the real service. What is here is the shape those tests need to exist at all.
