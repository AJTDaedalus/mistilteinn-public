"""Triangulate a FileCfg table's hash-obfuscated columns against known anchors.

FileCfg column names are hashed (``ACDHCCGDKOK`` …) and rotate per game patch,
so a static column map goes stale. The robust approach (DESIGN §Methodology):
join a table's rows to a set of **trusted (id → value) anchors** — values we
already have in our DB / nanoka — and label a column only when its values
reproduce a trusted field across (almost) every joined row.

The output is a column dictionary that records, per labeled column, *which*
anchor field it reproduced and *how* (the method), so it can be **re-derived**
when the hashes rotate rather than hand-maintained.

This module is pure (no I/O beyond what the caller passes in) so it's testable
and reusable across tables. ``build_column_dicts.py`` drives it for the priority
tables using the DB-anchor snapshot.
"""

from __future__ import annotations

from typing import Any

# A column counts as "mapped" only if it reproduces an anchor field on at least
# this fraction of joined rows. High on purpose — partial matches are noise.
MATCH_THRESHOLD = 0.95


class TableShapeError(ValueError):
    """A FileCfg table did not have the structure the cartography assumes."""


def wrapper_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The row list inside a ``wrapped-list`` FileCfg table, found by shape.

    Every FileCfg table is a single-key object whose value is the row list, and that
    key is hashed like every column — so it **rotates per patch**. It moved
    ``JKMFEMCLDNN`` → ``MLOEFHJHCID`` between the two SHAs this repo has pinned, which
    is why hardcoding it made the whole toolkit unrunnable at its own pin (issue #165):
    every builder died on a ``KeyError`` before reading a single row, so "regenerate the
    column dictionary" — the documented response to a hash rotation — could not be done.

    The shape is unambiguous (exactly one list-valued key of dict rows), so deriving it
    is strictly better than pinning it. Raises :class:`TableShapeError` rather than
    guessing if the table is not that shape.
    """
    candidates = [
        key
        for key, value in doc.items()
        if isinstance(value, list) and value and isinstance(value[0], dict)
    ]
    if len(candidates) != 1:
        raise TableShapeError(
            f"expected exactly one list-of-rows key, found {len(candidates)}: "
            f"{sorted(candidates)} (top-level keys: {sorted(doc)})"
        )
    return doc[candidates[0]]


def unique_key_column(
    rows: list[dict[str, Any]], anchors: dict[int, Any] | None = None
) -> str:
    """The table's id column: the all-unique int column, found by shape.

    Same rotation problem as :func:`wrapper_rows` — ``DBPDHPIBGHA`` is not the key
    column at every SHA — and the same unambiguous structure to recover it from.

    A table can carry two all-unique int columns (``WeaponTemplateTb`` has an id *and*
    an id-like second column). Breaking that tie by column order would silently join on
    the wrong one, so it is broken by **anchor coverage** instead — the id column is the
    one whose values actually hit the trusted ids we already hold — and refused outright
    when no anchors are supplied or the winner is not strictly better. Guessing a key
    column poisons every value-match downstream of it, which is the one failure this
    toolkit must not have.
    """
    if not rows:
        raise TableShapeError("cannot derive a key column from an empty table")
    unique: list[str] = []
    for col in rows[0]:
        values = [row.get(col) for row in rows]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            continue
        if len(set(values)) == len(values):
            unique.append(col)
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1 and anchors:
        hits = sorted(
            ((sum(1 for r in rows if r[col] in anchors), col) for col in unique),
            reverse=True,
        )
        if hits[0][0] > hits[1][0]:
            return hits[0][1]
        raise TableShapeError(
            f"all-unique int columns {unique} join to the anchors equally "
            f"({hits[0][0]} rows each) — cannot tell which is the id column"
        )
    raise TableShapeError(
        f"expected exactly one all-unique int column, found {len(unique)}: {unique}"
        + ("" if anchors else " (pass anchors to break the tie by id coverage)")
    )


def column_value_match(
    rows: list[dict[str, Any]],
    key_col: str,
    anchors: dict[int, dict[str, Any]],
    fields: list[str],
) -> dict[str, dict[str, Any]]:
    """For every scalar column, find the anchor field it best reproduces.

    ``rows``     — the table rows (list of dicts), each keyed by hashed columns.
    ``key_col``  — the column holding the row id used to join to ``anchors``.
    ``anchors``  — ``{row_id: {field: value}}`` trusted reference values.
    ``fields``   — the anchor fields to test against.

    Returns ``{column: {best_field, matches, joined, ratio}}`` for each scalar
    column (list/dict columns are skipped — handled separately by the caller).
    """
    joined = [(r, anchors[r[key_col]]) for r in rows if r[key_col] in anchors]
    n = len(joined)
    result: dict[str, dict[str, Any]] = {}
    if not rows:
        return result
    for col in rows[0]:
        if col == key_col:
            continue
        if isinstance(rows[0][col], (list, dict)):
            continue
        best_field, best_matches = None, -1
        for f in fields:
            matches = sum(1 for tr, ar in joined if tr[col] == ar.get(f))
            if matches > best_matches:
                best_field, best_matches = f, matches
        result[col] = {
            "best_field": best_field,
            "matches": best_matches,
            "joined": n,
            "ratio": (best_matches / n) if n else 0.0,
        }
    return result


def confident_map(
    match_report: dict[str, dict[str, Any]], threshold: float = MATCH_THRESHOLD
) -> dict[str, str]:
    """Reduce a match report to ``{column: field}`` for columns over ``threshold``.

    A field maps to at most one column — if two columns clear the threshold for
    the same field, the higher-ratio one wins (the other stays unmapped, to be
    inspected by hand: it usually means a near-duplicate or a wrong anchor).
    """
    candidates = sorted(
        (
            (col, info["best_field"], info["ratio"])
            for col, info in match_report.items()
            if info["ratio"] >= threshold and info["best_field"] is not None
        ),
        key=lambda t: t[2],
        reverse=True,
    )
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for col, field, _ratio in candidates:
        if field in used:
            continue
        mapping[col] = field
        used.add(field)
    return mapping


def nested_value_match(
    rows: list[dict[str, Any]],
    key_col: str,
    anchors: dict[int, dict[str, Any]],
    fields: list[str],
    dict_col: str,
) -> dict[str, dict[str, Any]]:
    """value-match every *inner* key of a nested ``{inner: scalar}`` dict column.

    Some FileCfg tables store a stat as a ``{prop_id, value}`` sub-object (e.g.
    ``WeaponTemplateTb`` base/secondary stats: ``{COLMGGLOLJJ: 12101,
    MHMKJPOJNDC: 32}``).  :func:`column_value_match` skips dict columns, so this
    drills one level: for each inner key found across the joined rows, it reports
    the anchor field that key's values best reproduce.  The caller reads off the
    *value* inner-key (reproduces a numeric field) and treats the other inner
    key (the categorical ``prop_id``) separately — both re-derived by content, so
    the map survives an inner-hash rotation.

    Returns ``{inner_key: {best_field, matches, joined, ratio}}``.
    """
    joined = [(r, anchors[r[key_col]]) for r in rows if r[key_col] in anchors]
    n = len(joined)
    inner_keys: set[str] = set()
    for tr, _ in joined:
        sub = tr.get(dict_col)
        if isinstance(sub, dict):
            inner_keys |= set(sub)
    result: dict[str, dict[str, Any]] = {}
    for ik in inner_keys:
        best_field, best_matches = None, -1
        for f in fields:
            matches = sum(
                1
                for tr, ar in joined
                if isinstance(tr.get(dict_col), dict)
                and tr[dict_col].get(ik) == ar.get(f)
            )
            if matches > best_matches:
                best_field, best_matches = f, matches
        result[ik] = {
            "best_field": best_field,
            "matches": best_matches,
            "joined": n,
            "ratio": (best_matches / n) if n else 0.0,
        }
    return result


def enum_join(
    rows: list[dict[str, Any]],
    key_col: str,
    anchors: dict[int, dict[str, Any]],
    field: str,
) -> dict[str, dict[str, Any]]:
    """For every scalar column, test whether it encodes a categorical anchor field.

    Unlike :func:`column_value_match` (which compares *values* directly), this
    groups joined rows by the column's value and asks: does each distinct column
    value map to a single dominant ``anchors[field]`` category? Returns, per
    column, the value→dominant-category mapping plus a **purity** ratio (the
    share of joined rows whose category equals their value's dominant category).

    Tolerant on purpose: a real enum can carry one stray row (a placeholder
    avatar whose id collides with a different DB entry), so we report purity and
    let the caller threshold it rather than demanding a perfect bijection.

    Returns ``{column: {mapping, purity, joined, distinct}}``.
    """
    joined = [(r, anchors[r[key_col]]) for r in rows if r[key_col] in anchors]
    n = len(joined)
    result: dict[str, dict[str, Any]] = {}
    if not rows:
        return result
    for col in rows[0]:
        if col == key_col or isinstance(rows[0][col], (list, dict)):
            continue
        # value -> Counter of anchor categories
        buckets: dict[Any, dict[Any, int]] = {}
        for tr, ar in joined:
            cat = ar.get(field)
            buckets.setdefault(tr[col], {})
            buckets[tr[col]][cat] = buckets[tr[col]].get(cat, 0) + 1
        mapping: dict[Any, Any] = {}
        correct = 0
        for val, counts in buckets.items():
            dom = max(counts, key=counts.get)
            mapping[val] = dom
            correct += counts[dom]
        result[col] = {
            "mapping": mapping,
            "purity": (correct / n) if n else 0.0,
            "joined": n,
            "distinct": len(buckets),
        }
    return result


def column_profiles(
    rows: list[dict[str, Any]], key_col: str
) -> dict[str, dict[str, Any]]:
    """Cheap structural profile per column: type, non-zero count, distinct sample.

    Used to characterise the columns that *don't* resolve to an anchor (reserved
    zero columns, id lists, label strings) so they can be honestly recorded as
    unresolved-with-observations rather than guessed.
    """
    profiles: dict[str, dict[str, Any]] = {}
    if not rows:
        return profiles
    for col in rows[0]:
        if col == key_col:
            continue
        sample = rows[0][col]
        kind = type(sample).__name__
        if isinstance(sample, (list, dict)):
            kind = "list" if isinstance(sample, list) else "dict"
            nonempty = sum(1 for r in rows if r[col])
            samples = [r[col] for r in rows if r[col]][:5]
            profiles[col] = {"kind": kind, "nonempty": nonempty, "samples": samples}
        elif isinstance(sample, str):
            vals = {r[col] for r in rows if r[col]}
            profiles[col] = {
                "kind": "str",
                "nonempty": sum(1 for r in rows if r[col]),
                "distinct": len(vals),
                "samples": sorted(vals)[:6],
            }
        else:
            vals = {r[col] for r in rows if r[col] not in (0, None)}
            profiles[col] = {
                "kind": kind,
                "nonzero": sum(1 for r in rows if r[col] not in (0, None)),
                "distinct": len(vals),
                "samples": sorted(vals)[:6] if vals else [],
            }
    return profiles
