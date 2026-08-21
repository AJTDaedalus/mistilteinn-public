"""ZZZ tag namespace conventions.

Tag categories used across the ZZZ DAG:

``q``
    Quantity name. Stat contributions (``atk_pct``, ``flat_atk``,
    ``crit_rate``, ``fire_dmg``, …), condition indicators
    (``cond_active``), stack counts (``stack``), resolved totals
    (``atk_total``).

``src``
    Source of a contribution. ``agent``, ``wengine``, ``disc``,
    ``disc_set``, ``mindscape``, ``core_skill``, ``team`` — mirrors
    :class:`app.services.modifiers.ModifierSource` values plus team
    attribution for Phase 5A buffs.

``cond``
    Condition name, used on condition-indicator reads and on the tag
    a conditional modifier registers under (so the solver can treat
    conditions as candidate variables in Phase 6.4).

``scope``
    Attack scope (``basic``, ``special``, …). Scope-gated modifiers
    register under ``{scope}`` in addition to their stat; evaluating
    under a specific attack pushes ``Tag.of(scope=...)`` into context,
    and ``read`` filters pick only the matching entries.

``elem``
    Element (see :data:`ELEMENTS`) for elemental damage bonus namespacing.

``label``
    Source label string for stackable modifiers ("Deep Sea Visitor R1").
    Used only by ``stack_count`` reads.

``sheet``
    Per-agent formula sheet slug ("burnice", "ellen"). Namespaces all
    formulas registered for a single agent — mirrors ZO's ``sheet`` tag.
    Auto-derived attack nodes and JSON-declared custom formulas both
    register under ``{sheet: <slug>, ...}``.

``name``
    Formula identifier string within a sheet ("basic_0", "core_afterburn_dmg").
    Lets the damage service pick the exact formula to evaluate without
    having to reconstruct the tag from its type.
"""

from __future__ import annotations

from app.formula.tags import Tag

# ---- Category names -------------------------------------------------------

Q = "q"
SRC = "src"
COND = "cond"
SCOPE = "scope"
ELEM = "elem"
LABEL = "label"
SHEET = "sheet"
NAME = "name"

# Canonical element list (F-26) — the single source every element-keyed table
# (DAG stats registration, disc-optimizer union fields, buff-resolver buildup
# routing) should derive from, so adding an element only requires editing this
# tuple. Mirrors app.models.enums.Element without importing it (formula/ stays
# decoupled from the ORM layer).
ELEMENTS: tuple[str, ...] = ("physical", "fire", "ice", "electric", "ether", "wind")


# ---- Quantity names -------------------------------------------------------
# Match the strings in app/services/buff_resolver.py for one-to-one porting.

# Aggregated stats (outputs — what the formula *solves for*)
Q_ATK = "atk"
Q_HP = "hp"
Q_DEF = "defense"
Q_CRIT_RATE = "crit_rate"
Q_CRIT_DMG = "crit_dmg"
Q_PEN_RATIO = "pen_ratio"
Q_PEN_FLAT = "pen_flat"
Q_ANOMALY_PROF = "anomaly_proficiency"
Q_ANOMALY_MASTERY = "anomaly_mastery"
Q_IMPACT = "impact"
Q_ENERGY_REGEN = "energy_regen"
Q_ELEM_DMG = "elem_dmg"

# Percentage contributions (inputs — what modifiers write to)
Q_HP_PCT = "hp_pct"
Q_ATK_PCT = "atk_pct"
Q_DEF_PCT = "def_pct"
Q_FLAT_HP = "flat_hp"
Q_FLAT_ATK = "flat_atk"
Q_FLAT_DEF = "flat_def"
Q_FINAL_HP_PCT = "final_hp_pct"
Q_FINAL_ATK_PCT = "final_atk_pct"
Q_FINAL_DEF_PCT = "final_def_pct"
Q_FINAL_FLAT_HP = "final_flat_hp"
Q_FINAL_FLAT_ATK = "final_flat_atk"
Q_FINAL_FLAT_DEF = "final_flat_def"

# Base stats (inputs from the build snapshot)
Q_AGENT_BASE_HP = "agent_base_hp"
Q_AGENT_BASE_ATK = "agent_base_atk"
Q_AGENT_BASE_DEF = "agent_base_def"
Q_WENGINE_BASE_ATK = "wengine_base_atk"
Q_AGENT_BASE_AM = "agent_base_am"  # AM "Base Stat" — % bonuses apply to this only
Q_AM_PCT = "am_pct"  # sum of AM% bonuses (2-pc set, W-Engine secondary)

