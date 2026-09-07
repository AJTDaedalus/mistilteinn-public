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
#: **Once per character per set** — owner's correction, 2026-09-03. A set favoured by three
#: characters you own is worth three invitations and 60 primogems, not 20.
#:
#: Two independent sources agreeing, because this repo's hardest-won lesson was fabricated
#: citations in curated data. Only the Primogems are modelled: Mora and the unique reward are
#: real but are not what anyone sorts by.
#:
#: **That is why `teapot_progress` is keyed by character as well as set.** A row per set could
#: not record having invited two of three favouring characters: the tracker would either call
#: the set finished and lose 20 primogems, or call it untouched and ask for work already done.
REWARD_PER_CHARACTER: int | None = 20


@dataclass(frozen=True)
class SuiteProgress:
    """One row of the tracker."""

    suite_id: str
    #: nanoka's own key for the set — `"1"` … `"109"`, ascending by release.
    #:
    #: Published so a client can offer release order as a sort. It is **not** the game's own
    #: list order and nothing here claims it is: the source carries no field for that, and
    #: labelling this "in-game order" would be a citation-shaped claim with no citation.
    nanoka_id: str
    name: str
    icon: str
    #: `"I"` / `"IG"` indoor, `"O"` / `"OG"` outdoor — nanoka's own spelling, uninterpreted.
    #:
    #: **Four values, not two.** At 7.0.51 the split is OG 48, IG 31, O 18, I 12, so a reader
    #: that matches `"I"` and `"O"` exactly sees 30 of 109 sets and silently mislabels the
    #: rest. What the `G` means is not documented anywhere this repo can cite, so it is carried
    #: through rather than interpreted; the leading letter is the part that is legible.
    placement: str
    # **Three states per character per set**, owner's own vocabulary, 2026-09-03. Every
    # character who favours this set is in exactly one of them, and the whole point of the
    # tracker is the first: *which set to build next, because it has characters you have not
    # invited yet*.
    #:
    #: **Available and owned** — you have them and have not invited them. Worth 20 primogems
    #: each, and the only state that makes a set worth building.
    available: tuple[str, ...]
    #: **Completed and owned** — invited already, so worth nothing more.
    #:
    #: Kept rather than subtracted away, because the page shows them: a user has to see a tick
    #: to undo one, and "3 of 4 done" is the sentence they are looking for.
    completed: tuple[str, ...]
    #: **Available and not owned** — they favour it, you do not have them.
    #:
    #: Shown rather than hidden: it is why a set can be worth less than its favourite count
    #: suggests, and it is what changes when the user pulls that character.
    unowned: tuple[str, ...]
    #: Has the user actually built this set?
    #:
    #: **A different axis from the invitations, not a summary of them.** Building costs
    #: materials and time; inviting to a set already standing costs a walk. So a built set
    #: with three characters left is the cheapest reward on the page, and an unbuilt one with
    #: three is the same primogems for much more work.
    built: bool = False

    @property
    def done(self) -> bool:
        """Nothing left to claim from the characters this user owns.

        **Derived rather than stored.** A set is finished when there is nobody available to
        invite; a separate flag could disagree with the rows it is meant to summarise. Note it
        is *not* the same as "every favouring character invited" — a set can be finished for
        you and still list characters you do not have.
        """
        return not self.available and bool(self.completed)

    @property
    def remaining(self) -> int:
        """Characters available and owned. One 20-primogem reward each."""
        return len(self.available)

    @property
    def remaining_primogems(self) -> int | None:
        """`remaining × REWARD_PER_CHARACTER`, or `None` if the constant is unset."""
        if REWARD_PER_CHARACTER is None:
            return None
        return self.remaining * REWARD_PER_CHARACTER


def rank(rows: Iterable[SuiteProgress]) -> list[SuiteProgress]:
    """Most worth doing first, for **this** user.

    Ordered by `remaining` — characters who favour the set, whom the user **owns**, and who
    have **not been invited yet**. That is the owner's ask exactly: *"ordering by the
    highest-gains sets for a given user."* A set favoured by six characters you do not have
    ranks below one favoured by a single character you do.

    It is also the order `remaining × reward` would give, because the reward is one constant
    per character and a positive multiplier cannot change a ranking.

    **Ties break on already-built first**, and that is a real preference rather than a
    tidy-up: two sets worth 60 primogems are not equal work if one is already standing in
    your teapot and the other needs materials. Then on name, so the list is stable between
    loads — an order that shuffles under the reader is one they stop trusting.
    """
    return sorted(rows, key=lambda row: (-row.remaining, not row.built, row.name.lower()))


def progress_for(
    suites: Iterable[Mapping[str, object]],
    owned_character_ids: set[str],
    invited: set[tuple[str, str]],
    built_suite_ids: set[str] | None = None,
) -> list[SuiteProgress]:
    """Build the tracker's rows from the catalogue and this user's state.

    `invited` is `(suite_id, character_nanoka_id)` pairs — **per character per set**, because
    that is how the reward is given. The same character invited to one of their two favourite
    sets is still owed the other.

    `built_suite_ids` is the separate axis: which sets this user has actually constructed.

    `suites` carries `favorite` as **nanoka character ids**, which is what
    `owned_character_ids` holds too — the join needs no translation, which is the finding that
    made this feature cheap.
    """
    already_built = built_suite_ids or set()
    rows = []
    for suite in suites:
        suite_id = str(suite["id"])
        favourites = tuple(suite.get("favorite") or ())
        owned = {c for c in favourites if c in owned_character_ids}
        already = {c for c in owned if (suite_id, c) in invited}
        rows.append(SuiteProgress(
            suite_id=suite_id,
            nanoka_id=str(suite.get("nanoka_id") or ""),
            name=str(suite["name"]),
            icon=str(suite.get("icon") or ""),
            placement=str(suite.get("placement") or ""),
            available=tuple(sorted(owned - already)),
            completed=tuple(sorted(already)),
            unowned=tuple(sorted(c for c in favourites if c not in owned_character_ids)),
            built=suite_id in already_built,
        ))
    return rank(rows)
