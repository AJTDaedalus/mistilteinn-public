"""Pando engine — port of frzyc/genshin-optimizer's ``libs/pando/engine``.

Consumes the symbolic DAG from :mod:`app.formula`. Provides a single-shot
``Calculator`` (mirror of Pando's), and (in later phases) interval-based
pruning, monotonicity-driven Pareto reduction, a solver for disc optimization,
and Numba-compiled hot-loop compilation.
"""
