"""MLModel — wraps a fitted scikit-learn/imbalanced-learn pipeline plus its metadata."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from imblearn.over_sampling import SMOTE, RandomOverSampler
from imblearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from app.ml.data_preprocessor import log_transformer
from app.ml.features import FEATURES_BY_LEVEL

log = logging.getLogger(__name__)

ALGORITHMS = {
    "random_forest": "Random Forest",
    "logistic_regression": "Logistic Regression",
    "mlp": "Neural Network (MLP)",
}
ALGO_SHORT = {"random_forest": "rf", "logistic_regression": "lr", "mlp": "mlp"}
IMBALANCE_STRATEGIES = {
    "smote": "SMOTE (in-fold)",
    # class_weight='balanced' for RF/LR; MLPClassifier has no class weights, so random
    # over-sampling is used as the equivalent re-weighting.
    "balanced": "Class weights (balanced)",
}


class ModelNotAvailableError(RuntimeError):
    """Raised when no usable model artifact can be loaded."""


class MLModel:
    def __init__(self, level: str, algorithm: str, imbalance: str, *,
                 random_state: int = 42, pipeline: Pipeline | None = None,
                 metadata: dict[str, Any] | None = None):
        if algorithm not in ALGORITHMS:
            raise ValueError(f"Unknown algorithm {algorithm!r}")
        if imbalance not in IMBALANCE_STRATEGIES:
            raise ValueError(f"Unknown imbalance strategy {imbalance!r}")
        self.level = level
        self.algorithm = algorithm
        self.imbalance = imbalance
        self.random_state = random_state
        self.features = list(FEATURES_BY_LEVEL[level])
        self.pipeline = pipeline or self.build_pipeline(algorithm, imbalance, random_state)
        self.metadata: dict[str, Any] = metadata or {}

    # ------------------------------------------------------------------ build
    @staticmethod
    def build_pipeline(algorithm: str, imbalance: str, random_state: int = 42,
                       n_jobs: int = 1) -> Pipeline:
        weighted = imbalance == "balanced"
        if algorithm == "random_forest":
            clf = RandomForestClassifier(
                n_estimators=300, min_samples_leaf=2, max_features="sqrt",
                class_weight="balanced" if weighted else None,
                random_state=random_state, n_jobs=n_jobs)
        elif algorithm == "logistic_regression":
            clf = LogisticRegression(
                C=1.0, max_iter=5000, class_weight="balanced" if weighted else None,
                random_state=random_state)
        else:
            clf = MLPClassifier(
                hidden_layer_sizes=(32, 16), alpha=1e-3, learning_rate_init=1e-3,
                max_iter=500, early_stopping=True, n_iter_no_change=15,
                random_state=random_state)

        steps: list[tuple[str, Any]] = [("log", log_transformer()), ("scale", StandardScaler())]
        if imbalance == "smote":
            steps.append(("sampler", SMOTE(k_neighbors=5, random_state=random_state)))
        elif algorithm == "mlp":  # balanced, but MLP lacks class_weight
            steps.append(("sampler", RandomOverSampler(random_state=random_state)))
        steps.append(("clf", clf))
        return Pipeline(steps)

    @property
    def key(self) -> str:
        return f"{self.algorithm}+{self.imbalance}"

    @property
    def display_name(self) -> str:
        return f"{ALGORITHMS[self.algorithm]} / {IMBALANCE_STRATEGIES[self.imbalance]}"

    # ------------------------------------------------------------------ train / predict
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "MLModel":
        self.pipeline.fit(X[self.features], y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Probability of the *defective* class for each row."""
        missing = set(self.features) - set(X.columns)
        if missing:
            raise ValueError(f"Missing features for prediction: {sorted(missing)}")
        return self.pipeline.predict_proba(X[self.features])[:, 1]

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """Input as seen by the final estimator (samplers are skipped at inference)."""
        Z = X[self.features]
        for name, step in self.pipeline.steps[:-1]:
            if name == "sampler":
                continue
            Z = step.transform(Z)
        return np.asarray(Z)

    @property
    def estimator(self):
        return self.pipeline.named_steps["clf"]

    # ------------------------------------------------------------------ persistence
    def save(self, model_dir: Path, version: int, extra: dict[str, Any] | None = None) -> Path:
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        fname = (f"{self.level}_v{version}_{ALGO_SHORT[self.algorithm]}_"
                 f"{self.imbalance}_{ts}.joblib")
        self.metadata.update({
            "level": self.level,
            "version": version,
            "algorithm": self.algorithm,
            "imbalance": self.imbalance,
            "features": self.features,
            "random_state": self.random_state,
            "sklearn_version": sklearn.__version__,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file": fname,
            **(extra or {}),
        })
        path = model_dir / fname
        # compress=3: forests trained on SMOTE-augmented data are large; ~5-10x smaller on disk.
        joblib.dump({"pipeline": self.pipeline, "metadata": self.metadata}, path, compress=3)
        log.info("Saved model %s", path)
        return path

    @classmethod
    def load(cls, path: Path) -> "MLModel":
        path = Path(path)
        if not path.exists():
            raise ModelNotAvailableError(f"Model file not found: {path}")
        try:
            blob = joblib.load(path)
            meta = blob["metadata"]
            clf = blob["pipeline"].steps[-1][1]
            if hasattr(clf, "n_jobs"):
                # Parallel tree voting sums in nondeterministic order (~1e-16 jitter);
                # single-threaded inference makes reports bit-for-bit reproducible.
                clf.n_jobs = 1
            return cls(meta["level"], meta["algorithm"], meta["imbalance"],
                       random_state=meta.get("random_state", 42),
                       pipeline=blob["pipeline"], metadata=meta)
        except ModelNotAvailableError:
            raise
        except Exception as exc:  # corrupt / incompatible artifact
            raise ModelNotAvailableError(f"Could not load model {path.name}: {exc}") from exc
