import numpy as np
import pandas as pd
import pytest

from app.ml.data_preprocessor import DataPreprocessor, DatasetSchemaError, LABEL
from app.ml.features import (
    CLASS_FEATURES,
    FUNCTION_BASE_FEATURES,
    FUNCTION_FEATURES,
    HALSTEAD_DERIVED_FEATURES,
    NASA_COLUMN_MAP,
    complete_function_features,
    halstead_derived,
)
from app.ml.ml_model import MLModel, ModelNotAvailableError
from app.ml.registry import ModelRegistry
from app.ml.trainer import cliffs_delta, holm, project_family


def _function_frame(n=120, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "loc_total": rng.integers(3, 200, n),
        "loc_executable": rng.integers(1, 150, n),
        "loc_comments": rng.integers(0, 30, n),
        "loc_blank": rng.integers(0, 30, n),
        "loc_code_and_comment": rng.integers(0, 5, n),
        "cyclomatic_complexity": rng.integers(1, 25, n),
        "branch_count": rng.integers(0, 40, n),
        "halstead_n1": rng.integers(1, 30, n),
        "halstead_n2": rng.integers(1, 60, n),
        "halstead_N1": rng.integers(1, 300, n),
        "halstead_N2": rng.integers(1, 250, n),
    })
    df[LABEL] = (df["cyclomatic_complexity"] + rng.normal(0, 4, n) > 14).astype(int)
    return df


def test_vectorised_halstead_matches_scalar():
    df = _function_frame(50)
    vec = DataPreprocessor.add_derived(df)
    for _, row in vec.iterrows():
        scalar = halstead_derived(row.halstead_n1, row.halstead_n2, row.halstead_N1, row.halstead_N2)
        for k in HALSTEAD_DERIVED_FEATURES:
            assert row[k] == pytest.approx(scalar[k], rel=1e-9, abs=1e-12)


def test_halstead_edge_cases_are_finite():
    d = halstead_derived(0, 0, 0, 0)
    assert all(np.isfinite(v) and v == 0 for v in d.values())
    full = complete_function_features({"loc_total": 5})
    assert list(full) == FUNCTION_FEATURES


def test_nasa_columns_normalise_and_clean():
    raw = pd.DataFrame({
        "LOC_TOTAL": [10, 0, 10, 20], "LOC_EXECUTABLE": [8, 0, 8, 15], "LOC_COMMENTS": [1, 0, 1, 2],
        "LOC_BLANK": [1, 0, 1, 3], "LOC_CODE_AND_COMMENT": [0, 0, 0, 0],
        "CYCLOMATIC_COMPLEXITY": [2, 1, 2, 5], "BRANCH_COUNT": [2, 0, 2, 8],
        "NUM_UNIQUE_OPERATORS": [5, 0, 5, 9], "NUM_UNIQUE_OPERANDS": [4, 0, 4, 11],
        "NUM_OPERATORS": [12, 0, 12, 40], "NUM_OPERANDS": [9, 0, 9, 30],
        "ESSENTIAL_COMPLEXITY": [1, 1, 1, 3], "Defective": ["N", "N", "N", "Y"],
    })
    pre = DataPreprocessor("function")
    df = pre.clean(pre.normalise(raw, "CM1"))
    assert list(df[LABEL]) == [0, 1]           # zero-LOC row and duplicate removed
    assert pre.report.dropped_invalid == 1
    assert pre.report.dropped_duplicates == 1
    assert set(FUNCTION_FEATURES).issubset(df.columns)


def _class_frame(values, bugs, project="ant-1.7"):
    raw = pd.DataFrame({c: list(values) for c in CLASS_FEATURES})
    raw["bug"] = bugs
    return DataPreprocessor("class").normalise(raw, project)


def test_promise_label_binarised_from_bug_count():
    pre = DataPreprocessor("class")
    df = pre.clean(_class_frame([1, 2, 3], [0, 3, 1]))
    assert list(df[LABEL]) == [0, 1, 1]


def test_conflicting_label_duplicates_are_dropped():
    pre = DataPreprocessor("class")
    df = pre.clean(_class_frame([1, 1, 2, 3], [0, 2, 0, 1]))   # value 1 appears clean AND buggy
    assert sorted(df["wmc"]) == [2, 3]
    assert pre.report.dropped_conflicts == 2


