import io
import stat
import zipfile

import pytest

from app.exceptions import GitCloneError, InvalidUploadError, UnsupportedLanguageError
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


@pytest.mark.network
def test_git_clone_public_repo(repo):
    ws = repo.from_git("https://github.com/octocat/Hello-World")
    try:
        assert (ws.path / "README").exists()
        assert not (ws.path / ".git").exists()
        assert len(ws.meta.get("commit", "")) == 40
    finally:
        repo.cleanup(ws)


@pytest.mark.network
def test_git_clone_missing_repo(repo):
    with pytest.raises(GitCloneError, match="Could not clone"):
        repo.from_git("https://github.com/octocat/this-repo-does-not-exist-sdp-test")
