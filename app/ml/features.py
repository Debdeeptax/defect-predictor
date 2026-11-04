"""Canonical feature specification shared by training (ml) and extraction (metrics).

Keeping a single source of truth guarantees that the features a model is trained on
are exactly the features the MetricExtractor produces at inference time.
"""
from __future__ import annotations

import math
from typing import Mapping

FUNCTION_LEVEL = "function"
CLASS_LEVEL = "class"
LEVELS = (FUNCTION_LEVEL, CLASS_LEVEL)

# ---------------------------------------------------------------------------
# Function level (NASA MDP)
# ---------------------------------------------------------------------------
# Base metrics that the extractor measures directly.
FUNCTION_BASE_FEATURES = [
    "loc_total",
    "loc_executable",
    "loc_comments",
    "loc_blank",
    "loc_code_and_comment",
    "cyclomatic_complexity",
    "branch_count",
    "halstead_n1",  # distinct operators
    "halstead_n2",  # distinct operands
    "halstead_N1",  # total operators
    "halstead_N2",  # total operands
]
# Halstead measures derived from (n1, n2, N1, N2) — recomputed identically for training
# and inference so both sides use the same formulas.
HALSTEAD_DERIVED_FEATURES = [
    "halstead_length",
    "halstead_volume",
    "halstead_difficulty",
    "halstead_effort",
    "halstead_level",
    "halstead_content",
    "halstead_error_est",
    "halstead_prog_time",
]
FUNCTION_FEATURES = FUNCTION_BASE_FEATURES + HALSTEAD_DERIVED_FEATURES

# NASA MDP column -> canonical name. ESSENTIAL_COMPLEXITY and DESIGN_COMPLEXITY are
# intentionally excluded (not reliably extractable from arbitrary source).
NASA_COLUMN_MAP = {
    "LOC_TOTAL": "loc_total",
    "LOC_EXECUTABLE": "loc_executable",
    "LOC_COMMENTS": "loc_comments",
    "LOC_BLANK": "loc_blank",
    "LOC_CODE_AND_COMMENT": "loc_code_and_comment",
    "CYCLOMATIC_COMPLEXITY": "cyclomatic_complexity",
    "BRANCH_COUNT": "branch_count",
    "NUM_UNIQUE_OPERATORS": "halstead_n1",
    "NUM_UNIQUE_OPERANDS": "halstead_n2",
    "NUM_OPERATORS": "halstead_N1",
    "NUM_OPERANDS": "halstead_N2",
}
NASA_LABEL = "Defective"

# ---------------------------------------------------------------------------
# Class level (PROMISE CK, Jureczko & Madeyski)
# ---------------------------------------------------------------------------
CLASS_FEATURES = ["wmc", "dit", "noc", "cbo", "rfc", "lcom", "loc", "max_cc", "avg_cc",
                  # Added after the Phase 2 cleaning experiment (+0.02 AUC), all extractable
                  # from Python AST: efferent coupling, public methods, avg method size,
                  # Henderson-Sellers LCOM.
                  "ce", "npm", "amc", "lcom3"]
PROMISE_LABEL = "bug"
# Releases whose labelled defect rate exceeds this are treated as mislabelled and
# excluded (xalan-2.7, log4j-1.2, xerces-1.4.4, poi-2.5 in PROMISE).
MAX_PROJECT_DEFECT_RATE = 0.75

FEATURES_BY_LEVEL = {FUNCTION_LEVEL: FUNCTION_FEATURES, CLASS_LEVEL: CLASS_FEATURES}

# Human-readable names for reports.
FEATURE_LABELS = {
    "loc_total": "Total LOC",
    "loc_executable": "Executable LOC",
    "loc_comments": "Comment lines",
    "loc_blank": "Blank lines",
    "loc_code_and_comment": "Code+comment lines",
    "cyclomatic_complexity": "Cyclomatic complexity v(g)",
    "branch_count": "Branch count",
    "halstead_n1": "Distinct operators (n1)",
    "halstead_n2": "Distinct operands (n2)",
    "halstead_N1": "Total operators (N1)",
    "halstead_N2": "Total operands (N2)",
    "halstead_length": "Halstead length (N)",
    "halstead_volume": "Halstead volume (V)",
    "halstead_difficulty": "Halstead difficulty (D)",
    "halstead_effort": "Halstead effort (E)",
    "halstead_level": "Halstead level (L)",
    "halstead_content": "Halstead content (I)",
    "halstead_error_est": "Halstead error estimate (B)",
    "halstead_prog_time": "Halstead programming time (T)",
    "wmc": "Weighted methods per class (WMC)",
    "dit": "Depth of inheritance (DIT)",
    "noc": "Number of children (NOC)",
    "cbo": "Coupling between objects (CBO)",
    "rfc": "Response for class (RFC)",
    "lcom": "Lack of cohesion (LCOM)",
    "loc": "Class LOC",
    "max_cc": "Max method complexity",
    "avg_cc": "Avg method complexity",
    "ce": "Efferent coupling (Ce)",
    "npm": "Public methods (NPM)",
    "amc": "Avg method size (AMC)",
    "lcom3": "Cohesion LCOM3 (Henderson-Sellers)",
}


def halstead_derived(n1: float, n2: float, N1: float, N2: float) -> dict[str, float]:
    """Standard Halstead formulas (as used by McCabe IQ / NASA MDP and radon)."""
    n1, n2, N1, N2 = (max(0.0, float(x)) for x in (n1, n2, N1, N2))
    vocabulary = n1 + n2
    length = N1 + N2
    volume = length * math.log2(vocabulary) if vocabulary > 1 else 0.0
    difficulty = (n1 / 2.0) * (N2 / n2) if n2 > 0 else 0.0
    effort = difficulty * volume
    level = 1.0 / difficulty if difficulty > 0 else 0.0
    content = volume / difficulty if difficulty > 0 else 0.0
    return {
        "halstead_length": length,
        "halstead_volume": volume,
        "halstead_difficulty": difficulty,
        "halstead_effort": effort,
        "halstead_level": level,
        "halstead_content": content,
        "halstead_error_est": volume / 3000.0,
        "halstead_prog_time": effort / 18.0,
    }


def complete_function_features(base: Mapping[str, float]) -> dict[str, float]:
    """Given base function metrics, return the full ordered FUNCTION_FEATURES dict."""
    out = {k: float(base.get(k, 0.0) or 0.0) for k in FUNCTION_BASE_FEATURES}
    out.update(halstead_derived(out["halstead_n1"], out["halstead_n2"],
                                out["halstead_N1"], out["halstead_N2"]))
    return {k: out[k] for k in FUNCTION_FEATURES}
