import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { Reconciler, type LogFn } from "../src/sync.js";

function makeStore() {
  return {
    addCollection: vi.fn(async (_n: string, _o: { path: string; pattern?: string }) => undefined),
    removeCollection: vi.fn(async (_n: string) => true),
    update: vi.fn(async (_o?: { collections?: string[] }) => ({
      collections: 1,
      indexed: 0,
      updated: 0,
      unchanged: 0,
      removed: 0,
      needsEmbedding: 0,
    })),
    embed: vi.fn(async () => ({})),
  };
}

type MockStore = ReturnType<typeof makeStore>;

function makeReconciler(store: MockStore, dataRoot: string, debounceMs = 100, log?: LogFn) {
  return new Reconciler({
    store: store as unknown as import("@tobilu/qmd").QMDStore,
    dataRoot,
    pattern: "**/*.md",
    debounceMs,
    log: log ?? (() => {}),
  });
}

let tmpRoot: string;

beforeEach(async () => {
  tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "dewey-qmd-sync-"));
});

afterEach(async () => {
  await fs.rm(tmpRoot, { recursive: true, force: true });
});

// ---------- path helpers ----------

describe("topLevelName", () => {
  it("returns name for a direct child of dataRoot", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.topLevelName("/data/personal")).toBe("personal");
  });

  it("returns null for nested paths", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.topLevelName("/data/personal/inputs")).toBeNull();
  });

  it("returns null for the data root itself", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.topLevelName("/data")).toBeNull();
  });

  it("returns null for invalid collection name", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.topLevelName("/data/.hidden")).toBeNull();
    expect(r.topLevelName("/data/-bad")).toBeNull();
  });
});

describe("collectionNameFromPath", () => {
  it("returns the owning collection for a file deep inside", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.collectionNameFromPath("/data/personal/inputs/foo.md")).toBe("personal");
  });

  it("returns null for paths outside dataRoot", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.collectionNameFromPath("/etc/passwd")).toBeNull();
  });

  it("returns null when the top-level segment is invalid", () => {
    const r = makeReconciler(makeStore(), "/data");
    expect(r.collectionNameFromPath("/data/.hidden/file.md")).toBeNull();
  });
});

// ---------- initialScan ----------

describe("initialScan", () => {
  it("adds a collection per valid top-level dir, then updates + embeds", async () => {
    await fs.mkdir(path.join(tmpRoot, "personal"));
    await fs.mkdir(path.join(tmpRoot, "photos"));
    await fs.writeFile(path.join(tmpRoot, "loose.md"), "ignored");

    const store = makeStore();
    store.update.mockResolvedValueOnce({
      collections: 2, indexed: 5, updated: 0, unchanged: 0, removed: 0, needsEmbedding: 3,
    });

    const r = makeReconciler(store, tmpRoot);
    await r.initialScan();

    const addedNames = store.addCollection.mock.calls.map((c) => c[0]).sort();
    expect(addedNames).toEqual(["personal", "photos"]);
    expect(store.update).toHaveBeenCalledTimes(1);
    expect(store.update).toHaveBeenCalledWith();  // no collections filter on the bulk pass
    expect(store.embed).toHaveBeenCalledTimes(1);
    expect(r.knownCollections().sort()).toEqual(["personal", "photos"]);
  });

  it("skips invalid collection names", async () => {
    await fs.mkdir(path.join(tmpRoot, ".hidden"));
    await fs.mkdir(path.join(tmpRoot, "-bad"));
    await fs.mkdir(path.join(tmpRoot, "good"));

    const store = makeStore();
    const r = makeReconciler(store, tmpRoot);
    await r.initialScan();

    const names = store.addCollection.mock.calls.map((c) => c[0]);
    expect(names).toEqual(["good"]);
  });

  it("skips embed when needsEmbedding is 0", async () => {
    await fs.mkdir(path.join(tmpRoot, "personal"));
    const store = makeStore();
    const r = makeReconciler(store, tmpRoot);
    await r.initialScan();
    expect(store.embed).not.toHaveBeenCalled();
  });

  it("does not crash if dataRoot is missing", async () => {
    const store = makeStore();
    const r = makeReconciler(store, path.join(tmpRoot, "does-not-exist"));
    await expect(r.initialScan()).resolves.toBeUndefined();
    expect(store.addCollection).not.toHaveBeenCalled();
    expect(store.update).not.toHaveBeenCalled();
  });

  it("does not call update when no collections were added", async () => {
    const store = makeStore();
    const r = makeReconciler(store, tmpRoot);
    await r.initialScan();
    expect(store.update).not.toHaveBeenCalled();
    expect(store.embed).not.toHaveBeenCalled();
  });
});

