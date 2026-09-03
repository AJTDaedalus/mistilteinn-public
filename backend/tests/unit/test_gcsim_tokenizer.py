"""Tokenizer over gcsim's config grammar — task 2.1.

The importer this replaces is line-oriented regex, which is the right shape for a subset and
the wrong one for a language. Everything here is measured against the five configs vendored
in `references/gcsim_db/` rather than against a grammar nobody has read.
"""
from __future__ import annotations

import pytest

from app.services.gcsim_tokenizer import TokenKind, tokenize


def kinds(source: str) -> list[TokenKind]:
    return [t.kind for t in tokenize(source)]


def texts(source: str) -> list[str]:
    return [t.text for t in tokenize(source)]


def test_an_action_statement_tokenizes() -> None:
    assert texts("furina skill;") == ["furina", "skill", ";"]


def test_both_comment_syntaxes_are_dropped() -> None:
    """Real configs use `#` and `//` **in the same file** — two of the five vendored do."""
    assert texts("a b; # one\nc d; // two\n") == ["a", "b", ";", "c", "d", ";"]


def test_a_comment_containing_a_url_does_not_reopen_as_a_comment() -> None:
    """`# … https://docs.gcsim.app/…` puts a `//` inside a `#` comment.

    The Mavuika config does exactly this on a `fn` header line. A tokenizer that scanned for
    `//` first would cut the line in the wrong place.
    """
    assert texts("fn f() { # see https://docs.gcsim.app/x\n a b;\n}") == [
        "fn", "f", "(", ")", "{", "a", "b", ";", "}",
    ]


def test_crlf_and_lf_tokenize_identically() -> None:
    """Four of the five vendored configs are CRLF and one is LF, and that is the API's own
    payload rather than an artefact of retrieval."""
    assert texts("a b;\r\nc d;\r\n") == texts("a b;\nc d;\n")


def test_a_hyphen_inside_a_state_path_is_part_of_the_name() -> None:
    """`.flins.status.manifest-flame` is one path, not a subtraction.

    This is the tokenizer's one genuinely ambiguous case: `-` is also the minus operator.
    Getting it wrong turns a status guard into arithmetic on two undefined names.
    """
    assert texts(".flins.status.manifest-flame") == [".flins.status.manifest-flame"]


def test_minus_between_numbers_is_still_an_operator() -> None:
    assert texts("a - b") == ["a", "-", "b"]
    assert texts("1-2") == ["1", "-", "2"]


@pytest.mark.parametrize(
    "op", ["&&", "||", "==", "!=", "<=", ">=", "<", ">", "=", "+", "-", "*", "/", "%", "!"],
)
def test_every_operator_is_one_token(op: str) -> None:
    assert texts(f"a {op} b") == ["a", op, "b"]


def test_a_two_character_operator_is_not_split() -> None:
    """`>=` must not tokenize as `>` then `=`; `.x.energy >= 30` would become an assignment."""
    assert texts(".x.energy >= 30") == [".x.energy", ">=", "30"]


def test_numbers_keep_their_decimals() -> None:
    assert texts("er=1.6;") == ["er", "=", "1.6", ";"]


def test_a_string_keeps_its_spaces_and_loses_its_quotes() -> None:
    token = next(t for t in tokenize('print("Not enough Dew, use N1");')
                 if t.kind is TokenKind.STRING)

    assert token.value == "Not enough Dew, use N1"


def test_bracketed_params_tokenize_as_punctuation() -> None:
    assert texts("skill[hold=1]:2;") == ["skill", "[", "hold", "=", "1", "]", ":", "2", ";"]


def test_every_token_carries_a_position() -> None:
    """Phase 6 underlines diagnostics, and cannot do it without this."""
    second = tokenize("furina skill;")[1]

    assert (second.line, second.column) == (1, 8)


def test_a_token_on_the_third_line_knows_it() -> None:
    assert tokenize("a;\nb;\nc;")[4].line == 3


def test_an_unterminated_string_is_refused_with_its_position() -> None:
    with pytest.raises(ValueError, match="line 1"):
        tokenize('print("oops);')


@pytest.mark.parametrize("source", ["resist=.1", "atk%=.466", "er=.641"])
def test_a_leading_decimal_is_a_number_not_a_path(source: str) -> None:
    """**Found by the corpus, not by these tests.** 34 of 500 real configs write a fraction
    without its leading zero, and the first tokenizer refused all of them: the path rule
    claimed the `.` and then found a digit where it wanted a letter."""
    assert [t.kind for t in tokenize(source)][-1] is TokenKind.NUMBER


def test_every_token_carries_its_source_offsets() -> None:
    """`RawNode` must reproduce the author's **exact** bytes — comments, spacing and line
    endings included — and line/column cannot do that. These are for fidelity; line and
    column are for diagnostics, and the two are not interchangeable."""
    source = "furina  skill;"
    tokens = tokenize(source)

    assert [source[t.start:t.end] for t in tokens] == ["furina", "skill", ";"]
