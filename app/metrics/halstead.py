"""Token-based Halstead counting (McCabe IQ / NASA MDP convention).

radon's Halstead only counts arithmetic/boolean operators, which yields values on a
much smaller scale than the NASA training data. Here every token counts:
operators = keywords + punctuation/operator symbols (bracket pairs counted once),
operands  = identifiers + literals.
"""
from __future__ import annotations

import keyword
import re
from collections import Counter
from dataclasses import dataclass, field

CLOSING = {")", "]", "}"}
PY_LITERAL_KEYWORDS = {"True", "False", "None"}
PY_KEYWORDS = set(keyword.kwlist) - PY_LITERAL_KEYWORDS


@dataclass
class HalsteadCounter:
    operators: Counter = field(default_factory=Counter)
    operands: Counter = field(default_factory=Counter)

    def add_operator(self, tok: str) -> None:
        if tok not in CLOSING:
            self.operators[tok] += 1

    def add_operand(self, tok: str) -> None:
        self.operands[tok] += 1

    def base(self) -> dict[str, float]:
        return {
            "halstead_n1": float(len(self.operators)),
            "halstead_n2": float(len(self.operands)),
            "halstead_N1": float(sum(self.operators.values())),
            "halstead_N2": float(sum(self.operands.values())),
        }


# ---------------------------------------------------------------- C-family tokeniser
C_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "default", "break", "continue",
    "return", "goto", "try", "catch", "finally", "throw", "throws", "new", "delete",
    "class", "struct", "union", "enum", "interface", "extends", "implements", "public",
    "private", "protected", "static", "final", "const", "volatile", "virtual", "override",
    "abstract", "void", "int", "long", "short", "char", "float", "double", "bool",
    "boolean", "byte", "unsigned", "signed", "auto", "var", "let", "function", "func",
    "fn", "import", "package", "using", "namespace", "typeof", "instanceof", "sizeof",
    "async", "await", "yield", "in", "of", "is", "as", "def", "val", "fun", "go", "defer",
    "select", "chan", "map", "range", "impl", "trait", "pub", "mut", "match", "where",
    "this", "super", "self", "echo", "foreach", "elif", "lambda", "with", "type",
}
C_LITERALS = {"true", "false", "null", "nil", "None", "undefined", "NULL", "nullptr"}

_C_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/|^\s*#(?!include|define|if|endif|else|pragma)[^\n]*",
                        re.S | re.M)
_C_TOKEN = re.compile(r"""
    (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)
  | (?P<num>\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?[fFlLuU]*\b|\b0[xX][0-9a-fA-F_]+\b)
  | (?P<id>[A-Za-z_$][\w$]*)
  | (?P<op>>>>=|<<=|>>=|===|!==|\.\.\.|->|=>|::|\+\+|--|&&|\|\||<<|>>|[<>!=+\-*/%&|^]=|[^\s\w])
""", re.X)


def strip_c_comments(code: str) -> str:
    # Keep line structure so line numbers stay valid.
    return _C_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), code)


def c_family_halstead(code: str) -> dict[str, float]:
    counter = HalsteadCounter()
    for m in _C_TOKEN.finditer(strip_c_comments(code)):
        kind, tok = m.lastgroup, m.group(0)
        if kind in ("str", "num"):
            counter.add_operand(tok)
        elif kind == "id":
            if tok in C_LITERALS:
                counter.add_operand(tok)
            elif tok in C_KEYWORDS:
                counter.add_operator(tok)
            else:
                counter.add_operand(tok)
        else:
            counter.add_operator(tok)
    return counter.base()
