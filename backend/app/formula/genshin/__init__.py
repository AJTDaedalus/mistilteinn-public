"""Genshin formula layer: the tag vocabulary, the stat graph, and the damage chain.

Sibling to the deleted `formula/zzz/`. Nothing here is renamed from it — the two games
disagree about enough that a rename would have been a lie (ZZZ's stats are two-stage and
stored in basis points; Genshin's are single-stage fractions).

**Every game constant in this package cites its source at the line that introduces it**,
per CLAUDE.md. The pinned reference is recorded in `docs/CROSSVAL_gcsim.md`; a citation
that names a file without that pin is a citation to a moving target.

This package must not import from `app.models` — the DAG is deliberately decoupled from the
ORM. Where the two vocabularies have to agree, a **test** pins the correspondence
(`tests/unit/test_genshin_tag_vocabulary.py`) rather than an import doing it implicitly.
"""
