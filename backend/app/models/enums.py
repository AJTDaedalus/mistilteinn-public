"""Domain enums.

**Port state.** Every game enum here was ZZZ's and was deleted in B.4: `Element`
(six ZZZ attributes), `Specialty`, `AttackType`, `Rarity`, `DiscSlot`, `StatType`,
`AnomalyType`, `HitMode`, `PotentialTag`, `PotentialVariant`, `RowCondition`, and
the numeric `*_ID_MAP`s the hakushin/nanoka importers translated through.

`UserStatus` is the only survivor — it describes account approval, not the game.

The Genshin vocabulary is written fresh in Chunk C (C.2), not renamed from what
was here: `Element` (7 visions, Physical **excluded** — it is a damage type, not a
vision), `DamageType`, `WeaponType` (six, including `WEAPON_CROSSBOW`), `Rarity`
(the character `QUALITY_*` / weapon integer-`rank` split normalized), `ArtifactSlot`
(a 5-member `StrEnum`), `TalentType`, and `StatType` from the observed
`FIGHT_PROP_*` vocabulary. Each carries a provenance comment naming the endpoint and
version it was read from, and an unmapped key must warn rather than drop silently.
"""

import enum


class UserStatus(enum.StrEnum):
    """Admin-approval lifecycle state for a `User` account."""

    PENDING = "pending"
    APPROVED = "approved"
    DISABLED = "disabled"
