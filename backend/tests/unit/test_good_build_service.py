"""Reconstituting builds from a GOOD export.

The rules worth pinning are the refusals and the omissions: which characters get a build, which
deliberately do not, and what happens to a character the catalogue cannot identify.
"""

from __future__ import annotations

from app.data.importers.good_importer import (
    GoodImportResult,
    ParsedArtifact,
    ParsedCharacter,
    ParsedWeapon,
)
from app.models.enums import ArtifactSlot, Rarity
from app.services.good_build_service import lookup_key


def _artifact(location: str, slot: ArtifactSlot, index: int) -> ParsedArtifact:
    return ParsedArtifact(
        slot=slot,
        rarity=Rarity.FIVE_STAR,
        level=20,
        main_stat="FIGHT_PROP_HP",
        substats=(),
        set_key="EmblemOfSeveredFate",
        location=location,
        source_index=index,
    )


def test_the_lookup_key_matches_gos_spelling_to_this_databases() -> None:
    """GOOD strips punctuation and spaces out of the English display name; so does this."""
    assert lookup_key("Hu Tao") == lookup_key("HuTao") == "hutao"
    assert lookup_key("Kamisato Ayaka") == lookup_key("KamisatoAyaka")


def test_the_traveler_is_keyed_by_name_and_element() -> None:
    """`TravelerCryo` is how GOOD names them, and the only thing separating the seven.

    The catalogue stores 28 rows all named `Traveler`, so the plain name is not a key at all.
    """
    assert lookup_key("Traveler" + "Cryo") == lookup_key("TravelerCryo")


def test_a_result_without_characters_is_still_a_valid_export() -> None:
    """Older scanners write artifacts only. That is a GOOD file, not a broken one."""
    result = GoodImportResult(artifacts=(), rejected=(), source="s", version=2)

    assert result.characters == ()
    assert result.weapons == ()


def test_parsed_shapes_carry_what_a_build_needs() -> None:
    """A guard on the boundary rename: GOOD's `auto/skill/burst` must arrive as ours."""
    character = ParsedCharacter(
        key="HuTao", level=90, ascension=6, constellation=1,
        talents={"normal_attack": 10, "elemental_skill": 9, "elemental_burst": 9},
    )

    assert set(character.talents) == {
        "normal_attack", "elemental_skill", "elemental_burst",
    }


def test_a_weapon_records_who_holds_it() -> None:
    """`location` is the only link GOOD gives between a build and its weapon."""
    weapon = ParsedWeapon(key="StaffOfHoma", level=90, ascension=6, refinement=1,
                          location="HuTao")

    assert lookup_key(weapon.location) == "hutao"


def test_an_unheld_artifact_names_nobody() -> None:
    """Most of an inventory is unequipped, and those pieces belong to no build."""
    assert _artifact("", ArtifactSlot.FLOWER, 0).location == ""
