"""Import game data from cached zzz-hakushin-data JSON files.

Source: github.com/Genshin-Optimizer/zzz-hakushin-data (pre-scraped, static).
Does NOT require hakush.in to be online.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.data.importers.base_importer import AnomalyStats, BaseImporter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent import Agent, AgentSkill, Attack, CoreSkill, Mindscape
from app.models.build import EnemyProfile
from app.models.disc import DiscSet
from app.models.enums import (
    ELEMENT_ID_MAP,
    RARITY_INT_MAP,
    SPECIALTY_ID_MAP,
    Element,
)
from app.models.w_engine import WEngine

logger = logging.getLogger(__name__)

# Skill type keys in hakushin data → our skill_key mapping
SKILL_TYPE_MAP = {
    "Basic": "Basic",
    "Dodge": "Dodge",
    "Special": "Special",
    "Chain": "Chain",
    "Assist": "Assist",
}

# Property name from hakushin → our secondary_stat_type
RAND_PROPERTY_MAP: dict[str, str] = {
    "Percent ATK": "atk_pct",
    "ATK": "atk_pct",
    "Percent HP": "hp_pct",
    "HP": "hp_pct",
    "Percent DEF": "def_pct",
    "DEF": "def_pct",
    "CRIT Rate": "crit_rate",
    "CRIT DMG": "crit_dmg",
    "Impact": "impact",
    "Anomaly Proficiency": "anomaly_proficiency",
    "Anomaly Mastery": "anomaly_mastery",
    "PEN Ratio": "pen_ratio",
    "Energy Regen": "energy_regen",
}


def _strip_color_tags(text: str) -> str:
    """Remove <color=#...>...</color> markup from hakushin descriptions."""
    return re.sub(r"<color=#[0-9A-Fa-f]+>(.*?)</color>", r"\1", text)


def _extract_element(element_dict: dict) -> Element:
    """Extract Element enum from hakushin element dict like {'203': 'Electric'}."""
    for eid_str in element_dict:
        eid = int(eid_str)
        if eid in ELEMENT_ID_MAP:
            return ELEMENT_ID_MAP[eid]
    return Element.PHYSICAL


def _extract_specialty_id(specialty_dict: dict) -> int:
    """Extract specialty int ID from hakushin dict like {'2': 'Stun'}."""
    for sid_str in specialty_dict:
        return int(sid_str)
    return 1


def _extract_anomaly_stats(stats: dict) -> AnomalyStats:
    """Return the agent's base Anomaly Mastery / Proficiency pair.

    Mirrors nanoka_importer._extract_anomaly_stats: `ElementAbnormalPower` is
    Anomaly MASTERY and `ElementMystery` is Anomaly PROFICIENCY, despite the
    names suggesting otherwise. Do not "fix" this mapping back — see
    docs/RESEARCH_batch32c_followups.md.
    """
    return AnomalyStats(
        mastery=stats.get("ElementAbnormalPower", 0),
        proficiency=stats.get("ElementMystery", 0),
    )


