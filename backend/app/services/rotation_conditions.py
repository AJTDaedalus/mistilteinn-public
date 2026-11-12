"""The conditions a guarded block may carry — one vocabulary for every reader and writer.

`DESIGN_conditional_steps.md` keeps the list short on purpose (readiness, energy, status): a
grammar that accepts what it cannot faithfully re-emit is how a rotation silently becomes a
different one, so anything outside it is refused **by name**.

**This is also a security boundary** (security audit F2). `group_condition` is emitted into a
gcsim config verbatim, and that config runs in whoever compiles it — including another user who
copied a published rotation. A condition that is not exactly one of these shapes could close
the block and append arbitrary gcsim script (`1 { } while 1 { } if 0`), hanging the viewer's
tab or falsifying their numbers. So the importer, the request schema, and the compiler all
check against the pattern defined here, and none of them restates it.

The pattern is deliberately narrow at the character level too: ASCII digits only, spaces or
tabs only, and no `{`, `}`, `;` or newline can appear anywhere in a match.
"""

from __future__ import annotations

import re

#: One condition, without the `if` and the brace around it. Shared verbatim by the importer's
#: block-opening regex, so the two cannot disagree about what a condition is.
CONDITION_PATTERN = (
    r"\.[a-z0-9]+\.[a-z_]+\.ready"
    r"|\.[a-z0-9]+\.energy[ \t]*(?:>=|<=|>|<|==)[ \t]*[0-9]+"
    r"|\.[a-z0-9]+\.status\.[a-z0-9_-]+"
)

_CONDITION = re.compile(rf"(?:{CONDITION_PATTERN})", re.ASCII)


def is_allowed_condition(text: str) -> bool:
    """True when *text* is exactly one condition from the vocabulary, and nothing more."""
    return _CONDITION.fullmatch(text) is not None


def refusal(text: str) -> str:
    """The sentence a refused condition is reported with."""
    return (
        f"{text!r} is not a condition a guarded block can carry. The vocabulary is "
        "`.<char>.<action>.ready`, `.<char>.energy <op> <number>` (op one of >=, <=, >, <, ==) "
        "and `.<char>.status.<name>` — see DESIGN_conditional_steps.md."
    )
