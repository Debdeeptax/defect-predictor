"""Trainer — compares candidate models with repeated stratified CV and saves the best.

Evaluation protocol (per level):
  1. Repeated stratified k-fold CV (default 5x5) on the pooled, cleaned dataset.
     Identical splits for every candidate -> paired per-fold scores.
  2. Metrics: accuracy, precision, recall, F1, ROC-AUC (+ PR-AUC, MCC).
  3. Friedman test across candidates; Wilcoxon signed-rank (best vs each, Holm-corrected)
     with Cliff's delta effect size on per-fold ROC-AUC.
  4. Cross-project check for the winner: leave-one-project-family-out.
  5. Winner refit on all data, permutation importance on a hold-out split, saved + registered.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split

from app.ml.data_preprocessor import DataPreprocessor
from app.ml.features import FEATURE_LABELS
from app.ml.ml_model import ALGORITHMS, IMBALANCE_STRATEGIES, MLModel
from app.ml.registry import ModelRegistry

log = logging.getLogger(__name__)

METRICS = ["accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "mcc"]
PRIMARY = "roc_auc"


@dataclass
class TrainingResult:
    level: str
    summary: pd.DataFrame
    fold_scores: pd.DataFrame
    stats: dict[str, Any]
    lopo: pd.DataFrame
    best_key: str
    model_path: Path | None
    metadata: dict[str, Any] = field(default_factory=dict)


def _fold_metrics(y_true, proba, threshold=0.5) -> dict[str, float]:
    pred = (proba >= threshold).astype(int)
    return {
        "accuracy": accuracy_score(y_true, pred),
        "precision": precision_score(y_true, pred, zero_division=0),
        "recall": recall_score(y_true, pred, zero_division=0),
        "f1": f1_score(y_true, pred, zero_division=0),
        "roc_auc": roc_auc_score(y_true, proba),
        "pr_auc": average_precision_score(y_true, proba),
        "mcc": matthews_corrcoef(y_true, pred),
    }


def _run_fold(pipeline, X, y, train_idx, test_idx):
    model = clone(pipeline)
    model.fit(X.iloc[train_idx], y.iloc[train_idx])
    proba = model.predict_proba(X.iloc[test_idx])[:, 1]
    return _fold_metrics(y.iloc[test_idx].to_numpy(), proba), proba


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a), np.asarray(b)
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))


def _cliffs_magnitude(d: float) -> str:
    d = abs(d)
    return "negligible" if d < 0.147 else "small" if d < 0.33 else "medium" if d < 0.474 else "large"


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, running, out = len(items), 0.0, {}
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def project_family(name: str) -> str:
    """'ant-1.7' -> 'ant'; NASA project names are returned unchanged."""
    return re.sub(r"-[\d.]+$", "", name)


class Trainer:
    def __init__(self, level: str, *, model_dir: Path, results_dir: Path,
                 folds: int = 5, repeats: int = 5, random_state: int = 42,
                 n_jobs: int = -1, algorithms: list[str] | None = None,
                 imbalance: list[str] | None = None,
                 progress: Callable[[str], None] | None = None):
        self.level = level
        self.model_dir = Path(model_dir)
        self.results_dir = Path(results_dir) / level
        self.folds, self.repeats = folds, repeats
        self.random_state = random_state
        self.n_jobs = n_jobs
        self.algorithms = algorithms or list(ALGORITHMS)
        self.imbalance = imbalance or list(IMBALANCE_STRATEGIES)
        self.progress = progress or (lambda msg: log.info(msg))
        self.preprocessor = DataPreprocessor(level)

    # ------------------------------------------------------------------ public
    def run(self, raw_dir: Path | None = None, csv_path: Path | None = None,
            save: bool = True, activate: bool = True) -> TrainingResult:
        t0 = time.time()
        if csv_path is not None:
            X, y, groups = self.preprocessor.prepare_uploaded_csv(csv_path)
            source = f"uploaded:{Path(csv_path).name}"
        else:
            X, y, groups = self.preprocessor.prepare_training(raw_dir)
            source = "nasa_mdp_d2" if self.level == "function" else "promise_ck"
        clean = self.preprocessor.report.as_dict()
        self.progress(f"[{self.level}] data: {len(X)} rows, {y.mean():.1%} defective, "
                      f"{len(set(groups))} projects")

        candidates = [MLModel(self.level, a, i, random_state=self.random_state)
                      for a in self.algorithms for i in self.imbalance]
        cv = RepeatedStratifiedKFold(n_splits=self.folds, n_repeats=self.repeats,
                                     random_state=self.random_state)
        splits = list(cv.split(X, y))

        fold_rows, oof = [], {}
        for cand in candidates:
            t = time.time()
            out = Parallel(n_jobs=self.n_jobs)(
                delayed(_run_fold)(cand.pipeline, X, y, tr, te) for tr, te in splits)
            first_repeat = np.zeros(len(y))
            for k, ((scores, proba), (_, te)) in enumerate(zip(out, splits)):
                fold_rows.append({"model": cand.key, "fold": k, **scores})
                if k < self.folds:
                    first_repeat[te] = proba
            oof[cand.key] = first_repeat
            auc = np.mean([s["roc_auc"] for s, _ in out])
            self.progress(f"[{self.level}] {cand.key:<32} AUC={auc:.3f}  ({time.time() - t:.0f}s)")

        fold_scores = pd.DataFrame(fold_rows)
        summary = self._summarise(fold_scores)
        best_key = summary.index[0]
        stat = self._significance(fold_scores, best_key)
        best = next(c for c in candidates if c.key == best_key)
        lopo = self._cross_project(best, X, y, groups)

        model_path, metadata = None, {}
        if save:
            model_path, metadata = self._fit_and_save(
                best, X, y, summary, stat, lopo, clean, source, activate)
        self._write_artifacts(summary, fold_scores, stat, lopo, oof, y, metadata, clean)
        self.progress(f"[{self.level}] best={best_key}  done in {time.time() - t0:.0f}s")
        return TrainingResult(self.level, summary, fold_scores, stat, lopo, best_key,
                              model_path, metadata)

    # ------------------------------------------------------------------ steps
    @staticmethod
    def _summarise(fold_scores: pd.DataFrame) -> pd.DataFrame:
        agg = fold_scores.groupby("model")[METRICS].agg(["mean", "std"])
        agg.columns = [f"{m}_{s}" for m, s in agg.columns]
        return agg.sort_values([f"{PRIMARY}_mean", "f1_mean"], ascending=False)

    @staticmethod
    def _significance(fold_scores: pd.DataFrame, best_key: str) -> dict[str, Any]:
        wide = fold_scores.pivot(index="fold", columns="model", values=PRIMARY)
        result: dict[str, Any] = {"metric": PRIMARY, "best": best_key, "n_folds": len(wide)}
        if wide.shape[1] >= 3:
            chi2, p = stats.friedmanchisquare(*[wide[c] for c in wide.columns])
            result["friedman"] = {"chi2": float(chi2), "p": float(p)}
        raw_p, deltas = {}, {}
        for other in wide.columns:
            if other == best_key:
                continue
            diff = wide[best_key] - wide[other]
            raw_p[other] = 1.0 if np.allclose(diff, 0) else float(
                stats.wilcoxon(wide[best_key], wide[other]).pvalue)
            deltas[other] = cliffs_delta(wide[best_key].to_numpy(), wide[other].to_numpy())
        adj = holm(raw_p) if raw_p else {}
        result["pairwise"] = [
            {"vs": k, "p_raw": raw_p[k], "p_holm": adj[k], "cliffs_delta": deltas[k],
             "effect": _cliffs_magnitude(deltas[k]), "significant": adj[k] < 0.05}
            for k in sorted(raw_p, key=lambda k: adj[k])
        ]
        result["note"] = ("Repeated-CV folds overlap, so p-values are optimistic; "
                          "read alongside effect sizes.")
        return result

    def _cross_project(self, best: MLModel, X, y, groups) -> pd.DataFrame:
        fam = groups.map(project_family).to_numpy()
        jobs = []
        for f in sorted(set(fam)):
            test = fam == f
            if y[test].nunique() < 2 or y[~test].nunique() < 2:
                continue
            jobs.append((f, np.flatnonzero(~test), np.flatnonzero(test)))
        out = Parallel(n_jobs=self.n_jobs)(
            delayed(_run_fold)(best.pipeline, X, y, tr, te) for _, tr, te in jobs)
        rows = [{"test_project": f, "n": len(te), "defect_rate": float(y.iloc[te].mean()),
                 **scores} for (f, _, te), (scores, _) in zip(jobs, out)]
        df = pd.DataFrame(rows)
        if not df.empty:
            self.progress(f"[{self.level}] cross-project (LOPO) mean AUC="
                          f"{df['roc_auc'].mean():.3f} over {len(df)} projects")
        return df

    def _fit_and_save(self, best: MLModel, X, y, summary, stat, lopo, clean, source, activate):
        # Permutation importance on a held-out split (unbiased), then refit on everything.
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y,
                                              random_state=self.random_state)
        probe = MLModel(self.level, best.algorithm, best.imbalance,
                        random_state=self.random_state)
        probe.pipeline = MLModel.build_pipeline(best.algorithm, best.imbalance,
                                                self.random_state, n_jobs=-1)
        probe.fit(Xtr, ytr)
        pi = permutation_importance(probe.pipeline, Xte, yte, scoring="roc_auc",
                                    n_repeats=10, random_state=self.random_state, n_jobs=-1)
        importance = sorted(
            ({"feature": f, "label": FEATURE_LABELS.get(f, f),
              "importance": float(m), "std": float(s)}
             for f, m, s in zip(X.columns, pi.importances_mean, pi.importances_std)),
            key=lambda d: d["importance"], reverse=True)

        final = MLModel(self.level, best.algorithm, best.imbalance,
                        random_state=self.random_state)
        final.pipeline = MLModel.build_pipeline(best.algorithm, best.imbalance,
                                                self.random_state, n_jobs=-1)
        final.fit(X, y)
        # Background sample kept with the model for SHAP / explanations at inference.
        background = X.sample(min(200, len(X)), random_state=self.random_state)

        registry = ModelRegistry(self.model_dir)
        version = registry.next_version(self.level)
        row = summary.loc[best.key]
        cv_metrics = {m: {"mean": float(row[f"{m}_mean"]), "std": float(row[f"{m}_std"])}
                      for m in METRICS}
        extra = {
            "display_name": best.display_name,
            "dataset": source,
            "n_samples": int(len(X)),
            "positive_rate": float(y.mean()),
            "cv": {"folds": self.folds, "repeats": self.repeats, "metrics": cv_metrics},
            "cross_project_auc": float(lopo["roc_auc"].mean()) if not lopo.empty else None,
            "significance": stat,
            "feature_importance": importance,
            "cleaning": clean,
            "background": background.round(6).to_dict(orient="list"),
        }
        path = final.save(self.model_dir, version, extra)
        registry.register(final.metadata, activate=activate)
        self.progress(f"[{self.level}] saved {path.name} (v{version}, active={activate})")
        return path, final.metadata

    # ------------------------------------------------------------------ outputs
    def _write_artifacts(self, summary, fold_scores, stat, lopo, oof, y, metadata, clean):
        d = self.results_dir
        d.mkdir(parents=True, exist_ok=True)
        summary.round(4).to_csv(d / "cv_summary.csv")
        fold_scores.round(5).to_csv(d / "cv_fold_scores.csv", index=False)
        if not lopo.empty:
            lopo.round(4).to_csv(d / "cross_project.csv", index=False)
        (d / "significance.json").write_text(json.dumps(stat, indent=2), encoding="utf-8")
        (d / "cleaning.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
        self._plots(summary, oof, y, metadata, d)

    def _plots(self, summary, oof, y, metadata, d: Path) -> None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 5))
        for key, proba in oof.items():
            fpr, tpr, _ = roc_curve(y, proba)
            ax.plot(fpr, tpr, lw=1.4,
                    label=f"{key} (AUC={roc_auc_score(y, proba):.3f})")
        ax.plot([0, 1], [0, 1], "--", color="grey", lw=0.8)
        ax.set(xlabel="False positive rate", ylabel="True positive rate",
               title=f"ROC — {self.level} level (out-of-fold, repeat 1)")
        ax.legend(fontsize=7, loc="lower right")
        fig.tight_layout()
        fig.savefig(d / "roc_curves.png", dpi=150)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 4))
        x = np.arange(len(summary))
        w = 0.4
        ax.bar(x - w / 2, summary["roc_auc_mean"], w, yerr=summary["roc_auc_std"],
               label="ROC-AUC", capsize=3)
        ax.bar(x + w / 2, summary["f1_mean"], w, yerr=summary["f1_std"], label="F1", capsize=3)
        ax.set_xticks(x, summary.index, rotation=30, ha="right", fontsize=8)
        ax.set_ylim(0, 1)
        ax.set_title(f"CV performance — {self.level} level (mean ± std)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(d / "model_comparison.png", dpi=150)
        plt.close(fig)

        imp = metadata.get("feature_importance")
        if imp:
            top = imp[:12][::-1]
            fig, ax = plt.subplots(figsize=(6, 4.5))
            ax.barh([t["label"] for t in top], [t["importance"] for t in top],
                    xerr=[t["std"] for t in top], capsize=2)
            ax.set_xlabel("Permutation importance (Δ ROC-AUC)")
            ax.set_title(f"Feature importance — {metadata.get('display_name', '')}", fontsize=9)
            fig.tight_layout()
            fig.savefig(d / "feature_importance.png", dpi=150)
            plt.close(fig)
