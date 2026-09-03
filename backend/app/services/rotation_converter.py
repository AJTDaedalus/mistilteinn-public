"""Rewrite the mechanically-translatable parts of a gcsim config into the shape we can read.

Owner ruling (2026-08-29, `DECISIONS.md` §21, OQ-1): **refuse, plus a converter.** Rewrite what
is mechanically translatable first, then refuse whatever is still unexpressible — by line.
"Whatever the four need", the four being the real database configs committed under
`references/gcsim_db/`.

## What it converts, and why each is safe

| from | to | why it is a rewrite and not a guess |
|---|---|---|
| `# …`, `// …` | dropped | comments carry no behaviour |
| `char a;` | the statement, verbatim | actions are emitted ungated since 2026-09-01 |
| `char a, b, c;` | three statements | gcsim's own shorthand for three actions in order |
| `char a;` | `char a;` | unchanged — actions are ungated since 2026-09-01 |

**The `.ready` gate is no longer added.** It used to be, on the argument that `while 1`
deadlocks on an ungated action — true, and irrelevant once the compiler stopped emitting
`while 1`. A gate makes gcsim *skip* an action it cannot afford rather than *wait* for it,
which is how `insufficient_energy` came to read 0 for a team plainly starved. A converted
config now says what the author wrote.

## What it refuses, and will keep refusing

Not everything in a community config is a syntax difference. These are **different rotations**,
and rewriting them would be inventing the author's intent:

- **conditionals on anything but `.ready`** — `if !is_even(i) { … }` runs a branch on alternate
  cycles; a model with no cycle index cannot say that;
- **user-defined functions** — `clorinde_combo()`, `mav_dc_cancel(6)`: a named sequence with its
  own body and arguments;
- **action parameters** — `skill[hold=1]`, `charge[final=1]`: a different action, not a
  different spelling of one;
- **`wait`/`delay`, explicit `swap`, `energy every …`** — timing and scenario, which this model
  states elsewhere or not at all.

Measured against the four: **two convert, two are refused** — and the two refused are refused
for the reasons above rather than for anything a bigger converter would fix.
"""

from __future__ import annotations

import re

#: `# …` and `// …`. Applied to whole lines and to trailing text, since the real configs use
#: both, sometimes on the same line as an action.
_COMMENT = re.compile(r"(#|//).*$")

#: `for let i=0; i<4; i=i+1 {` in the several spacings the four configs actually use.
_FOR_LOOP = re.compile(r"^for\s+let\s+\w+\s*=.*?\{$")

#: `nicole burst, skill;` — one character, then a comma-separated action list.
_SEQUENCE = re.compile(r"^([a-z0-9_]+)\s+(.+);$")

#: A single action within a sequence: `attack:6`, `skill`, `charge`.
#: An action inside a comma sequence: a name, an optional `[param=1]` variant, an
#: optional `:n` repeat. The bracket is captured rather than excluded so that a variant
#: survives the split and reaches the parser, which is the half that knows which
#: parameters are real kit variants and refuses the rest by name.
#: A `print(...)` statement, gcsim's debug output.
#:
#: It writes to the log and changes no damage, which makes it a comment with parentheses. It
#: is stripped rather than refused because it was refusing whole *configs*: it trails a real
#: statement often enough (`navia attack:2, dash;    print(.navia.shrapnel);`) that the
#: actions in front of it went down with it.
_PRINT = re.compile(r"\bprint\s*\([^)]*\)\s*;?")

_ACTION = re.compile(r"^([a-z_]+)(\[[^\]]*\])?(?::(\d+))?$")


#: `if .sucrose.burst.ready {` — a branch whose condition this model already understands.
_READY_BRANCH = re.compile(r"^if\s+(\.[a-z0-9]+\.[a-z_]+\.ready)\s*\{$")
_ELSE = re.compile(r"^\}\s*else\s*\{$")
_CLOSE = re.compile(r"^\}$")


