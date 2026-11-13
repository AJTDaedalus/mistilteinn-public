"""Turn a talent's published rows into hits. M.1.

`DESIGN_multipliers.md` §2. A talent's `promote[level]` carries `desc` — a padded list of
`"Label|{paramN:FMT}"` — beside a flat `param` list that `paramN` indexes **1-based**:

    desc:  ["Cutting DMG|{param1:P}", "CD|{param4:F1}s", "Energy Cost|{param5:I}", "", …]
    param: [1.123, 1.6845, 5, 20, 80, 0, …]

Across the 498 non-empty rows in the committed fixtures there are four format codes — `F1P`,
`P`, `F1`, `I` — and five tails. **The params are already fractions**: `1.123` is 112.3%,
matching this repo's convention, so nothing here converts them. `P` and `F1P` differ only in
display precision; treating `F1P` as needing a divide would quietly make every normal attack a
hundredth of its real value.

## The separator carries meaning

- `{p}×3` — one hit landing three times. The count stays **separate** (OQ-M2): the damage
  chain applies crit and DEF per hit, so a pre-multiplied `param × 3` would apply them once to
  a tripled number, which is a different and smaller answer.
- `{a}+{b}` — **two hits that both land**, not one summed multiplier. Venti's `1-Hit DMG` is
  `{param1}+{param1}`: two arrows of 0.20382 each, and gcsim stores one per-hit value rather
  than 0.40764. Summing applies crit and DEF once to a doubled figure, which is the same
  mistake as folding `×3` into the multiplier — **M.4 caught it summing, and this is the fix.**
- `{a}/{b}` — two **alternatives**, `Low/High Plunge DMG`. Only one of them happens. A
  repeat binds to the alternative it follows: `{a}/{b}/{c}×3` repeats only `c`, which is how
  gcsim models Clorinde's three Bond-of-Life lunges.

Both shapes yield two hits; `exclusive` is what tells them apart, because a caller totalling a
talent's damage adds the first pair and picks one of the second.

## The words after a param name its stat (math-fallback P0)

`{p} Max HP`, `{p} DEF`, `{p} Elemental Mastery` and `{p} ATK` say what the multiplier scales
off; a param with no word is ATK. **This parser used to throw the words away**, so every hit
was ATK, and `{a} ATK+{b} Elemental Mastery` — Nahida's Tri-Karma Purification, one instance of
damage — became two ATK hits that both landed. `RESEARCH_math_fallback_inventory.md` §2.3.

- A bare param takes the **next stat word to its right**: `{a}/{b} Max HP` is two HP
  alternatives (Nilou), `{a}+{b} DEF` is two DEF parts. A bare param *after* the last word
  has nothing to take, and is refused rather than guessed as ATK.
- `+` between parts of **one** stat keeps its meaning above: separate hits. `+` between
  parts of **different** stats is one hit with one `ScalingTerm` per stat — what gcsim and
  GO both model, with the second part as flat damage (`damage.ScalingTerm`).
- `({a} ATK+{b} Elemental Mastery)×2` — Alhaitham's mirrors — is one two-term hit landing
  twice. A repeat may follow a word or a space (`{p} Max HP ×3`) and may be an ASCII `*`
  (`{p}*4`); the old pattern wanted `×` straight after the brace and read those as one hit.

Every word is in a table below — a stat, an element, a per-instance unit, or a named refusal
— and **a word in none of them refuses the row by name** (`RefusedHit.unrecognised`), so a
new patch's vocabulary arrives as a refusal, not as an ATK hit nobody checked.

## What counts as damage

The **label** contains `DMG`. Not the format: `Blazing Threshold` and `Nightsoul Point Limit`
are `P`-formatted percentages that are not damage.

**Or the label is one of eleven exact strings that are damage without saying so** —
`Aimed Shot`, `Fully-Charged Aimed Shot`, Neuvillette's `Charged Attack: Equitable Judgment`,
the `DoT` rows (`_DAMAGE_WITHOUT_DMG`). The `DMG` rule alone hid them, so no bow user's aimed
shot and not Neuvillette's main damage source was ever offered as a hit (math-fallback P1).
Every other percentage row without `DMG` must match a known non-damage word
(`_NOT_DAMAGE_WORDS`: healing, costs, shields, buffs, debuffs); one that matches neither is
**refused by name**, so the classification stays explicit in both directions.

**This is a heuristic over English text and that is a real limitation** — the fixtures are the
`en` locale. `TASKS_multipliers.md` M.4 is what stops it being taken on trust: gcsim's
generated tables carry the same numbers, so the parse is checked against an independent
implementation rather than reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.formula.genshin.damage import ScalingStat, ScalingTerm

#: `{param12:F1P}` — the index is 1-based against the `param` list.
_PARAM = re.compile(r"\{param(\d+):([A-Za-z0-9]+)\}")

#: One `+`-separated part: a param, then an optional word, then an optional repeat.
#:
#: `×` is U+00D7 MULTIPLICATION SIGN, which is what the payload contains. Written as an
#: escape because ruff's ambiguity check is right that an inline `×` beside an ASCII `x` is
#: indistinguishable to a reader. The ASCII `*` is Xiangling's 4-Hit, the one row that uses it.
_PART = re.compile(
    r"^\{param(\d+):[A-Za-z0-9]+\}\s*(?P<word>.*?)\s*(?:[\u00d7*]\s*(?P<repeat>\d+))?$",
)

#: `( … )×N` around a whole alternative — Alhaitham's mirror projections.
_GROUP = re.compile(r"^\((?P<inner>.*)\)\s*[\u00d7*]\s*(?P<repeat>\d+)$")

#: What marks a row as damage. See the module docstring on why this is the label, not `FMT`.
_DAMAGE = "DMG"

#: Words that make a `DMG` label something other than an instance of damage.
#:
#: **Derived from the data, not guessed.** Of the 430 distinct `DMG` labels across the seeded
#: catalogue, 50 carry one of these — `Shield DMG Absorption` is a shield's capacity,
#: `Anemo DMG Bonus` is an additive modifier, `DMG Reduction` is damage *taken*, and
#: `Elemental Mastery-Based Swirl DMG Increase` is a coefficient per point of EM. gcsim's own
#: comment for that last one ends `per Point`, which is what first identified it (M.4).
#: `Interval` (P0) is two rows whose value is seconds between hits — `{param10:F1}s` — which
#: had been parsed as a hit worth 1.5x ATK.
#:
#: Treating any of them as a hit produces a multiplier for something that never strikes.
_NOT_A_HIT = ("Bonus", "Increase", "Absorption", "Reduction", "Resistance", "per ", "Interval")

#: Labels that **are** damage and do not say `DMG`, each one exact (math-fallback P1).
#:
#: The `DMG` rule missed them, so Neuvillette's Equitable Judgment and every bow user's aimed
#: shots were never offered as hits. Surveyed over every level-1 row in the seeded catalogue
#: (nanoka 7.2.51, 2026-11-13): of the 91 distinct percent-formatted labels without `DMG`,
#: these eleven are damage and the rest are healing, shields, costs, buffs and debuffs
#: (`_NOT_DAMAGE_WORDS`). **Every one but `Riptide Slash` has a table of the same label in
#: gcsim's `talent_multipliers.json`**, which is the independent check that they strike —
#: `scripts.gcsim.crossval_multipliers` compares their numbers and their scaling stat.
#: `Riptide Slash` is Tartaglia's melee-stance proc; gcsim models it under another name.
#:
#: Exact strings, not a pattern: `Aimed Shot` is damage and `Aimed Shot Charge Time` would
#: not be, and a substring rule is how the next patch's non-damage row becomes a hit.
_DAMAGE_WITHOUT_DMG = frozenset({
    "Aimed Shot",
    "Aimed Shot Charge Level 1",
    "Fully-Charged Aimed Shot",
    "Level 1 Aimed Shot",
    "Charged Attack",
    "Charged Attack: Equitable Judgment",
    "DoT",
    "Ice Lance DoT",
    "Pyro DoT",
    "Coda at Dawn's Tolling DoT",
    "Riptide Slash",
})

#: Words that mark a percent-formatted, `DMG`-less label as **not** damage — the other 80 of
#: the 91 surveyed above, each matched by at least one: healing and regeneration, HP costs and
#: losses, shields, buffs (`Bonus`, `Increase`, `Ratio`, `Conversion`), debuffs (`Decrease`,
#: `Reduction`), thresholds and stack caps. A percent row matching none of these and not in
#: `_DAMAGE_WITHOUT_DMG` is **refused by name** (`RefusedHit.unrecognised`), so a new patch's
#: wording arrives as a refusal that `crossval_multipliers` reports, never as a silent skip
#: of a real hit — the gap this table closes.
_NOT_DAMAGE_WORDS = (
    "Healing", "Regeneration", "HP Restored", "Life Drain", "HP Loss", "Cost", "Consumption",
    "Shield", "Absorption", "Bonus", "Increase", "Decrease", "Reduction", "Mitigation",
    "Ratio", "Conversion", "Inherited HP", "Bond of Life", "Threshold", "Maximum", "Chance",
)

#: A format code ending in `P` is a percentage — `P`, `F1P`, `F2P`. A row with none is
#: seconds, a count or an energy cost (`F1`, `I`) and is never a damage multiplier.
_PERCENT_FORMAT = re.compile(r"\{param\d+:[A-Za-z0-9]*P\}")

#: The row whose value is a burst's energy cost. `Character.burst_energy_cost` has been
#: nullable since Chunk D precisely because this had never been parsed out.
_ENERGY_COST = "Energy Cost"

#: The stat words, verbatim, as the catalogue spells them. Surveyed over every level-1 DMG row
#: in the seeded catalogue (nanoka 7.0.51, 2026-11-13): these four are all there are.
_STAT_WORDS: dict[str, ScalingStat] = {
    "ATK": ScalingStat.ATK,
    "Max HP": ScalingStat.HP,
    "DEF": ScalingStat.DEF,
    "Elemental Mastery": ScalingStat.ELEMENTAL_MASTERY,
}

#: Words naming the **element** a part lands as, not what it scales off. Freminet's
#: `{a} Cryo + {b} Physical` is two ATK parts in two elements. The channel stays the caller's
#: (`talent_hits` module docstring), so these carry no information this parser keeps.
_ELEMENT_WORDS = frozenset({
    "Anemo", "Cryo", "Dendro", "Electro", "Geo", "Hydro", "Physical", "Pyro",
})

#: Words saying the multiplier is **per damage instance** — which is what a hit already is.
#: Albedo's Fatal Blossom (`each`), Diona's Icy Paw (`per Paw`) and the Traveler's Ice Javelin
#: (`/Strike`, which follows the param after a slash rather than a space).
_INSTANCE_WORDS = frozenset({"each", "per Paw", "Strike"})

#: Tails that are **not** `multiplier x own stat`, each with why. They used to be read as ATK.
_REFUSED_WORDS: dict[str, str] = {
    "Normal Attack DMG": (
        "a multiple of the character's Normal Attack DMG, not of a stat — the hit is a "
        "fraction of another hit, which the closed-form chain has no term for"
    ),
    "Charged Attack DMG": (
        "a multiple of the character's Charged Attack DMG, not of a stat — the hit is a "
        "fraction of another hit, which the closed-form chain has no term for"
    ),
    "Corresponding Character's ATK": (
        "scales off another party member's ATK, which a single build does not have"
    ),
    "Elemental Mastery Per Verdant Dew": (
        "Elemental Mastery per Verdant Dew — the multiplier scales with a stack count that "
        "is kit state, not something the table states"
    ),
    "Beacon": (
        "Elemental Mastery per Beacon — the multiplier scales with a count that is kit "
        "state, not something the table states"
    ),
}


class TalentScalingError(ValueError):
    """A row this parser cannot read.

    Raised rather than skipped. A `DMG` row that does not resolve is a gap in the parser, and
    returning nothing for it would present an incomplete kit as a complete one.
    """


@dataclass(frozen=True)
class TalentHit:
    """One hit a talent can land."""

    #: The published label, e.g. `Cutting DMG`. Kept so a caller can offer the user the
    #: game's own wording rather than an invented name.
    label: str
    #: Already a fraction: `1.123` is 112.3%. The multiplier of the **first** term.
    multiplier: float
    #: How many times this hit lands per use. Separate from the multiplier — see the module
    #: docstring.
    hits: int = 1
    #: True when this hit is **one of several alternatives** and only one of them happens —
    #: a low plunge against a high plunge. False for the parts of a multi-hit attack, which
    #: all land. A caller totalling a talent's damage sums the latter and picks one of the
    #: former, and without this it cannot tell which it is looking at.
    exclusive: bool = False
    #: What `multiplier` scales off, read from the word after the param.
    scaling_stat: ScalingStat = ScalingStat.ATK
    #: The other terms of a mixed-stat hit (`# ATK+# Elemental Mastery`). Empty otherwise.
    extra_terms: tuple[ScalingTerm, ...] = ()


@dataclass(frozen=True)
class RefusedHit:
    """A `DMG` row this parser recognised as damage and will not score, and why."""

    label: str
    spec: str
    reason: str
    #: True when the tail carried a word in none of this module's tables — the next patch's
    #: vocabulary. False for the named refusals in `_REFUSED_WORDS`.
    unrecognised: bool = False


@dataclass(frozen=True)
class TalentRow:
    """One level's row: the hits it yields and the damage rows it refuses."""

    hits: list[TalentHit] = field(default_factory=list)
    refused: list[RefusedHit] = field(default_factory=list)


