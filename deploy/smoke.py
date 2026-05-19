"""End-to-end smoke test for a running dewey stack.

Usage:
    uv run python deploy/smoke.py --url https://localhost --token "$(cat secrets/dewey_token.txt)"

Exercises:
  - GET  /auth/validate              (Caddy → dewey:8001)
  - MCP  list tools                  (Caddy → mcp-proxy → dewey, qmd)
  - MCP  fs_write/read/grep/stat/delete
  - MCP  qmd_status                  (lightweight, no model load required)
  - --with-qmd-search → end-to-end qmd: write → reindex → search

The qmd search step is opt-in because the first ever call against a fresh
qmd_cache volume triggers a ~2 GB GGUF download. Once cached, the search
takes seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from fastmcp import Client

COLLECTION = "smoke"
TEST_PATH = "hello.md"
TEST_CONTENT = "dewey smoke test sentence — auth flow lookup target"
QMD_SEARCH_TIMEOUT = 600  # seconds; first run may download models

FS_TOOLS = {
    "fs_read", "fs_write", "fs_edit", "fs_append", "fs_stat",
    "fs_list", "fs_glob", "fs_grep", "fs_copy", "fs_move", "fs_delete",
}
QMD_TOOLS = {"qmd_search", "qmd_get", "qmd_multi_get", "qmd_status", "qmd_update"}


async def check_auth_validate(base_url: str, token: str, verify_tls: bool) -> None:
    url = f"{base_url.rstrip('/')}/auth/validate"
    async with httpx.AsyncClient(verify=verify_tls) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    body = r.json()
    assert body.get("valid") is True, f"/auth/validate rejected: {body}"
    print(f"  /auth/validate ok — collections={body.get('collections')}")


async def check_fs_round_trip(client: Client) -> None:
    write = await client.call_tool(
        "fs_write",
        {"collection": COLLECTION, "path": TEST_PATH, "content": TEST_CONTENT},
    )
    print(f"  fs_write ok — bytes_written={write.structured_content.get('bytes_written')}")

    read = await client.call_tool(
        "fs_read",
        {"collection": COLLECTION, "path": TEST_PATH},
    )
    content = read.structured_content["content"]
    assert content == TEST_CONTENT, f"unexpected content: {content!r}"
    print(f"  fs_read ok — version_token={read.structured_content['version_token']}")

    grep = await client.call_tool(
        "fs_grep",
        {"collection": COLLECTION, "pattern": "auth flow"},
    )
    assert "auth flow" in (grep.content[0].text if grep.content else ""), "fs_grep missed match"
    print("  fs_grep ok")


async def cleanup_fs(client: Client) -> None:
    try:
        stat = await client.call_tool("fs_stat", {"collection": COLLECTION, "path": TEST_PATH})
        token = stat.structured_content["version_token"]
        await client.call_tool(
            "fs_delete",
            {"collection": COLLECTION, "path": TEST_PATH, "version_token": token},
        )
        print("  fs_delete ok")
    except Exception as e:
        print(f"  fs_delete skipped: {e}")


async def check_qmd_status(client: Client) -> None:
    result = await client.call_tool("qmd_status", {})
    assert not result.is_error, f"qmd_status errored: {result.content}"
    print(f"  qmd_status ok — {result.structured_content}")


async def check_qmd_search(client: Client) -> None:
    # Force a reindex so the file we just wrote is in qmd before searching.
    upd = await client.call_tool(
        "qmd_update",
        {"collection": COLLECTION},
    )
    print(f"  qmd_update ok — {upd.structured_content}")

    search = await client.call_tool(
        "qmd_search",
        {"collection": COLLECTION, "query": "auth flow lookup", "rerank": False, "limit": 5},
    )
    assert not search.is_error, f"qmd_search errored: {search.content}"
    results = search.structured_content.get("results", [])
    assert results, "qmd_search returned no results"
    paths = [r.get("path") for r in results]
    assert any(TEST_PATH in (p or "") for p in paths), f"test file missing from results: {paths}"
    print(f"  qmd_search ok — top hit={results[0].get('path')}")


async def check_mcp(base_url: str, token: str, verify_tls: bool, with_qmd_search: bool) -> None:
    mcp_url = f"{base_url.rstrip('/')}/mcp"
    async with Client(mcp_url, auth=token, verify=verify_tls, timeout=QMD_SEARCH_TIMEOUT) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        missing_fs = FS_TOOLS - names
        missing_qmd = QMD_TOOLS - names
        assert not missing_fs, f"missing fs tools: {sorted(missing_fs)}"
        assert not missing_qmd, f"missing qmd tools: {sorted(missing_qmd)}"
        print(f"  list_tools ok — {len(tools)} tools exposed")

        await check_fs_round_trip(c)
        await check_qmd_status(c)

        if with_qmd_search:
            await check_qmd_search(c)
        else:
            print("  qmd_search skipped (pass --with-qmd-search to run)")

        await cleanup_fs(c)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="https://localhost", help="Base URL (Caddy)")
    p.add_argument("--token", required=True, help="Bearer token")
    p.add_argument("--insecure", action="store_true", help="Skip TLS verification (local self-signed)")
    p.add_argument(
        "--with-qmd-search",
        action="store_true",
        help="Exercise qmd_search end-to-end. First run may take minutes (downloads GGUF models).",
    )
    args = p.parse_args()

    verify = not args.insecure
    print(f"== dewey smoke test against {args.url} ==")

    try:
        print("[1] auth/validate")
        asyncio.run(check_auth_validate(args.url, args.token, verify))

        print("[2] MCP tools + fs + qmd_status" + (" + qmd_search" if args.with_qmd_search else ""))
        asyncio.run(check_mcp(args.url, args.token, verify, args.with_qmd_search))
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print("PASS — stack is healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
