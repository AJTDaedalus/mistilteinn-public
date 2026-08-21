"""Anchor assertions: values a correct fetch must reproduce.

**This is the part of the ZZZ toolkit that was worth porting.** The `base ⊕ overwrite`
merge it guarded does not exist in Genshin (there is one TextMap layer, see
`fetch.load_textmap`), but the reason the merge had an anchor does: a fetch can return
something structurally perfect and factually wrong — the wrong branch, a stale cache, a
truncated file — and every downstream table would then look seeded.

The anchors below are **cross-source**: each expected value comes from the nanoka payloads
committed in `tests/fixtures/nanoka_gi/`, which Chunk D already seeded the database from.
So a passing anchor says more than "the file downloaded" — it says the two independent
sources agree about the same object, which is the property Chunk F's citations will rest on.

Row counts are **not** anchored here. The snapshot's own tests do that job against the
committed files (`tests/unit/test_yuanshen_snapshot.py` pins 200 monster curve levels and
21 artifact levels), and a second copy of those numbers in a module that only the fetch CLI
imports would be a place for them to drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: `TextMap hash -> (expected English string, where the expectation and the hash come
#: from)`. Each hash is read out of an `ExcelBinOutput` row at the pinned commit; each
#: expected value is read out of a committed nanoka payload. Both halves are citable, and
#: they come from **independent sources that never see each other**.
#:
#: The layer each hash lives in is recorded because it is the point: three of these four
#: resolve **only** through `TextMap_Medium`, so an implementation that loaded the big
#: `TextMapEN.json` alone would fail them — which is precisely the mistake this anchor set
#: exists to catch, and the one an implementer would otherwise make silently.
TEXTMAP_ANCHORS: dict[str, tuple[str, str]] = {
    "1006042610": (
        "Kamisato Ayaka",
        (
            "AvatarExcelConfigData[10000002].nameTextMapHash (medium layer) against "
            "tests/fixtures/nanoka_gi/detail/character_10000002.json `name`"
        ),
    ),
    "902264035": (
        "Aquila Favonia",
        (
            "WeaponExcelConfigData[11501].nameTextMapHash (medium layer) against "
            "tests/fixtures/nanoka_gi/detail/weapon_11501.json `name`"
        ),
    ),
    "1675078771": (
        "Deepwood Memories",
        (
            "EquipAffixExcelConfigData[215025].nameTextMapHash (medium layer) against "
            "tests/fixtures/nanoka_gi/detail/artifact_15025.json `affix[0].name`"
        ),
    ),
    "235670334": (
        "Obtained from Mystic Offering",
        (
            "ReliquarySetExcelConfigData[15025].textList[0] (**full layer**) — included "
            "so a loader that dropped the full map instead of the medium one also fails"
        ),
    ),
}


def check_textmap_anchors(textmap: Mapping[str, str]) -> list[str]:
    """Every anchor that did **not** hold, as human-readable lines.

    Returns a list rather than raising so a caller can report all of them at once; an
    empty list is the pass. A missing key and a wrong value are reported differently,
    because they fail for different reasons — a missing key usually means the wrong file,
    a wrong value usually means the wrong commit.
    """
    failures: list[str] = []
    for key, (expected, source) in TEXTMAP_ANCHORS.items():
        actual = textmap.get(key)
        if actual is None:
            failures.append(f"key {key} is absent (expected {expected!r}, from {source})")
        elif actual != expected:
            failures.append(f"key {key} is {actual!r}, expected {expected!r} (from {source})")
    if not TEXTMAP_ANCHORS:
        failures.append(
            "no anchors are defined, so nothing was checked — a check that cannot run "
            "must block rather than pass (see CLAUDE.md, gate discipline).",
        )
    return failures
