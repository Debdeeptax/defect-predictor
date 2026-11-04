import json

import pytest

from app.exceptions import ModelNotAvailableError
from app.ml.explain import EXACT_SHAP, FAST_SHAP
from app.ml.registry import ModelRegistry
from app.services.prediction_engine import PredictionEngine, risk_label


@pytest.mark.parametrize("p,label", [(0.0, "Low"), (0.399, "Low"), (0.4, "Medium"),
                                     (0.699, "Medium"), (0.7, "High"), (1.0, "High")])
def test_risk_label_boundaries(p, label):
    assert risk_label(p, 0.4, 0.7) == label


@pytest.mark.parametrize("medium,high", [(0.7, 0.4), (0, 0.5), (0.5, 1.2)])
def test_invalid_thresholds_rejected(tmp_path, medium, high):
    with pytest.raises(ValueError):
        PredictionEngine(ModelRegistry(tmp_path), medium=medium, high=high)


def test_payload_structure_and_invariants(sample_payload):
    files = sample_payload["files"]
    assert len(files) == sample_payload["summary"]["files"] == 8
    assert [f["rank"] for f in files] == list(range(1, len(files) + 1))
    probs = [f["probability"] for f in files]
    assert probs == sorted(probs, reverse=True)
    for f in files:
        assert 0 <= f["probability"] <= 1
        assert f["risk"] in {"Low", "Medium", "High"}
        unit_max = max(u["probability"] for u in f["units"])
        assert f["probability"] == pytest.approx(unit_max)          # file = riskiest unit
        assert f["driver"]["unit"] in {u["unit"] for u in f["units"]}
        assert 1 <= len(f["top_metrics"]) <= 5
        assert all(m["direction"] in {"increases", "decreases"} for m in f["top_metrics"])
    counts = sample_payload["summary"]["risk_counts"]
    assert sum(counts.values()) == len(files)
    json.dumps(sample_payload)  # must be storable as JSON


def test_sample_ranking_is_sensible(sample_payload):
    top = sample_payload["files"][0]
    assert top["path"] == "legacy/report_builder.py" and top["risk"] == "Medium"
    utils = next(f for f in sample_payload["files"] if f["path"] == "inventory/utils.py")
    assert utils["risk"] == "Low"
    models_py = next(f for f in sample_payload["files"] if f["path"] == "inventory/models.py")
    assert models_py["class_probability"] is not None


def test_driver_units_get_exact_shap(sample_payload):
    assert sample_payload["summary"]["exact_explanations"] == len(sample_payload["files"])
    assert {f["explanation_method"] for f in sample_payload["files"]} == {EXACT_SHAP}
    non_driver = [u for f in sample_payload["files"] for u in f["units"]
                  if u["unit"] != f["driver"]["unit"]]
    assert non_driver and {u["explanation_method"] for u in non_driver} == {FAST_SHAP}


def test_predictions_are_deterministic(engine, sample_extraction, sample_payload):
    again = engine.predict(sample_extraction)
    assert [(f["path"], f["probability"]) for f in again["files"]] == \
           [(f["path"], f["probability"]) for f in sample_payload["files"]]


def test_zero_budget_uses_fast_explanations(engine, sample_extraction):
    fast = PredictionEngine(engine.registry, exact_budget_sec=0)
    p = fast.predict(sample_extraction)
    assert p["summary"]["exact_explanations"] == 0
    assert {f["explanation_method"] for f in p["files"]} == {FAST_SHAP}


def test_missing_function_model_raises(tmp_path, sample_extraction):
    with pytest.raises(ModelNotAvailableError):
        PredictionEngine(ModelRegistry(tmp_path)).predict(sample_extraction)


def test_missing_class_model_degrades_gracefully(engine, sample_extraction, monkeypatch):
    reg = engine.registry
    real_active = reg.active_file
    monkeypatch.setattr(reg, "active_file", lambda lvl: None if lvl == "class" else real_active(lvl))
    eng = PredictionEngine(reg, exact_budget_sec=0)
    p = eng.predict(sample_extraction)
    assert all(f["class_probability"] is None for f in p["files"])
    assert p["models"]["class"] is None
    assert any("class-level model" in w for w in p["warnings"])
