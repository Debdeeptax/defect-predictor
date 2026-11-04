"""Partial metrics for non-Python languages via lizard (CC, LOC) + token Halstead approximation.
No class-level OO metrics are produced for these languages."""
from __future__ import annotations

import re

import lizard

from app.metrics.halstead import c_family_halstead, strip_c_comments
from app.metrics.python_metrics import FunctionUnit
from app.ml.features import complete_function_features

_DECISION = re.compile(r"\b(if|for|while|case|catch|foreach)\b|&&|\|\||\?(?!\?|\.)")


def _line_classes(original: list[str], stripped: list[str], start: int, end: int):
    exe = comments = blank = both = 0
    for ln in range(start, end + 1):
        o = original[ln - 1] if ln - 1 < len(original) else ""
        s = stripped[ln - 1] if ln - 1 < len(stripped) else ""
        if not o.strip():
            blank += 1
        elif not s.strip():
            comments += 1
        elif s.strip() != o.strip():
            both += 1
        else:
            exe += 1
    return {"loc_total": float(end - start + 1), "loc_executable": float(exe),
            "loc_comments": float(comments), "loc_blank": float(blank),
            "loc_code_and_comment": float(both)}


def analyse_with_lizard(source: str, rel_path: str) -> tuple[list[FunctionUnit], dict[str, float]]:
    info = lizard.analyze_file.analyze_source_code(rel_path, source)
    original = source.splitlines()
    stripped_src = strip_c_comments(source)
    stripped = stripped_src.splitlines()

    units: list[FunctionUnit] = []
    for fn in info.function_list:
        start, end = fn.start_line, fn.end_line
        body = "\n".join(original[start - 1:end])
        cc = max(1, int(fn.cyclomatic_complexity))
        base = {**_line_classes(original, stripped, start, end), **c_family_halstead(body),
                "cyclomatic_complexity": float(cc), "branch_count": float(2 * cc - 1)}
        units.append(FunctionUnit(fn.name.split("::")[-1], fn.name, start, end,
                                  complete_function_features(base)))

    n = max(1, len(original))
    if not units and stripped_src.strip():
        cc = 1 + len(_DECISION.findall(stripped_src))
        base = {**_line_classes(original, stripped, 1, n), **c_family_halstead(source),
                "cyclomatic_complexity": float(cc), "branch_count": float(2 * cc - 1)}
        units.append(FunctionUnit("<module>", "<module>", 1, n, complete_function_features(base)))

    totals = _line_classes(original, stripped, 1, n)
    totals["maintainability_index"] = None
    return units, totals
