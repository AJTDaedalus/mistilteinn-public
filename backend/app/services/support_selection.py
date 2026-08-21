"""Selecting a team's *support* members relative to the one being scored.

Every pipeline that scores one member of a team needs the same list: the other
members, whose ``target=team`` modifiers buff the one under evaluation. Seven call
sites built that list independently, each as ``[m for i, m in enumerate(members)
if i != active_index]``, and each carried the same latent defect (issue #133).

Selecting by slot index alone is not enough. A build occupying **two** slots comes
back as its own support, and `build_snapshot_from_db` then folds that build's own
``target=team`` kit modifiers into its own scoring snapshot a second time — the
primary buffing itself. Measured during the #132 review:

    normal support  -> own TEAM mod count = 1
    self as support -> own TEAM mod count = 2

The optimizer carried this from the moment it passed ``support_builds=``. Rank and
the scorer inherited it in #121, as a side effect of supports reaching their scoring
snapshots at all — the number of affected paths went from one to three because two
paths that had previously ignored supports entirely began honouring them.

`TeamCreate`/`TeamUpdate` reject a duplicated build (`assert_slots_distinct`), and
prod holds no such row, so this is a guard against rows that predate that validation
or arrive by some future path — not a live miscalculation.

**Exclusion is by build identity, never by ``owner_name`` and never by agent name.**
`owner_name` is the #97 trap: `snapshot_builder` stamps ``owner_name=<dps name>`` on
the primary's *own* kit, core, W-Engine and disc modifiers, so filtering on it
deletes the primary's entire modifier list. Agent name is wrong for a different
reason — it cannot distinguish two builds of the same agent, which
`assert_slots_distinct` does not forbid.
"""

from __future__ import annotations

from typing import Any


def build_identity(member: Any) -> str | None:
    """Stable build identity for a team member, or None when it has none.

    Handles both shapes this codebase passes around: an ORM ``Build`` (``.id``) and a
    ``TeamMember`` value object (``.build_id``). ``build_id`` is checked first because
    ``TeamMember`` has no ``.id`` and a future dataclass carrying both should mean the
    build it refers to, not its own row.
    """
    for attr in ("build_id", "id"):
        value = getattr(member, attr, None)
        if value is not None:
            return str(value)
    return None


def select_support_members[T](members: list[T | None], active_index: int) -> list[T]:
    """The team members that buff the member at ``active_index``.

    Drops empty slots, the target's own slot, and — the point of this helper — any
    other slot holding the *same build* as the target (issue #133). See the module
    docstring for why identity rather than index, and why build id rather than
    ``owner_name``.

    Order is preserved: callers such as `normalize_team_sequence` and
    `resolve_stateful_am_step_lists` map ``support1``/``support2`` onto slot order.
    """
    target = members[active_index] if 0 <= active_index < len(members) else None
    target_id = build_identity(target) if target is not None else None

    supports: list[T] = []
    for i, member in enumerate(members):
        if i == active_index or member is None:
            continue
        if target_id is not None and build_identity(member) == target_id:
            continue
        supports.append(member)
    return supports
