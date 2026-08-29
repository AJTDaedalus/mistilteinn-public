"""Committed reaction data, derived from a cited source rather than from memory.

`elemental_reactions.json` is lifted verbatim from the machine-readable block in
`docs/RESEARCH_elemental_reactions.md`, which records the URL, the retrieval date and the wiki's
own wording per reaction. **Nothing here was written from knowledge of the game.**

This exists because the repo genuinely had no reaction-to-element data:
`app/formula/genshin/damage.py` carries the four *amplifying* reactions and says in its own
docstring that transformative and additive ones are deliberately absent, since gcsim computes
them on another path. That is right for the damage chain and useless for a team filter.
"""