class HakushinJsonImporter(BaseImporter):
    """Reads cached JSON from zzz-hakushin-data repo on disk."""

    def __init__(self, session: AsyncSession, data_dir: str | Path) -> None:
        super().__init__(session)
        self.data_dir = Path(data_dir)

    async def import_agents(self) -> int:
        """Import agents from cached hakushin ``character/*.json`` files."""
        char_dir = self.data_dir / "character"
        if not char_dir.exists():
            logger.warning("Character directory not found: %s", char_dir)
            return 0

        count = 0
        for json_file in sorted(char_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                agent = await self._import_one_agent(data)
                if agent:
                    count += 1
            except Exception:
                logger.exception("Failed to import character from %s", json_file.name)

        await self.session.flush()
        logger.info("Imported %d agents", count)
        return count

    async def _import_one_agent(self, data: dict) -> Agent | None:
        hakushin_id = data["Id"]

        # Skip if already exists
        existing = await self.session.execute(
            select(Agent).where(Agent.hakushin_id == hakushin_id)
        )
        if existing.scalar_one_or_none():
            logger.debug("Agent %s already exists, skipping", hakushin_id)
            return None

        stats = data.get("Stats", {})
        element = _extract_element(data.get("ElementType", {}))
        specialty_id = _extract_specialty_id(data.get("WeaponType", {}))
        specialty = SPECIALTY_ID_MAP.get(specialty_id, SPECIALTY_ID_MAP[1])
        rarity = RARITY_INT_MAP.get(data.get("Rarity", 3), RARITY_INT_MAP[3])
        anomaly = _extract_anomaly_stats(stats)

        # Faction info
        camp = data.get("Camp", {})
        faction_name = ""
        faction_id = 0
        for fid, fname in camp.items():
            faction_id = int(fid)
            faction_name = fname
            break

        agent = Agent(
            hakushin_id=hakushin_id,
            name=data.get("Name", ""),
            full_name=data.get("CodeName", data.get("Name", "")),
            element=element,
            specialty=specialty,
            rarity=rarity,
            faction=faction_name,
            faction_id=faction_id,
            base_hp=stats.get("HpMax", 0),
            base_atk=stats.get("Attack", 0),
            base_def=stats.get("Defence", 0),
            hp_growth=stats.get("HpGrowth", 0),
            atk_growth=stats.get("AttackGrowth", 0),
            def_growth=stats.get("DefenceGrowth", 0),
            base_crit_rate=stats.get("Crit", 500),
            base_crit_dmg=stats.get("CritDamage", 5000),
            base_anomaly_mastery=anomaly.mastery,
            base_anomaly_proficiency=anomaly.proficiency,
            base_impact=stats.get("BreakStun", 0),
            base_energy_regen=stats.get("SpRecover", 0),
            base_pen_flat=stats.get("PenDelta", 0),
            base_pen_ratio=stats.get("PenRate", 0),
        )
        self.session.add(agent)
        await self.session.flush()

        # Import sub-entities
        await self._import_agent_skills(agent, data)
        await self._import_attacks(agent, data)
        await self._import_core_skills(agent, data)
        await self._import_mindscapes(agent, data)

        return agent

    async def _import_agent_skills(self, agent: Agent, data: dict) -> None:
        """Import skill type groupings (Basic, Dodge, Special, Chain, Assist)."""
        skill_data = data.get("Skill", {})
        for skill_key, skill_info in skill_data.items():
            if skill_key not in SKILL_TYPE_MAP:
                continue
            descriptions = skill_info.get("Description", [])
            name = ""
            desc = ""
            if descriptions and isinstance(descriptions, list) and descriptions:
                name = descriptions[0].get("Name", skill_key)
                desc = _strip_color_tags(descriptions[0].get("Desc", ""))

            skill = AgentSkill(
                agent_id=agent.id,
                skill_key=SKILL_TYPE_MAP[skill_key],
                name=name,
                description=desc,
            )
            self.session.add(skill)

    async def _import_attacks(self, agent: Agent, data: dict) -> None:
        """Import per-hit attack data with damage multipliers."""
        skill_data = data.get("Skill", {})
        skill_list = data.get("SkillList", {})

        for skill_key, skill_info in skill_data.items():
            if skill_key not in SKILL_TYPE_MAP:
                continue

            descriptions = skill_info.get("Description", [])
            for desc_entry in descriptions:
                params = desc_entry.get("Param", [])
                if not isinstance(params, list):
                    continue

                for hit_index, param in enumerate(params):
                    param_dict = param.get("Param", {})
                    param_name = param.get("Name", "")

                    for skill_id_str, values in param_dict.items():
                        skill_id = int(skill_id_str)
                        damage_pct = values.get("DamagePercentage", 0)
                        damage_growth = values.get("DamagePercentageGrowth", 0)
                        stun_base = values.get("StunRatio", 0)
                        stun_growth = values.get("StunRatioGrowth", 0)
                        sp_recovery = values.get("SpRecovery", 0)
                        anomaly = values.get("AttributeInfliction", 0)

                        # Determine element for this hit from SkillList
                        skill_info_entry = skill_list.get(skill_id_str, {})
                        hit_element_id = skill_info_entry.get("ElementType", 0)
                        hit_element = ELEMENT_ID_MAP.get(hit_element_id, agent.element)

                        attack_name = (
                            skill_info_entry.get("Name", "")
                            or param_name
                            or f"{skill_key} Hit {hit_index + 1}"
                        )

                        attack = Attack(
                            agent_id=agent.id,
                            hakushin_skill_id=skill_id,
                            skill_key=SKILL_TYPE_MAP[skill_key],
                            name=attack_name[:200],
                            hit_index=hit_index,
                            element=hit_element,
                            damage_base=damage_pct,
                            damage_growth=damage_growth,
                            stun_base=stun_base,
                            stun_growth=stun_growth,
                            energy_gain=sp_recovery,
                            anomaly_buildup=anomaly,
                        )
                        self.session.add(attack)

    async def _import_core_skills(self, agent: Agent, data: dict) -> None:
        """Import core passive skill levels from Passive.Level."""
        passive = data.get("Passive", {})
        levels = passive.get("Level", {})

        for _level_id, level_info in levels.items():
            level_num = level_info.get("Level", 0)
            names = level_info.get("Name", [])
            descs = level_info.get("Desc", [])

            name = names[0] if names else ""
            desc = _strip_color_tags(" | ".join(descs)) if descs else ""

            core_skill = CoreSkill(
                agent_id=agent.id,
                hakushin_id=int(_level_id),
                level=level_num,
                name=name[:200],
                description=desc,
            )
            self.session.add(core_skill)

    async def _import_mindscapes(self, agent: Agent, data: dict) -> None:
        """Import Mindscape Cinema levels (Talent in hakushin)."""
        talent = data.get("Talent", {})

        for level_str, talent_info in talent.items():
            level_num = talent_info.get("Level", int(level_str))
            name = talent_info.get("Name", "")
            desc = _strip_color_tags(talent_info.get("Desc", ""))

            mindscape = Mindscape(
                agent_id=agent.id,
                level=level_num,
                name=name[:200],
                description=desc,
            )
            self.session.add(mindscape)

    async def import_w_engines(self) -> int:
        """Import W-Engines from cached hakushin ``weapon/*.json`` files."""
        weapon_dir = self.data_dir / "weapon"
        if not weapon_dir.exists():
            logger.warning("Weapon directory not found: %s", weapon_dir)
            return 0

        count = 0
        for json_file in sorted(weapon_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                engine = await self._import_one_w_engine(data)
                if engine:
                    count += 1
            except Exception:
                logger.exception("Failed to import weapon from %s", json_file.name)

        await self.session.flush()
        logger.info("Imported %d W-Engines", count)
        return count

    async def _import_one_w_engine(self, data: dict) -> WEngine | None:
        hakushin_id = data["Id"]

        existing = await self.session.execute(
            select(WEngine).where(WEngine.hakushin_id == hakushin_id)
        )
        if existing.scalar_one_or_none():
            return None

        rarity = RARITY_INT_MAP.get(data.get("Rarity", 2), RARITY_INT_MAP[2])

        # Specialty
        weapon_type = data.get("WeaponType", {})
        specialty_id = _extract_specialty_id(weapon_type)
        specialty = SPECIALTY_ID_MAP.get(specialty_id, SPECIALTY_ID_MAP[1])

        # Base property
        base_prop = data.get("BaseProperty", {})
        base_atk = base_prop.get("Value", 0)

        # Secondary stat
        rand_prop = data.get("RandProperty", {})
        rand_name = rand_prop.get("Name2", rand_prop.get("Name", ""))
        secondary_type = RAND_PROPERTY_MAP.get(rand_name, rand_name.lower())
        secondary_value = rand_prop.get("Value", 0)

        # Level scaling
        level_data = data.get("Level", {})
        level_scaling = {}
        for lv, lv_info in level_data.items():
            level_scaling[lv] = {
                "rate": lv_info.get("Rate", 0),
                "rate2": lv_info.get("Rate2", 0),
            }

        # Star scaling (promotion bonuses)
        stars = data.get("Stars", {})
        star_scaling = {}
        for star_lv, star_info in stars.items():
            star_scaling[star_lv] = {
                "star_rate": star_info.get("StarRate", 0),
                "rand_rate": star_info.get("RandRate", 0),
            }

        # Merge into single scaling dict
        scaling = {"level": level_scaling, "stars": star_scaling}

        # Passive descriptions (R1-R5)
        talents = data.get("Talents", {})
        passive_name = ""
        passive_descs: dict[str, str] = {}
        for rank_str, talent_info in talents.items():
            if not passive_name:
                passive_name = talent_info.get("Name", "")
            passive_descs[rank_str] = _strip_color_tags(talent_info.get("Desc", ""))

        engine = WEngine(
            hakushin_id=hakushin_id,
            name=data.get("Name", "")[:200],
            rarity=rarity,
            specialty=specialty,
            base_atk=base_atk,
            secondary_stat_type=secondary_type[:30],
            secondary_stat_value=secondary_value,
            level_scaling=scaling,
            passive_name=passive_name[:200],
            passive_descriptions=passive_descs,
            description=data.get("Desc", "")[:2000],
        )
        self.session.add(engine)
        return engine

    async def import_disc_sets(self) -> int:
        """Import disc sets from cached hakushin ``equipment/*.json`` files."""
        equip_dir = self.data_dir / "equipment"
        if not equip_dir.exists():
            logger.warning("Equipment directory not found: %s", equip_dir)
            return 0

        count = 0
        for json_file in sorted(equip_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                disc_set = await self._import_one_disc_set(data)
                if disc_set:
                    count += 1
            except Exception:
                logger.exception("Failed to import equipment from %s", json_file.name)

        await self.session.flush()
        logger.info("Imported %d disc sets", count)
        return count

    async def _import_one_disc_set(self, data: dict) -> DiscSet | None:
        hakushin_id = data["Id"]

        existing = await self.session.execute(
            select(DiscSet).where(DiscSet.hakushin_id == hakushin_id)
        )
        if existing.scalar_one_or_none():
            return None

        two_piece_text = _strip_color_tags(data.get("Desc2", ""))
        four_piece_text = _strip_color_tags(data.get("Desc4", ""))

        # Parse structured bonuses from description text
        two_piece_effects = _parse_set_bonus(two_piece_text)
        four_piece_effects = _parse_set_bonus(four_piece_text)

        icon = data.get("Icon", "")

        disc_set = DiscSet(
            hakushin_id=hakushin_id,
            name=data.get("Name", "")[:200],
            two_piece_text=two_piece_text[:1000],
            four_piece_text=four_piece_text[:2000],
            two_piece_effects=two_piece_effects or None,
            four_piece_effects=four_piece_effects or None,
            icon_path=icon[:500],
        )
        self.session.add(disc_set)
        return disc_set

    async def import_enemies(self) -> int:
        """Import enemy profiles from cached hakushin ``monster/*.json`` files."""
        monster_dir = self.data_dir / "monster"
        if not monster_dir.exists():
            logger.warning("Monster directory not found: %s", monster_dir)
            return 0

        count = 0
        for json_file in sorted(monster_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                enemy = await self._import_one_enemy(data)
                if enemy:
                    count += 1
            except Exception:
                logger.exception("Failed to import monster from %s", json_file.name)

        await self.session.flush()
        logger.info("Imported %d enemies", count)
        return count

    async def _import_one_enemy(self, data: dict) -> EnemyProfile | None:
        hakushin_id = data.get("Id")

        existing = await self.session.execute(
            select(EnemyProfile).where(EnemyProfile.hakushin_id == hakushin_id)
        )
        if existing.scalar_one_or_none():
            return None

        # Get stats from first MonsterInfo entry
        monster_info = data.get("MonsterInfo", {})
        stats: dict = {}
        for minfo in monster_info.values():
            stats = minfo.get("Stats", {})
            break

        rarity_val = data.get("Rarity", 1)
        tags = data.get("Tag", [])
        tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)

        element_abnormal = data.get("ElementAbnormal", {})

        def _get_capacity(curve_id: int | None) -> int:
            if not curve_id or not element_abnormal:
                return 100
            key = str(curve_id)
            if key in element_abnormal:
                return element_abnormal[key]
            # Fallback: the curve's own prefix (1xxxx/2xxxx/3xxxx) is the gauge
            # tier, independent of monster rarity — reconstruct from the curve
            # itself, never from `rarity_val`.
            tier = curve_id // 10000
            suffix = curve_id % 10000
            fallback_key = str(tier * 10000 + suffix)
            return element_abnormal.get(fallback_key, 100)

        enemy = EnemyProfile(
            hakushin_id=hakushin_id,
            name=data.get("Name", "Unknown")[:200],
            level=60,
            hp=stats.get("Hp", 0),
            atk=stats.get("Attack", 0),
            defense=stats.get("Defence", 50),
            physical_res=stats.get("PhysicalDamageRes", 0),
            fire_res=stats.get("FireDamageRes", 0),
            ice_res=stats.get("IceDamageRes", 0),
            electric_res=stats.get("ElectricDamageRes", 0),
            ether_res=stats.get("EtherDamageRes", 0),
            wind_res=stats.get("WindDamageRes", 0),
            anomaly_capacity_physical=_get_capacity(stats.get("PhysicalBuildupCurve")),
            anomaly_capacity_fire=_get_capacity(stats.get("FireBuildupCurve")),
            anomaly_capacity_ice=_get_capacity(stats.get("IceBuildupCurve")),
            anomaly_capacity_electric=_get_capacity(stats.get("ElectricBuildupCurve")),
            anomaly_capacity_ether=_get_capacity(stats.get("EtherBuildupCurve")),
            anomaly_capacity_wind=_get_capacity(stats.get("WindBuildupCurve")),
            anomaly_res_physical=stats.get("PhysicalBuildupRes", 0),
            anomaly_res_fire=stats.get("FireBuildupRes", 0),
            anomaly_res_ice=stats.get("IceBuildupRes", 0),
            anomaly_res_electric=stats.get("ElectricBuildupRes", 0),
            anomaly_res_ether=stats.get("EtherBuildupRes", 0),
            anomaly_res_wind=stats.get("WindBuildupRes", 0),
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
            stun_threshold=stats.get("BreakStun", 0),
            stun_dmg_taken_ratio=stats.get("StunDamageTakenRatio", 5000),
            rarity=rarity_val if isinstance(rarity_val, int) else 1,
            tags=tags_str[:500],
        )
        self.session.add(enemy)
        return enemy


# --- Bonus text parser ---

# Regex patterns for common set bonus descriptions
_BONUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"CRIT Rate \+(\d+)%"), "crit_rate"),
    (re.compile(r"CRIT DMG \+(\d+)%"), "crit_dmg"),
    (re.compile(r"ATK \+(\d+)%"), "atk_pct"),
    (re.compile(r"HP \+(\d+)%"), "hp_pct"),
    (re.compile(r"DEF \+(\d+)%"), "def_pct"),
    (re.compile(r"PEN Ratio \+(\d+)%"), "pen_ratio"),
    (re.compile(r"Energy Regen \+(\d+)%"), "energy_regen"),
    (re.compile(r"Anomaly Proficiency \+(\d+)"), "anomaly_proficiency"),
    (re.compile(r"Anomaly Mastery \+(\d+)"), "anomaly_mastery"),
    (re.compile(r"Impact \+(\d+)%"), "impact_pct"),
    (re.compile(r"Physical DMG \+(\d+)%"), "physical_dmg"),
    (re.compile(r"Fire DMG \+(\d+)%"), "fire_dmg"),
    (re.compile(r"Ice DMG \+(\d+)%"), "ice_dmg"),
    (re.compile(r"Electric DMG \+(\d+)%"), "electric_dmg"),
    (re.compile(r"Ether DMG \+(\d+)%"), "ether_dmg"),
]