def test_implausibly_labelled_releases_are_dropped():
    good = _class_frame(range(1, 11), [1, 1, 0, 0, 0, 0, 0, 0, 0, 0], "ant-1.7")
    bad = _class_frame(range(11, 21), [1] * 9 + [0], "xalan-2.7")      # 90 % defective
    pre = DataPreprocessor("class")
    df = pre.clean(pd.concat([good, bad], ignore_index=True))
    assert set(df["project"]) == {"ant-1.7"}
    assert pre.report.dropped_projects[0]["project"] == "xalan-2.7"


def test_missing_columns_raise_schema_error():
    pre = DataPreprocessor("class")
    with pytest.raises(DatasetSchemaError):
        pre.normalise(pd.DataFrame({"wmc": [1], "bug": [0]}))


def test_single_class_dataset_rejected():
    df = _function_frame(20)
    df[LABEL] = 0
    pre = DataPreprocessor("function")
    with pytest.raises(DatasetSchemaError):
        pre.clean(pre.normalise(df))


@pytest.mark.parametrize("algo", ["random_forest", "logistic_regression", "mlp"])
@pytest.mark.parametrize("imb", ["smote", "balanced"])
def test_model_fit_save_load_roundtrip(tmp_path, algo, imb):
    pre = DataPreprocessor("function")
    df = pre.clean(pre.normalise(_function_frame(200)))
    X, y = df[FUNCTION_FEATURES], df[LABEL]
    m = MLModel("function", algo, imb).fit(X, y)
    p = m.predict_proba(X)
    assert p.shape == (len(X),) and ((p >= 0) & (p <= 1)).all()
    path = m.save(tmp_path, version=1)
    loaded = MLModel.load(path)
    np.testing.assert_allclose(loaded.predict_proba(X), p)
    assert loaded.metadata["features"] == FUNCTION_FEATURES
    assert loaded.transform(X).shape == (len(X), len(FUNCTION_FEATURES))


def test_load_missing_or_corrupt_model(tmp_path):
    with pytest.raises(ModelNotAvailableError):
        MLModel.load(tmp_path / "nope.joblib")
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a pickle")
    with pytest.raises(ModelNotAvailableError):
        MLModel.load(bad)


def test_registry_versions_and_activation(tmp_path):
    reg = ModelRegistry(tmp_path)
    with pytest.raises(ModelNotAvailableError):
        reg.load_active("function")
    assert reg.next_version("function") == 1
    reg.register({"level": "function", "version": 1, "file": "a.joblib"})
    reg.register({"level": "function", "version": 2, "file": "b.joblib"}, activate=False)
    assert reg.active_file("function") == "a.joblib"
    assert reg.next_version("function") == 3
    reg.activate("function", "b.joblib")
    assert reg.active_file("function") == "b.joblib"
    with pytest.raises(ModelNotAvailableError):
        reg.activate("function", "zzz.joblib")


def test_stats_helpers():
    assert cliffs_delta(np.array([3, 4]), np.array([1, 2])) == 1.0
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03) and adj["b"] >= adj["c"]
    assert project_family("xerces-1.4.4") == "xerces" and project_family("PC1") == "PC1"


def test_load_raw_dir_skips_incompatible_files(tmp_path):
    nasa = tmp_path / "nasa"
    nasa.mkdir()
    good = _function_frame(40).rename(columns={v: k for k, v in NASA_COLUMN_MAP.items()})
    good["Defective"] = good.pop(LABEL).map({1: "Y", 0: "N"})
    good.to_csv(nasa / "GOOD.csv", index=False)
    good.drop(columns=["LOC_BLANK"]).to_csv(nasa / "NOBLANK.csv", index=False)   # like PC2
    pre = DataPreprocessor("function")
    X, y, groups = pre.prepare_training(tmp_path)
    assert set(groups) == {"GOOD"} and len(X) > 0
    assert pre.report.skipped_files[0]["file"] == "NOBLANK.csv"
    with pytest.raises(FileNotFoundError):
        DataPreprocessor("class").load_raw_dir(tmp_path)   # no promise/ folder
