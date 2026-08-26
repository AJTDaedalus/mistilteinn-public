"""A compiled multi-character rotation emits no swap, and that is recorded, not accidental.

`docs/RESEARCH_recipe_cost.md` §2: gcsim's **browser** build cannot run a rotation that acts
on a non-active character. It demands an explicit swap, its evaluator is supposed to insert
one implicitly, and the wasm entry point cannot — `initialize()` parses into an `ast.File`
then discards it, so `simulate()` hands `NewEvaluator` a fresh empty one. The native binary
keeps the parsed file and runs these configs correctly.

This test does not assert that the limitation is *fine*. It pins the current behaviour so
that adding swaps is a deliberate change with a reason, rather than a silent one — and so
that the day the pin moves and upstream fixes it, something says this reasoning is stale.
"""

from __future__ import annotations

import types

from app.services.rotation_compiler import compile_rotation

_CHARS = {
    "10000052": types.SimpleNamespace(
        nanoka_id="10000052", name="Raiden Shogun", element="Electro",
    ),
    "10000023": types.SimpleNamespace(
        nanoka_id="10000023", name="Xiangling", element="Pyro",
    ),
}


def _compiled() -> str:
    return compile_rotation(
        [
            {"character": "10000052", "action": "burst", "repeat": 1},
            {"character": "10000023", "action": "burst", "repeat": 1},
            {"character": "10000052", "action": "attack", "repeat": 3},
        ],
        _CHARS,
    )


def test_a_two_character_rotation_names_both_characters() -> None:
    """Guards the assertion below from passing because the compile did nothing."""
    config = _compiled()

    assert "raidenshogun burst" in config
    assert "xiangling burst" in config


def test_it_emits_no_swap_action() -> None:
    """The browser build rejects this; the native binary runs it.

    If this starts failing because swaps were added, the comment in `rotation_compiler` and
    `docs/RESEARCH_recipe_cost.md` §2 both need updating — the swap syntax that works is not
    established, and inventing one would be working around an upstream defect in a compiler
    whose argument is that it emits what gcsim documents.
    """
    assert "swap" not in _compiled()


def test_the_active_character_is_the_first_step_not_the_first_slot() -> None:
    """Unchanged by the above, and the reason a swap is needed at all for the others."""
    assert _compiled().startswith("active raidenshogun;")
