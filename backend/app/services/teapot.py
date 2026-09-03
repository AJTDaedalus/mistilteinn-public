"""Which furnishing sets are worth doing next.

`DESIGN_account_tracking.md` Track 3. Owner: *"sortable by remaining primogems and lets users
mark off which they've already done like Seelie does."*

## The reward constant, and why the sort works without it

The primogem reward for inviting a favoured character to their set is a **game constant this
repo does not have a citation for**, and CLAUDE.md's rule is explicit: no game value is written
from memory. So `REWARD_PER_CHARACTER` is `None` until somebody cites it (**OQ-A4**), and the
API reports `remaining_primogems` as null rather than as a number nobody checked.

**The headline sort still works, exactly.** The reward is the same for every character, so
`reward × remaining` and `remaining` order identically — a positive constant multiplier cannot
change a ranking. Sorting by *remaining favoured characters* is therefore not a stand-in for
the owner's ask; it **is** the owner's ask, minus a label. When the constant arrives it changes
the number on screen and not one row's position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: Primogems for inviting one favoured character to their set.
#:
#: **Cited, not remembered** (OQ-A4, answered 2026-09-03). Inviting a companion to a
#: furnishing set they favour gives **20 Primogems**, 20,000 Mora and a unique reward
#: (an ascension gem fragment or two talent books), **once per set**:
#:
#: - GameWith, *How To Get Gifts From Companion (Serenitea Pot)* —
#:   <https://gamewith.net/genshin-impact/article/show/29165>
#: - Genshin Impact Wiki, *Furnishing Set* —
#:   <https://genshin-impact.fandom.com/wiki/Furnishing_Set>
#:
#: Two independent sources agreeing, because this repo's hardest-won lesson was fabricated
#: citations in curated data. Only the Primogems are modelled: Mora and the unique reward are
#: real but are not what anyone sorts by.
#:
#: **One-time per set is what makes `teapot_progress` the right shape.** The reward does not
#: repeat, so a ticked set is finished rather than on cooldown.
REWARD_PER_CHARACTER: int | None = 20


@dataclass(frozen=True)
class SuiteProgress:
    """One row of the tracker."""

    suite_id: str
    name: str
    icon: str
    placement: str
    #: Characters who favour this set **and whom the user owns**.
    owned_favorites: tuple[str, ...]
    #: Characters who favour it that the user does not have — why a set can be worth less
    #: than its favourite count suggests, and why that is shown rather than hidden.
    unowned_favorites: tuple[str, ...]
    done: bool

    @property
    def remaining(self) -> int:
        """Owned favoured characters still to invite. Zero once the set is marked done."""
        return 0 if self.done else len(self.owned_favorites)

    @property
    def remaining_primogems(self) -> int | None:
        """`remaining × REWARD_PER_CHARACTER`, or `None` while the constant is uncited."""
        if REWARD_PER_CHARACTER is None:
            return None
        return self.remaining * REWARD_PER_CHARACTER


def rank(rows: Iterable[SuiteProgress]) -> list[SuiteProgress]:
    """Most worth doing first.

    Ordered by `remaining`, which is the same order `remaining × reward` would give: the
    reward is one constant for every character, and a positive constant multiplier cannot
    change a ranking. Ties break on name so the list is stable between loads — an order that
    shuffles under the reader is one they stop trusting.
    """
    return sorted(rows, key=lambda row: (-row.remaining, row.name.lower()))


def progress_for(
    suites: Iterable[Mapping[str, object]],
    owned_character_ids: set[str],
    done_suite_ids: set[str],
) -> list[SuiteProgress]:
    """Build the tracker's rows from the catalogue and this user's state.

    `suites` carries `favorite` as **nanoka character ids**, which is what
    `owned_character_ids` holds too — the join needs no translation, which is the finding that
    made this feature cheap.
    """
    rows = [
        SuiteProgress(
            suite_id=str(suite["id"]),
            name=str(suite["name"]),
            icon=str(suite.get("icon") or ""),
            placement=str(suite.get("placement") or ""),
            owned_favorites=tuple(
                sorted(c for c in (suite.get("favorite") or ()) if c in owned_character_ids),
            ),
            unowned_favorites=tuple(
                sorted(
                    c for c in (suite.get("favorite") or ()) if c not in owned_character_ids
                ),
            ),
            done=str(suite["id"]) in done_suite_ids,
        )
        for suite in suites
    ]
    return rank(rows)