#: `for let i=0; i<6; i=i+1 {` — the loop variable and its bound, for resolving a branch that
#: only asks which cycle this is.
_FOR_INDEXED = re.compile(r"^for\s+let\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\d+)\s*;.*\{$")
#: `if is_even(i) {` and `if !is_even(i) {`.
_PARITY = re.compile(r"^if\s+(!?)is_even\(\s*(\w+)\s*\)\s*\{$")


def _unroll_parity(lines: list[str]) -> tuple[list[str], list[str]]:
    """Resolve `if is_even(i)` inside `for let i=0; i<N` by writing the cycles out.

    **Not a runtime condition at all.** `is_even(i)` asks which cycle this is, and inside a
    counted loop that is known before the simulation starts — cycle 0 takes one branch, cycle 1
    the other, and so on to the bound. Writing them out leaves a flat list of steps, which is
    what this model already is.

    From the owner's report (`gcsim.app/db/bgHjR7MP7Fkn`), where one character bursts on odd
    cycles and another on even ones. Refusing that was refusing arithmetic.

    **Only for the loop's own variable, and only when nothing else in the loop needs it.** A
    parity test on some other name is a condition this cannot resolve, and it is left for the
    parser to refuse by name.
    """
    # **The loop is not always the first line.** A config opens with `active <char>;` and any
    # number of `energy` or option statements before it, and looking only at `lines[0]` meant
    # the unroll silently did nothing on every real config — including the one it was written
    # for.
    start = next(
        (i for i, line in enumerate(lines) if _FOR_INDEXED.match(line)),
        None,
    )
    if start is None:
        return lines, []
    header = _FOR_INDEXED.match(lines[start])
    if header is None:  # pragma: no cover — `start` was found by this same match
        return lines, []
    variable, bound = header.group(1), int(header.group(2))
    end = _closes_at(lines, start)
    if end is None:
        return lines, []
    inner = lines[start + 1:end]
    if not any(
        (parity := _PARITY.match(line)) and parity.group(2) == variable for line in inner
    ):
        return lines, []

    prefix, suffix, body = lines[:start], lines[end + 1:], inner
    cycles: list[str] = []
    for index in range(bound):
        resolved = _one_cycle(body, variable, index)
        if resolved is None:
            return lines, []
        cycles.extend(resolved)
    note = (
        f"`is_even({variable})` inside `for {variable} < {bound}` was written out as "
        f"{bound} cycles: which cycle it is, is known before the run."
    )
    return [*prefix, *cycles, *suffix], [note]


def _closes_at(lines: list[str], start: int) -> int | None:
    """Where the block opened at *start* closes, counting nesting. `None` if it never does."""
    depth = 0
    for cursor in range(start, len(lines)):
        line = lines[cursor].strip()
        if line.endswith("{"):
            depth += 1
        if line.startswith("}"):
            depth -= 1
            if depth == 0:
                return cursor
    return None


def _one_cycle(body: list[str], variable: str, index: int) -> list[str] | None:
    """One iteration of a counted loop, with its parity branches resolved. `None` if nested."""
    out: list[str] = []
    cursor = 0
    while cursor < len(body):
        line = body[cursor]
        parity = _PARITY.match(line)
        if parity is None:
            if line.endswith("{"):
                # **Copied through, not given up on.** A block this does not understand — the
                # status guard in the owner's config — is still a block the *parser* will
                # refuse by name. Bailing here meant one unresolvable construct anywhere in the
                # loop threw away the parity resolution too, so a config with both got neither.
                close = _closes_at(body, cursor)
                if close is None:
                    return None
                out.extend(body[cursor:close + 1])
                cursor = close + 1
                continue
            out.append(line)
            cursor += 1
            continue
        if parity.group(2) != variable:
            return None
        taken = (index % 2 == 0) != bool(parity.group(1))
        chosen, alternative, close = _branches(body, cursor + 1)
        if close is None:
            return None
        out.extend(chosen if taken else alternative)
        cursor = close + 1
    return out


def _branches(body: list[str], start: int) -> tuple[list[str], list[str], int | None]:
    """The two sides of an `if … } else { … }`, and where it closes."""
    first, cursor = _until(body, start, _ELSE)
    if cursor is None:
        rest, close = _until(body, start, _CLOSE)
        return rest, [], close
    second, close = _until(body, cursor + 1, _CLOSE)
    return first, second, close


