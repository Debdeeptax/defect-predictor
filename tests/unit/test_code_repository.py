import io
import socket
import stat
import subprocess
import zipfile

import pytest

from app.exceptions import GitCloneError, InvalidUploadError, UnsupportedLanguageError
from pathlib import Path

from app.services.code_repository import CodeRepository


@pytest.fixture
def repo(tmp_path):
    return CodeRepository(tmp_path / "ws", max_upload_bytes=50_000, max_repo_bytes=200_000,
                          allowed_git_hosts=["github.com", "gitlab.com"], clone_timeout=60)


def make_zip(entries: dict, symlink: str | None = None) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    buf.seek(0)
    return buf


def test_single_source_file(repo):
    ws = repo.from_upload("../../evil name.py", io.BytesIO(b"def f():\n    return 1\n"))
    files = [p.name for p in ws.path.iterdir()]
    assert files == ["evil_name.py"] and ws.source_type == "file"   # name sanitised


def test_unsupported_single_file(repo):
    with pytest.raises(UnsupportedLanguageError):
        repo.from_upload("notes.txt", io.BytesIO(b"hello"))


@pytest.mark.parametrize("name,data,msg", [
    ("", b"x", "choose a file"),
    ("a.py", b"", "empty"),
    ("a.py", b"x" * 60_000, "larger than"),
], ids=["no-name", "empty", "too-large"])
def test_bad_uploads(repo, name, data, msg):
    with pytest.raises(InvalidUploadError, match=msg):
        repo.from_upload(name, io.BytesIO(data))


def test_zip_extracts_tree(repo):
    ws = repo.from_upload("p.zip", make_zip({"pkg/a.py": "x = 1\n", "pkg/sub/b.js": "let y;"}))
    got = sorted(p.relative_to(ws.path).as_posix() for p in ws.path.rglob("*") if p.is_file())
    assert got == ["pkg/a.py", "pkg/sub/b.js"]


@pytest.mark.parametrize("bad", ["../evil.py", "/abs/evil.py", "C:/evil.py", "a/../../evil.py"])
def test_zip_slip_rejected(repo, tmp_path, bad):
    with pytest.raises(InvalidUploadError, match="Unsafe path"):
        repo.from_upload("p.zip", make_zip({"ok.py": "x=1", bad: "pwned"}))
    assert not (tmp_path / "evil.py").exists()
    assert not any((tmp_path / "ws").rglob("*.py"))  # nothing extracted


def test_zip_symlink_rejected(repo):
    with pytest.raises(InvalidUploadError, match="Symbolic links"):
        repo.from_upload("p.zip", make_zip({"ok.py": "x=1"}, symlink="link.py"))


