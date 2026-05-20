"""Path resolution and version tokens for dewey.

Single responsibility: resolve a user-supplied path within a collection, rejecting
traversal and symlink escapes. Every fs operation routes through `resolve()` so the
containment guarantee lives in exactly one place.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data")).resolve()

_VALID_COLLECTION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def resolve(collection: str, user_path: str) -> Path:
    """Resolve `user_path` within `collection` under DATA_ROOT.

    Returns the absolute, symlink-resolved path. Rejects:
      - invalid collection names (must match _VALID_COLLECTION)
      - absolute user paths
      - traversal that escapes the collection root
      - symlinks pointing outside the collection root
    """
    if not _VALID_COLLECTION.match(collection):
        raise ValueError(f"Invalid collection name: {collection!r}")
    if os.path.isabs(user_path):
        raise ValueError(f"Absolute paths not allowed: {user_path!r}")

    root = (DATA_ROOT / collection).resolve()
    if not root.is_relative_to(DATA_ROOT):
        raise ValueError(f"Collection escapes data root: {collection!r}")

    resolved = (root / user_path).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"Path outside collection root: {user_path!r}")
    return resolved


def version_token(path: Path) -> str:
    """Opaque version token for optimistic locking. hash(mtime_ns + size).

    Computed from `stat()` fields only — no file read. Returned to clients as an
    opaque string; they echo it back on commit so dewey can detect concurrent changes.
    """
    s = path.stat()
    raw = f"{s.st_mtime_ns}:{s.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