_PCT_STATS = {
    "crit_rate",
    "crit_dmg",
    "atk_pct",
    "hp_pct",
    "def_pct",
    "pen_ratio",
    "energy_regen",
    "impact_pct",
    "physical_dmg",
    "fire_dmg",
    "ice_dmg",
    "electric_dmg",
    "ether_dmg",
}


def _parse_set_bonus(text: str) -> list[dict]:
    """Parse set bonus description into structured effects.

    e.g. "CRIT Rate +8%" → [{"stat": "crit_rate", "value": 800, "is_conditional": false}]
    """
    effects: list[dict] = []
    for pattern, stat_name in _BONUS_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = int(match.group(1))
            # Convert percentage to basis points (8% → 800)
            value = raw_value * 100 if stat_name in _PCT_STATS else raw_value
            effects.append(
                {
                    "stat": stat_name,
                    "value": value,
                    "is_conditional": False,
                }
            )

    # If the description mentions conditions but we found a stat, mark conditional
    conditional_keywords = [
        "when",
        "after",
        "upon",
        "during",
        "if",
        "increases by",
        "for 6s",
        "for 8s",
        "for 10s",
        "for 12s",
        "for 15s",
    ]
    has_condition = any(kw in text.lower() for kw in conditional_keywords)
    if has_condition and effects:
        for effect in effects:
            effect["is_conditional"] = True

    return effects
