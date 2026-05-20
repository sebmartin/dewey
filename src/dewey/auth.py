"""Token loading and bearer-token verification.

The token is a single per-deployment secret: same value for every caller in v1.
It's loaded once at first access and cached for the process lifetime — rotations
require a container restart. Tests reset the cache via the `_TOKEN` module attr.

Two sources, checked in order:
  1. /run/secrets/dewey_token  — Docker secret (production)
  2. DEWEY_TOKEN env var       — local dev / tests
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

_SECRET_FILE = Path("/run/secrets/dewey_token")
_TOKEN: str | None = None


def load_token() -> str:
    """Return the configured token, loading on first call."""
    global _TOKEN
    if _TOKEN is not None:
        return _TOKEN
    if _SECRET_FILE.exists():
        _TOKEN = _SECRET_FILE.read_text().strip()
    else:
        env_token = os.environ.get("DEWEY_TOKEN", "").strip()
        if not env_token:
            raise RuntimeError(
                "No token configured: set DEWEY_TOKEN or mount /run/secrets/dewey_token"
            )
        _TOKEN = env_token
    if not _TOKEN:
        raise RuntimeError("Configured token is empty")
    return _TOKEN


def verify_bearer(authorization_header: str | None) -> bool:
    """Constant-time check of an `Authorization: Bearer <token>` header."""
    if not authorization_header:
        return False
    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        return False
    return hmac.compare_digest(token.encode(), load_token().encode())
