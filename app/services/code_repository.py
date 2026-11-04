"""CodeRepository — materialises a submission (source file, ZIP, or Git URL) into an isolated
workspace directory that the MetricExtractor can walk.

Security measures: secure filenames, zip-slip / absolute-path / symlink rejection,
zip-bomb limits (entry count + total uncompressed size), HTTPS-only Git with a host
allow-list, no credentials in URLs, no interactive prompts, hard clone timeout,
post-clone size cap. Submitted code is only parsed, never executed.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlparse

from werkzeug.utils import secure_filename

from app.exceptions import GitCloneError, InvalidUploadError, UnsupportedLanguageError
from app.metrics.languages import detect_language

log = logging.getLogger(__name__)

MAX_ZIP_ENTRIES = 20_000
_REPO_PATH = re.compile(r"^/[\w.-]+/[\w.-]+(?:/[\w.-]+)*?(?:\.git)?/?$")


@dataclass
class Workspace:
    id: str
    path: Path
    source_type: str  # "file" | "zip" | "git"
    source_name: str
    meta: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class CodeRepository:
    def __init__(self, workspace_root: Path, *, max_upload_bytes: int = 20 * 1024 * 1024,
                 max_repo_bytes: int = 100 * 1024 * 1024,
                 allowed_git_hosts: list[str] | None = None, clone_timeout: int = 60):
        self.root = Path(workspace_root)
        self.max_upload_bytes = max_upload_bytes
        self.max_repo_bytes = max_repo_bytes
        self.allowed_git_hosts = [h.lower() for h in (allowed_git_hosts or ["github.com"])]
        self.clone_timeout = clone_timeout

    @classmethod
    def from_config(cls, cfg) -> "CodeRepository":
        return cls(cfg.WORKSPACE_DIR, max_upload_bytes=cfg.MAX_CONTENT_LENGTH,
                   max_repo_bytes=cfg.MAX_REPO_MB * 1024 * 1024,
                   allowed_git_hosts=cfg.ALLOWED_GIT_HOSTS, clone_timeout=cfg.GIT_CLONE_TIMEOUT_SEC)

    # ------------------------------------------------------------------ workspace
    def _new_workspace(self, source_type: str, source_name: str) -> Workspace:
        ws_id = uuid.uuid4().hex[:12]
        path = self.root / ws_id / "src"
        path.mkdir(parents=True, exist_ok=False)
        return Workspace(ws_id, path, source_type, source_name)

    def cleanup(self, ws: Workspace) -> None:
        target = ws.path.parent
        if target.resolve().parent != self.root.resolve():  # never delete outside root
            log.error("Refusing to delete %s outside workspace root", target)
            return
        shutil.rmtree(target, onerror=_force_remove)

    # ------------------------------------------------------------------ uploads
    def from_upload(self, filename: str, stream: BinaryIO) -> Workspace:
        """A single source file or a .zip archive."""
        name = secure_filename(filename or "")
        if not name:
            raise InvalidUploadError("Please choose a file to upload.")
        data = stream.read(self.max_upload_bytes + 1)
        if len(data) > self.max_upload_bytes:
            raise InvalidUploadError(
                f"File is larger than the {self.max_upload_bytes // (1024 * 1024)} MB limit.")
        if not data:
            raise InvalidUploadError("The uploaded file is empty.")
        if name.lower().endswith(".zip"):
            return self._from_zip_bytes(name, data)
        if detect_language(name) is None:
            raise UnsupportedLanguageError(
                f"'{name}' is not a supported source file. Upload a source file or a .zip archive.")
        ws = self._new_workspace("file", name)
        (ws.path / name).write_bytes(data)
        return ws

    def _from_zip_bytes(self, name: str, data: bytes) -> Workspace:
        import io
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise InvalidUploadError("The ZIP archive is corrupt or not a ZIP file.") from exc
        with zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise InvalidUploadError(f"ZIP has too many entries (> {MAX_ZIP_ENTRIES}).")
            total = sum(i.file_size for i in infos)
            if total > self.max_repo_bytes:
                raise InvalidUploadError(
                    f"ZIP expands to {total // (1024 * 1024)} MB; the limit is "
                    f"{self.max_repo_bytes // (1024 * 1024)} MB.")
            for info in infos:
                _check_zip_member(info)
            ws = self._new_workspace("zip", name)
            try:
                written = 0
                for info in infos:
                    if info.is_dir():
                        continue
                    target = ws.path.joinpath(*PurePosixPath(info.filename.replace("\\", "/")).parts)
                    if ws.path.resolve() not in target.resolve().parents:
                        raise InvalidUploadError(f"Unsafe path in ZIP: {info.filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        while chunk := src.read(1 << 16):
                            written += len(chunk)
                            if written > self.max_repo_bytes:  # lying headers
                                raise InvalidUploadError("ZIP content exceeds the size limit.")
                            dst.write(chunk)
            except Exception:
                self.cleanup(ws)
                raise
        return ws

    # ------------------------------------------------------------------ git
    def validate_git_url(self, url: str) -> str:
        url = (url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise GitCloneError("Only https:// Git URLs are supported.")
        if parsed.username or parsed.password or "@" in parsed.netloc:
            raise GitCloneError("Credentials in Git URLs are not allowed (public repositories only).")
        host = (parsed.hostname or "").lower()
        if host not in self.allowed_git_hosts:
            raise GitCloneError(f"Host '{host}' is not allowed. Allowed: {', '.join(self.allowed_git_hosts)}.")
        if parsed.query or parsed.fragment or not _REPO_PATH.match(parsed.path or ""):
            raise GitCloneError("URL must look like https://host/owner/repository(.git).")
        return url

    def from_git(self, url: str) -> Workspace:
        url = self.validate_git_url(url)
        ws = self._new_workspace("git", url)
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo",
               "GCM_INTERACTIVE": "never", "GIT_LFS_SKIP_SMUDGE": "1"}
        cmd = ["git", "-c", "protocol.file.allow=never", "-c", "core.symlinks=false",
               "-c", "credential.helper=", "clone", "--depth", "1", "--single-branch",
               "--no-tags", "--quiet", "--", url, str(ws.path)]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                  timeout=self.clone_timeout)
        except subprocess.TimeoutExpired as exc:
            self.cleanup(ws)
            raise GitCloneError(f"Cloning took longer than {self.clone_timeout} s and was stopped.") from exc
        except FileNotFoundError as exc:
            self.cleanup(ws)
            raise GitCloneError("git is not installed on the server.") from exc
        if proc.returncode != 0:
            self.cleanup(ws)
            msg = (proc.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
            log.warning("git clone failed for %s: %s", url, proc.stderr)
            raise GitCloneError(f"Could not clone repository: {msg[0][:200]}")

        size = _dir_size(ws.path, exclude={".git"})
        if size > self.max_repo_bytes:
            self.cleanup(ws)
            raise GitCloneError(f"Repository is {size // (1024 * 1024)} MB; the limit is "
                                f"{self.max_repo_bytes // (1024 * 1024)} MB.")
        try:
            from git import Repo
            repo = Repo(ws.path)
            ws.meta = {"commit": repo.head.commit.hexsha, "branch": repo.active_branch.name,
                       "commit_date": repo.head.commit.committed_datetime.isoformat()}
        except Exception as exc:  # metadata is best-effort
            log.info("Could not read git metadata: %s", exc)
        shutil.rmtree(ws.path / ".git", onerror=_force_remove)
        return ws


def _check_zip_member(info: zipfile.ZipInfo) -> None:
    name = info.filename.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in p.parts:
        raise InvalidUploadError(f"Unsafe path in ZIP: {info.filename}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise InvalidUploadError(f"Symbolic links are not allowed in ZIP uploads: {info.filename}")
    if info.flag_bits & 0x1:
        raise InvalidUploadError("Encrypted ZIP archives are not supported.")


def _dir_size(path: Path, exclude: set[str]) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        total += sum((Path(dirpath) / f).stat().st_size for f in filenames
                     if not (Path(dirpath) / f).is_symlink())
    return total


def _force_remove(func, path, _exc):
    """Windows: git object files are read-only; make writable and retry."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass
