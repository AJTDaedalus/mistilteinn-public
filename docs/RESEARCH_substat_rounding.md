# 25.7% CRIT DMG is a legal roll, and the importer refuses it

**Status:** findings only, with a proposed one-line-ish fix. 2026-09-04, from a user's import
report in `references/user_errors.png`:

> 1909 imported. 66 build(s) rebuilt. 4 not imported:
> • #32 substat value(s) no combination of rolls can produce: `FIGHT_PROP_CRITICAL_HURT=0.257` …
> • #527 substat value(s) no combination of rolls can produce: `FIGHT_PROP_CRITICAL_HURT=0.257` …

The owner's reading — *"25.7% crit damage doesn't seem unrealistic"* — is correct, and the
message is wrong. **Two pieces carrying the same "impossible" value is the tell**: an
independent scanner slip does not repeat itself exactly.

## The value is reachable, and this is the combination

5★ CRIT DMG rolls at `5.44 / 6.22 / 6.99 / 7.77`. Four rolls:

```
6.22 + 6.22 + 6.22 + 6.99 = 25.65   → the game displays 25.7   → GOOD writes 0.257
```

An ordinary four-roll CRIT DMG line on a +16 or +20 piece. Nothing exotic, no elixir.

## Why the check says otherwise: the de-noise is calibrated for one roll

`substat_rolls._displayed` compares the *displayed* value — right, and the fix that took the
undetermined share of a real inventory from 3.5% to 0.04%. It de-noises float32 tier values
before rounding half-up, because a true `5.25%` ATK% roll is stored as `0.05249999836` and
banker's rounding would give `5.2`.

The de-noise is `round(scaled, 6)` — **six decimal places of the percentage**, i.e. an absolute
tolerance of `5e-7`. That is comfortably enough for **one** roll (`5.25` is off by `1.6e-7`).
It is not enough for four, because the error accumulates:

```python
sum((0.0622, 0.0622, 0.0622, 0.0699))  # the float32 tiers
# 0.256499994546175           →  ×100 = 25.6499994546175
round(25.6499994546175, 6)    # 25.649999   ← still below the 25.65 boundary
Decimal("25.649999").quantize(Decimal("0.1"), ROUND_HALF_UP)  # 25.6
```

`25.6 != 25.7`, no combination fits, `analyse` returns `rolls=None, candidates=()`, and
`_impossible_substats` classifies the piece as a scanner error and drops it.

**The module docstring already knew the shape of this** — *"de-noise before rounding, or the
boundary case rounds the wrong way"* — and fixed it for the single-roll case only. The
`_impossible_substats` docstring then wrote the symptom down as ground truth: *"the nearest
reachable four-roll sums are 25.6 and 26.4"*. They are 25.6, **25.7** and 26.4.

## How much this affects

Enumerating every legal `(rarity, prop, roll-count)` combination — 4,170 of them — and comparing
the current de-noise against exact tier values: **38 combinations, 28 distinct displayed values,
land on the wrong side.**

| rarity · stat | rolls | app says | truth |
|---|---|---|---|
| 5★ CRIT DMG | 3 | 21.7 | **21.8** |
| 5★ CRIT DMG | 4 | 25.6 | **25.7** |
| 5★ CRIT DMG | 4 | 28.7 | **28.8** |
| 5★ CRIT DMG | 5 | 32.6 / 34.9 / 35.7 / 38.8 | **32.7 / 35.0 / 35.8 / 38.9** |
| 5★ CRIT DMG | 6 | 38.8 / 41.9 | **38.9 / 42.0** |
| 5★ ATK% / HP% | 5 | 25.6 / 26.2 | **25.7 / 26.3** |
| 5★ ATK% / HP% | 6 | 28.5 / 29.1 / 32.6 | **28.6 / 29.2 / 32.7** |
| 5★ DEF% | 5, 6 | 29.1 / 36.4 / 34.2 / 41.5 | **29.2 / 36.5 / 34.3 / 41.6** |
| 4★ CRIT DMG | 5 | 21.7 / 29.8 | **21.8 / 29.9** |
| 4★ DEF% | 5 | 25.6 / 26.2 | **25.7 / 26.3** |

It cuts **both ways**, which is worth stating plainly:

* a real piece showing 25.7 CRIT DMG is **refused outright** — the whole artifact, not the line;
* a hypothetical piece showing 25.6 is **accepted and decomposed**, when 25.6 is not actually a
  reachable four-roll sum.

The corpus this was measured against (2,370 pieces, 7,878 substats) contained exactly one
25.7 CRIT DMG line, which is why it read as a one-off scanner slip rather than a boundary. The
new user's 1,909-piece export has two, and CRIT DMG is the stat people reroll into hardest, so
this will keep arriving.

## Fix: de-noise the table, not the sum

The noise is in the tier values, and the tables are float32 (~7.2 significant digits) while the
published values have at most five. Rounding each tier to **six significant figures** erases the
noise exactly and cannot alter a real value:

```python
_denoise = lambda v: float(f"{v:.6g}")
# 0.0544000007212162 → 0.0544      298.7500000001 → 298.75
```

Applied in `_tiers_for` — the one place the tables are read — every sum is then exact and
`_displayed` needs no tolerance at all beyond its existing `ROUND_HALF_UP`. Verified: the
6-significant-figure rule and explicit per-kind rounding (4 dp for fractions, 2 dp for flat
stats) agree on all 4,170 combinations, so the rule is not tuned to the failure.

`_NOISE_PLACES` and the `round(scaled, _NOISE_PLACES)` inside `_displayed` become dead once the
table is clean; leaving them is harmless but the comment that justifies them would then be
describing a problem that has moved.

### Tests worth adding, given this class of bug survived once already

1. **The boundary case by name.** `analyse(stars=5, stat=FIGHT_PROP_CRITICAL_HURT, value=0.257,
   level=20).rolls == 4` — and it should have `roll_tiers`, not just a count.
2. **The invariant, not the instance.** For every rarity, prop and legal roll count, the
   displayed sum of the *stored* tiers must equal the displayed sum of the *published* ones.
   That is the 4,170-combination sweep above; it runs in well under a second and it is the check
   that would have caught this without anyone knowing to look at CRIT DMG.
3. **A planted failure.** Per the repo's own rule about checks that can only return one answer:
   re-noise one tier by `1e-6` and confirm (2) fails.

## Separately: refusing the whole piece for one line

Not a bug, and `_impossible_reason` argues the case well (*"every number computed from it would
inherit the fault"*). But once (1)-(3) are in, an actually-impossible value is rare enough that
the message could name **which of the four substats** and offer to import the piece with that
line dropped, rather than losing a piece a user may have spent forty resin on. Worth an owner
ruling rather than a unilateral change; recorded here so it is not lost.