def parse_talent_row(
    desc: list[str] | None, param: list[float] | None,
) -> list[TalentHit]:
    """The damage hits in one level's row of a talent's table.

    `desc` and `param` are not required to be the same length: `param` is padded with real
    zeroes well past the end of `desc`, and requiring them to match would refuse most rows.

    Rows refused by `classify_talent_row` are absent: a page offering them would offer a
    number the chain cannot compute.
    """
    return classify_talent_row(desc, param).hits


def classify_talent_row(desc: list[str] | None, param: list[float] | None) -> TalentRow:
    """`parse_talent_row`, with the damage rows it refuses named rather than dropped."""
    row = TalentRow()
    for entry in desc or []:
        if not entry:
            continue
        label, _, spec = entry.partition("|")
        if not _is_damage_row(label, spec):
            if _is_unclassified(label, spec):
                row.refused.append(
                    RefusedHit(
                        label=label, spec=spec, unrecognised=True,
                        reason=(
                            f"{entry!r}: a percentage row whose label names neither damage "
                            f"nor a known non-damage quantity. Classify it in "
                            f"talent_scaling._DAMAGE_WITHOUT_DMG or _NOT_DAMAGE_WORDS."
                        ),
                    ),
                )
            continue
        try:
            row.hits.extend(_hits_from(label, spec, param or []))
        except _RefusedError as refusal:
            row.refused.append(
                RefusedHit(
                    label=label, spec=spec, reason=refusal.reason,
                    unrecognised=refusal.unrecognised,
                ),
            )
    return row


