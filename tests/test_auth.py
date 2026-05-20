import asyncio

import pytest

from dewey import auth


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch, tmp_path):
    """Clear the token cache and point _SECRET_FILE somewhere non-existent."""
    monkeypatch.setattr(auth, "_TOKEN", None)
    monkeypatch.setattr(auth, "_SECRET_FILE", tmp_path / "nonexistent")
    monkeypatch.delenv("DEWEY_TOKEN", raising=False)


# ---------- load_token ----------

def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "env-token")
    assert auth.load_token() == "env-token"


def test_load_token_from_secret_file_preferred(monkeypatch, tmp_path):
    secret = tmp_path / "dewey_token"
    secret.write_text("file-token\n")
    monkeypatch.setattr(auth, "_SECRET_FILE", secret)
    monkeypatch.setenv("DEWEY_TOKEN", "env-token")
    assert auth.load_token() == "file-token"


def test_load_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "  spaced  \n")
    assert auth.load_token() == "spaced"


def test_load_token_caches(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "first")
    assert auth.load_token() == "first"
    monkeypatch.setenv("DEWEY_TOKEN", "second")
    # Cached value wins
    assert auth.load_token() == "first"


def test_load_token_missing_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="No token"):
        auth.load_token()


def test_load_token_empty_env_raises(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "   ")
    with pytest.raises(RuntimeError, match="No token"):
        auth.load_token()


def test_load_token_empty_secret_file_raises(monkeypatch, tmp_path):
    secret = tmp_path / "dewey_token"
    secret.write_text("   \n")
    monkeypatch.setattr(auth, "_SECRET_FILE", secret)
    with pytest.raises(RuntimeError, match="empty"):
        auth.load_token()


# ---------- verify_bearer ----------

def test_verify_bearer_valid(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "good")
    assert auth.verify_bearer("Bearer good") is True


def test_verify_bearer_wrong_token(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "good")
    assert auth.verify_bearer("Bearer bad") is False


def test_verify_bearer_no_prefix(monkeypatch):
    """Some clients send just the token; we strip 'Bearer ' if present."""
    monkeypatch.setenv("DEWEY_TOKEN", "good")
    assert auth.verify_bearer("good") is True


def test_verify_bearer_none(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "good")
    assert auth.verify_bearer(None) is False


def test_verify_bearer_empty(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "good")
    assert auth.verify_bearer("") is False
    assert auth.verify_bearer("Bearer ") is False


# ---------- StaticTokenVerifier (server.py) ----------

def test_static_token_verifier(monkeypatch):
    monkeypatch.setenv("DEWEY_TOKEN", "secret")
    # Import here so the env var is in place for any load-on-import side effects
    from dewey.server import StaticTokenVerifier

    v = StaticTokenVerifier()
    good = asyncio.run(v.verify_token("secret"))
    bad = asyncio.run(v.verify_token("nope"))
    assert good is not None
    assert good.token == "secret"
    assert bad is None
