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

from pydantic import BaseModel, computed_field

from app.models.enums import Element, Rarity, StatType, WeaponType
from app.services import element_symbols, traveler, weapon_symbols

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


class WeaponClassed(BaseModel):
    """A schema that names a weapon class, and publishes a readable label for it.

    A mixin rather than the same four lines in two schemas. They were written twice first,
    and the mutation harness refused the injection for an ambiguous target — which is the
    duplication showing up as a tooling complaint before it shows up as a bug. This repo's
    recurring failure is a second implementation nobody is exercising.
    """

    weapon_type: WeaponType

    @computed_field
    @property
    def weapon_type_display(self) -> str:
        """`Sword`, beside the raw `WEAPON_SWORD_ONE_HAND`.

        The value is the game's internal spelling — the reason `Element` reads well in this
        output and `WeaponType` does not. Published rather than left to each client, because
        a page deriving it would be a second copy of `WeaponType.display`.
        """
        return self.weapon_type.display

    @computed_field
    @property
    def weapon_type_icon(self) -> str | None:
        """The class mark's basename — Genshin's own sword/bow/polearm/claymore/catalyst glyph.

        On the **mixin**, so a character card and a weapon card cannot show different marks
        for the same class. They spell the class differently in the source
        (`WEAPON_CROSSBOW` against `ITEM_TPS_WEAPON`) and this is the second thing after
        `weapon_type_display` that would otherwise be derived twice.

        `None` for the crossbow class, which has no mark at this pin — two unreleased Traveler
        variants with no talents seeded, so there is nothing to derive.
        `app/services/weapon_symbols.py` on why the mapping is a query and not five lines
        written from memory.
        """
        return weapon_symbols.symbol_for(self.weapon_type)


class CharacterSummary(WeaponClassed):
    """A character as a list entry."""

    id: str
    #: The source key verbatim — a **string**, because 28 of the 150 carry a body-and-element
    #: key spelled `10000005-2`: **14 Traveler variants and 14 practice mannequins**. An int
    #: here would drop them. (The catalogue holds **16** Travelers, not 28 — the other two are
    #: the unreleased crossbow bodies, whose keys have no suffix.)
    nanoka_id: str
    name: str
    #: Null for the two entries whose payload element is the literal `"None"`.
    element: Element | None = None
    #: Datamined ahead of release, and **absent from this list unless asked for**: the
    #: endpoint's `include_beta` defaults to false, so a caller that does not know about beta
    #: characters never receives one. `/planner` asks; nothing else does.
    #:
    #: Published so a caller that opts in can *say so* on screen. A beta row that arrived
    #: looking like any other would be the worst of both: shown, and shown as settled.
    is_beta: bool = False
    rarity: Rarity
    region: str | None = None
    icon: str | None = None

    model_config = _FROM_ORM

    @computed_field
    @property
    def element_icon(self) -> str | None:
        """The vision emblem's basename — the flame, the droplet, the snowflake.

        Published rather than derived client-side, for the same reason `weapon_type_icon` is:
        a page building `f"{element}.webp"` would request art nobody vendored the moment a
        patch adds a vision, and would render a broken mark instead of nothing.

        `None` for the two rows whose element is the literal `"None"`.
        """
        return element_symbols.symbol_for(self.element)

    @computed_field
    @property
    def display_name(self) -> str:
        """The name to put on a card, which for sixteen characters is not `name`.

        Every `Traveler` row is *named* `Traveler` — no gender column, no title, and upstream
        publishes one `en` value for all sixteen. So the roster tab drew Aether Pyro and Lumine
        Pyro as the same row twice, and the two unreleased bodies, which have no element and so
        no chip, drew *identically*.

        **Computed rather than stored**, like `element_icon` and `stars` beside it: a display
        name is presentation, and storing it would mean a migration whenever a body or element
        is added plus a second copy of the truth to keep in step.

        `app/services/traveler.py` says why it is keyed on the icon — it is the only signal
        that exists — and `docs/RESEARCH_traveler_identity.md` has the rest.
        """
        return traveler.display_name(
            name=self.name,
            icon=self.icon,
            element=getattr(self.element, "value", self.element),
        )

    @computed_field
    @property
    def stars(self) -> int:
        """`5` for `five_star`, from `Rarity.stars`.

        Published for the same reason `WeaponSummary.stars` is: the characters page was
        deriving it with `rarity === 'five_star' ? 5 : 4`, which silently calls anything else
        — a lower rarity, a null — a four-star. A second copy of a rule that already exists
        server-side, and the copy is the one that guesses.
        """
        return Rarity(self.rarity).stars


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


