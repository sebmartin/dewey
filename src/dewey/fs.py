"""Filesystem tools exposed via MCP.

Every tool routes paths through `paths.resolve()` so containment is enforced in
exactly one place. `inputs/` write protection is provided by POSIX permissions at
deploy time, not by application checks — PermissionError just propagates.

Reads and stats return an opaque `version_token` (hash of mtime_ns + size) that
clients echo back on subsequent writes/deletes for optimistic locking. The token
is the same shape the commit API uses, so extensions and the fs tools agree.
"""

from __future__ import annotations

import shutil
import subprocess

from fastmcp import FastMCP

from dewey.paths import resolve, version_token

fs = FastMCP("dewey")

MAX_READ_BYTES = 1_000_000
MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 500
GREP_TIMEOUT_S = 10


def _cap(content: str, max_bytes: int | None = None) -> str:
    limit = MAX_READ_BYTES if max_bytes is None else max_bytes
    encoded = content.encode()
    if len(encoded) <= limit:
        return content
    truncated = encoded[:limit].decode(errors="replace")
    return f"{truncated}\n\n[TRUNCATED at {limit} bytes]"


@fs.tool
def fs_read(
    collection: str,
    path: str,
    offset: int = 0,
    limit: int | None = None,
) -> dict:
    """Read file contents. `offset` is 0-indexed line skip. Returns content and version_token."""
    p = resolve(collection, path)
    text = p.read_text(errors="replace")
    if offset or limit is not None:
        lines = text.splitlines(keepends=True)
        if offset:
            lines = lines[offset:]
        if limit is not None:
            lines = lines[:limit]
        text = "".join(lines)
    return {"content": _cap(text), "version_token": version_token(p)}


@fs.tool
def fs_write(
    collection: str,
    path: str,
    content: str,
    version_token: str | None = None,
) -> dict:
    """Create or replace a file.

    Omit `version_token` to create a new file (fails if it exists).
    Provide the token returned by a previous read/stat to replace (fails on mismatch).
    """
    from dewey.paths import version_token as _vt  # avoid shadowing param

    p = resolve(collection, path)
    if p.exists() and p.is_dir():
        raise IsADirectoryError(f"{path} is a directory")
    if version_token is None and p.exists():
        raise FileExistsError(f"{path} already exists; provide version_token to replace")
    if version_token is not None and p.exists() and _vt(p) != version_token:
        raise ValueError("version_token mismatch — file changed since last read")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return {"path": path, "version_token": _vt(p), "bytes_written": len(content.encode())}


@fs.tool
def fs_edit(
    collection: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict:
    """Exact-string edit. Fails if `old_string` is missing or ambiguous (unless replace_all)."""
    from dewey.paths import version_token as _vt

    p = resolve(collection, path)
    content = p.read_text()
    count = content.count(old_string)
    if count == 0:
        raise ValueError("old_string not found in file")
    if count > 1 and not replace_all:
        raise ValueError(f"old_string found {count} times; set replace_all=True or add more context")
    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
    p.write_text(new_content)
    return {
        "path": path,
        "replacements": count if replace_all else 1,
        "version_token": _vt(p),
    }


@fs.tool
def fs_append(collection: str, path: str, content: str) -> dict:
    """Append content to a file. Creates the file (and parents) if missing."""
    from dewey.paths import version_token as _vt

    p = resolve(collection, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(content)
    return {"path": path, "bytes_appended": len(content.encode()), "version_token": _vt(p)}


@fs.tool
def fs_stat(collection: str, path: str) -> dict:
    """Return metadata and version_token for a path."""
    p = resolve(collection, path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    s = p.stat()
    if p.is_dir():
        kind = "dir"
    elif p.is_symlink():
        kind = "symlink"
    else:
        kind = "file"
    return {
        "path": path,
        "type": kind,
        "size_bytes": s.st_size,
        "mtime": s.st_mtime,
        "version_token": version_token(p),
    }


@fs.tool
def fs_list(
    collection: str,
    path: str = ".",
    recursive: bool = False,
    max_entries: int = MAX_LIST_ENTRIES,
) -> list[str]:
    """List directory entries as collection-relative paths."""
    root = resolve(collection, ".")
    p = resolve(collection, path)
    if not p.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")
    cap = min(max_entries, MAX_LIST_ENTRIES)
    entries = []
    iterator = p.rglob("*") if recursive else p.iterdir()
    for e in iterator:
        entries.append(str(e.relative_to(root)))
        if len(entries) >= cap:
            break
    return sorted(entries)


@fs.tool
def fs_glob(collection: str, pattern: str, path: str = ".") -> list[str]:
    """Glob within a collection. Returns collection-relative paths, mtime-desc."""
    root = resolve(collection, ".")
    base = resolve(collection, path)
    matches = sorted(base.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
    return [str(e.relative_to(root)) for e in matches]


@fs.tool
def fs_grep(
    collection: str,
    pattern: str,
    path: str = ".",
    glob_pattern: str | None = None,
    case_insensitive: bool = False,
    context: int = 0,
) -> str:
    """ripgrep over collection. Pattern is passed as an arg, never via shell."""
    base = resolve(collection, path)
    args = ["rg", "--no-heading", "--line-number", f"--max-count={MAX_GREP_MATCHES}"]
    if case_insensitive:
        args.append("-i")
    if context:
        args += ["-C", str(context)]
    if glob_pattern:
        args += ["--glob", glob_pattern]
    args += ["--", pattern, str(base)]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=GREP_TIMEOUT_S,
        check=False,
    )
    return _cap(result.stdout or "(no matches)")


@fs.tool
def fs_copy(collection: str, from_path: str, to_path: str) -> dict:
    """Copy a file within a collection."""
    from dewey.paths import version_token as _vt

    src = resolve(collection, from_path)
    dst = resolve(collection, to_path)
    if not src.exists():
        raise FileNotFoundError(f"{from_path} does not exist")
    if src.is_dir():
        raise IsADirectoryError(f"{from_path} is a directory")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {"from": from_path, "to": to_path, "version_token": _vt(dst)}


@fs.tool
def fs_move(collection: str, from_path: str, to_path: str) -> dict:
    """Move or rename within a collection."""
    from dewey.paths import version_token as _vt

    src = resolve(collection, from_path)
    dst = resolve(collection, to_path)
    if not src.exists():
        raise FileNotFoundError(f"{from_path} does not exist")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"from": from_path, "to": to_path, "version_token": _vt(dst)}


@fs.tool
def fs_delete(collection: str, path: str, version_token: str) -> dict:
    """Delete a file. Requires a matching version_token."""
    from dewey.paths import version_token as _vt

    p = resolve(collection, path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if p.is_dir():
        raise IsADirectoryError(f"{path} is a directory")
    if _vt(p) != version_token:
        raise ValueError("version_token mismatch — file changed since last read")
    p.unlink()
    return {"path": path, "deleted": True}
