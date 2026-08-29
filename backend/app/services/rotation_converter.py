"""Rewrite the mechanically-translatable parts of a gcsim config into the shape we can read.

Owner ruling (2026-08-29, `DECISIONS.md` §21, OQ-1): **refuse, plus a converter.** Rewrite what
is mechanically translatable first, then refuse whatever is still unexpressible — by line.
"Whatever the four need", the four being the real database configs committed under
`references/gcsim_db/`.

## What it converts, and why each is safe

| from | to | why it is a rewrite and not a guess |
|---|---|---|
| `# …`, `// …` | dropped | comments carry no behaviour |
| `char a;` | gated statement | `while 1` **deadlocks** on an ungated action; see below |
| `char a, b, c;` | three statements | gcsim's own shorthand for three actions in order |
| `char a;` | `if .char.a.ready { char a; }` | see below |

**The `.ready` gate is added, not assumed.** That is a real change to the text, and it is the
same change `rotation_compiler` makes to everything authored here — because `while 1` **deadlocks**
on an ungated action, so an un-gated import would produce a config that hangs rather than one
that runs. A converted rotation therefore behaves exactly like an authored one, which is the
only behaviour this app can honestly claim.

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
_ACTION = re.compile(r"^([a-z_]+)(?::(\d+))?$")


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

    for raw in config.splitlines():
        line = _COMMENT.sub("", raw).strip()
        if not line:
            continue

        if _FOR_LOOP.match(line):
            notes.append(
                f"{raw.strip()!r} became `while 1 {{`. A rotation here is a cycle, and how "
                f"long to run for is stated separately.",
            )
            out.append("while 1 {")
            continue

        expanded = _split_sequence(line)
        if expanded is None:
            out.append(line)
            continue
        if len(expanded) > 1:
            notes.append(f"{raw.strip()!r} became {len(expanded)} steps.")
        out.extend(expanded)

    return "\n".join(out) + "\n", notes


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
            # A parameterised action (`skill[hold=1]`), a function call, anything else. Passed
            # through unconverted so `rotation_parser` refuses it **by name** — a converter
            # that swallowed it would turn a refusal into a silent omission.
            return None
        name, repeat = action.groups()
        call = f"{key} {name}:{repeat};" if repeat else f"{key} {name};"
        statements.append(f"if .{key}.{name}.ready {{ {call} }}")
    return statements