class WeaponSummary(WeaponClassed):
    """A weapon as a list entry.

    `base_atk` and `sub_stat_type` are nullable because eight rows (the `ITEM_TPS_WEAPON`
    family, ids 224001-224008) publish `atk: null` and `sub: null`. They are imported
    visibly rather than dropped; a client should expect to see them.
    """

    id: str
    nanoka_id: int
    name: str
    #: Datamined ahead of release, and absent from this list unless `include_beta` asks.
    #: Published so a caller that opts in can mark the card rather than showing it as settled.
    is_beta: bool = False
    rarity: Rarity
    base_atk: float | None = None
    sub_stat_type: str | None = None
    icon: str | None = None

    model_config = _FROM_ORM

    @computed_field
    @property
    def sub_stat_display(self) -> str | None:
        """`CRIT DMG` for `FIGHT_PROP_CRITICAL_HURT`, from `StatType.display`.

        Published rather than left to the client, for the reason `weapon_type_display`
        already is: a page translating `FIGHT_PROP_*` itself would be a second copy of a
        rule that lives in `models/enums.py`, free to drift. The catalogue was printing the
        raw key on screen because there was nothing else to print.

        Null for the **18** weapons whose payload substat is absent — a weapon with no
        substat, not one whose substat is unknown. (Counted, not copied: two comments in
        `services/stat_calculator.py` say "ten" and "the eight TPS entries" for related but
        differently-scoped sets, and repeating either here would have made a third number.)
        """
        if not self.sub_stat_type:
            return None
        try:
            return StatType(self.sub_stat_type).display
        except ValueError:
            # A key this enum does not cover is shown verbatim rather than blanked: a
            # visible oddity is findable, and a blank is a weapon that looks substat-less.
            return self.sub_stat_type

    @computed_field
    @property
    def stars(self) -> int:
        """`5` for `five_star`. The card draws these; nobody reads `four_star`."""
        return Rarity(self.rarity).stars


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
    #: The set's representative icon — nanoka's own, which is the **flower**.
    icon: str | None = None
    #: The icon for each slot, keyed by `ArtifactSlot` value.
    #:
    #: Null on a database seeded before this field existed, in which case a client should fall
    #: back to `icon` — the old behaviour, which drew a flower in every slot.
    part_icons: dict[str, str] | None = None
    piece_thresholds: list[Any] = []
    available_ranks: list[Any] = []
    affixes: list[ArtifactSetAffixRead] = []
    #: Whether gcsim implements this set at the pin, and so whether it can be simulated.
    #:
    #: **Published because a client cannot work it out and was guessing.** The optimizer's
    #: "All 4-piece" button selected every set the inventory could field four of, which
    #: included ones gcsim has no key for — and one such set fails the *whole* calibration
    #: with a 422 naming it, so the run returns nothing at all. The picker has to be able to
    #: offer only what can be run, which is the guarantee `RotationOptions` already makes
    #: about actions: *the picker offers exactly what the validator accepts.*
    #:
    #: A set is usually absent because it was released after the pin. That is a re-pin, not a
    #: fault, and it is why this is a fact about the set rather than an error about the run.
    simulable: bool = False

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
    #: The monster's art basename, e.g. `UI_MonsterIcon_Hili_None_01`. Read from the family
    #: payload — `child` variants carry none, and the codex shows one picture per family.
    icon: str | None = None
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


class OwnedWeaponRead(BaseModel):
    """One weapon a user owns, with who is holding it.

    **The holder is a portrait, not a name**, which is what the owner asked for — so this
    publishes `holder_icon` beside `holder_name`. Both: an icon alone is a label only for
    someone who already recognises the art, which is the argument `ElementChip` and
    `WeaponMark` both make.
    """

    id: str
    #: Null when the catalogue no longer has the row — a re-pin that retires a weapon leaves
    #: the user's copy visible and unresolved rather than deleting their inventory.
    weapon: WeaponSummary | None = None
    level: int
    ascension: int
    refinement: int
    #: The build holding this copy, or null when it is spare.
    build_id: str | None = None
    holder_name: str | None = None
    #: The holder's avatar basename, for `CatalogueIcon`.
    holder_icon: str | None = None

    model_config = _FROM_ORM

    @classmethod
    def of(cls, row: object) -> OwnedWeaponRead:
        """Build one from an `OwnedWeapon` with its relationships loaded.

        A classmethod rather than a validator so the holder is resolved in **one** place: the
        character hangs off the build, which hangs off the row, and three call sites walking
        that chain themselves is three chances to render a weapon on the wrong face.
        """
        build = getattr(row, "build", None)
        character = getattr(build, "character", None) if build is not None else None
        weapon = getattr(row, "weapon", None)
        return cls(
            id=str(row.id),
            weapon=WeaponSummary.model_validate(weapon) if weapon is not None else None,
            level=row.level,
            ascension=row.ascension,
            refinement=row.refinement,
            build_id=str(build.id) if build is not None else None,
            holder_name=getattr(character, "name", None),
            holder_icon=getattr(character, "icon", None),
        )


class ElementRead(BaseModel):
    """One vision, and the emblem that stands for it.

    Published rather than derived client-side, for exactly the reason `element_icon` is: a
    filter bar building `f"{element}.webp"` would request art nobody vendored the moment a
    patch adds an eighth vision, and would render a broken mark instead of nothing. The
    allowlist lives in `app/services/element_symbols.py` and this is its only other reader.

    **Physical is not a vision** and is absent, which is the ZZZ-shaped trap DESIGN §2.6 names.
    """

    #: The element's own name — `Pyro`, `Anemo`. Both the value a filter sends and its label.
    value: str
    #: Basename of the vision emblem, for `CatalogueIcon`.
    icon: str


class WeaponClassRead(BaseModel):
    """One weapon class, its readable name, and its mark.

    Published for the same reason `ElementRead` is: a filter bar otherwise carries its own
    copy of the class list *and* builds an icon basename, and both are allowlists server-side
    on purpose. `app/services/weapon_symbols.py` explains why the crossbow class is not here.
    """

    #: The source's own spelling — `WEAPON_SWORD_ONE_HAND`. What a filter sends.
    value: str
    #: What a person reads — `Sword`, `Polearm`.
    display: str
    #: Basename of the class mark, for `CatalogueIcon`.
    icon: str


class WeaponRecommendationRead(BaseModel):
    """One weapon KeqingMains lists for a character."""

    #: Where it appears in KQM's list. **Not a rank**: the table carries an order and no rank
    #: numbers, and publishing it as a rank would put words in the source's mouth.
    position: int
    #: The catalogue row, resolved from `weapon_nanoka_id` at read time.
    #:
    #: **Null when this pin does not have the weapon**, rather than the row being dropped:
    #: KQM's sentence and their ordering are still true, and what is missing is a card to hang
    #: them on. A client marks such a row unlisted; shortening a cited list quietly would be
    #: worse than showing one entry it cannot link.
    weapon_id: str | None = None
    #: The game's id, which is what the snapshot stores — see `services/kqm_weapons.py`.
    #: Published so a client that already works in nanoka ids (the optimizer's set catalogue
    #: does) can join without a second lookup.
    weapon_nanoka_id: int
    weapon_name: str
    #: KQM's own sentence, verbatim. Summarising it would be this repo asserting a judgement
    #: it did not make.
    note: str
    #: Which build this is for, on a guide that recommends per build; `""` on a quick guide.
    #:
    #: **A ranking KQM wrote for *Burst Support Zhongli* is not a ranking for Zhongli.** His
    #: guide carries 46 recommendations across five playstyles, and publishing them without
    #: this would flatten a distinction the source drew deliberately.
    playstyle: str = ""
    #: KQM's own comparison as published — `"114.2%"` of a baseline their note names. `""` on a
    #: quick guide, which states an order and no number; deriving one would be a figure this
    #: repo invented under someone else's name.
    relative_dps: str = ""


class SetRecommendationRead(BaseModel):
    """One artifact set — or one *kind* of two-piece — KeqingMains lists for a character."""

    position: int
    #: `"set"` when this names a set in this catalogue; `"stat"` when KQM described a two-piece
    #: by the stat it grants rather than by a name.
    #:
    #: **`2pc HP% / Skill% / ER / Hydro%` is not a set and must not become one.** It names
    #: *every* set whose two-piece grants HP%, which this catalogue already knows — so it is
    #: published as KQM's text and the client colours the two-piece selector from it, rather
    #: than being resolved to a name KQM never wrote.
    kind: str
    #: KQM's own text for the row, verbatim, whichever kind it is.
    as_written: str
    #: KQM's own sentence about it. Verbatim.
    note: str
    #: The catalogue row, resolved at read time; null on a `stat` row and on a set this pin
    #: does not have.
    set_id: str | None = None
    #: The game's id. Null on a `stat` row, which names no set.
    set_nanoka_id: int | None = None
    set_name: str | None = None
    #: `"4pc"`, `"2pc"`, or `"2pc/4pc"` when KQM wrote a piece count in front of the name.
    pieces: str = ""
    #: Which build this is for, on a guide that recommends per build.
    playstyle: str = ""
    #: KQM's own comparison as published — `"100%"` of a baseline their note names.
    relative_dps: str = ""


class CharacterWeaponGuideRead(BaseModel):
    """A character's captured recommendations, and where they came from.

    **The citation travels with the claim.** `url` and `retrieved_at` are published so a reader
    can open the page rather than take this repo's word — the same discipline as the reaction
    table, and for the reason `CLAUDE.md` names: fabricated citations in curated data is the
    failure this project must not import.
    """

    character: str
    url: str
    retrieved_at: str
    weapons: list[WeaponRecommendationRead]
    #: The artifact-set half of the same guide. Empty where KQM's page has no set table.
    sets: list[SetRecommendationRead] = []


class ReactionRead(BaseModel):
    """One elemental reaction, and what a party must field to produce it.

    Published so the client filters on the **same committed table** the backend reads, rather
    than a second copy that would drift — the reason every vocabulary here is served rather
    than restated.

    **Fifteen are listed and six are not** — Shattered, which is not an element pair, and the
    five Lunar/Stellar variants by owner ruling (`DECISIONS.md` §23).
    `app/services/reactions.py` explains each, and every excluded row stays in the committed
    JSON with its citation. A filter that quietly mis-classified a team is worse than one that
    offers less.
    """

    id: str
    name: str
    #: Elements every party must have.
    required: list[str]
    #: Swirl and Crystallize only: one of these, *in addition* to `required`. Empty otherwise.
    one_of: list[str] = []
