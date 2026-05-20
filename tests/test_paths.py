import os
from pathlib import Path

import pytest

from dewey import paths


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """Override DATA_ROOT to a per-test tmp dir."""
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path.resolve())
    return tmp_path.resolve()


@pytest.fixture
def collection(data_root):
    """Create and return a 'personal' collection directory."""
    col = data_root / "personal"
    col.mkdir()
    return col


# ---------- collection name validation ----------

@pytest.mark.parametrize("name", [
    "a", "personal", "my-col", "my_col", "Photos", "col123", "a" * 64,
])
def test_collection_name_valid(data_root, name):
    (data_root / name).mkdir()
    assert paths.resolve(name, ".") == (data_root / name).resolve()


@pytest.mark.parametrize("name", [
    "",                # empty
    "-col",            # starts with hyphen
    "_col",            # starts with underscore
    ".hidden",         # starts with dot
    "../etc",          # traversal in name
    "my/col",          # slash in name
    "my col",          # space
    "my.col",          # dot
    "a" * 65,          # too long
    "café",            # non-ASCII
])
def test_collection_name_invalid(data_root, name):
    with pytest.raises(ValueError, match="Invalid collection name"):
        paths.resolve(name, ".")


# ---------- user_path: absolute rejection ----------

@pytest.mark.parametrize("user_path", [
    "/etc/passwd",
    "/",
    "/data/personal/foo",
])
def test_absolute_path_rejected(collection, user_path):
    with pytest.raises(ValueError, match="Absolute paths not allowed"):
        paths.resolve("personal", user_path)


# ---------- user_path: traversal rejection ----------

@pytest.mark.parametrize("user_path", [
    "../../etc/passwd",
    "../sibling/file",
    "foo/../../escape",
    "..",
])
def test_traversal_rejected(collection, user_path):
    with pytest.raises(ValueError, match="outside collection root"):
        paths.resolve("personal", user_path)


# ---------- user_path: valid ----------

@pytest.mark.parametrize("user_path,expected_suffix", [
    (".", ""),
    ("", ""),
    ("file.md", "file.md"),
    ("threads/dewey/README.md", "threads/dewey/README.md"),
    ("a/b/../c", "a/c"),  # internal traversal that stays inside
])
def test_valid_paths(collection, user_path, expected_suffix):
    result = paths.resolve("personal", user_path)
    expected = (collection / expected_suffix).resolve() if expected_suffix else collection.resolve()
    assert result == expected


# ---------- symlink escapes ----------

def test_symlink_escape_rejected(data_root, collection, tmp_path):
    """Symlink inside the collection pointing outside DATA_ROOT must be rejected."""
    outside = tmp_path.parent / "outside_target"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified")
    (collection / "evil_link").symlink_to(outside)

    with pytest.raises(ValueError, match="outside collection root"):
        paths.resolve("personal", "evil_link/secret.txt")


def test_symlink_inside_collection_allowed(collection):
    """Symlink pointing to a sibling inside the same collection is fine."""
    (collection / "target.md").write_text("hello")
    (collection / "alias.md").symlink_to(collection / "target.md")

    result = paths.resolve("personal", "alias.md")
    assert result == (collection / "target.md").resolve()


def test_symlink_collection_root_to_outside_rejected(data_root, tmp_path):
    """If the collection 'directory' is itself a symlink to outside DATA_ROOT, reject."""
    outside = tmp_path.parent / "outside_root"
    outside.mkdir()
    (data_root / "evil").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes data root"):
        paths.resolve("evil", "file.md")


# ---------- version_token ----------

def test_version_token_deterministic(collection):
    f = collection / "file.md"
    f.write_text("contents")
    assert paths.version_token(f) == paths.version_token(f)


def test_version_token_format(collection):
    f = collection / "file.md"
    f.write_text("contents")
    token = paths.version_token(f)
    assert len(token) == 16
    assert all(c in "0123456789abcdef" for c in token)


def test_version_token_changes_on_size(collection):
    f = collection / "file.md"
    f.write_text("a")
    t1 = paths.version_token(f)
    f.write_text("ab")
    os.utime(f, (1_700_000_000, 1_700_000_000))  # pin mtime so only size differs
    t2 = paths.version_token(f)
    assert t1 != t2


def test_version_token_changes_on_mtime(collection):
    f = collection / "file.md"
    f.write_text("same")
    os.utime(f, (1_700_000_000, 1_700_000_000))
    t1 = paths.version_token(f)
    os.utime(f, (1_800_000_000, 1_800_000_000))
    t2 = paths.version_token(f)
    assert t1 != t2


def test_version_token_missing_file_raises(collection):
    with pytest.raises(FileNotFoundError):
        paths.version_token(collection / "nope.md")
