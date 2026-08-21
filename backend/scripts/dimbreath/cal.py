"""Parser + evaluator for the TextMap ``{CAL:...}`` formula mini-language.

Grammar (observed across all 54 ``{CAL:}`` values in the pinned EN TextMap)::

    {CAL:<expr>,<scale>,<decimals>}[<literal suffix, e.g. %>]

* ``<expr>`` — arithmetic over numeric literals and the single function
  ``AvatarSkillLevel(<slot>)``; operators ``+ - * /`` and ``*`` precedence.
  ``<slot>`` is an integer skill-slot id (0..N); the level of that slot is the
  per-character investment level substituted at display time.
* ``<scale>`` — observed values ``1`` or ``100``. For the *fraction → percent*
  family (intercepts like ``0.07``/``0.34``, suffix ``%``) it is the ×100 that
  converts the ratio to a percent number. **OPEN:** a few formulas (e.g.
  ``Yanagi …ExtraDamageRatio = 5+lvl*2.25,100``) have an integer-unit intercept
  where a literal ×100 would over-scale — their in-game display has not been
  re-confirmed against a live tooltip (see ``docs/MAP_cal_grammar.md``).
* ``<decimals>`` — decimal places to round the displayed number to.

``AvatarSkillLevel`` is the ONLY function present at this SHA. The client
resolves ``{CAL:}`` live from the player's skill levels — nanoka/hakushin pass
the raw formula through, so there is no pre-resolved per-level table to diff
against; the formula *is* the source value.

Read-only; used by the cartography generators and (later) any importer that
needs to materialise level-scaled values.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# {CAL:...} may appear standalone or embedded in a longer description string;
# the literal display suffix we care about is an immediately-trailing '%'.
_CAL_RE = re.compile(r"\{CAL:(?P<expr>[^,}]+),(?P<scale>[^,}]+),(?P<dec>[^,}]+)\}(?P<suffix>%?)")
_FUNC_RE = re.compile(r"AvatarSkillLevel\(\s*(\d+)\s*\)")


@dataclass(frozen=True)
class Cal:
    expr: str
    scale: float
    decimals: int
    suffix: str  # literal trailing text, e.g. "%" or ""

    @property
    def slots(self) -> set[int]:
        return {int(s) for s in _FUNC_RE.findall(self.expr)}


def parse(value: str) -> Cal | None:
    """Parse a raw ``{CAL:...}`` string. Returns ``None`` if not a CAL value."""
    m = _CAL_RE.search(value)
    if not m:
        return None
    return Cal(
        expr=m.group("expr").strip(),
        scale=float(m.group("scale")),
        decimals=int(m.group("dec")),
        suffix=m.group("suffix"),
    )


def _safe_eval(expr: str) -> float:
    """Evaluate a pure arithmetic expression (literals + - * /) safely."""
    node = ast.parse(expr, mode="eval")
    return _eval_node(node.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    raise ValueError(f"unsupported expression node: {ast.dump(node)}")


def evaluate(cal: Cal, levels: dict[int, int]) -> float:
    """Evaluate a parsed CAL at given per-slot ``levels`` → the scaled, rounded
    numeric value (without the literal suffix).

    ``levels`` maps ``slot -> skill level``. Missing slots raise ``KeyError`` so
    callers are forced to be explicit about which level a vector assumes.
    """
    def repl(m: re.Match[str]) -> str:
        slot = int(m.group(1))
        return str(levels[slot])

    substituted = _FUNC_RE.sub(repl, cal.expr)
    raw = _safe_eval(substituted)
    return round(raw * cal.scale, cal.decimals)


def render(cal: Cal, levels: dict[int, int]) -> str:
    """Evaluate and append the literal suffix, mimicking the displayed string."""
    val = evaluate(cal, levels)
    # Drop a trailing .0 the way an integer-valued tooltip would display.
    if val == int(val):
        val_str = str(int(val))
    else:
        val_str = f"{val:.{cal.decimals}f}".rstrip("0").rstrip(".")
    return f"{val_str}{cal.suffix}"
