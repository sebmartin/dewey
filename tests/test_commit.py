import pytest
from fastapi.testclient import TestClient

from dewey import auth, paths
from dewey.commit import commit_app

TOKEN = "test-token-secret"


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path.resolve())
    monkeypatch.setattr(auth, "_TOKEN", TOKEN)
    monkeypatch.setattr(auth, "_SECRET_FILE", tmp_path / "no-such-file")
    return tmp_path.resolve()


@pytest.fixture
def client(data_root):
    return TestClient(commit_app)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def col(data_root):
    c = data_root / "personal"
    c.mkdir()
    return c


# ---------- auth ----------

def test_missing_authorization_rejected(client):
    r = client.post("/commit", json={"operation": "add", "collection": "x", "path": "p"})
    assert r.status_code == 401


def test_wrong_token_rejected(client, col):
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "personal", "path": "f.md", "content": "x"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_malformed_authorization_rejected(client):
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "x", "path": "p"},
        headers={"Authorization": "Basic xxxxx"},
    )
    assert r.status_code == 401


# ---------- add ----------

def test_add_creates_file(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "personal", "path": "new.md", "content": "hello"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["path"] == "new.md"
    assert len(body["version_token"]) == 16
    assert (col / "new.md").read_text() == "hello"


def test_add_creates_parent_dirs(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "personal", "path": "a/b/c.md", "content": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert (col / "a/b/c.md").read_text() == "x"


def test_add_conflict_when_exists(client, col, auth_headers):
    (col / "f.md").write_text("orig")
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "personal", "path": "f.md", "content": "new"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_add_requires_content(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={"operation": "add", "collection": "personal", "path": "f.md"},
        headers=auth_headers,
    )
    assert r.status_code == 400


# ---------- replace ----------

def test_replace_with_matching_token(client, col, auth_headers):
    (col / "f.md").write_text("orig")
    token = paths.version_token(col / "f.md")
    r = client.post(
        "/commit",
        json={
            "operation": "replace",
            "collection": "personal",
            "path": "f.md",
            "content": "new",
            "version_token": token,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert (col / "f.md").read_text() == "new"
    assert r.json()["version_token"] != token


def test_replace_with_stale_token_409(client, col, auth_headers):
    (col / "f.md").write_text("orig")
    r = client.post(
        "/commit",
        json={
            "operation": "replace",
            "collection": "personal",
            "path": "f.md",
            "content": "new",
            "version_token": "deadbeef00000000",
        },
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_replace_missing_token_400(client, col, auth_headers):
    (col / "f.md").write_text("orig")
    r = client.post(
        "/commit",
        json={"operation": "replace", "collection": "personal", "path": "f.md", "content": "new"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_replace_missing_file_404(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "replace",
            "collection": "personal",
            "path": "nope.md",
            "content": "x",
            "version_token": "abc",
        },
        headers=auth_headers,
    )
    assert r.status_code == 404


# ---------- delete ----------

def test_delete_with_matching_token(client, col, auth_headers):
    (col / "f.md").write_text("bye")
    token = paths.version_token(col / "f.md")
    r = client.post(
        "/commit",
        json={
            "operation": "delete",
            "collection": "personal",
            "path": "f.md",
            "version_token": token,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert not (col / "f.md").exists()


def test_delete_stale_token_409(client, col, auth_headers):
    (col / "f.md").write_text("bye")
    r = client.post(
        "/commit",
        json={
            "operation": "delete",
            "collection": "personal",
            "path": "f.md",
            "version_token": "deadbeef00000000",
        },
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_delete_missing_token_400(client, col, auth_headers):
    (col / "f.md").write_text("bye")
    r = client.post(
        "/commit",
        json={"operation": "delete", "collection": "personal", "path": "f.md"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_delete_missing_file_404(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "delete",
            "collection": "personal",
            "path": "nope.md",
            "version_token": "abc",
        },
        headers=auth_headers,
    )
    assert r.status_code == 404


# ---------- containment ----------

def test_traversal_rejected(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "add",
            "collection": "personal",
            "path": "../escape.md",
            "content": "x",
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_absolute_path_rejected(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "add",
            "collection": "personal",
            "path": "/etc/passwd",
            "content": "x",
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_invalid_collection_name_rejected(client, data_root, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "add",
            "collection": "../etc",
            "path": "passwd",
            "content": "x",
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


# ---------- collections ----------

def test_missing_collection_without_create_404(client, data_root, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "add",
            "collection": "new-col",
            "path": "f.md",
            "content": "x",
        },
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_create_collection_on_demand(client, data_root, auth_headers):
    r = client.post(
        "/commit",
        json={
            "operation": "add",
            "collection": "fresh",
            "path": "f.md",
            "content": "x",
            "create_collection": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert (data_root / "fresh" / "f.md").read_text() == "x"


# ---------- unknown op ----------

def test_unknown_operation(client, col, auth_headers):
    r = client.post(
        "/commit",
        json={"operation": "yeet", "collection": "personal", "path": "f.md"},
        headers=auth_headers,
    )
    assert r.status_code == 400


# ---------- auth/validate ----------

def test_auth_validate_valid(client, data_root, auth_headers):
    (data_root / "alpha").mkdir()
    (data_root / "beta").mkdir()
    r = client.get("/auth/validate", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["collections"] == ["alpha", "beta"]


def test_auth_validate_invalid(client, data_root):
    r = client.get("/auth/validate", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 200
    assert r.json() == {"valid": False}


def test_auth_validate_missing_header(client, data_root):
    r = client.get("/auth/validate")
    assert r.status_code == 200
    assert r.json() == {"valid": False}


def test_auth_validate_empty_data_root(client, data_root, auth_headers):
    r = client.get("/auth/validate", headers=auth_headers)
    assert r.json() == {"valid": True, "collections": []}
