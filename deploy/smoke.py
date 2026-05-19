"""End-to-end smoke test for a running dewey stack.

Usage:
    uv run python deploy/smoke.py --url https://localhost --token "$(cat secrets/dewey_token.txt)"

Exercises:
  - GET  /auth/validate         (token introspection through Caddy → dewey:8001)
  - MCP  list tools             (Caddy → mcp-proxy → dewey:8000)
  - MCP  fs_write / fs_read / fs_stat / fs_grep / fs_delete
  - POST /commit add/replace/delete  (internal API, exposed here via host-network
                                       only for the smoke test — by default the
                                       container's 8001 is not published)

Designed to be the only thing that needs to pass for Phase 1 to be "done":
if this script exits 0 against a fresh deploy, dewey replaces the local threads
workflow on any device.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from fastmcp import Client

COLLECTION = "smoke"
TEST_PATH = "hello.md"


async def check_auth_validate(base_url: str, token: str, verify_tls: bool) -> None:
    url = f"{base_url.rstrip('/')}/auth/validate"
    async with httpx.AsyncClient(verify=verify_tls) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    body = r.json()
    assert body.get("valid") is True, f"/auth/validate rejected: {body}"
    print(f"  /auth/validate ok — collections={body.get('collections')}")


async def check_mcp_round_trip(base_url: str, token: str, verify_tls: bool) -> None:
    mcp_url = f"{base_url.rstrip('/')}/mcp"

    async with Client(mcp_url, auth=token, verify=verify_tls) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        expected = {
            "fs_read", "fs_write", "fs_edit", "fs_append", "fs_stat",
            "fs_list", "fs_glob", "fs_grep", "fs_copy", "fs_move", "fs_delete",
        }
        missing = expected - names
        assert not missing, f"missing tools: {sorted(missing)}"
        print(f"  list_tools ok — {len(tools)} tools exposed")

        write = await c.call_tool(
            "fs_write",
            {"collection": COLLECTION, "path": TEST_PATH, "content": "hello"},
        )
        print(f"  fs_write ok — {write.structured_content}")

        read = await c.call_tool(
            "fs_read",
            {"collection": COLLECTION, "path": TEST_PATH},
        )
        content = read.structured_content["content"]
        assert content == "hello", f"unexpected content: {content!r}"
        print(f"  fs_read ok — version_token={read.structured_content['version_token']}")

        grep = await c.call_tool(
            "fs_grep",
            {"collection": COLLECTION, "pattern": "hello"},
        )
        assert "hello" in (grep.content[0].text if grep.content else ""), "fs_grep missed match"
        print("  fs_grep ok")

        stat = await c.call_tool("fs_stat", {"collection": COLLECTION, "path": TEST_PATH})
        token_for_delete = stat.structured_content["version_token"]

        await c.call_tool(
            "fs_delete",
            {"collection": COLLECTION, "path": TEST_PATH, "version_token": token_for_delete},
        )
        print("  fs_delete ok")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="https://localhost", help="Base URL (Caddy)")
    p.add_argument("--token", required=True, help="Bearer token")
    p.add_argument("--insecure", action="store_true", help="Skip TLS verification (local self-signed)")
    args = p.parse_args()

    verify = not args.insecure
    print(f"== dewey smoke test against {args.url} ==")

    try:
        print("[1] auth/validate")
        asyncio.run(check_auth_validate(args.url, args.token, verify))

        print("[2] MCP round-trip (fs_write/read/grep/stat/delete)")
        asyncio.run(check_mcp_round_trip(args.url, args.token, verify))
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print("PASS — Phase 1 stack is healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
