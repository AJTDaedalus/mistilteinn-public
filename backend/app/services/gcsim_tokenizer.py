"""Tokens for gcsim's config language.

`DESIGN_rotation_language.md`. The importer this feeds replaces line-oriented regex, which is
the right shape for a subset and the wrong one for a language.

**Everything here was measured against real configs**, not derived from a grammar document:
the 500-config corpus of 2026-09-03 and the five files vendored in `references/gcsim_db/`.
Three of its rules exist because those files break the obvious implementation:

- `#` and `//` both start comments, **in the same file**, and a `#` comment can contain a URL
  whose `//` must not reopen as a second comment.
- Line endings are CRLF in four of the five vendored configs and LF in the fifth, and that is
  the API's own payload rather than an artefact of retrieval.
- A hyphen inside a state path is part of the name — `.flins.status.manifest-flame` — while a
  hyphen anywhere else is subtraction. This is the one genuinely ambiguous character in the
  language and getting it wrong turns a status guard into arithmetic on two undefined names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Operators, **longest first**, so `>=` is never read as `>` then `=`.
#:
#: That mistake turns `.x.energy >= 30` into an assignment, which gcsim would reject and a
#: careless tokenizer would produce silently.
OPERATORS: tuple[str, ...] = (
    "&&", "||", "==", "!=", "<=", ">=",
    "<", ">", "=", "+", "-", "*", "/", "%", "!",
)

PUNCTUATION: frozenset[str] = frozenset("{}()[];,:")

_IDENT_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_BODY = _IDENT_START + "0123456789"
#: A state path may hold hyphens; a bare identifier may not. See the module docstring.
_PATH_BODY = _IDENT_BODY + ".-"


class TokenKind(Enum):
    """What a token is, for the parser to branch on."""

    IDENT = "ident"
    #: A `.a.b.c` reach into the simulation, kept whole.
    PATH = "path"
    NUMBER = "number"
    STRING = "string"
    OPERATOR = "operator"
    PUNCT = "punct"


@dataclass(frozen=True)
class Token:
    """One token, with the position a diagnostic will underline."""

    kind: TokenKind
    text: str
    line: int
    column: int
    #: For a string, its content without the quotes. Otherwise the same as `text`.
    value: str = ""
    #: Absolute offsets into the source, so a `RawNode` can carry the author's **exact**
    #: bytes — comments, spacing and line endings included. Line and column are for
    #: diagnostics; these are for fidelity, and the two are not interchangeable.
    start: int = 0
    end: int = 0

    def __post_init__(self) -> None:
        if not self.value:
            object.__setattr__(self, "value", self.text)


class GcsimSyntaxError(ValueError):
    """Source that cannot be tokenized at all, reported with its position."""


@dataclass
class _Cursor:
    """Position bookkeeping, kept in one place so every scanner below agrees about it."""

    text: str
    i: int = 0
    line: int = 1
    column: int = 1

    def done(self) -> bool:
        return self.i >= len(self.text)

    def at(self, offset: int = 0) -> str:
        j = self.i + offset
        return self.text[j] if j < len(self.text) else ""

    def advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self.at() == "\n":
                self.line, self.column = self.line + 1, 1
            else:
                self.column += 1
            self.i += 1

    def take_while(self, allowed: str) -> str:
        start = self.i
        while not self.done() and self.at() in allowed:
            self.advance()
        return self.text[start:self.i]


def _skip_trivia(cur: _Cursor) -> bool:
    """Consume whitespace or a comment; `True` if anything was consumed.

    **Comments are consumed before anything else looks at the text.** A `#` comment can
    contain a URL whose `//` must not reopen as a second comment — the Mavuika config puts one
    on a `fn` header line — so scanning for `//` first would cut in the wrong place.
    """
    char = cur.at()
    if char in " \t\r\n":
        cur.advance()
        return True
    if char == "#" or cur.text.startswith("//", cur.i):
        while not cur.done() and cur.at() != "\n":
            cur.advance()
        return True
    return False


def _scan_string(cur: _Cursor) -> Token:
    line, column, start = cur.line, cur.column, cur.i
    cur.advance()
    chars: list[str] = []
    while not cur.done() and cur.at() != '"':
        if cur.at() == "\n":
            msg = f"unterminated string starting at line {line} column {column}"
            raise GcsimSyntaxError(msg)
        chars.append(cur.at())
        cur.advance()
    if cur.done():
        msg = f"unterminated string starting at line {line} column {column}"
        raise GcsimSyntaxError(msg)
    cur.advance()
    value = "".join(chars)
    return Token(TokenKind.STRING, f'"{value}"', line, column, value, start, cur.i)


def _scan_word(cur: _Cursor) -> Token | None:
    """A path, an identifier or a number, or `None` if this is not the start of one."""
    line, column, char, start = cur.line, cur.column, cur.at(), cur.i

    # **A leading-decimal number.** `resist=.1` and `atk%=.466` appear in 34 of the 500 corpus
    # configs, so a `.` does not always start a path. Checked first because both begin alike.
    if char == "." and cur.at(1).isdigit():
        cur.advance()
        text = "." + cur.take_while("0123456789")
        return Token(TokenKind.NUMBER, text, line, column, text, start, cur.i)
    if char == "." and cur.at(1) in _IDENT_START:
        cur.advance()
        text = "." + cur.take_while(_PATH_BODY)
        return Token(TokenKind.PATH, text, line, column, text, start, cur.i)
    if char in _IDENT_START:
        text = cur.take_while(_IDENT_BODY)
        return Token(TokenKind.IDENT, text, line, column, text, start, cur.i)
    if char.isdigit():
        text = cur.take_while("0123456789.")
        return Token(TokenKind.NUMBER, text, line, column, text, start, cur.i)
    return None


def tokenize(source: str) -> list[Token]:
    """Every token in `source`, comments and whitespace dropped.

    Raises `GcsimSyntaxError` — a `ValueError` — naming the line and column, because Phase 6's
    diagnostics underline and cannot do it without one.
    """
    cur = _Cursor(source)
    tokens: list[Token] = []

    while not cur.done():
        if _skip_trivia(cur):
            continue
        if cur.at() == '"':
            tokens.append(_scan_string(cur))
            continue
        word = _scan_word(cur)
        if word is not None:
            tokens.append(word)
            continue

        line, column = cur.line, cur.column
        matched = next((op for op in OPERATORS if cur.text.startswith(op, cur.i)), None)
        if matched is not None:
            cur.advance(len(matched))
            tokens.append(
                Token(TokenKind.OPERATOR, matched, line, column, matched,
                      cur.i - len(matched), cur.i),
            )
            continue
        if cur.at() in PUNCTUATION:
            char, start = cur.at(), cur.i
            cur.advance()
            tokens.append(Token(TokenKind.PUNCT, char, line, column, char, start, cur.i))
            continue

        msg = (
            f"line {line} column {column}: {cur.at()!r} is not part of gcsim's config language"
        )
        raise GcsimSyntaxError(msg)

    return tokens