# Damage bonuses (register under ``{q: dmg_bonus, scope: <scope>}``)
Q_DMG_BONUS = "dmg_bonus"
Q_ANOMALY_DMG_BONUS = "anomaly_dmg_bonus"

# Combat-path stats
Q_RES_REDUCTION = "res_reduction"
Q_RES_IGNORE = "res_ignore"
Q_DEF_IGNORE = "def_ignore"
Q_VULNERABILITY = "vulnerability"
Q_DISORDER_DMG_BONUS = "disorder_dmg_bonus"
Q_VORTEX_DMG_BONUS = "vortex_dmg_bonus"
Q_BASE_DMG_BONUS_PCT = "base_dmg_bonus_pct"  # Yanagi Polarity Disorder: -8500 (-85%)
Q_FLAT_BASE_DMG = "flat_base_dmg"  # AP-scaled flat add to Disorder BaseDMG

# Condition system
Q_COND_ACTIVE = "cond_active"  # Indicator reads return 1 if active, else 0
Q_STACK = "stack"  # Per-label stack count reads

# Enemy / damage-context inputs (registered per-compute by register_enemy)
Q_ENEMY_BASE_DEF = "enemy_base_def"
Q_ENEMY_LEVEL = "enemy_level"
Q_ENEMY_LEVEL_FACTOR = "enemy_level_factor"
Q_ATTACKER_LEVEL_FACTOR = "attacker_level_factor"
Q_ENEMY_RES = "enemy_res"
Q_ATTACKER_LEVEL = "attacker_level"
Q_STUN_BONUS = "stun_bonus"  # stun_dmg_mult - 10000 when stunned, absent otherwise
Q_ENEMY_ANOMALY_RES = "enemy_anomaly_res"
Q_STUN_BUILDUP_BONUS = "stun_buildup_bonus"
Q_REMAINING_DURATION = "remaining_duration"
Q_MAX_DURATION = "max_duration"
Q_ADDITIONAL_MV = "additional_mv"

# Per-agent formula output quantities (Phase 6.2c+) — mirror ZO's ``q`` values
# on formula tags. A sheet registers one node per (name, quantity) pair.
Q_STANDARD_DMG = "standard_dmg"  # crit-averaged standard damage number
Q_ANOMALY_DMG = "anomaly_dmg"  # single anomaly proc damage
Q_DISORDER_DMG = "disorder_dmg"  # disorder proc damage (Jane, etc.)
Q_VORTEX_DMG = "vortex_dmg"  # vortex proc damage
Q_ANOM_BUILDUP = "anom_buildup"  # anomaly gauge gained per hit
Q_DAZE_BUILDUP = "daze_buildup"  # daze gauge gained per hit
Q_ANOMALY_BUILDUP = "anomaly_buildup"

# Character-state reads (provided per-compute by the sheet registrar).
Q_MINDSCAPE = "mindscape"  # 0-6, user-chosen mindscape level
Q_CORE_LEVEL = "core_level"  # 0-5, core-skill passive level (A-F → 0-5)
Q_AGENT_LEVEL = "agent_level"


# ---- Convenience builders -------------------------------------------------


def stat_tag(quantity: str, **extra: str | None) -> Tag:
    """Tag for a stat contribution: ``{q: <quantity>, ...extra}``."""
    return Tag.of(**{Q: quantity, **extra})


def cond_tag(condition: str) -> Tag:
    """Tag for a condition indicator: ``{q: cond_active, cond: <name>}``."""
    return Tag.of(**{Q: Q_COND_ACTIVE, COND: condition})


def stack_tag(label: str) -> Tag:
    """Tag for a stack-count read: ``{q: stack, label: <label>}``."""
    return Tag.of(**{Q: Q_STACK, LABEL: label})


def elem_dmg_tag(element: str) -> Tag:
    """Tag for per-element damage bonus: ``{q: elem_dmg, elem: <name>}``."""
    return Tag.of(**{Q: Q_ELEM_DMG, ELEM: element})


def dmg_bonus_tag(scope: str) -> Tag:
    """Tag for scope-gated damage bonus: ``{q: dmg_bonus, scope: <scope>}``."""
    return Tag.of(**{Q: Q_DMG_BONUS, SCOPE: scope})


def formula_tag(sheet: str, name: str, quantity: str) -> Tag:
    """Tag for a per-agent formula output: ``{sheet, name, q: <quantity>}``.

    Per-agent sheets (``app/formula/zzz/sheets/`` + ``modifiers/agents/*.json``
    ``formulas`` sections) register one node per formula at this tag. The
    damage service looks up a formula by its ``(sheet, name, quantity)``
    triple without needing to know how the node was assembled.
    """
    return Tag.of(**{SHEET: sheet, NAME: name, Q: quantity})