// ---------- collection dir add/remove ----------

describe("onCollectionDirAdded / Removed", () => {
  it("adds a new collection and schedules a reindex", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/fresh");
      expect(store.addCollection).toHaveBeenCalledWith("fresh", {
        path: "/data/fresh",
        pattern: "**/*.md",
      });
      // debounced update hasn't fired yet
      expect(store.update).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(150);
      expect(store.update).toHaveBeenCalledWith({ collections: ["fresh"] });
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores nested dirs", async () => {
    const store = makeStore();
    const r = makeReconciler(store, "/data");
    await r.onCollectionDirAdded("/data/personal/inputs");
    expect(store.addCollection).not.toHaveBeenCalled();
  });

  it("ignores dirs with invalid collection names", async () => {
    const store = makeStore();
    const r = makeReconciler(store, "/data");
    await r.onCollectionDirAdded("/data/.hidden");
    expect(store.addCollection).not.toHaveBeenCalled();
  });

  it("removes a known collection on dir delete", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/gone");

      r.onFileEvent("/data/gone/file.md");  // queue a pending reindex too

      await r.onCollectionDirRemoved("/data/gone");
      expect(store.removeCollection).toHaveBeenCalledWith("gone");
      expect(r.knownCollections()).not.toContain("gone");

      // The pending reindex should have been cancelled
      await vi.advanceTimersByTimeAsync(500);
      expect(store.update).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("is a no-op when removing an unknown collection", async () => {
    const store = makeStore();
    const r = makeReconciler(store, "/data");
    await r.onCollectionDirRemoved("/data/never-existed");
    expect(store.removeCollection).not.toHaveBeenCalled();
  });
});

// ---------- file events / debounce ----------

describe("onFileEvent + debounce", () => {
  it("schedules a single reindex for a burst of events", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/notes");
      store.update.mockClear();

      r.onFileEvent("/data/notes/a.md");
      r.onFileEvent("/data/notes/b.md");
      r.onFileEvent("/data/notes/c.md");

      await vi.advanceTimersByTimeAsync(50);
      expect(store.update).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(60);
      expect(store.update).toHaveBeenCalledTimes(1);
      expect(store.update).toHaveBeenCalledWith({ collections: ["notes"] });
    } finally {
      vi.useRealTimers();
    }
  });

  it("debounces independently per collection", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/a");
      await r.onCollectionDirAdded("/data/b");
      store.update.mockClear();

      r.onFileEvent("/data/a/x.md");
      r.onFileEvent("/data/b/y.md");

      await vi.advanceTimersByTimeAsync(150);
      expect(store.update).toHaveBeenCalledTimes(2);
      const calls = store.update.mock.calls.map((c) => c[0]?.collections?.[0]).sort();
      expect(calls).toEqual(["a", "b"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores file events outside any valid collection", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      r.onFileEvent("/data/.hidden/file.md");
      r.onFileEvent("/etc/passwd");
      await vi.advanceTimersByTimeAsync(500);
      expect(store.update).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("triggers embed when reindex reports new chunks", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      store.update.mockResolvedValue({
        collections: 1, indexed: 1, updated: 0, unchanged: 0, removed: 0, needsEmbedding: 2,
      });
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/notes");
      store.embed.mockClear();

      r.onFileEvent("/data/notes/x.md");
      await vi.advanceTimersByTimeAsync(150);
      // Microtask drain for the await chain inside the timer callback
      await Promise.resolve();
      await Promise.resolve();
      expect(store.embed).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("flush cancels pending reindexes", async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore();
      const r = makeReconciler(store, "/data", 100);
      await r.onCollectionDirAdded("/data/n");
      store.update.mockClear();

      r.onFileEvent("/data/n/a.md");
      r.flush();

      await vi.advanceTimersByTimeAsync(500);
      expect(store.update).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