def _reduce_ready_branches(lines: list[str]) -> tuple[list[str], list[str]]:
    """Rewrite `if .x.a.ready { A } else { B }` to a gated step, when B is A without the gate.

    **This is the commonest shape in real community configs, and it was refused.** Reported by
    the owner from `gcsim.app/db/bgHjR7MP7Fkn`:

        if .sucrose.burst.ready {
          sucrose burst, attack, skill, dash;
        } else {
          sucrose attack, skill, dash;
        }

    Read the branches side by side and the `else` is the `if` with the burst taken out. So the
    whole construct *means* "burst if it is ready, then attack, skill, dash" — which is exactly
    what a `.ready`-gated step already is, and exactly what this repo's own compiler emits. The
    model was never missing the expressiveness; the importer was not recognising the shape.

    **Only when the branches actually say that.** If the `else` differs by anything more than
    the gated action, the two sides are genuinely different rotations and this leaves them
    alone for the parser to refuse by name. A branch reduced on a guess would be a rotation the
    author did not write, which is the whole reason imports refuse rather than drop.
    """
    out: list[str] = []
    notes: list[str] = []
    index = 0
    while index < len(lines):
        opened = _READY_BRANCH.match(lines[index])
        if opened is None:
            out.append(lines[index])
            index += 1
            continue

        body, cursor = _until(lines, index + 1, _ELSE)
        if cursor is None:
            out.append(lines[index])
            index += 1
            continue
        alternative, close = _until(lines, cursor + 1, _CLOSE)
        if close is None:
            out.append(lines[index])
            index += 1
            continue

        gate = opened.group(1)
        action = f"{gate.split('.')[1]} {gate.split('.')[2]};"
        if body[:1] == [action] and body[1:] == alternative:
            out.append(f"if {gate} {{ {action} }}")
            out.extend(alternative)
            notes.append(
                f"`if {gate} … else …` became a gated step: the two branches differ only by "
                f"`{action}`, which is what a readiness gate says.",
            )
            index = close + 1
            continue

        # Not that shape. Left whole, for the parser to refuse and name.
        out.extend(lines[index:close + 1])
        index = close + 1
    return out, notes


def _until(
    lines: list[str], start: int, marker: re.Pattern[str],
) -> tuple[list[str], int | None]:
    """The steps from *start* up to *marker*, expanded, and where the marker was.

    `None` when the marker never arrives or a nested block intervenes: a branch containing
    another branch is not the flat shape this reduction is about.
    """
    body: list[str] = []
    for cursor in range(start, len(lines)):
        line = lines[cursor]
        if marker.match(line):
            return body, cursor
        if line.endswith("{"):
            return body, None
        body.extend(_split_sequence(line) or [line])
    return body, None


