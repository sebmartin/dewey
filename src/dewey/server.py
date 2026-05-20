"""Process entry point: MCP server on port 8000 + commit API on port 8001.

The MCP server (the fs extension) sits behind a single bearer-token check —
the same token the commit API expects. The commit API runs in a background
thread on a separate port that is never published outside the Docker network.

Both servers share state through the filesystem only; no in-process objects
cross between them.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import threading

import uvicorn
from fastmcp.server.auth import AccessToken, TokenVerifier

from dewey.auth import load_token
from dewey.commit import commit_app
from dewey.fs import fs

log = logging.getLogger("dewey")

COMMIT_PORT = 8001
MCP_PORT = 8000
MCP_PATH = "/mcp"


class StaticTokenVerifier(TokenVerifier):
    """Verify against the single per-deployment token from dewey.auth."""

    async def verify_token(self, token: str) -> AccessToken | None:
        expected = load_token()
        if hmac.compare_digest(token.encode(), expected.encode()):
            return AccessToken(token=token, client_id="dewey", scopes=[])
        return None


def _run_commit_api() -> None:
    asyncio.run(
        uvicorn.Server(
            uvicorn.Config(
                commit_app,
                host="0.0.0.0",
                port=COMMIT_PORT,
                log_level="info",
                access_log=True,
            )
        ).serve()
    )


def main() -> None:
    load_token()  # fail fast if no token is configured
    fs.auth = StaticTokenVerifier()
    log.info("starting dewey: MCP on :%d%s, commit on :%d", MCP_PORT, MCP_PATH, COMMIT_PORT)
    threading.Thread(target=_run_commit_api, daemon=True, name="commit-api").start()
    fs.run(transport="http", host="0.0.0.0", port=MCP_PORT, path=MCP_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    main()
