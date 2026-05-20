"""Internal commit API (port 8001).

Never published outside the Docker network. Extensions write to /tmp/, then POST
here to land their results in /data/ under dewey's containment guarantees:
- collection bounds enforced via paths.resolve()
- optimistic locking via opaque version_token (hash of mtime_ns + size)
- bearer token forwarded by the extension carries user identity / authorization

Operations: add / replace / delete. Always full-file content; no diffs, no patches.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from dewey import paths
from dewey.auth import verify_bearer
from dewey.paths import resolve, version_token

commit_app = FastAPI(title="dewey-commit", docs_url=None, redoc_url=None)


class CommitRequest(BaseModel):
    operation: str
    collection: str
    path: str
    content: str | None = None
    version_token: str | None = None
    create_collection: bool = False


@commit_app.post("/commit")
async def commit(req: CommitRequest, authorization: str | None = Header(default=None)):
    if not verify_bearer(authorization):
        raise HTTPException(401, "Invalid token")

    try:
        col_root = resolve(req.collection, ".")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not col_root.exists():
        if not req.create_collection:
            raise HTTPException(
                404,
                f"Collection {req.collection!r} does not exist; set create_collection=true",
            )
        col_root.mkdir(parents=True)

    try:
        dst = resolve(req.collection, req.path)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if req.operation == "add":
        if dst.exists():
            raise HTTPException(409, f"{req.path} already exists; use operation='replace'")
        if req.content is None:
            raise HTTPException(400, "content required for add")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(req.content)

    elif req.operation == "replace":
        if req.version_token is None:
            raise HTTPException(400, "version_token required for replace")
        if not dst.exists():
            raise HTTPException(404, f"{req.path} does not exist")
        if version_token(dst) != req.version_token:
            raise HTTPException(409, "version_token mismatch — file changed since last read")
        if req.content is None:
            raise HTTPException(400, "content required for replace")
        dst.write_text(req.content)

    elif req.operation == "delete":
        if req.version_token is None:
            raise HTTPException(400, "version_token required for delete")
        if not dst.exists():
            raise HTTPException(404, f"{req.path} does not exist")
        if version_token(dst) != req.version_token:
            raise HTTPException(409, "version_token mismatch — file changed since last read")
        dst.unlink()

    else:
        raise HTTPException(400, f"Unknown operation: {req.operation!r}")

    response = {"ok": True, "path": req.path, "collection": req.collection}
    if req.operation in ("add", "replace"):
        response["version_token"] = version_token(dst)
    return response


@commit_app.get("/auth/validate")
async def auth_validate(authorization: str | None = Header(default=None)):
    if not verify_bearer(authorization):
        return {"valid": False}
    collections = (
        sorted(p.name for p in paths.DATA_ROOT.iterdir() if p.is_dir())
        if paths.DATA_ROOT.exists()
        else []
    )
    return {"valid": True, "collections": collections}
