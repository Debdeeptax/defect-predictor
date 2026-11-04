"""MetricExtractor — walks a source tree and produces function- and class-level metrics."""
from __future__ import annotations

import logging
import os
import tokenize
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.exceptions import EmptyRepositoryError, UnsupportedLanguageError
from app.metrics.languages import (
    MAX_FILE_BYTES,
    PYTHON,
    IGNORED_DIRS,
    detect_language,
    is_ignored,
)
from app.metrics.lizard_metrics import analyse_with_lizard
from app.metrics.oo_metrics import compute_oo_metrics
from app.metrics.python_metrics import ClassFacts, analyse_python

log = logging.getLogger(__name__)
MAX_SKIPPED_LISTED = 200


@dataclass
class UnitMetrics:
    kind: str  # "function" | "class"
    name: str
    qualname: str
    start_line: int
    end_line: int
    metrics: dict[str, float]


@dataclass
class FileMetrics:
    path: str  # repo-relative, forward slashes
    language: str
    partial: bool  # True when only lizard-level metrics are available
    totals: dict[str, Any]
    functions: list[UnitMetrics] = field(default_factory=list)
    classes: list[UnitMetrics] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        ccs = [u.metrics["cyclomatic_complexity"] for u in self.functions]
        return {
            "loc": self.totals.get("loc_total", 0),
            "functions": len([u for u in self.functions if u.name != "<module>"]),
            "classes": len(self.classes),
            "max_cc": max(ccs, default=0),
            "avg_cc": round(sum(ccs) / len(ccs), 2) if ccs else 0,
            "halstead_volume": round(sum(u.metrics["halstead_volume"] for u in self.functions), 1),
            "maintainability_index": self.totals.get("maintainability_index"),
        }


@dataclass
class ExtractionResult:
    files: list[FileMetrics]
    skipped: list[dict[str, str]]
    skipped_count: int
    languages: dict[str, int]
    warnings: list[str] = field(default_factory=list)

    def function_rows(self) -> list[dict[str, Any]]:
        return [{"file": f.path, "unit": u.qualname, "start_line": u.start_line, **u.metrics}
                for f in self.files for u in f.functions]

    def class_rows(self) -> list[dict[str, Any]]:
        return [{"file": f.path, "unit": u.qualname, "start_line": u.start_line, **u.metrics}
                for f in self.files for u in f.classes]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricExtractor:
    def __init__(self, max_files: int = 2000, max_file_bytes: int = MAX_FILE_BYTES):
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    # ------------------------------------------------------------------ discovery
    def discover(self, root: Path) -> tuple[list[tuple[Path, str, str]], list[dict], int]:
        root = Path(root)
        found, skipped, skipped_count = [], [], 0

        def skip(rel, reason):
            nonlocal skipped_count
            skipped_count += 1
            if len(skipped) < MAX_SKIPPED_LISTED:
                skipped.append({"path": rel, "reason": reason})

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in IGNORED_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                p = Path(dirpath) / name
                rel = p.relative_to(root).as_posix()
                if p.is_symlink() or is_ignored(rel):
                    continue
                lang = detect_language(rel)
                if lang is None:
                    skip(rel, "unsupported language")
                    continue
                size = p.stat().st_size
                if size == 0:
                    skip(rel, "empty file")
                    continue
                if size > self.max_file_bytes:
                    skip(rel, f"file too large ({size // 1024} KB)")
                    continue
                found.append((p, rel, lang))
        return found, skipped, skipped_count

    # ------------------------------------------------------------------ extraction
    def extract(self, root: Path) -> ExtractionResult:
        root = Path(root)
        if not root.exists():
            raise EmptyRepositoryError("Submission directory does not exist.")
        files, skipped, skipped_count = self.discover(root)
        if not files:
            if skipped_count:
                raise UnsupportedLanguageError(
                    "None of the submitted files are in a supported language "
                    "(Python, Java, C/C++, C#, JavaScript/TypeScript, Go, Kotlin, Swift, "
                    "PHP, Scala, Rust).")
            raise EmptyRepositoryError()

        warnings = []
        if len(files) > self.max_files:
            warnings.append(f"Repository has {len(files)} source files; only the first "
                            f"{self.max_files} were analysed.")
            files = files[: self.max_files]

        results: list[FileMetrics] = []
        all_classes: list[ClassFacts] = []
        for path, rel, lang in files:
            try:
                source = path.read_text(encoding="utf-8-sig", errors="replace")
                fm, classes = self.extract_source(source, rel, lang)
            except (SyntaxError, tokenize.TokenError, ValueError, RecursionError) as exc:
                line = getattr(exc, "lineno", None)
                reason = f"parse error{f' (line {line})' if line else ''}: {type(exc).__name__}"
                log.info("Skipping %s: %s", rel, exc)
                skipped_count += 1
                if len(skipped) < MAX_SKIPPED_LISTED:
                    skipped.append({"path": rel, "reason": reason})
                continue
            results.append(fm)
            all_classes.extend(classes)

        if not results:
            reasons = "; ".join(f"{s['path']}: {s['reason']}" for s in skipped
                                if "parse error" in s["reason"])[:300]
            raise EmptyRepositoryError(f"No submitted file could be parsed ({reasons}).")

        self._attach_oo(results, all_classes)
        langs = Counter(f.language for f in results)
        log.info("Extracted %d files (%s), skipped %d", len(results), dict(langs), skipped_count)
        return ExtractionResult(results, skipped, skipped_count, dict(langs), warnings)

    def extract_source(self, source: str, rel: str, lang: str | None = None
                       ) -> tuple[FileMetrics, list[ClassFacts]]:
        lang = lang or detect_language(rel)
        if lang is None:
            raise UnsupportedLanguageError(f"Unsupported file type: {rel}")
        if lang == PYTHON:
            a = analyse_python(source, rel)
            fm = FileMetrics(rel, lang, False, a.totals,
                             [UnitMetrics("function", u.name, u.qualname, u.start, u.end, u.metrics)
                              for u in a.functions])
            return fm, a.classes
        units, totals = analyse_with_lizard(source, rel)
        fm = FileMetrics(rel, lang, True, totals,
                         [UnitMetrics("function", u.name, u.qualname, u.start, u.end, u.metrics)
                          for u in units])
        return fm, []

    @staticmethod
    def _attach_oo(results: list[FileMetrics], classes: list[ClassFacts]) -> None:
        if not classes:
            return
        oo = compute_oo_metrics(classes)
        by_file = {f.path: f for f in results}
        for c in classes:
            fm = by_file.get(c.file)
            if fm is not None:
                fm.classes.append(UnitMetrics("class", c.name, c.qualname, c.start, c.end,
                                              oo[(c.file, c.qualname)]))
