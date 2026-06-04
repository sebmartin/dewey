/**
 * MCP server: registers the five qmd_* tools, attaches a stateless
 * Streamable HTTP transport, and exposes a /health probe.
 *
 * Auth is intentionally absent — Caddy is the bearer-token boundary and
 * the Docker network is the trust scope for traffic that reaches us.
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { QMDStore } from "@tobilu/qmd";

import { MCP_HOST, MCP_PATH, MCP_PORT } from "./config.js";
import {
  CollectionError,
  qmdGet,
  qmdMultiGet,
  qmdSearch,
  qmdStatus,
  qmdUpdate,
} from "./tools.js";

const SERVER_NAME = "dewey-qmd";
const SERVER_VERSION = "0.1.0";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
    structuredContent: value as Record<string, unknown>,
  };
}

function errorResult(message: string) {
  return {
    isError: true,
    content: [{ type: "text" as const, text: message }],
  };
}

async function safe<T>(fn: () => Promise<T>) {
  try {
    return jsonResult(await fn());
  } catch (e) {
    if (e instanceof CollectionError) return errorResult(e.message);
    const msg = e instanceof Error ? e.message : String(e);
    return errorResult(msg);
  }
}

export function buildMcpServer(store: QMDStore, dataRoot: string): McpServer {
  const server = new McpServer(
    { name: SERVER_NAME, version: SERVER_VERSION },
    { capabilities: { tools: {} } },
  );

  server.registerTool(
    "qmd_search",
    {
      title: "Search a collection (hybrid: BM25 + vector + LLM rerank)",
      description:
        "Full hybrid search over one collection. Combines BM25, vector similarity, and LLM reranking.",
      inputSchema: {
        collection: z.string().describe("Dewey collection to search"),
        query: z.string().describe("Natural-language query"),
        limit: z.number().int().positive().optional(),
        intent: z.string().optional().describe("Domain intent hint (e.g. 'code', 'notes')"),
        rerank: z.boolean().optional().describe("Default true; disable for speed"),
      },
    },
    async (input) => safe(() => qmdSearch(store, input)),
  );

  server.registerTool(
    "qmd_get",
    {
      title: "Get a document from a collection",
      description:
        "Returns the metadata for a path inside a collection, plus the body unless include_body is false.",
      inputSchema: {
        collection: z.string(),
        path: z.string().describe("Relative path within the collection"),
        include_body: z.boolean().optional(),
        from_line: z.number().int().nonnegative().optional(),
        max_lines: z.number().int().positive().optional(),
      },
    },
    async (input) => safe(() => qmdGet(store, dataRoot, input)),
  );

  server.registerTool(
    "qmd_multi_get",
    {
      title: "Get multiple documents by glob",
      description: "Batch retrieval by glob, scoped to a single collection.",
      inputSchema: {
        collection: z.string(),
        pattern: z.string().describe("Glob relative to the collection root, e.g. '**/*.md'"),
        include_body: z.boolean().optional(),
        max_bytes: z.number().int().positive().optional(),
      },
    },
    async (input) => safe(() => qmdMultiGet(store, dataRoot, input)),
  );

  server.registerTool(
    "qmd_status",
    {
      title: "Index status",
      description: "Document counts and embedding coverage across all collections.",
      inputSchema: {},
    },
    async () => safe(() => qmdStatus(store)),
  );

  server.registerTool(
    "qmd_update",
    {
      title: "Force a reindex",
      description:
        "Scan and reindex collections. The watcher does this automatically on file changes; use this to force a refresh.",
      inputSchema: {
        collection: z.string().optional(),
      },
    },
    async (input) => safe(() => qmdUpdate(store, input)),
  );

  return server;
}

export interface HttpServerHandle {
  close(): Promise<void>;
}

export async function startHttpServer(store: QMDStore, dataRoot: string): Promise<HttpServerHandle> {
  const mcp = buildMcpServer(store, dataRoot);
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  await mcp.connect(transport);

  const httpServer = createServer((req: IncomingMessage, res: ServerResponse) => {
    if (req.url === "/health") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, service: SERVER_NAME, version: SERVER_VERSION }));
      return;
    }
    if (req.url?.startsWith(MCP_PATH)) {
      void transport.handleRequest(req, res);
      return;
    }
    res.writeHead(404);
    res.end();
  });

  await new Promise<void>((resolve) => httpServer.listen(MCP_PORT, MCP_HOST, resolve));
  console.log(`[dewey-qmd] listening on http://${MCP_HOST}:${MCP_PORT}${MCP_PATH}`);

  return {
    async close() {
      await new Promise<void>((resolve, reject) =>
        httpServer.close((err) => (err ? reject(err) : resolve())),
      );
      await mcp.close();
    },
  };
}
