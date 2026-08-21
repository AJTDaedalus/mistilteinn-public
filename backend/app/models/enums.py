"""Domain enums plus the numeric ID maps importers use to translate hakushin/nanoka codes."""

import enum


class UserStatus(enum.StrEnum):
    """Admin-approval lifecycle state for a `User` account."""

    PENDING = "pending"
    APPROVED = "approved"
    DISABLED = "disabled"


class Element(enum.StrEnum):
    """One of the 5 ZZZ damage elements (plus Wind/Aero, used only for anomaly typing)."""

    PHYSICAL = "physical"
    FIRE = "fire"
    ICE = "ice"
    ELECTRIC = "electric"
    ETHER = "ether"
    WIND = "wind"
    # Remielle's unique sixth "attribute" — no DMG% bucket, no disc main stat, no
    # enemy RES, and no anomaly (see DESIGN_remielle.md §4.2). Its numeric
    # ELEMENT_ID_MAP entry is intentionally NOT filled in here — it is added in
    # Task 5 from the raw id logged by _extract_element's unmapped-element warning.
    LUMIFLUX = "lumiflux"


# Mapping from hakushin element IDs to our enum
ELEMENT_ID_MAP: dict[int, Element] = {
    200: Element.PHYSICAL,
    201: Element.FIRE,
    202: Element.ICE,
    203: Element.ELECTRIC,
    204: Element.WIND,
    205: Element.ETHER,
    # 300 = Remielle's raw hakushin element id, confirmed from the Task 5
    # re-seed warning: "Unmapped element id(s) ['300'] in element_type" and
    # "Unmapped per-hit element id 300 on skill_id 1581NNN (agent
    # hakushin_id=1581)" — see docs/LOG_remielle.md Task 5 (Worker).
    300: Element.LUMIFLUX,
}


class Specialty(enum.StrEnum):
    """One of the 6 ZZZ agent roles (Attack, Stun, Anomaly, Support, Defense, Rupture)."""

    ATTACK = "attack"
    STUN = "stun"
    ANOMALY = "anomaly"
    SUPPORT = "support"
    DEFENSE = "defense"
    RUPTURE = "rupture"


SPECIALTY_ID_MAP: dict[int, Specialty] = {
    1: Specialty.ATTACK,
    2: Specialty.STUN,
    3: Specialty.ANOMALY,
    4: Specialty.SUPPORT,
    5: Specialty.DEFENSE,
    6: Specialty.RUPTURE,
}


class AttackType(enum.StrEnum):
    """One of the 8 attack categories an `Attack` hit belongs to (Basic, Dash, Ultimate, etc.)."""

    BASIC = "basic"
    DASH = "dash"
    DODGE_COUNTER = "dodge_counter"
    SPECIAL = "special"
    EX_SPECIAL = "ex_special"
    CHAIN = "chain"
    ULTIMATE = "ultimate"
    ASSIST_FOLLOWUP = "assist_followup"


class Rarity(enum.StrEnum):
    """Item/agent rank tier (S highest, then A, B), shared across agents, discs, and W-Engines."""

    S = "S"
    A = "A"
    B = "B"


RARITY_INT_MAP: dict[int, Rarity] = {
    4: Rarity.S,
    3: Rarity.A,
    2: Rarity.B,
}


class DiscSlot(enum.IntEnum):
    """Which of the 6 Disc Drive equip slots a `Disc` occupies (fixed main-stat pool per slot)."""

    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6


class StatType(enum.StrEnum):
    """Every stat key usable as a disc main/substat or a buff target in the calc engine."""

    HP = "hp"
    HP_PCT = "hp_pct"
    ATK = "atk"
    ATK_PCT = "atk_pct"
    DEF = "def"
    DEF_PCT = "def_pct"
    CRIT_RATE = "crit_rate"
    CRIT_DMG = "crit_dmg"
    PEN_FLAT = "pen_flat"
    PEN_RATIO = "pen_ratio"
    ANOMALY_MASTERY = "anomaly_mastery"
    ANOMALY_PROFICIENCY = "anomaly_proficiency"
    IMPACT = "impact"
    IMPACT_PCT = "impact_pct"
    ENERGY_REGEN = "energy_regen"
    PHYSICAL_DMG = "physical_dmg"
    FIRE_DMG = "fire_dmg"
    ICE_DMG = "ice_dmg"
    ELECTRIC_DMG = "electric_dmg"
    ETHER_DMG = "ether_dmg"
    WIND_DMG = "wind_dmg"
    DISORDER_DMG_BONUS = "disorder_dmg_bonus"
    VORTEX_DMG_BONUS = "vortex_dmg_bonus"


class AnomalyType(enum.StrEnum):
    """The status-effect anomaly triggered by each element's buildup (see `ELEMENT_TO_ANOMALY`)."""

    ASSAULT = "assault"  # Physical
    BURN = "burn"  # Fire
    SHATTER = "shatter"  # Ice
    SHOCK = "shock"  # Electric
    CORRUPTION = "corruption"  # Ether
    WINDSWEPT = "windswept"  # Aero


