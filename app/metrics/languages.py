"""Language detection and file filtering."""
from __future__ import annotations

from pathlib import PurePosixPath

PYTHON = "python"

# Extension -> language. Python gets full metrics; the rest go through lizard (partial).
EXTENSIONS = {
    ".py": PYTHON,
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".kt": "kotlin",
    ".swift": "swift",
    ".php": "php",
    ".scala": "scala",
    ".rs": "rust",
}
SUPPORTED_LANGUAGES = sorted(set(EXTENSIONS.values()))

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "venv", ".venv", "env", "node_modules", "build", "dist",
    "__pycache__", "site-packages", ".tox", ".mypy_cache", ".pytest_cache", ".idea",
    ".vscode", "target", "bin", "obj", ".gradle", "vendor", "__MACOSX",
}
IGNORED_SUFFIXES = (".min.js", ".bundle.js", ".pb.go", "_pb2.py")

MAX_FILE_BYTES = 1_000_000  # larger files are almost always generated


def detect_language(path: str) -> str | None:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.name.endswith(IGNORED_SUFFIXES):
        return None
    return EXTENSIONS.get(p.suffix.lower())


def is_ignored(rel_path: str) -> bool:
    parts = PurePosixPath(rel_path.replace("\\", "/")).parts[:-1]
    return any(part in IGNORED_DIRS or part.startswith(".") for part in parts)
