"""Explanations for every model family an admin can activate (RF, LR, MLP), and the
PredictionEngine running end-to-end on non-tree models."""
import numpy as np
import pandas as pd
import pytest

from app.ml.data_preprocessor import LABEL, DataPreprocessor
from app.ml.explain import EXACT_SHAP, FAST_SHAP, IMPORTANCE, LINEAR_SHAP, Explainer
from app.ml.features import FUNCTION_FEATURES
from app.ml.ml_model import MLModel
from app.ml.registry import ModelRegistry
from app.services.prediction_engine import PredictionEngine


@pytest.fixture(scope="module")
def data():
    rng = np.random.default_rng(1)
    n = 300
    df = pd.DataFrame({
        "loc_total": rng.integers(3, 300, n), "loc_executable": rng.integers(1, 200, n),
        "loc_comments": rng.integers(0, 30, n), "loc_blank": rng.integers(0, 30, n),
        "loc_code_and_comment": rng.integers(0, 5, n),
        "cyclomatic_complexity": rng.integers(1, 30, n), "branch_count": rng.integers(0, 60, n),
        "halstead_n1": rng.integers(1, 30, n), "halstead_n2": rng.integers(1, 60, n),
        "halstead_N1": rng.integers(1, 300, n), "halstead_N2": rng.integers(1, 250, n),
    })
    df[LABEL] = (df["loc_total"] + rng.normal(0, 40, n) > 170).astype(int)
    pre = DataPreprocessor("function")
    clean = pre.clean(pre.normalise(df))
    return clean[FUNCTION_FEATURES], clean[LABEL]


def _model(algo, data):
    X, y = data
    m = MLModel("function", algo, "balanced").fit(X, y)
    m.metadata["background"] = X.sample(50, random_state=0).to_dict(orient="list")
    m.metadata["feature_importance"] = [{"feature": f, "importance": 0.01 * (i + 1)}
                                        for i, f in enumerate(FUNCTION_FEATURES)]
    return m


@pytest.mark.parametrize("algo,kind,fast,exact", [
    ("random_forest", "tree", FAST_SHAP, EXACT_SHAP),
    ("logistic_regression", "linear", LINEAR_SHAP, LINEAR_SHAP),
    ("mlp", "importance", IMPORTANCE, IMPORTANCE),
])
def test_explainer_per_model_family(data, algo, kind, fast, exact):
    X, _ = data
    ex = Explainer(_model(algo, data))
    assert ex.kind == kind
    c_fast, m_fast = ex.fast(X.iloc[:5])
    c_exact, m_exact = ex.exact(X.iloc[:5])
    assert c_fast.shape == c_exact.shape == (5, len(FUNCTION_FEATURES))
    assert (m_fast, m_exact) == (fast, exact)
    assert np.isfinite(c_fast).all() and np.isfinite(c_exact).all()
    assert ex.fast_method == fast and ex.exact_method == exact
    assert ex.has_costly_exact == (kind == "tree")
    empty, _ = ex.fast(X.iloc[:0])
    assert empty.shape == (0, len(FUNCTION_FEATURES))


def test_tree_shap_is_additive(data):
    X, _ = data
    m = _model("random_forest", data)
    ex = Explainer(m)
    contrib, _ = ex.exact(X.iloc[:10])
    base = ex._tree.expected_value
    base = base[1] if np.ndim(base) else base
    np.testing.assert_allclose(contrib.sum(axis=1) + base, m.predict_proba(X.iloc[:10]), atol=1e-6)


def test_linear_contributions_point_the_right_way(data):
    X, _ = data
    m = _model("logistic_regression", data)
    ex = Explainer(m)
    big = X.iloc[[0]].copy()
    big["loc_total"] = 5000
    contrib, _ = ex.fast(big)
    i = FUNCTION_FEATURES.index("loc_total")
    assert contrib[0, i] > 0   # far more LOC than the background -> pushes risk up


@pytest.mark.parametrize("algo", ["logistic_regression", "mlp"])
def test_engine_with_non_tree_active_model(tmp_path, data, sample_extraction, algo):
    m = _model(algo, data)
    path = m.save(tmp_path, version=1)
    reg = ModelRegistry(tmp_path)
    reg.register(m.metadata)
    payload = PredictionEngine(reg).predict(sample_extraction)
    assert payload["models"]["class"] is None            # only a function model registered
    assert payload["summary"]["exact_explanations"] == 0  # nothing costly to refine
    assert all(f["top_metrics"] for f in payload["files"])
    assert path.exists()
