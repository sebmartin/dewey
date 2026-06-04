import { describe, expect, it, vi } from "vitest";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { buildMcpServer } from "../src/server.js";

function makeStore() {
  return {
    search: vi.fn(async () => [{ path: "/data/personal/a.md", score: 0.9 }]),
    get: vi.fn(async () => ({
      path: "/data/personal/a.md",
      docid: "abc",
      collection: "personal",
      title: "A",
    })),
    getDocumentBody: vi.fn(async () => "body"),
    multiGet: vi.fn(async () => ({ docs: [], errors: [] })),
    getStatus: vi.fn(async () => ({
      collections: [{ name: "personal", docs: 1 }],
      totalDocs: 1,
    })),
    update: vi.fn(async () => ({
      collections: 1, indexed: 0, updated: 0, unchanged: 1, removed: 0, needsEmbedding: 0,
    })),
    embed: vi.fn(async () => ({})),
  };
}

const asStore = (s: ReturnType<typeof makeStore>) =>
  s as unknown as import("@tobilu/qmd").QMDStore;

async function pair(store: ReturnType<typeof makeStore>) {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const mcp = buildMcpServer(asStore(store), "/data");
  await mcp.connect(serverTransport);
  const client = new Client({ name: "test", version: "0.0.0" });
  await client.connect(clientTransport);
  return { client, mcp };
}

describe("MCP server", () => {
  it("registers all five tools", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const { tools } = await client.listTools();
    const names = tools.map((t) => t.name).sort();
    expect(names).toEqual([
      "qmd_get",
      "qmd_multi_get",
      "qmd_search",
      "qmd_status",
      "qmd_update",
    ]);
  });

  it("qmd_search round-trips through the transport", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const result = await client.callTool({
      name: "qmd_search",
      arguments: { collection: "personal", query: "hello" },
    });
    expect(store.search).toHaveBeenCalledWith({
      query: "hello",
      collection: "personal",
      limit: undefined,
      intent: undefined,
      rerank: undefined,
    });
    expect(result.isError).toBeFalsy();
    expect(result.structuredContent).toMatchObject({
      results: [{ path: "/data/personal/a.md" }],
    });
  });

  it("qmd_search returns isError=true on invalid collection name", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const result = await client.callTool({
      name: "qmd_search",
      arguments: { collection: ".hidden", query: "x" },
    });
    expect(result.isError).toBe(true);
    expect(store.search).not.toHaveBeenCalled();
  });

  it("qmd_get returns body + metadata", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const result = await client.callTool({
      name: "qmd_get",
      arguments: { collection: "personal", path: "a.md" },
    });
    expect(result.isError).toBeFalsy();
    expect(result.structuredContent).toMatchObject({
      found: true,
      body: "body",
      doc: { path: "/data/personal/a.md" },
    });
  });

  it("qmd_get rejects traversal", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const result = await client.callTool({
      name: "qmd_get",
      arguments: { collection: "personal", path: "../escape" },
    });
    expect(result.isError).toBe(true);
  });

  it("qmd_multi_get anchors the glob under the collection", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    await client.callTool({
      name: "qmd_multi_get",
      arguments: { collection: "personal", pattern: "**/*.md" },
    });
    expect(store.multiGet).toHaveBeenCalledWith(
      "/data/personal/**/*.md",
      expect.objectContaining({ includeBody: true }),
    );
  });

  it("qmd_status forwards", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    const result = await client.callTool({ name: "qmd_status", arguments: {} });
    expect(store.getStatus).toHaveBeenCalled();
    expect(result.structuredContent).toMatchObject({ totalDocs: 1 });
  });

  it("qmd_update with collection scopes the call", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    await client.callTool({
      name: "qmd_update",
      arguments: { collection: "personal" },
    });
    expect(store.update).toHaveBeenCalledWith({ collections: ["personal"] });
  });

  it("qmd_update without collection does a full update", async () => {
    const store = makeStore();
    const { client } = await pair(store);
    await client.callTool({ name: "qmd_update", arguments: {} });
    expect(store.update).toHaveBeenCalledWith(undefined);
  });
});