def test_zip_bomb_rejected(repo):
    big = "0" * 300_000  # compresses to < 50 KB but expands past the 200 KB cap
    with pytest.raises(InvalidUploadError, match="expands to|limit"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.py", big)
        buf.seek(0)
        repo.from_upload("p.zip", buf)


def test_corrupt_zip(repo):
    with pytest.raises(InvalidUploadError, match="corrupt"):
        repo.from_upload("p.zip", io.BytesIO(b"PK\x03\x04garbage"))


@pytest.mark.parametrize("url,msg", [
    ("http://github.com/a/b", "https"),
    ("https://user:tok@github.com/a/b", "Credentials"),
    ("https://evil.com/a/b", "not allowed"),
    ("https://github.com/onlyowner", "must look like"),
    ("https://github.com/a/b?x=1", "must look like"),
    ("ssh://git@github.com/a/b", "https"),
    ("file:///etc", "https"),
])
def test_git_url_validation_rejects(repo, url, msg):
    with pytest.raises(GitCloneError, match=msg):
        repo.validate_git_url(url)


@pytest.mark.parametrize("url", ["https://github.com/owner/repo", "https://github.com/owner/repo.git",
                                 "https://gitlab.com/group/sub/repo"])
def test_git_url_validation_accepts(repo, url):
    assert repo.validate_git_url(url) == url


def test_cleanup_removes_workspace(repo):
    ws = repo.from_upload("a.py", io.BytesIO(b"x = 1\n"))
    repo.cleanup(ws)
    assert not ws.path.parent.exists()


def _github_reachable() -> bool:
    try:
        socket.create_connection(("github.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.fixture
def online():
    if not _github_reachable():
        pytest.skip("github.com unreachable (offline run)")


@pytest.mark.network
def test_git_clone_public_repo(repo, online):
    ws = repo.from_git("https://github.com/octocat/Hello-World")
    try:
        assert (ws.path / "README").exists()
        assert not (ws.path / ".git").exists()
        assert len(ws.meta.get("commit", "")) == 40
    finally:
        repo.cleanup(ws)


@pytest.mark.network
def test_git_clone_missing_repo(repo, online):
    with pytest.raises(GitCloneError, match="Could not clone"):
        repo.from_git("https://github.com/octocat/this-repo-does-not-exist-sdp-test")


# ---------------------------------------------------------------------- git (hermetic)
@pytest.fixture
def fake_git(monkeypatch):
    """Replace `git clone` with a scripted fake; returns a dict to configure behaviour."""
    behaviour = {"mode": "ok", "files": {"src/app.py": b"x = 1\n"}}

    def run(cmd, **kwargs):
        assert cmd[0] == "git" and "clone" in cmd and "--depth" in cmd
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0" and kwargs["timeout"] == 60
        dest = Path(cmd[-1])
        if behaviour["mode"] == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        if behaviour["mode"] == "missing-git":
            raise FileNotFoundError("git")
        if behaviour["mode"] == "fail":
            return subprocess.CompletedProcess(cmd, 128, "", "Cloning...\nfatal: repository not found\n")
        for rel, data in behaviour["files"].items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(data)
        (dest / ".git").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("app.services.code_repository.subprocess.run", run)
    return behaviour


def test_git_clone_success_strips_git_dir(repo, fake_git):
    ws = repo.from_git("https://github.com/owner/repo")
    assert (ws.path / "src" / "app.py").exists() and not (ws.path / ".git").exists()
    assert ws.source_type == "git" and ws.meta == {}   # metadata is best-effort


@pytest.mark.parametrize("mode,msg", [("timeout", "longer than 60 s"),
                                      ("missing-git", "git is not installed"),
                                      ("fail", "repository not found")])
def test_git_clone_failures_clean_up(repo, fake_git, mode, msg):
    fake_git["mode"] = mode
    with pytest.raises(GitCloneError, match=msg):
        repo.from_git("https://github.com/owner/repo")
    assert not any(repo.root.iterdir())   # workspace removed


def test_git_clone_too_large(repo, fake_git):
    fake_git["files"] = {"big.py": b"0" * 250_000}   # cap is 200 KB
    with pytest.raises(GitCloneError, match="limit is"):
        repo.from_git("https://github.com/owner/repo")
    assert not any(repo.root.iterdir())


def test_zip_with_directories_and_encrypted_flag(repo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pkg/", "")
        zf.writestr("pkg/a.py", "x = 1")
    ws = repo.from_upload("d.zip", io.BytesIO(buf.getvalue()))
    assert (ws.path / "pkg" / "a.py").exists()
    raw = bytearray(buf.getvalue())
    # set the "encrypted" general-purpose flag bit in the central directory entries
    idx = raw.find(b"PK\x01\x02")
    while idx != -1:
        raw[idx + 8] |= 0x1
        idx = raw.find(b"PK\x01\x02", idx + 4)
    with pytest.raises(InvalidUploadError, match="Encrypted"):
        repo.from_upload("e.zip", io.BytesIO(bytes(raw)))


def test_cleanup_refuses_paths_outside_root(repo, tmp_path):
    from app.services.code_repository import Workspace
    victim = tmp_path / "victim" / "src"
    victim.mkdir(parents=True)
    repo.cleanup(Workspace("x", victim, "file", "x"))
    assert victim.exists()
