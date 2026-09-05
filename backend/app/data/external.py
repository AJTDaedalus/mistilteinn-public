"""The one reader of `app/data/external/` — data that is cited rather than derived.

`app/data/yuanshen/snapshot/` holds what this repo *derives* from a pinned AnimeGameData
capture, and `scripts/yuanshen/build_snapshot.py` rebuilds it. **This module reads the other
kind**: numbers that no primary source publishes, which therefore arrive with a citation and a
caveat instead of a derivation.

There is exactly one such file today — the artifact draw model — and the separate directory is
the point. A reader who finds a number under `snapshot/` may assume `build_snapshot.py` can
reproduce it; that assumption is load-bearing and must not be quietly false.

## Why the draw model is not derived

Measured 2026-09-05 against the capture at `5445617e33b2`:

- `ReliquaryAffixExcelConfigData` — 350 rows of `id / propType / group_id / propValue /
  depotId`. **No weight.**
- `ReliquaryMainPropExcelConfigData` — 66 rows of `id / propDepotId / propType / affixName`.
  **No weight.**
- `ReliquaryExcelConfigData` — *does* carry a `weight`, and it is an **item-drop weight on the
  artifact entry**. Reaching for it because the key matched would be confidently wrong, which
  is why the finding is written here rather than left to be rediscovered.

So the weights come from Genshin Optimizer's `libs/gi/upopt/src/consts.ts` at a pinned commit,
which itself cites the fandom *Artifact/Distribution* page. That is a **named secondary
source**, and this repo already ships one openly rather than pretending otherwise —
`gcsim_config.ENERGY_DRIP`. `docs/DESIGN_artifact_ranking.md` §8.3.

Nothing here reaches the network. The file is committed and E.6's unit-lane socket guard is
what keeps that true.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

EXTERNAL_DIR = Path(__file__).resolve().parent / "external"

#: The five equipment slots, in GOOD's own spelling. Stated rather than derived from the file's
#: keys: a slot missing from the data must raise, and a lookup that took its universe *from*
#: the data could never notice one was absent.
SLOTS = ("flower", "plume", "sands", "goblet", "circlet")


class ExternalDataUnavailableError(RuntimeError):
    """A committed external data file is missing, unreadable, or lacks what was asked of it."""


@cache
def _load(name: str) -> dict[str, Any]:
    path = EXTERNAL_DIR / f"{name}.json"
    if not path.exists():
        msg = (
            f"{path} is missing. It is a committed, cited artifact — not a cache and not "
            f"something `build_snapshot.py` can regenerate. Check out a tree that has it."
        )
        raise ExternalDataUnavailableError(msg)
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def substat_weights() -> dict[str, int]:
    """How likely each substat is to be drawn onto a piece, as an unnormalised weight.

    Used for choosing which substats an artifact *has* — a weighted draw **without
    replacement**, excluding the main stat and any line already present. It is **not** used for
    deciding which existing line an upgrade enhances: that is uniform over the four, and
    conflating the two is the mistake `RESEARCH_genshin_optimizer_scoring.md` §2 records GO as
    correctly avoiding.
    """
    weights = _load("artifact_draw_model")["substat_weights"]
    if not weights:
        msg = "artifact_draw_model.json carries no substat_weights"
        raise ExternalDataUnavailableError(msg)
    return dict(weights)


@cache
def main_stat_probabilities(slot: str) -> dict[str, float]:
    """The chance each main stat is rolled on `slot`, summing to 1.

    Raises for an unknown slot rather than returning `{}`. An empty mapping would read as "this
    slot has no main stats", which is not a fact about any slot, and a probability model handed
    one would silently contribute nothing.
    """
    if slot not in SLOTS:
        msg = f"{slot!r} is not an artifact slot; expected one of {', '.join(SLOTS)}"
        raise ExternalDataUnavailableError(msg)
    probs = _load("artifact_draw_model")["main_stat_probabilities"].get(slot)
    if not probs:
        msg = f"artifact_draw_model.json carries no main-stat probabilities for {slot!r}"
        raise ExternalDataUnavailableError(msg)
    return dict(probs)


@cache
def draw_model_provenance() -> dict[str, Any]:
    """Where the draw model came from, and what it could not be checked against.

    Exposed rather than left in the file because **a score is a claim**: anything that reports a
    probability derived from these numbers has to be able to say they are cited, not measured,
    and that the caveat exists.
    """
    data = _load("artifact_draw_model")
    return {
        "note": data["note"],
        "sources": data["sources"],
        "caveat": data["caveat"],
    }
