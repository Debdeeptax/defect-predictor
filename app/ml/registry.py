"""File-based model registry (models/registry.json).

Tracks every saved model version per level and which one is active. The Flask app
(Phase 5) mirrors this into the `model_versions` table; this file remains the
portable source so CLI training works without the web app.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.ml.features import LEVELS
from app.ml.ml_model import MLModel, ModelNotAvailableError

_LOCK = threading.Lock()
REGISTRY_EXCLUDED_KEYS = {"background"}


class ModelRegistry:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.path = self.model_dir / "registry.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {lvl: {"active": None, "versions": []} for lvl in LEVELS}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for lvl in LEVELS:
            data.setdefault(lvl, {"active": None, "versions": []})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def next_version(self, level: str) -> int:
        versions = self._read()[level]["versions"]
        return max((v["version"] for v in versions), default=0) + 1

    def register(self, metadata: dict[str, Any], activate: bool = True) -> None:
        # Bulky fields live only inside the .joblib artifact.
        metadata = {k: v for k, v in metadata.items() if k not in REGISTRY_EXCLUDED_KEYS}
        with _LOCK:
            data = self._read()
            entry = data[metadata["level"]]
            entry["versions"] = [v for v in entry["versions"] if v["file"] != metadata["file"]]
            entry["versions"].append(metadata)
            if activate or entry["active"] is None:
                entry["active"] = metadata["file"]
            self._write(data)

    def activate(self, level: str, file: str) -> None:
        with _LOCK:
            data = self._read()
            if not any(v["file"] == file for v in data[level]["versions"]):
                raise ModelNotAvailableError(f"No {level} model version {file!r}")
            data[level]["active"] = file
            self._write(data)

    def list_versions(self, level: str) -> list[dict[str, Any]]:
        return sorted(self._read()[level]["versions"], key=lambda v: v["version"], reverse=True)

    def active_file(self, level: str) -> str | None:
        return self._read()[level]["active"]

    def load_active(self, level: str) -> MLModel:
        file = self.active_file(level)
        if not file:
            raise ModelNotAvailableError(
                f"No active {level}-level model. Train one (scripts/train.py) or upload via Admin.")
        return MLModel.load(self.model_dir / file)
