"""PredictionEngine — scores extracted units with the active models and builds the report payload.

Per-file probability = max over the file's units (function and class level): a file is as
risky as its riskiest unit. The unit that sets the file's probability is its *driver*; its
explanation is computed with exact SHAP (within a time budget), all others with fast SHAP.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.metrics.metric_extractor import ExtractionResult
from app.ml.data_preprocessor import DataPreprocessor
from app.ml.explain import Explainer
from app.ml.features import CLASS_LEVEL, FEATURE_LABELS, FUNCTION_LEVEL
from app.ml.ml_model import MLModel, ModelNotAvailableError
from app.ml.registry import ModelRegistry

log = logging.getLogger(__name__)

RISK_LOW, RISK_MEDIUM, RISK_HIGH = "Low", "Medium", "High"
RISK_ORDER = {RISK_HIGH: 0, RISK_MEDIUM: 1, RISK_LOW: 2}
TOP_K_UNIT = 3
TOP_K_FILE = 5
EXACT_CHUNK = 4


def risk_label(p: float, medium: float, high: float) -> str:
    if p >= high:
        return RISK_HIGH
    if p >= medium:
        return RISK_MEDIUM
    return RISK_LOW


def _top_contributions(contrib: np.ndarray, values: pd.Series, features: list[str], k: int):
    order = np.argsort(-np.abs(contrib))[:k]
    return [{
        "feature": features[i],
        "label": FEATURE_LABELS.get(features[i], features[i]),
        "value": round(float(values.iloc[i]), 3),
        "contribution": round(float(contrib[i]), 4),
        "direction": "increases" if contrib[i] > 0 else "decreases",
    } for i in order if abs(contrib[i]) > 0]


class PredictionEngine:
    def __init__(self, registry: ModelRegistry, *, medium: float = 0.4, high: float = 0.7,
                 exact_budget_sec: float = 15.0):
        if not 0 < medium < high <= 1:
            raise ValueError("Risk thresholds must satisfy 0 < medium < high <= 1")
        self.registry = registry
        self.medium, self.high = medium, high
        self.exact_budget_sec = exact_budget_sec
        self._cache: dict[str, tuple[str, MLModel, Explainer]] = {}

    @classmethod
    def from_config(cls, cfg) -> "PredictionEngine":
        return cls(ModelRegistry(cfg.MODEL_DIR), medium=cfg.RISK_MEDIUM_THRESHOLD,
                   high=cfg.RISK_HIGH_THRESHOLD, exact_budget_sec=cfg.EXACT_SHAP_BUDGET_SEC)

    # ------------------------------------------------------------------ models
    def _model(self, level: str, required: bool) -> tuple[MLModel, Explainer] | None:
        active = self.registry.active_file(level)
        cached = self._cache.get(level)
        if cached and cached[0] == active:
            return cached[1], cached[2]
        try:
            model = self.registry.load_active(level)
        except ModelNotAvailableError:
            if required:
                raise
            log.warning("No active %s-level model; continuing without it", level)
            return None
        explainer = Explainer(model)
        self._cache[level] = (active, model, explainer)
        return model, explainer

    def model_info(self) -> dict[str, Any]:
        info = {}
        for level in (FUNCTION_LEVEL, CLASS_LEVEL):
            loaded = self._model(level, required=False)
            if loaded is None:
                info[level] = None
                continue
            meta = loaded[0].metadata
            info[level] = {"file": meta.get("file"), "version": meta.get("version"),
                           "display_name": meta.get("display_name"),
                           "cv_auc": (meta.get("cv", {}).get("metrics", {})
                                      .get("roc_auc", {}).get("mean"))}
        return info

    # ------------------------------------------------------------------ scoring
    def _score_level(self, level: str, rows: list[dict], required: bool) -> "LevelScores | None":
        if not rows:
            return None
        loaded = self._model(level, required)
        if loaded is None:
            return None
        model, explainer = loaded
        meta = pd.DataFrame(rows)[["file", "unit", "start_line"]]
        X = DataPreprocessor(level).prepare_inference(rows)
        proba = model.predict_proba(X)
        contrib, method = explainer.fast(X)
        df = meta.assign(level=level, probability=proba, row_idx=np.arange(len(meta)))
        return LevelScores(df, X, np.array(contrib, dtype=float), [method] * len(df),
                           explainer, model.features)

    def predict(self, extraction: ExtractionResult) -> dict[str, Any]:
        t0 = time.time()
        fn = self._score_level(FUNCTION_LEVEL, extraction.function_rows(), required=True)
        if fn is None:  # extractor guarantees ≥1 unit per parsed file, but be safe
            raise ModelNotAvailableError("No function-level units to score.")
        cl = self._score_level(CLASS_LEVEL, extraction.class_rows(), required=False)
        levels = {FUNCTION_LEVEL: fn, CLASS_LEVEL: cl}
        units = pd.concat([s.df for s in (fn, cl) if s is not None], ignore_index=True)

        # Driver unit per file: highest probability across both levels.
        drivers = units.loc[units.groupby("file")["probability"].idxmax()]
        drivers = drivers.sort_values("probability", ascending=False)
        n_exact = self._refine_drivers(drivers, levels)

        files_by_path = {f.path: f for f in extraction.files}
        file_entries = []
        for path, fm in files_by_path.items():
            u = units[units["file"] == path]
            if u.empty:
                prob, driver_row = 0.0, None
            else:
                driver_row = drivers[drivers["file"] == path].iloc[0]
                prob = float(driver_row["probability"])
            entry = {
                "path": path,
                "language": fm.language,
                "partial": fm.partial,
                "probability": round(prob, 4),
                "risk": risk_label(prob, self.medium, self.high),
                "function_probability": _max_or_none(u[u["level"] == FUNCTION_LEVEL]),
                "class_probability": _max_or_none(u[u["level"] == CLASS_LEVEL]),
                "metrics": fm.summary,
                "driver": None,
                "top_metrics": [],
                "explanation_method": None,
                "units": [],
            }
            if driver_row is not None:
                lvl = driver_row["level"]
                s = levels[lvl]
                r = int(driver_row["row_idx"])
                entry["driver"] = {"level": lvl, "unit": driver_row["unit"],
                                   "start_line": int(driver_row["start_line"]),
                                   "probability": round(prob, 4)}
                entry["top_metrics"] = s.top(r, TOP_K_FILE)
                entry["explanation_method"] = s.methods[r]
            for lvl, s in levels.items():
                if s is None:
                    continue
                for row in s.df[s.df["file"] == path].itertuples(index=False):
                    r = int(row.row_idx)
                    p = float(row.probability)
                    entry["units"].append({
                        "level": lvl, "unit": row.unit, "start_line": int(row.start_line),
                        "probability": round(p, 4),
                        "risk": risk_label(p, self.medium, self.high),
                        "top_metrics": s.top(r, TOP_K_UNIT),
                        "explanation_method": s.methods[r],
                    })
            entry["units"].sort(key=lambda x: -x["probability"])
            file_entries.append(entry)

        file_entries.sort(key=lambda e: (-e["probability"], e["path"]))
        for rank, e in enumerate(file_entries, 1):
            e["rank"] = rank

        probs = [e["probability"] for e in file_entries]
        counts = {k: sum(1 for e in file_entries if e["risk"] == k)
                  for k in (RISK_HIGH, RISK_MEDIUM, RISK_LOW)}
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "thresholds": {"medium": self.medium, "high": self.high},
            "models": self.model_info(),
            "summary": {
                "files": len(file_entries),
                "units": int(len(units)),
                "function_units": int(len(fn.df)),
                "class_units": int(len(cl.df)) if cl is not None else 0,
                "risk_counts": counts,
                "mean_probability": round(float(np.mean(probs)), 4) if probs else 0.0,
                "max_probability": round(float(max(probs)), 4) if probs else 0.0,
                "languages": extraction.languages,
                "skipped_count": extraction.skipped_count,
                "exact_explanations": n_exact,
                "elapsed_sec": round(time.time() - t0, 2),
            },
            "files": file_entries,
            "skipped": extraction.skipped,
            "warnings": list(extraction.warnings),
        }
        if cl is None and extraction.class_rows():
            payload["warnings"].append("No active class-level model: class metrics were not scored.")
        if any(e["partial"] for e in file_entries):
            payload["warnings"].append(
                "Non-Python files have partial metrics (no OO metrics; Halstead approximated).")
        return payload

    def _refine_drivers(self, drivers: pd.DataFrame, levels: dict) -> int:
        """Replace fast explanations of driver units with exact SHAP, riskiest files first,
        until the time budget is used up."""
        deadline = time.time() + self.exact_budget_sec
        done = 0
        pending = [(r["level"], int(r["row_idx"])) for _, r in drivers.iterrows()]
        while pending and time.time() < deadline:
            chunk, pending = pending[:EXACT_CHUNK], pending[EXACT_CHUNK:]
            for lvl in {c[0] for c in chunk}:
                s: LevelScores = levels[lvl]
                rows = [r for l, r in chunk if l == lvl]
                exact, method = s.explainer.exact(s.X.iloc[rows])
                for i, r in enumerate(rows):
                    s.contrib[r] = exact[i]
                    s.methods[r] = method
                if s.explainer.has_costly_exact:
                    done += len(rows)
        if pending:
            log.info("Exact SHAP budget exhausted; %d driver units keep fast explanations",
                     len(pending))
        return done


@dataclass
class LevelScores:
    df: pd.DataFrame          # file, unit, start_line, level, probability, row_idx
    X: pd.DataFrame           # model input, row-aligned with df
    contrib: np.ndarray       # (n_units, n_features) explanation values
    methods: list[str]        # explanation method per unit
    explainer: Explainer
    features: list[str]

    def __len__(self) -> int:
        return len(self.df)

    def top(self, row: int, k: int) -> list[dict]:
        return _top_contributions(self.contrib[row], self.X.iloc[row], self.features, k)


def _max_or_none(df: pd.DataFrame):
    return round(float(df["probability"].max()), 4) if not df.empty else None
