import os
import subprocess

import pytest

from dewey import fs as fsmod
from dewey import paths


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path.resolve())
    return tmp_path.resolve()


@pytest.fixture
def col(data_root):
    c = data_root / "personal"
    c.mkdir()
    return c


# ---------- fs_read ----------

def test_read_returns_content_and_token(col):
    (col / "hello.md").write_text("contents")
    result = fsmod.fs_read("personal", "hello.md")
    assert result["content"] == "contents"
    assert len(result["version_token"]) == 16


def test_read_offset_skips_lines(col):
    (col / "lines.md").write_text("a\nb\nc\nd\n")
    result = fsmod.fs_read("personal", "lines.md", offset=2)
    assert result["content"] == "c\nd\n"


def test_read_limit_truncates(col):
    (col / "lines.md").write_text("a\nb\nc\nd\n")
    result = fsmod.fs_read("personal", "lines.md", limit=2)
    assert result["content"] == "a\nb\n"


def test_read_caps_at_max_bytes(col, monkeypatch):
    monkeypatch.setattr(fsmod, "MAX_READ_BYTES", 10)
    (col / "big.md").write_text("x" * 100)
    result = fsmod.fs_read("personal", "big.md")
    assert "[TRUNCATED at 10 bytes]" in result["content"]


def test_read_missing_file_raises(col):
    with pytest.raises(FileNotFoundError):
        fsmod.fs_read("personal", "nope.md")


def test_read_rejects_traversal(col):
    with pytest.raises(ValueError, match="outside collection root"):
        fsmod.fs_read("personal", "../escape")


# ---------- fs_write ----------

def test_write_creates_new_file(col):
    result = fsmod.fs_write("personal", "new.md", "hello")
    assert (col / "new.md").read_text() == "hello"
    assert result["bytes_written"] == 5
    assert len(result["version_token"]) == 16


def test_write_creates_parent_dirs(col):
    fsmod.fs_write("personal", "a/b/c/deep.md", "x")
    assert (col / "a/b/c/deep.md").read_text() == "x"


def test_write_without_token_fails_if_exists(col):
    (col / "f.md").write_text("orig")
    with pytest.raises(FileExistsError):
        fsmod.fs_write("personal", "f.md", "new")


def test_write_with_correct_token_replaces(col):
    (col / "f.md").write_text("orig")
    token = paths.version_token(col / "f.md")
    result = fsmod.fs_write("personal", "f.md", "new", version_token=token)
    assert (col / "f.md").read_text() == "new"
    assert result["version_token"] != token


def test_write_with_stale_token_rejected(col):
    (col / "f.md").write_text("orig")
    with pytest.raises(ValueError, match="version_token mismatch"):
        fsmod.fs_write("personal", "f.md", "new", version_token="deadbeef00000000")


def test_write_into_dir_path_rejected(col):
    (col / "subdir").mkdir()
    with pytest.raises(IsADirectoryError):
        fsmod.fs_write("personal", "subdir", "x")


# ---------- fs_edit ----------

def test_edit_single_replacement(col):
    (col / "f.md").write_text("foo bar baz")
    result = fsmod.fs_edit("personal", "f.md", "bar", "BAR")
    assert (col / "f.md").read_text() == "foo BAR baz"
    assert result["replacements"] == 1


def test_edit_missing_string_raises(col):
    (col / "f.md").write_text("foo bar baz")
    with pytest.raises(ValueError, match="not found"):
        fsmod.fs_edit("personal", "f.md", "qux", "X")


def test_edit_ambiguous_without_replace_all_raises(col):
    (col / "f.md").write_text("foo foo foo")
    with pytest.raises(ValueError, match="found 3 times"):
        fsmod.fs_edit("personal", "f.md", "foo", "X")


def test_edit_replace_all(col):
    (col / "f.md").write_text("foo foo foo")
    result = fsmod.fs_edit("personal", "f.md", "foo", "X", replace_all=True)
    assert (col / "f.md").read_text() == "X X X"
    assert result["replacements"] == 3


# ---------- fs_append ----------

def test_append_creates_file(col):
    fsmod.fs_append("personal", "log.md", "line1\n")
    assert (col / "log.md").read_text() == "line1\n"


def test_append_to_existing(col):
    (col / "log.md").write_text("line1\n")
    result = fsmod.fs_append("personal", "log.md", "line2\n")
    assert (col / "log.md").read_text() == "line1\nline2\n"
    assert result["bytes_appended"] == len("line2\n".encode())


# ---------- fs_stat ----------

def test_stat_file(col):
    (col / "f.md").write_text("data")
    result = fsmod.fs_stat("personal", "f.md")
    assert result["type"] == "file"
    assert result["size_bytes"] == 4
    assert len(result["version_token"]) == 16


def test_stat_directory(col):
    (col / "d").mkdir()
    result = fsmod.fs_stat("personal", "d")
    assert result["type"] == "dir"


def test_stat_missing_raises(col):
    with pytest.raises(FileNotFoundError):
        fsmod.fs_stat("personal", "nope.md")


# ---------- fs_list ----------

def test_list_shallow(col):
    (col / "a.md").touch()
    (col / "b.md").touch()
    (col / "sub").mkdir()
    result = fsmod.fs_list("personal")
    assert result == ["a.md", "b.md", "sub"]


def test_list_recursive(col):
    (col / "a.md").touch()
    (col / "sub").mkdir()
    (col / "sub/b.md").touch()
    result = fsmod.fs_list("personal", recursive=True)
    assert "a.md" in result
    assert "sub" in result
    assert "sub/b.md" in result