ELEMENT_TO_ANOMALY: dict[Element, AnomalyType] = {
    Element.PHYSICAL: AnomalyType.ASSAULT,
    Element.FIRE: AnomalyType.BURN,
    Element.ICE: AnomalyType.SHATTER,
    Element.ELECTRIC: AnomalyType.SHOCK,
    Element.ETHER: AnomalyType.CORRUPTION,
    Element.WIND: AnomalyType.WINDSWEPT,
}

# Inverse of ELEMENT_TO_ANOMALY. Needed by callers that hold an anomaly and must
# recover the element it belongs to — element-scoped buff rows are filtered
# against the *anomaly's* element, not the acting agent's (issue #162: Jane's
# Assault CRIT grant is Physical-scoped and must not reach a teammate's Burn).
ANOMALY_TO_ELEMENT: dict[AnomalyType, Element] = {
    anomaly: element for element, anomaly in ELEMENT_TO_ANOMALY.items()
}


class HitMode(enum.StrEnum):
    """How an `Attack`'s hits group for damage calc: single, cycling, context-variant, or held.

    The last three are *parameterized* modes — a combo step carries one value that decides
    how the move's rows resolve (`cycle_position`, `variant_label`, `channel_s` respectively).
    CHANNEL differs from the other two in kind: its parameter is a quantity, not a row
    selector, so it scales the `tick`-role rows rather than picking among them
    (docs/DESIGN_channeled_moves.md §4.1).
    """

    ATOMIC = "atomic"
    SEQUENTIAL = "sequential"
    VARIANT = "variant"
    CHANNEL = "channel"


class PotentialTag(enum.StrEnum):
    """Which Potential state a row belongs to (issue #90, DESIGN_potential_toggle.md §4.2).

    Stored on `Attack` / `AgentSkill` / `CoreSkill` as a *nullable* column: NULL means
    "present in both states" and is ~96% of rows. It is deliberately not a boolean —
    conflating "shared" with either variant is precisely the bug #85 was filed for.
    """

    BASE = "base"  # nanoka `potential: [0]`      — only without Potential unlocked
    UNLOCKED = "unlocked"  # nanoka `potential: [<aid>00..05]` — only with it unlocked


class PotentialVariant(enum.StrEnum):
    """Which set of rows a caller wants. Never defaulted — see DESIGN §5.1.

    `BOTH` exists so auditing tools can be explicit rather than reaching around the
    repository layer. It is never valid on a calc path: a calc that sees both variants
    double-counts every hit the two kits disagree about.
    """

    LOCKED = "locked"  # shared + base
    UNLOCKED = "unlocked"  # shared + unlocked
    BOTH = "both"  # auditing only

    @classmethod
    def for_rank(cls, potential_rank: int) -> "PotentialVariant":
        """The variant a build at this rank sees. Rank 0 is locked; 1-5 unlocked.

        The single place the ``>= 1`` predicate lives. Variant selection is binary --
        every Potential-marked entry in the roster carries the full 6-node list, so no
        entry is gated on a subset of nodes -- while the *rank* additionally indexes
        Track 2's value ramps.
        """
        return cls.UNLOCKED if potential_rank >= 1 else cls.LOCKED

    def includes(self, tag: "PotentialTag | str | None") -> bool:
        """Whether a row tagged ``tag`` is part of this variant's kit.

        Compares by **value**, not identity. The column is ``String(16)``, so a row
        loaded from the DB carries a plain ``str`` rather than a ``PotentialTag`` --
        the same shape as ``Attack.hit_mode``, which ``_classify_move`` coerces for the
        same reason. An ``is`` comparison here silently returns False for every tagged
        row read back from Postgres, which would 404 legitimate moves on the by-ID
        damage path while passing every in-memory unit test.
        """
        if self is PotentialVariant.BOTH or tag is None:
            return True
        wanted = PotentialTag.BASE if self is PotentialVariant.LOCKED else PotentialTag.UNLOCKED
        return tag == wanted


class RowCondition(enum.StrEnum):
    """A runtime game state a single ``attacks`` row is gated on (D-CH5).

    ``NULL`` in the column means *unconditional* -- the row always fires -- deliberately
    the same shape as :class:`PotentialTag`, which is the existing precedent for per-row
    conditional visibility.

    The difference from ``potential``, and the reason this is evaluated in the simulator
    rather than in a repository query: ``potential`` is fixed for a build, so it filters
    once at fetch time. Stun is not. ``is_enemy_stunned`` starts from the enemy profile and
    then flips on the ``stun_trigger`` / ``stun_end`` markers as a rotation runs, so a row
    gated on it has to be re-checked at every hit.

    Deliberately only two members. The corpus wants more of this shape -- Manato's "(Charged
    or Successful Block)", Hugo's ``ALT`` rows, the tap-vs-charged suspects the Task 2 sweep
    deferred -- but each needs its own citation and its own evaluation point, and a member
    nothing evaluates is worse than no member at all.

    Note what this does NOT model: the engine has no stun bar. Stun comes from the enemy
    profile and from markers the user places in the rotation, never from simulated daze. A
    row gated here is correct with respect to the rotation *as authored*.
    """

    ENEMY_STUNNED = "enemy_stunned"
    ENEMY_NOT_STUNNED = "enemy_not_stunned"
