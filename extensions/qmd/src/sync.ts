/**
 * Keeps qmd's collections in sync with the on-disk shape of /data.
 *
 * Two pieces:
 *   - `Reconciler` — pure logic. Maps filesystem events to store calls,
 *      debounces reindex per collection. No chokidar, easy to unit-test.
 *   - `CollectionSync` — the chokidar wiring on top. Owns the watcher and
 *      forwards events into the reconciler.
 *
 * Each top-level directory under DATA_ROOT is a dewey collection (provided
 * the name passes the collection-name regex). Subdirs and files are
 * indexed under that collection's qmd pattern.
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import chokidar, { type FSWatcher } from "chokidar";
import type { QMDStore } from "@tobilu/qmd";

import { DATA_ROOT, DEFAULT_PATTERN, REINDEX_DEBOUNCE_MS, isValidCollectionName } from "./config.js";

export type LogFn = (msg: string, err?: unknown) => void;

const defaultLog: LogFn = (msg, err) =>
  err ? console.error(`[sync] ${msg}`, err) : console.log(`[sync] ${msg}`);

export interface ReconcilerOptions {
  store: QMDStore;
  dataRoot: string;
  pattern: string;
  debounceMs: number;
  log: LogFn;
}

/** Pure orchestration over a QMDStore. No filesystem watching. */
export class Reconciler {
  private readonly pending = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly known = new Set<string>();

  readonly dataRoot: string;

  constructor(private readonly opts: ReconcilerOptions) {
    this.dataRoot = opts.dataRoot;
  }

  /** Snapshot DATA_ROOT and addCollection for each valid top-level dir. */
  async initialScan(): Promise<void> {
    let entries: import("node:fs").Dirent[];
    try {
      entries = await fs.readdir(this.opts.dataRoot, { withFileTypes: true });
    } catch (e) {
      this.opts.log(`initial scan: cannot read ${this.opts.dataRoot}`, e);
      return;
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (!isValidCollectionName(entry.name)) {
        this.opts.log(`skipping invalid collection name: ${entry.name}`);
        continue;
      }
      await this.addCollection(entry.name);
    }

    if (this.known.size === 0) {
      this.opts.log("initial scan: no collections found");
      return;
    }

    try {
      const result = await this.opts.store.update();
      this.opts.log(
        `initial scan complete: ${result.indexed} indexed, ${result.unchanged} unchanged across ${result.collections} collection(s)`,
      );
      if (result.needsEmbedding > 0) {
        await this.opts.store.embed();
        this.opts.log(`initial embeddings: ${result.needsEmbedding} chunk(s) embedded`);
      }
    } catch (e) {
      this.opts.log("initial scan: update/embed failed", e);
    }
  }

  /** Top-level dir under DATA_ROOT appeared (e.g. user created a new collection). */
  async onCollectionDirAdded(absPath: string): Promise<void> {
    const name = this.topLevelName(absPath);
    if (!name) return;
    await this.addCollection(name);
    this.scheduleReindex(name);
  }

  /** Top-level dir under DATA_ROOT removed. */
  async onCollectionDirRemoved(absPath: string): Promise<void> {
    const name = this.topLevelName(absPath);
    if (!name) return;
    if (!this.known.has(name)) return;
    try {
      await this.opts.store.removeCollection(name);
      this.known.delete(name);
      const t = this.pending.get(name);
      if (t) {
        clearTimeout(t);
        this.pending.delete(name);
      }
      this.opts.log(`removed collection ${name}`);
    } catch (e) {
      this.opts.log(`removeCollection failed for ${name}`, e);
    }
  }

  /** Any file event inside DATA_ROOT — schedules a debounced reindex of the owning collection. */
  onFileEvent(absPath: string): void {
    const name = this.collectionNameFromPath(absPath);
    if (!name) return;
    this.scheduleReindex(name);
  }

  /** Cancel pending reindexes (for shutdown). */
  flush(): void {
    for (const t of this.pending.values()) clearTimeout(t);
    this.pending.clear();
  }

  // ---- internals ----

  private async addCollection(name: string): Promise<void> {
    try {
      await this.opts.store.addCollection(name, {
        path: path.join(this.opts.dataRoot, name),
        pattern: this.opts.pattern,
      });
      this.known.add(name);
      this.opts.log(`added collection ${name}`);
    } catch (e) {
      this.opts.log(`addCollection failed for ${name}`, e);
    }
  }

  private scheduleReindex(name: string): void {
    const existing = this.pending.get(name);
    if (existing) clearTimeout(existing);
    const handle = setTimeout(() => {
      this.pending.delete(name);
      void this.runReindex(name);
    }, this.opts.debounceMs);
    this.pending.set(name, handle);
  }

  private async runReindex(name: string): Promise<void> {
    try {
      const r = await this.opts.store.update({ collections: [name] });
      this.opts.log(
        `reindexed ${name}: indexed=${r.indexed} updated=${r.updated} removed=${r.removed} unchanged=${r.unchanged}`,
      );
      if (r.needsEmbedding > 0) {
        await this.opts.store.embed();
        this.opts.log(`embedded new chunks after ${name} reindex (${r.needsEmbedding})`);
      }
    } catch (e) {
      this.opts.log(`reindex failed for ${name}`, e);
    }
  }

  /** Returns the collection name iff `absPath` is a direct child of DATA_ROOT (and the name is valid). */
  topLevelName(absPath: string): string | null {
    const rel = path.relative(this.opts.dataRoot, absPath);
    if (!rel || rel.startsWith("..")) return null;
    if (rel.includes(path.sep)) return null;
    if (!isValidCollectionName(rel)) return null;
    return rel;
  }

  /** Returns the owning collection for an arbitrary path inside DATA_ROOT (or null). */
  collectionNameFromPath(absPath: string): string | null {
    const rel = path.relative(this.opts.dataRoot, absPath);
    if (!rel || rel.startsWith("..")) return null;
    const [first] = rel.split(path.sep);
    if (!first || !isValidCollectionName(first)) return null;
    return first;
  }

  /** Test helper. */
  knownCollections(): readonly string[] {
    return [...this.known];
  }
}

export interface SyncOptions {
  store: QMDStore;
  dataRoot?: string;
  pattern?: string;
  debounceMs?: number;
  log?: LogFn;
}

/** chokidar wiring. Delegates all decisions to a Reconciler. */
export class CollectionSync {
  private readonly reconciler: Reconciler;
  private watcher?: FSWatcher;

  constructor(opts: SyncOptions) {
    this.reconciler = new Reconciler({
      store: opts.store,
      dataRoot: opts.dataRoot ?? DATA_ROOT,
      pattern: opts.pattern ?? DEFAULT_PATTERN,
      debounceMs: opts.debounceMs ?? REINDEX_DEBOUNCE_MS,
      log: opts.log ?? defaultLog,
    });
  }

  async start(): Promise<void> {
    await this.reconciler.initialScan();
    this.watcher = chokidar.watch(this.reconciler.dataRoot, {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 300, pollInterval: 100 },
      followSymlinks: false,
    });

    this.watcher
      .on("addDir", (p) => void this.reconciler.onCollectionDirAdded(p))
      .on("unlinkDir", (p) => void this.reconciler.onCollectionDirRemoved(p))
      .on("add", (p) => this.reconciler.onFileEvent(p))
      .on("change", (p) => this.reconciler.onFileEvent(p))
      .on("unlink", (p) => this.reconciler.onFileEvent(p));
  }

  async stop(): Promise<void> {
    if (this.watcher) {
      await this.watcher.close();
      this.watcher = undefined;
    }
    this.reconciler.flush();
  }
}
