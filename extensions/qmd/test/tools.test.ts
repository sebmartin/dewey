import { describe, expect, it, vi } from "vitest";

import {
  CollectionError,
  qmdGet,
  qmdMultiGet,
  qmdSearch,
  qmdStatus,
  qmdUpdate,
  resolveCollectionPath,
} from "../src/tools.js";

function makeStore() {
  return {
    search: vi.fn(async () => []),
    get: vi.fn(async (_p: string, _o?: { includeBody?: boolean }) => ({
      path: "/data/personal/a.md",
      docid: "abc",
      collection: "personal",
      title: "A",
    })),
    getDocumentBody: vi.fn(async () => "hello world"),
    multiGet: vi.fn(async () => ({ docs: [], errors: [] })),
    getStatus: vi.fn(async () => ({ collections: [], totalDocs: 0 })),
    update: vi.fn(async () => ({
      collections: 1, indexed: 0, updated: 0, unchanged: 0, removed: 0, needsEmbedding: 0,
    })),
    embed: vi.fn(async () => ({})),
  };
}

type Store = ReturnType<typeof makeStore>;
const asStore = (s: Store) => s as unknown as import("@tobilu/qmd").QMDStore;

const DATA = "/data";

// ---------- resolveCollectionPath ----------

describe("resolveCollectionPath", () => {
  it("joins collection root + relative path", () => {
    expect(resolveCollectionPath(DATA, "personal", "inputs/foo.md")).toBe("/data/personal/inputs/foo.md");
  });

  it("allows '.'", () => {
    expect(resolveCollectionPath(DATA, "personal", ".")).toBe("/data/personal");
  });

  it.each(["../etc", "../../etc/passwd", "foo/../../escape", ".."])(
    "rejects traversal %s",
    (p) => {
      expect(() => resolveCollectionPath(DATA, "personal", p)).toThrow(CollectionError);
    },
  );

  it("rejects absolute paths", () => {
    expect(() => resolveCollectionPath(DATA, "personal", "/etc/passwd")).toThrow(CollectionError);
  });

  it.each([".hidden", "-bad", "../etc", "my/col", ""])(
    "rejects invalid collection name %s",
    (n) => {
      expect(() => resolveCollectionPath(DATA, n, "x.md")).toThrow(CollectionError);
    },
  );
});

// ---------- qmd_search ----------

describe("qmdSearch", () => {
  it("forwards collection + limit + intent to store.search", async () => {
    const store = makeStore();
    await qmdSearch(asStore(store), {
      collection: "personal",
      query: "auth flow",
      limit: 5,
      intent: "code",
      rerank: false,
    });
    expect(store.search).toHaveBeenCalledWith({
      query: "auth flow",
      collection: "personal",
      limit: 5,
      intent: "code",
      rerank: false,
    });
  });

  it("rejects invalid collection name", async () => {
    const store = makeStore();
    await expect(
      qmdSearch(asStore(store), { collection: ".hidden", query: "x" }),
    ).rejects.toThrow(CollectionError);
    expect(store.search).not.toHaveBeenCalled();
  });
});

// ---------- qmd_get ----------

describe("qmdGet", () => {
  it("returns doc + body for include_body default true", async () => {
    const store = makeStore();
    const out = await qmdGet(asStore(store), DATA, {
      collection: "personal",
      path: "a.md",
    });
    expect(store.get).toHaveBeenCalledWith("/data/personal/a.md", { includeBody: false });
    expect(store.getDocumentBody).toHaveBeenCalledWith("/data/personal/a.md", {
      fromLine: undefined,
      maxLines: undefined,
    });
    expect(out).toMatchObject({ found: true, body: "hello world" });
  });

  it("skips body when include_body is false", async () => {
    const store = makeStore();
    const out = await qmdGet(asStore(store), DATA, {
      collection: "personal",
      path: "a.md",
      include_body: false,
    });
    expect(store.getDocumentBody).not.toHaveBeenCalled();
    expect(out).toMatchObject({ found: true, body: null });
  });

  it("returns found=false when qmd reports not-found", async () => {
    const store = makeStore();
    store.get.mockResolvedValueOnce({ error: "Document not found" } as never);
    const out = await qmdGet(asStore(store), DATA, { collection: "personal", path: "nope.md" });
    expect(out.found).toBe(false);
  });

  it("rejects traversal", async () => {
    const store = makeStore();
    await expect(
      qmdGet(asStore(store), DATA, { collection: "personal", path: "../escape" }),
    ).rejects.toThrow(CollectionError);
  });
});

// ---------- qmd_multi_get ----------

describe("qmdMultiGet", () => {
  it("anchors pattern under collection root", async () => {
    const store = makeStore();
    await qmdMultiGet(asStore(store), DATA, {
      collection: "personal",
      pattern: "**/*.md",
    });
    expect(store.multiGet).toHaveBeenCalledWith("/data/personal/**/*.md", {
      includeBody: true,
      maxBytes: undefined,
    });
  });

  it("respects include_body=false", async () => {
    const store = makeStore();
    await qmdMultiGet(asStore(store), DATA, {
      collection: "personal",
      pattern: "*.md",
      include_body: false,
    });
    expect(store.multiGet).toHaveBeenCalledWith(
      "/data/personal/*.md",
      expect.objectContaining({ includeBody: false }),
    );
  });

  it("rejects invalid collection", async () => {
    const store = makeStore();
    await expect(
      qmdMultiGet(asStore(store), DATA, { collection: "../etc", pattern: "*" }),
    ).rejects.toThrow(CollectionError);
    expect(store.multiGet).not.toHaveBeenCalled();
  });
});

// ---------- qmd_status ----------

describe("qmdStatus", () => {
  it("forwards to store.getStatus", async () => {
    const store = makeStore();
    const out = await qmdStatus(asStore(store));
    expect(store.getStatus).toHaveBeenCalled();
    expect(out).toEqual({ collections: [], totalDocs: 0 });
  });
});

// ---------- qmd_update ----------

describe("qmdUpdate", () => {
  it("scopes update when collection is provided", async () => {
    const store = makeStore();
    await qmdUpdate(asStore(store), { collection: "personal" });
    expect(store.update).toHaveBeenCalledWith({ collections: ["personal"] });
  });

  it("does a full update when collection is omitted", async () => {
    const store = makeStore();
    await qmdUpdate(asStore(store), {});
    expect(store.update).toHaveBeenCalledWith(undefined);
  });

  it("calls embed only when needsEmbedding > 0", async () => {
    const store = makeStore();
    store.update.mockResolvedValueOnce({
      collections: 1, indexed: 0, updated: 0, unchanged: 0, removed: 0, needsEmbedding: 4,
    });
    const out = await qmdUpdate(asStore(store), {});
    expect(store.embed).toHaveBeenCalledTimes(1);
    expect(out.embedded).toBe(true);
  });

  it("skips embed when needsEmbedding is 0", async () => {
    const store = makeStore();
    const out = await qmdUpdate(asStore(store), {});
    expect(store.embed).not.toHaveBeenCalled();
    expect(out.embedded).toBe(false);
  });

  it("rejects invalid collection name", async () => {
    const store = makeStore();
    await expect(qmdUpdate(asStore(store), { collection: ".hidden" })).rejects.toThrow(CollectionError);
    expect(store.update).not.toHaveBeenCalled();
  });
});
