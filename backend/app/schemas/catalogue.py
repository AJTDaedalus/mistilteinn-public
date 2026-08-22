"""Response schemas for the seeded game catalogue — characters, weapons, sets, enemies.

Read-only. Nothing here has a `Create` or `Update` sibling: these rows come from the nanoka
importer and a route that let a user edit them would put fabricated game data behind an API
whose whole value is that it is the game's.

## The enums are the enums

`element`, `weapon_type` and `rarity` are typed as their `models.enums` members rather than
as `str`. The wire format is identical — they are `StrEnum`s whose values are the payload's
own spellings — but the *schema* then says what the field can actually be, and the generated
client gets the same precision the query parameters already had.

A response typed `str` where an enum is always returned is the contract under-describing
itself: it forces every consumer to re-state the vocabulary or cast, which is how a second
definition of the same list gets created.

## Two shapes per entity, on purpose

A `*Summary` is what a list returns and a `*Read` is what one row returns. The catalogue's
detail rows are large — a character carries six talents with a level table each, six
constellations and four passives — and returning that for 150 characters at once is a
response nobody wants and a query nobody needs. The split is why
`CharacterRepository.search` loads no relationships at all.

## Curves and raw payload fields are exposed, not hidden

`prop_curves`, `ascension_stats`, `param_list` and `add_props` are all in the responses.
They look like internals and they are not: **`base_hp` alone cannot be evaluated at any
level** without the curve that grows it (F.3 found that out by having two of the three), and
`param_list` is where a conditional set bonus's numbers live at all — 324 affix rows across
the 65 sets have `add_props` entirely `FIGHT_PROP_NONE`. A client that only got the pretty
fields would have to re-fetch the source to do anything with them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.models.enums import Element, Rarity, WeaponType

_FROM_ORM = {"from_attributes": True}


# ---- Characters ------------------------------------------------------------

class TalentScalingRead(BaseModel):
    """One level's row of a talent's published multiplier table."""

    level: int
    #: The `desc` format strings, e.g. `"1-Hit DMG|{param1:F1P}"`. Kept beside `params`
    #: rather than pre-parsed: a mis-parse is then a bug in a parser, not lost data.
    labels: list[Any]
    params: list[Any]

    model_config = _FROM_ORM


class TalentRead(BaseModel):
    """One talent, with its per-level scaling table."""

    nanoka_id: int
    talent_type: str
    name: str
    description: str
    icon: str | None = None
    scalings: list[TalentScalingRead] = []

    model_config = _FROM_ORM


class ConstellationRead(BaseModel):
    """One constellation."""

    nanoka_id: int
    position: int
    name: str
    description: str
    icon: str | None = None

    model_config = _FROM_ORM


class AscensionPassiveRead(BaseModel):
    """One ascension passive.

    `unlock_ascension` is **nullable and stays that way**: a passive gated by a condition
    rather than a phase has no phase, and a `0` there would claim it is ungated.
    """

    nanoka_id: int
    unlock_ascension: int | None = None
    unlock_condition_ids: list[Any] = []
    name: str
    description: str
    icon: str | None = None

    model_config = _FROM_ORM


class CharacterSummary(BaseModel):
    """A character as a list entry."""

    id: str
    #: The source key verbatim — a **string**, because 28 of the 150 are Traveler variants
    #: spelled `10000005-2`. An int here would drop them.
    nanoka_id: str
    name: str
    #: Null for the two entries whose payload element is the literal `"None"`.
    element: Element | None = None
    weapon_type: WeaponType
    rarity: Rarity
    region: str | None = None
    icon: str | None = None

    model_config = _FROM_ORM


class CharacterRead(CharacterSummary):
    """A character in full: base stats, curves, ascension table, and the kit rows."""

    base_hp: float
    base_atk: float
    base_def: float
    base_elemental_mastery: float
    base_crit_rate: float
    base_crit_dmg: float
    #: `{FIGHT_PROP_BASE_*: GROW_CURVE_*}`. Without it the three base stats above cannot be
    #: evaluated at any level, so it is part of the answer, not an implementation detail.
    prop_curves: dict[str, Any] = {}
    ascension_stat_type: str | None = None
    ascension_stats: list[Any] = []
    #: Nullable until the burst's `Energy Cost` row is parsed out of its description, and
    #: deliberately not defaulted to a number that would look like real data.
    burst_energy_cost: int | None = None
    release_date: str | None = None

    talents: list[TalentRead] = []
    constellations: list[ConstellationRead] = []
    ascension_passives: list[AscensionPassiveRead] = []


# ---- Weapons ---------------------------------------------------------------

class WeaponRefinementRead(BaseModel):
    """One refinement step, R1-R5."""

    level: int
    name: str
    description: str
    #: The numbers the description renders inside `<color=…>` markup.
    param_list: list[Any] = []

    model_config = _FROM_ORM


class WeaponSummary(BaseModel):
    """A weapon as a list entry.

    `base_atk` and `sub_stat_type` are nullable because eight rows (the `ITEM_TPS_WEAPON`
    family, ids 224001-224008) publish `atk: null` and `sub: null`. They are imported
    visibly rather than dropped; a client should expect to see them.
    """

    id: str
    nanoka_id: int
    name: str
    weapon_type: WeaponType
    rarity: Rarity
    base_atk: float | None = None
    sub_stat_type: str | None = None
    icon: str | None = None

    model_config = _FROM_ORM


class WeaponRead(WeaponSummary):
    """A weapon in full, with its growth curves and refinement rows."""

    base_atk_curve: str | None = None
    sub_stat_base_value: float | None = None
    sub_stat_curve: str | None = None
    ascension_atk: dict[str, Any] = {}
    description: str = ""
    refinements: list[WeaponRefinementRead] = []


# ---- Artifact sets ---------------------------------------------------------

class ArtifactSetAffixRead(BaseModel):
    """One set-bonus row."""

    position: int
    pieces_required: int
    name: str
    description: str
    #: The static props, `[{prop_type, value}, …]`. A **conditional** bonus has
    #: `FIGHT_PROP_NONE` for every one of them and its numbers in `param_list`.
    add_props: list[Any] = []
    param_list: list[Any] = []

    model_config = _FROM_ORM


class ArtifactSetRead(BaseModel):
    """One artifact set and its affixes.

    `piece_thresholds` is **data**, not the constant `[2, 4]`: 60 of the 65 sets at 7.0.51
    are `[2, 4]` and five are `[1]` — the "Prayers" circlets. A client hardcoding 2pc/4pc
    gets those five wrong, which is why the field is on the summary and not buried.
    """

    id: str
    nanoka_id: int
    name: str
    icon: str | None = None
    piece_thresholds: list[Any] = []
    available_ranks: list[Any] = []
    affixes: list[ArtifactSetAffixRead] = []

    model_config = _FROM_ORM


# ---- Enemies ---------------------------------------------------------------

class EnemyProfileRead(BaseModel):
    """One enemy profile.

    **`base_hp` / `base_atk` / `base_def` are curve bases, not level-90 stats.** A
    Hilichurl's `base_hp` is `13.584`. The number a damage calculation needs is that base
    scaled by the growth curve named in `stat_curves` at `level`. Anything that multiplies
    these by a crit multiplier and calls the result damage is wrong, so `stat_curves` ships
    with them and the field names keep the word "base".

    `level` describes what the profile is *for*; it is not a level these stats have been
    evaluated at.
    """

    id: str
    nanoka_id: int | None = None
    name: str
    level: int
    base_hp: float
    base_atk: float
    base_def: float
    stat_curves: dict[str, Any] = {}

    physical_res: float
    anemo_res: float
    cryo_res: float
    dendro_res: float
    electro_res: float
    geo_res: float
    hydro_res: float
    pyro_res: float

    tags: str = ""
    #: Which spawn configuration these stats came from, and how many the family had. One
    #: row is one monster *family*: 189 of the 360 with children have children that differ
    #: in base stats. "These are one of N configs" should be readable, not folklore.
    variant_nanoka_id: int | None = None
    variant_count: int = 0

    model_config = _FROM_ORM
