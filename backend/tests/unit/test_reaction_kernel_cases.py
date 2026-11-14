"""The reaction case file `npm run kernel:verify` replays, and whether it is current.

`scripts/kernel/generate_reaction_cases.py` writes it from `app/formula/genshin/reactions.py`;
the browser's mirror in `damage.ts` must match every case. This test fails if the committed
file is not what the chain gives now — a stale file would let the two implementations drift
apart while the gate kept passing against yesterday's answers.
"""

from __future__ import annotations

import json
from collections import Counter

from scripts.kernel.generate_reaction_cases import OUT, generate


def test_the_committed_cases_are_what_the_chain_gives_now():
    committed = json.loads(OUT.read_text())
    assert committed == json.loads(json.dumps(generate())), (
        "reaction_cases.json is stale: run `python -m scripts.kernel.generate_reaction_cases`"
    )


def test_every_family_and_every_reaction_is_swept():
    cases = json.loads(OUT.read_text())["cases"]
    kinds = Counter(c["kind"] for c in cases)
    assert set(kinds) == {"transformative", "additive", "lunar"}
    assert min(kinds.values()) >= 300
    reactions = {c["reaction"] for c in cases}
    assert {"overloaded", "electro_charged", "superconduct", "swirl", "shattered", "burning",
            "bloom", "hyperbloom", "burgeon", "spread", "aggravate", "lunar_charged",
            "lunar_crystallize"} <= reactions
    # A reaction CRIT and the 0.75 RES boundary are each exercised, not left to chance.
    assert any(c["kind"] == "transformative" and c["crit_rate"] > 0 for c in cases)
    assert any(c["resistance"] == 0.75 for c in cases)
