"""Read-only cartography toolkit for the Dimbreath ZenlessData dataset.

This package supports the data-cartography initiative (see
``docs/DESIGN_dimbreath_cartography.md``). It fetches, caches, and merges the
Dimbreath TextMap / FileCfg files at a pinned commit SHA so that mapping the
dataset is reproducible. It deliberately does **not** modify importers, models,
or seed behaviour — it only produces schema artifacts under
``app/data/dimbreath/schema/`` and docs under ``docs/MAP_*``.
"""