def test_list_caps_at_max_entries(col):
    for i in range(20):
        (col / f"f{i}.md").touch()
    result = fsmod.fs_list("personal", max_entries=5)
    assert len(result) == 5


def test_list_max_entries_clamped_to_module_cap(col, monkeypatch):
    monkeypatch.setattr(fsmod, "MAX_LIST_ENTRIES", 3)
    for i in range(10):
        (col / f"f{i}.md").touch()
    result = fsmod.fs_list("personal", max_entries=999)
    assert len(result) == 3


def test_list_on_file_raises(col):
    (col / "f.md").touch()
    with pytest.raises(NotADirectoryError):
        fsmod.fs_list("personal", "f.md")


# ---------- fs_glob ----------

def test_glob_matches_pattern(col):
    (col / "a.md").touch()
    (col / "b.md").touch()
    (col / "c.txt").touch()
    result = fsmod.fs_glob("personal", "*.md")
    assert sorted(result) == ["a.md", "b.md"]


def test_glob_recursive(col):
    (col / "a.md").touch()
    (col / "sub").mkdir()
    (col / "sub/b.md").touch()
    result = fsmod.fs_glob("personal", "**/*.md")
    assert "a.md" in result
    assert "sub/b.md" in result


# ---------- fs_grep ----------

def test_grep_finds_matches(col):
    (col / "a.md").write_text("hello world\nfoo bar\n")
    (col / "b.md").write_text("nothing here\n")
    result = fsmod.fs_grep("personal", "hello")
    assert "hello world" in result
    assert "a.md" in result


def test_grep_no_matches(col):
    (col / "a.md").write_text("nope\n")
    result = fsmod.fs_grep("personal", "zzz")
    assert "(no matches)" in result


def test_grep_case_insensitive(col):
    (col / "a.md").write_text("Hello\n")
    result = fsmod.fs_grep("personal", "HELLO", case_insensitive=True)
    assert "Hello" in result


def test_grep_glob_filter(col):
    (col / "a.md").write_text("target\n")
    (col / "b.txt").write_text("target\n")
    result = fsmod.fs_grep("personal", "target", glob_pattern="*.md")
    assert "a.md" in result
    assert "b.txt" not in result


def test_grep_pattern_starting_with_dash_not_treated_as_flag(col):
    """The `--` separator before the pattern keeps ripgrep from interpreting flags."""
    (col / "a.md").write_text("--flag-like-content\n")
    result = fsmod.fs_grep("personal", "--flag-like-content")
    assert "--flag-like-content" in result


def test_grep_no_shell_expansion(col):
    """Pattern is passed as an arg array, never via shell — `;` is a literal char."""
    (col / "a.md").write_text("foo;bar\n")
    result = fsmod.fs_grep("personal", "foo;bar")
    assert "foo;bar" in result


# ---------- fs_copy / fs_move ----------

def test_copy_file(col):
    (col / "src.md").write_text("data")
    fsmod.fs_copy("personal", "src.md", "dst.md")
    assert (col / "dst.md").read_text() == "data"
    assert (col / "src.md").exists()


def test_copy_creates_parent_dirs(col):
    (col / "src.md").write_text("data")
    fsmod.fs_copy("personal", "src.md", "new/sub/dst.md")
    assert (col / "new/sub/dst.md").read_text() == "data"


def test_copy_missing_src(col):
    with pytest.raises(FileNotFoundError):
        fsmod.fs_copy("personal", "nope.md", "dst.md")


def test_move_renames(col):
    (col / "src.md").write_text("data")
    fsmod.fs_move("personal", "src.md", "dst.md")
    assert not (col / "src.md").exists()
    assert (col / "dst.md").read_text() == "data"


# ---------- fs_delete ----------

def test_delete_with_correct_token(col):
    (col / "f.md").write_text("bye")
    token = paths.version_token(col / "f.md")
    fsmod.fs_delete("personal", "f.md", version_token=token)
    assert not (col / "f.md").exists()


def test_delete_missing_token_rejected(col):
    (col / "f.md").write_text("bye")
    with pytest.raises(ValueError, match="version_token mismatch"):
        fsmod.fs_delete("personal", "f.md", version_token="deadbeef00000000")


def test_delete_missing_file(col):
    with pytest.raises(FileNotFoundError):
        fsmod.fs_delete("personal", "nope.md", version_token="x")


def test_delete_directory_rejected(col):
    (col / "d").mkdir()
    with pytest.raises(IsADirectoryError):
        fsmod.fs_delete("personal", "d", version_token="x")


# ---------- containment / safety ----------

@pytest.mark.parametrize("op", [
    lambda: fsmod.fs_read("personal", "../../etc/passwd"),
    lambda: fsmod.fs_write("personal", "../escape.md", "x"),
    lambda: fsmod.fs_append("personal", "../escape.md", "x"),
    lambda: fsmod.fs_stat("personal", "../etc"),
    lambda: fsmod.fs_glob("personal", "*", path=".."),
])
def test_all_ops_route_through_paths_resolve(col, op):
    with pytest.raises(ValueError):
        op()


def test_symlink_escape_rejected_through_fs(col, tmp_path):
    """A symlink inside the collection pointing outside DATA_ROOT must be rejected
    by the same containment that guards `paths.resolve()`."""
    outside = tmp_path.parent / "outside_fs"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified")
    (col / "evil").symlink_to(outside)
    with pytest.raises(ValueError, match="outside collection root"):
        fsmod.fs_read("personal", "evil/secret.txt")
