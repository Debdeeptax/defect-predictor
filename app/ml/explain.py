"""Per-prediction explanations: which metrics pushed a unit's defect probability up or down.

Method by model type
--------------------
* Tree ensembles  -> SHAP TreeExplainer. `exact` = exact tree-path-dependent Tree SHAP
                     (~0.5 s/row on the shipped forests); `fast` = Saabas path attribution
                     (~0.5 ms/row, ~72 % top-3 agreement with exact on our models).
* Linear models   -> exact linear SHAP in the scaled feature space: coef * (z - mean(z_bg)).
* Anything else   -> importance-weighted deviation: perm_importance * z (approximation).
All contributions are in model-output units for the *defective* class; > 0 raises risk.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.ml.ml_model import MLModel

log = logging.getLogger(__name__)

EXACT_SHAP = "SHAP (exact)"
FAST_SHAP = "SHAP (fast approx.)"
LINEAR_SHAP = "SHAP (linear)"
IMPORTANCE = "Importance-weighted (approx.)"


class Explainer:
    def __init__(self, model: MLModel):
        self.model = model
        self.features = model.features
        clf = model.estimator
        bg = pd.DataFrame(model.metadata.get("background") or {})
        self._bg_z = model.transform(bg) if not bg.empty else None

        if hasattr(clf, "estimators_") and hasattr(clf, "n_estimators"):
            import shap  # heavy import; only when a tree model is explained
            self.kind = "tree"
            self._tree = shap.TreeExplainer(clf)
        elif hasattr(clf, "coef_"):
            self.kind = "linear"
            self._coef = np.asarray(clf.coef_).ravel()
            self._mean = self._bg_z.mean(axis=0) if self._bg_z is not None else 0.0
        else:
            self.kind = "importance"
            imp = {d["feature"]: d["importance"] for d in model.metadata.get("feature_importance", [])}
            self._imp = np.array([max(imp.get(f, 0.0), 0.0) for f in self.features])
            self._mean = self._bg_z.mean(axis=0) if self._bg_z is not None else 0.0
            self._std = (self._bg_z.std(axis=0) + 1e-9) if self._bg_z is not None else 1.0

    # ------------------------------------------------------------------ api
    def fast(self, X: pd.DataFrame) -> tuple[np.ndarray, str]:
        if len(X) == 0:
            return np.zeros((0, len(self.features))), self.fast_method
        Z = self.model.transform(X)
        if self.kind == "tree":
            sv = self._tree.shap_values(Z, approximate=True, check_additivity=False)
            return self._positive(sv), FAST_SHAP
        return self._non_tree(Z)

    def exact(self, X: pd.DataFrame) -> tuple[np.ndarray, str]:
        if len(X) == 0:
            return np.zeros((0, len(self.features))), self.exact_method
        Z = self.model.transform(X)
        if self.kind == "tree":
            sv = self._tree.shap_values(Z, check_additivity=False)
            return self._positive(sv), EXACT_SHAP
        return self._non_tree(Z)

    @property
    def fast_method(self) -> str:
        return {"tree": FAST_SHAP, "linear": LINEAR_SHAP}.get(self.kind, IMPORTANCE)

    @property
    def exact_method(self) -> str:
        return {"tree": EXACT_SHAP, "linear": LINEAR_SHAP}.get(self.kind, IMPORTANCE)

    @property
    def has_costly_exact(self) -> bool:
        return self.kind == "tree"

    # ------------------------------------------------------------------ helpers
    def _non_tree(self, Z: np.ndarray) -> tuple[np.ndarray, str]:
        if self.kind == "linear":
            return self._coef * (Z - self._mean), LINEAR_SHAP
        return self._imp * (Z - self._mean) / self._std, IMPORTANCE

    @staticmethod
    def _positive(sv) -> np.ndarray:
        arr = np.asarray(sv)
        if isinstance(sv, list):  # older shap: list per class
            arr = np.asarray(sv[1])
        elif arr.ndim == 3:  # (n, features, classes)
            arr = arr[..., 1]
        return arr
