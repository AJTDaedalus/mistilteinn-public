"""Pydantic schemas for Agent and sub-resources."""

from pydantic import BaseModel

from app.models.enums import Element, HitMode, Rarity, Specialty

# --- Sub-resource schemas (read-only, seeded from import) ---


class AttackRead(BaseModel):
    """One hit/attack definition nested under `AgentRead`; drives damage calc and combo steps."""

    id: str
    hakushin_skill_id: int
    skill_key: str
    name: str
    hit_index: int
    element: Element
    damage_base: int
    damage_growth: int
    stun_base: int
    stun_growth: int
    energy_gain: int
    anomaly_buildup: int
    hit_mode: HitMode = HitMode.ATOMIC
    variant_label: str | None = None

    model_config = {"from_attributes": True}


class AgentSkillRead(BaseModel):
    """One named skill (Basic/Dash/Special/etc.) nested under `AgentRead`."""

    id: str
    skill_key: str
    name: str
    description: str

    model_config = {"from_attributes": True}


class CoreSkillRead(BaseModel):
    """One core passive level nested under `AgentRead`."""

    id: str
    hakushin_id: int
    level: int
    name: str
    description: str

    model_config = {"from_attributes": True}


class MindscapeRead(BaseModel):
    """One mindscape cinema level nested under `AgentRead`."""

    id: str
    level: int
    name: str
    description: str

    model_config = {"from_attributes": True}


# --- Agent schemas ---


class AgentSummary(BaseModel):
    """Lightweight agent for list endpoints."""

    id: str
    hakushin_id: int
    name: str
    full_name: str
    element: Element
    specialty: Specialty
    rarity: Rarity
    faction: str
    icon_path: str = ""
    # #90: the build editor renders the Potential toggle from the summary, not the
    # full agent read, so the flag has to be on both.
    has_potential: bool = False

    model_config = {"from_attributes": True}


class AgentRead(BaseModel):
    """Full agent detail with stats and sub-resources."""

    id: str
    hakushin_id: int
    name: str
    full_name: str
    element: Element
    specialty: Specialty
    rarity: Rarity
    faction: str
    faction_id: int
    icon_path: str = ""
    # #90: does this agent have a Potential tree? Drives whether the build editor
    # offers the toggle at all.
    has_potential: bool = False

    # Base stats
    base_hp: int
    base_atk: int
    base_def: int
    hp_growth: int
    atk_growth: int
    def_growth: int

    # Combat stats (basis points)
    base_crit_rate: int
    base_crit_dmg: int
    base_anomaly_mastery: int
    base_anomaly_proficiency: int
    base_impact: int
    base_energy_regen: int
    base_pen_flat: int
    base_pen_ratio: int

    # Sub-resources
    skills: list[AgentSkillRead]
    attacks: list[AttackRead]
    core_skills: list[CoreSkillRead]
    mindscapes: list[MindscapeRead]

    model_config = {"from_attributes": True}