def _is_damage_row(label: str, spec: str) -> bool:
    """`DMG` in the label and no modifier word, or one of the reviewed exact labels."""
    if label in _DAMAGE_WITHOUT_DMG:
        return bool(_PARAM.search(spec))
    return _DAMAGE in label and not any(word in label for word in _NOT_A_HIT)


def _is_unclassified(label: str, spec: str) -> bool:
    """A percentage row without `DMG` that neither list accounts for."""
    if _DAMAGE in label or not _PERCENT_FORMAT.search(spec):
        return False
    return not any(word in label for word in _NOT_DAMAGE_WORDS)


def energy_cost(desc: list[str] | None, param: list[float] | None) -> int | None:
    """A burst's energy cost, or `None` for a talent that has none.

    `None` rather than zero: a normal attack has no burst cost, and zero would claim it is
    free to cast.
    """
    for entry in desc or []:
        if not entry:
            continue
        label, _, spec = entry.partition("|")
        if label != _ENERGY_COST:
            continue
        found = _PARAM.search(spec)
        if found is None:
            msg = f"{_ENERGY_COST!r} row has no param: {entry!r}"
            raise TalentScalingError(msg)
        return int(_value(found.group(1), param or [], entry))
    return None


class _RefusedError(Exception):
    """Internal: this row is damage, and it will not be scored. Becomes a `RefusedHit`."""

    def __init__(self, reason: str, *, unrecognised: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.unrecognised = unrecognised


@dataclass
class _Part:
    """One `+`-separated part of one alternative, before stats are resolved."""

    index: str
    word: str
    repeat: int
    stat: ScalingStat | None


def _hits_from(label: str, spec: str, param: list[float]) -> list[TalentHit]:
    """One `Label|spec` pair, as the hits it describes.

    The spec is read **positionally**, which is how the payload writes it:

        {param4:F1P}/{param5:F1P}/{param7:F1P}×3

    Split on `/` gives three alternatives; the `×3` belongs to the third because it follows
    it. gcsim models exactly that — Clorinde's `Impale the Night` is three tables, no / low /
    full Bond of Life, and only the third repeats (M.4). Within an alternative, `+` joins
    parts: separate hits when they share a stat, one multi-term hit when they do not.
    """
    entry = f"{label}|{spec}"
    alternatives = _alternatives(spec, entry)
    if not alternatives:
        msg = (
            f"{label!r} is a damage row with no param reference: {spec!r}. A hit the parser "
            f"cannot resolve is a gap in the parser, not a hit that does no damage."
        )
        raise TalentScalingError(msg)

    parsed = [(_parts(segment, entry), group) for segment, group in alternatives]
    _resolve_stats([part for parts, _ in parsed for part in parts], entry)

    exclusive = len(parsed) > 1
    hits: list[TalentHit] = []
    for parts, group in parsed:
        hits.extend(_combine(label, parts, group, exclusive, param, entry))
    return hits


def _alternatives(spec: str, entry: str) -> list[tuple[str, int]]:
    """The spec split on `/` into alternatives, each with its group repeat (1 if none).

    A slash followed by a word and no param — `{p}/Strike`, `{p} Elemental Mastery/Beacon` —
    is a unit, not a second alternative, and is folded back into the segment it follows.
    """
    segments: list[str] = []
    for raw in spec.split("/"):
        if _PARAM.search(raw) or not segments:
            segments.append(raw)
            continue
        unit = raw.strip()
        if unit in _INSTANCE_WORDS:
            continue
        if unit in _REFUSED_WORDS:
            raise _RefusedError(f"{entry!r}: {_REFUSED_WORDS[unit]}")
        raise _RefusedError(
            f"{entry!r}: the unit {unit!r} after a slash is not one this parser knows; "
            f"reading it as ATK would be a guess",
            unrecognised=True,
        )

    out: list[tuple[str, int]] = []
    for segment in segments:
        stripped = segment.strip()
        if not _PARAM.search(stripped):
            continue
        group = _GROUP.match(stripped)
        if group:
            out.append((group["inner"], int(group["repeat"])))
        else:
            out.append((stripped, 1))
    return out


def _parts(segment: str, entry: str) -> list[_Part]:
    """One alternative's `+`-separated parts, each with its word classified."""
    parts: list[_Part] = []
    for raw in segment.split("+"):
        text = raw.strip()
        if len(_PARAM.findall(text)) > 1:
            # **Not defaulted to a sum.** Params joined by something this has not been taught
            # is a shape nobody has checked, and combining them would produce a confident
            # multiplier for a hit whose composition is a guess. Refusing names the row.
            joins = _PARAM.sub("", text).strip()
            msg = (
                f"{entry!r} references several params joined by {joins!r}, which this "
                f"parser does not recognise. Combining them would invent a composition."
            )
            raise TalentScalingError(msg)
        found = _PART.match(text)
        if found is None:
            msg = f"{entry!r}: part {text!r} is not `{{param}} [word] [xN]`."
            raise TalentScalingError(msg)
        word = found["word"]
        parts.append(
            _Part(
                index=found.group(1),
                word=word,
                repeat=int(found["repeat"]) if found["repeat"] else 1,
                stat=_classify_word(word, entry),
            ),
        )
    return parts


def _classify_word(word: str, entry: str) -> ScalingStat | None:
    """The stat a word names, `None` for a word that names no stat, or a refusal."""
    if not word or word in _ELEMENT_WORDS or word in _INSTANCE_WORDS:
        return None
    if word in _STAT_WORDS:
        return _STAT_WORDS[word]
    if word in _REFUSED_WORDS:
        raise _RefusedError(f"{entry!r}: {_REFUSED_WORDS[word]}")
    raise _RefusedError(
        f"{entry!r}: the tail word {word!r} is not a stat, element or unit this parser "
        f"knows. Reading it as ATK would be the silent assumption this table exists to stop.",
        unrecognised=True,
    )


def _resolve_stats(parts: list[_Part], entry: str) -> None:
    """Give every bare part the next stat word to its right; ATK if the row has none."""
    pending: ScalingStat | None = None
    for part in reversed(parts):
        if part.stat is not None:
            pending = part.stat
        else:
            part.stat = pending
    if all(part.stat is None for part in parts):
        for part in parts:
            part.stat = ScalingStat.ATK
    elif any(part.stat is None for part in parts):
        msg = (
            f"{entry!r}: a param after the last stat word has no stat word to take. "
            f"Defaulting it to ATK would be a guess beside a row that names its stats."
        )
        raise TalentScalingError(msg)


def _combine(
    label: str,
    parts: list[_Part],
    group: int,
    exclusive: bool,
    param: list[float],
    entry: str,
) -> list[TalentHit]:
    """One alternative's parts as hits."""
    stats = [part.stat for part in parts]
    if len(set(stats)) == 1:
        # Parts of one stat all land separately: the `+` meaning M.4 established.
        return [
            TalentHit(
                label=label,
                multiplier=_value(part.index, param, entry),
                hits=part.repeat * group,
                exclusive=exclusive,
                scaling_stat=part.stat or ScalingStat.ATK,
            )
            for part in parts
        ]
    if len(set(stats)) != len(stats) or any(part.repeat != 1 for part in parts):
        msg = (
            f"{entry!r}: parts {[str(s) for s in stats]} are neither one stat (separate "
            f"hits) nor one term per stat (one hit). Picking either reading would invent a "
            f"composition."
        )
        raise TalentScalingError(msg)
    first, *rest = parts
    return [
        TalentHit(
            label=label,
            multiplier=_value(first.index, param, entry),
            hits=group,
            exclusive=exclusive,
            scaling_stat=first.stat or ScalingStat.ATK,
            extra_terms=tuple(
                ScalingTerm(part.stat or ScalingStat.ATK, _value(part.index, param, entry))
                for part in rest
            ),
        ),
    ]


def _value(index: str, param: list[float], entry: str) -> float:
    """`param[index - 1]`, refusing an index the list does not reach.

    **Not defaulted to zero.** `param` is padded with real zeroes, so a default is
    indistinguishable from a published value — and a zero multiplier is a real answer meaning
    "this hit does no damage", which is the plausible-wrong-number this repo refuses.
    """
    position = int(index) - 1
    if position < 0 or position >= len(param):
        msg = (
            f"param{index} is past the end of a {len(param)}-long param list, in {entry!r}. "
            f"Defaulting to zero would be a real multiplier for a hit that does no damage."
        )
        raise TalentScalingError(msg)
    return float(param[position])
