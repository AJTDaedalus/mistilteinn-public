"""Pando engine — port of frzyc/genshin-optimizer's ``libs/pando/engine``.

Consumes the symbolic DAG from :mod:`app.formula`. Provides a single-shot
``Calculator`` (mirror of Pando's), and (in later phases) interval-based
pruning, monotonicity-driven Pareto reduction, a solver for artifact
optimization, and Numba-compiled hot-loop compilation.

This package arrived in fairy as a generic engine lifted from *the Genshin
optimizer this project is compared to*; in mistilteinn it is a component
returning to its native game (DESIGN §2.4). ``calculator.py`` carries no
game vocabulary and was not touched by the port. ``translator.py`` moved to
``app/services/_ported/`` in B.3 — it converted the ZZZ modifier DSL to DAG
entries, so despite having no ZZZ *words* it was never game-agnostic; its
Genshin replacement is Chunk F work.
"""
