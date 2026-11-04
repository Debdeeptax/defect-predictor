"""DataPreprocessor — loads, cleans and shapes defect datasets for training and inference."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import FunctionTransformer

from app.ml.features import (
    CLASS_FEATURES,
    CLASS_LEVEL,
    FEATURES_BY_LEVEL,
    FUNCTION_BASE_FEATURES,
    FUNCTION_FEATURES,
    FUNCTION_LEVEL,
    MAX_PROJECT_DEFECT_RATE,
    NASA_COLUMN_MAP,
    NASA_LABEL,
    PROMISE_LABEL,
)

log = logging.getLogger(__name__)

LABEL = "defective"
GROUP = "project"


class DatasetSchemaError(ValueError):
    """Raised when a dataset does not contain the required columns."""


@dataclass
class CleaningReport:
    level: str
    rows_in: int = 0
    dropped_na: int = 0
    dropped_invalid: int = 0
    dropped_duplicates: int = 0
    dropped_conflicts: int = 0
    dropped_projects: list[dict] = field(default_factory=list)
    rows_out: int = 0
    positive_rate: float = 0.0
    projects: list[str] = field(default_factory=list)
    skipped_files: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _log1p_nonneg(x):
    return np.log1p(np.clip(x, 0, None))


def log_transformer() -> FunctionTransformer:
    """Shared skew-reducing transform used inside every model pipeline."""
    return FunctionTransformer(_log1p_nonneg, feature_names_out="one-to-one")


class DataPreprocessor:
    """Turns raw public datasets (or an uploaded CSV) into a clean (X, y, groups) frame."""

    def __init__(self, level: str):
        if level not in FEATURES_BY_LEVEL:
            raise ValueError(f"Unknown level {level!r}")
        self.level = level
        self.features = list(FEATURES_BY_LEVEL[level])
        self.report = CleaningReport(level=level)

    # ------------------------------------------------------------------ loading
    def load_raw_dir(self, raw_dir: Path) -> pd.DataFrame:
        sub = "nasa" if self.level == FUNCTION_LEVEL else "promise"
        files = sorted((Path(raw_dir) / sub).glob("*.csv"))
        if not files:
            raise FileNotFoundError(
                f"No CSVs in {Path(raw_dir) / sub}. Run scripts/download_datasets.py first.")
        frames = []
        for f in files:
            try:
                frames.append(self.normalise(pd.read_csv(f), project=f.stem))
            except DatasetSchemaError as exc:
                log.warning("Skipping %s: %s", f.name, exc)
                self.report.skipped_files.append({"file": f.name, "reason": str(exc)})
        if not frames:
            raise DatasetSchemaError(f"No usable {self.level}-level files in {raw_dir}")
        return pd.concat(frames, ignore_index=True)

    def normalise(self, df: pd.DataFrame, project: str = "uploaded") -> pd.DataFrame:
        """Map a source-specific frame onto canonical feature names + binary label."""
        if self.level == FUNCTION_LEVEL:
            return self._normalise_function(df, project)
        return self._normalise_class(df, project)

    def _normalise_function(self, df: pd.DataFrame, project: str) -> pd.DataFrame:
        looks_nasa = "LOC_TOTAL" in df.columns or NASA_LABEL in df.columns
        if looks_nasa:  # raw NASA format
            missing = sorted(set(NASA_COLUMN_MAP) - set(df.columns))
            if missing:
                raise DatasetSchemaError(f"Missing NASA MDP columns: {missing}")
            out = df.rename(columns=NASA_COLUMN_MAP)[FUNCTION_BASE_FEATURES].copy()
            label = df[NASA_LABEL] if NASA_LABEL in df.columns else df.get("label")
        elif set(FUNCTION_BASE_FEATURES).issubset(df.columns):  # canonical format
            out = df[FUNCTION_BASE_FEATURES].copy()
            label = df.get(LABEL)
        else:
            missing = sorted(set(FUNCTION_BASE_FEATURES) - set(df.columns))
            raise DatasetSchemaError(f"Missing function-level columns: {missing}")
        if label is None:
            raise DatasetSchemaError(f"Missing label column ({NASA_LABEL!r} or {LABEL!r})")
        out = out.apply(pd.to_numeric, errors="coerce")
        out[LABEL] = self._binarise(label)
        out[GROUP] = project
        return out

    def _normalise_class(self, df: pd.DataFrame, project: str) -> pd.DataFrame:
        cols = {c: c.strip().lower() for c in df.columns}
        df = df.rename(columns=cols)
        missing = sorted(set(CLASS_FEATURES) - set(df.columns))
        if missing:
            raise DatasetSchemaError(f"Missing class-level columns: {missing}")
        label_col = PROMISE_LABEL if PROMISE_LABEL in df.columns else LABEL
        if label_col not in df.columns:
            raise DatasetSchemaError(f"Missing label column ({PROMISE_LABEL!r} or {LABEL!r})")
        out = df[CLASS_FEATURES].apply(pd.to_numeric, errors="coerce")
        out[LABEL] = self._binarise(df[label_col])
        out[GROUP] = project
        return out

    @staticmethod
    def _binarise(label: pd.Series) -> pd.Series:
        s = label.astype(str).str.strip().str.lower()
        truthy = s.isin({"y", "yes", "true", "1", "t", "defective"})
        numeric = pd.to_numeric(label, errors="coerce")
        return (truthy | (numeric.fillna(0) > 0)).astype(int)

    # ------------------------------------------------------------------ cleaning
    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        r = self.report
        r.rows_in = len(df)
        base = FUNCTION_BASE_FEATURES if self.level == FUNCTION_LEVEL else CLASS_FEATURES

        before = len(df)
        df = df.dropna(subset=base + [LABEL])
        r.dropped_na = before - len(df)

        before = len(df)
        valid = (df[base] >= 0).all(axis=1)
        if self.level == FUNCTION_LEVEL:
            valid &= df["loc_total"] > 0
            valid &= df["cyclomatic_complexity"] >= 1
        else:
            valid &= df["loc"] > 0
        df = df[valid]
        r.dropped_invalid = before - len(df)

        if self.level == FUNCTION_LEVEL:
            df = self.add_derived(df)

        # Exact duplicates (same features + label) inflate CV scores; keep one.
        before = len(df)
        df = df.drop_duplicates(subset=self.features + [LABEL])
        r.dropped_duplicates = before - len(df)

        # Inconsistent instances: identical metric vectors with contradictory labels are
        # unlearnable noise (Shepperd et al. 2013 remove these for NASA D''). Drop all copies.
        before = len(df)
        n_labels = df.groupby(self.features, dropna=False)[LABEL].transform("nunique")
        df = df[n_labels == 1]
        r.dropped_conflicts = before - len(df)

        # Implausibly labelled releases (class level, multi-project training data only).
        if self.level == CLASS_LEVEL and GROUP in df and df[GROUP].nunique() > 1:
            rates = df.groupby(GROUP)[LABEL].mean()
            bad = rates[rates > MAX_PROJECT_DEFECT_RATE]
            r.dropped_projects = [{"project": p, "defect_rate": round(float(v), 4),
                                   "rows": int((df[GROUP] == p).sum())}
                                  for p, v in bad.sort_values(ascending=False).items()]
            df = df[~df[GROUP].isin(bad.index)]

        r.rows_out = len(df)
        r.positive_rate = float(df[LABEL].mean()) if len(df) else 0.0
        r.projects = sorted(df[GROUP].unique().tolist()) if GROUP in df else []
        log.info("Cleaned %s data: %s", self.level, r.as_dict())
        if r.rows_out == 0:
            raise DatasetSchemaError("No valid rows left after cleaning")
        if df[LABEL].nunique() < 2:
            raise DatasetSchemaError("Dataset needs both defective and clean examples")
        return df.reset_index(drop=True)

    @staticmethod
    def add_derived(df: pd.DataFrame) -> pd.DataFrame:
        """Vectorised twin of features.halstead_derived (kept identical by a unit test)."""
        n1, n2, N1, N2 = (df[c].clip(lower=0).astype(float)
                          for c in ("halstead_n1", "halstead_n2", "halstead_N1", "halstead_N2"))
        vocab = n1 + n2
        length = N1 + N2
        volume = np.where(vocab > 1, length * np.log2(vocab.where(vocab > 1, 2)), 0.0)
        difficulty = np.where(n2 > 0, (n1 / 2.0) * (N2 / n2.where(n2 > 0, 1)), 0.0)
        effort = difficulty * volume
        safe_d = np.where(difficulty > 0, difficulty, 1.0)
        out = df.copy()
        out["halstead_length"] = length
        out["halstead_volume"] = volume
        out["halstead_difficulty"] = difficulty
        out["halstead_effort"] = effort
        out["halstead_level"] = np.where(difficulty > 0, 1.0 / safe_d, 0.0)
        out["halstead_content"] = np.where(difficulty > 0, volume / safe_d, 0.0)
        out["halstead_error_est"] = volume / 3000.0
        out["halstead_prog_time"] = effort / 18.0
        return out

    # ------------------------------------------------------------------ API
    def prepare_training(self, raw_dir: Path) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        df = self.clean(self.load_raw_dir(raw_dir))
        return df[self.features], df[LABEL], df[GROUP]

    def prepare_uploaded_csv(self, path: Path) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        df = pd.read_csv(path)
        df = self.clean(self.normalise(df, project=Path(path).stem))
        return df[self.features], df[LABEL], df[GROUP]

    def prepare_inference(self, rows: list[dict]) -> pd.DataFrame:
        """Order/validate extractor output for model input (no label)."""
        df = pd.DataFrame(rows)
        missing = sorted(set(self.features) - set(df.columns))
        if missing:
            raise DatasetSchemaError(f"Extractor output missing features: {missing}")
        return df[self.features].apply(pd.to_numeric, errors="coerce").fillna(0.0)


__all__ = ["DataPreprocessor", "DatasetSchemaError", "CleaningReport", "LABEL", "GROUP",
           "log_transformer", "FUNCTION_FEATURES", "CLASS_FEATURES", "CLASS_LEVEL"]
