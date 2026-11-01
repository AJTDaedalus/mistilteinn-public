"""The banner page parser, against the shapes the wiki actually served.

Each case is a page that went wrong on the 2026-11-01 refresh: a stub's placeholders and
`TBA` end date (Mitya's banner, ahead of its run), and a weapon banner the wiki files as a
character one because its infobox sets `type` twice.
"""

from __future__ import annotations

from scripts.refresh_banners import parse_wikitext

STUB = """{{Stub}}
{{Wish
|name              = Myriad Patterns Unfold 2026-11-04
|type              = Character Event
|time_start        = 2026-11-04 11:00:00
|time_end          = TBA<!--2026-12-31 17:59:59-->
|alongside         = Chanson of Many Waters/2026-11-04
}}
{{Wish Pool
|character_5_F = Mitya
|character_4_F = Valeriy; Unknown Character; Unknown Character
|character_5   = Dehya; Diluc
}}
"""

TYPED_TWICE = """{{Wish
|name              = Epitome Invocation 2026-10-13
|type              = Weapon Event
|type              = Character Event
|time_start        = 2026-10-13 18:00:00
|time_end          = 2026-11-03 14:59:59
}}
{{Wish Pool
|weapon_5_F = Azurelight; Symphonist of Scents
|weapon_4_F = Sturdy Bone; The Widsith
}}
"""


def test_a_stub_keeps_the_names_it_has_and_drops_the_placeholders() -> None:
    banner = parse_wikitext("Myriad Patterns Unfold/2026-11-04", "character", STUB)
    assert banner.featured_five == ["Mitya"]
    assert banner.featured_four == ["Valeriy"]


def test_an_unannounced_end_is_no_date_rather_than_the_raw_field() -> None:
    banner = parse_wikitext("Myriad Patterns Unfold/2026-11-04", "character", STUB)
    assert banner.starts_at == "2026-11-04 11:00:00"
    assert banner.ends_at is None


def test_the_pool_decides_the_kind_over_the_category() -> None:
    banner = parse_wikitext("Epitome Invocation/2026-10-13", "character", TYPED_TWICE)
    assert banner.kind == "weapon"
    assert banner.ends_at == "2026-11-03 14:59:59"


def test_an_ordinary_character_banner_is_unchanged() -> None:
    banner = parse_wikitext("Myriad Patterns Unfold/2026-11-04", "weapon", STUB)
    assert banner.kind == "character"