def convert(config: str) -> tuple[str, list[str]]:
    """Rewrite `config` toward the supported subset.

    Returns `(text, notes)` — the rewritten config and a human-readable list of what was
    changed. **Nothing is dropped silently**: every rewrite is named, so a user can see that
    their `for` became a `while 1` rather than discovering it in a damage number.

    This does **not** decide whether the result is importable. It rewrites what it can and
    hands the text to `rotation_parser`, which refuses anything still unexpressible and names
    the lines. Two functions because they answer different questions: *what can be rewritten*
    and *what is left*.
    """
    notes: list[str] = []
    out: list[str] = []

    for raw in _joined(config.splitlines()):
        line = _COMMENT.sub("", raw).strip()
        if not line:
            continue

        # **Named, not silently dropped**, even though it provably cannot change a number.
        # That rule is what makes the rest of this converter's notes worth reading.
        if _PRINT.search(line):
            line = _PRINT.sub("", line).strip()
            notes.append("gcsim `print(...)` debug output was dropped; it affects no damage.")
            if not line:
                continue

        if _FOR_LOOP.match(line):
            # **Kept verbatim, bound and all.** This used to rewrite the header to `while 1 {`
            # and note that "how long to run for is stated separately" — which was true while
            # `duration=90` stated it, and threw away the one number the author *did* write.
            # `group_repeat` holds it now, so the parser reads the bound off this line and the
            # rotation runs the number of cycles its author asked for.
            out.append(line)
            continue

        expanded = _split_sequence(line)
        if expanded is None:
            out.append(line)
            continue
        if len(expanded) > 1:
            notes.append(f"{raw.strip()!r} became {len(expanded)} steps.")
        out.extend(expanded)

    # **After the line rewrites, not instead of them.** The reduction compares two branches
    # step for step, and a comma sequence is several steps written as one line — so it has to
    # run once both sides have been expanded into the same shape.
    out, parity_notes = _unroll_parity(out)
    notes.extend(parity_notes)
    out, branch_notes = _reduce_ready_branches(out)
    notes.extend(branch_notes)

    # **Each rewrite named once, with a count** — the same rule the refusal list follows, and
    # for the same reason. Unrolling a counted loop copies the lines inside it, so one branch
    # reduction inside `for i < 6` produced six identical notes. A rewrite list that repeats
    # itself is one nobody reads, and these notes exist to be read: they are how a user sees
    # that their `for` became six cycles rather than discovering it in a damage number.
    counted: dict[str, int] = {}
    for note in notes:
        counted[note] = counted.get(note, 0) + 1
    return "\n".join(out) + "\n", [
        note if times == 1 else f"{note} (x{times})"
        for note, times in counted.items()
    ]


def _joined(lines: list[str]) -> list[str]:
    """Rejoin a statement that was written across several lines.

    **A statement ends at `;`, not at a newline**, and the real configs use that — Arlecchino's
    is written

        arle charge,
             attack:6,
             attack:6,
             attack:3;

    for readability. Line-by-line, the converter saw `arle charge,` and then three orphans, and
    refused all four as *"not a statement this model can express"* — a refusal that was true of
    the lines and false of the config.

    Joined on a **trailing comma only**. That is unambiguous: a comma at the end of a line means
    the list continues. Joining on "no semicolon yet" would swallow `for let i=0; i<4; …` and
    every brace line with it.
    """
    out: list[str] = []
    pending = ""
    for raw in lines:
        stripped = _COMMENT.sub("", raw).strip()
        if not stripped:
            if not pending:
                out.append(raw)
            continue
        pending = f"{pending} {stripped}".strip() if pending else stripped
        if pending.endswith(","):
            continue
        out.append(pending)
        pending = ""
    if pending:
        out.append(pending)
    return out


def _split_sequence(line: str) -> list[str] | None:
    """`nicole burst, skill;` → two gated statements, or `None` if this is not a sequence.

    `None` rather than an empty list: "not an action line" and "an action line that produced
    nothing" are different, and the caller passes the first through untouched so `active`,
    `options`, `target` and every stanza survive the pass.
    """
    match = _SEQUENCE.match(line)
    if match is None:
        return None
    key, body = match.groups()

    # An already-gated statement is left exactly as it is. Re-gating would nest, and this is
    # the shape our own compiler emits — a config we produced must round-trip untouched.
    if key in {"if", "while", "for", "active", "options", "target", "energy", "let", "fn"}:
        return None

    statements: list[str] = []
    for part in body.split(","):
        action = _ACTION.match(part.strip())
        if action is None:
            # A function call, a bare expression, anything with no action shape at all. Passed
            # through unconverted so `rotation_parser` refuses it **by name** — a converter
            # that swallowed it would turn a refusal into a silent omission.
            return None
        name, variant, repeat = action.groups()
        # **The variant rides along rather than blocking the split.** Bailing out here refused
        # `razor skill[hold=1], dash, attack, burst;` whole, although `razor skill[hold=1];`
        # imports on its own — `hold` is one of the three variants the model holds. Found by
        # importing 256 real database configs, where this was the largest single cause of a
        # false refusal. The rule the bail-out protected is untouched: an unknown parameter
        # still arrives at the parser intact and is still refused there by name, now on its
        # own line rather than buried in a sequence the reader has to bisect by hand.
        suffix = f":{repeat}" if repeat else ""
        statements.append(f"{key} {name}{variant or ''}{suffix};")
    return statements
