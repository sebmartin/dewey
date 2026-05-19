/**
 * Tool implementations — plain async functions over a QMDStore.
 *
 * Each tool takes a typed input and returns a structured result. They're
 * kept free of MCP framework concerns (no registerTool, no zod here) so
 * tests can drive them directly. server.ts wraps them with schemas.
 */

import path from "node:path";

import type {
  QMDStore,
  HybridQueryResult,
  DocumentResult,
  DocumentNotFound,
  MultiGetResult,
  IndexStatus,
} from "@tobilu/qmd";

import { isValidCollectionName } from "./config.js";

export class CollectionError extends Error {}

/** Resolve a user-supplied relative path within a collection. Rejects traversal. */
export function resolveCollectionPath(
  dataRoot: string,
  collection: string,
  userPath: string,
): string {
  if (!isValidCollectionName(collection)) {
    throw new CollectionError(`invalid collection name: ${JSON.stringify(collection)}`);
  }
  if (path.isAbsolute(userPath)) {
    throw new CollectionError(`absolute paths not allowed: ${JSON.stringify(userPath)}`);
  }
  const root = path.resolve(dataRoot, collection);
  const resolved = path.resolve(root, userPath);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
    throw new CollectionError(`path outside collection root: ${JSON.stringify(userPath)}`);
  }
  return resolved;
}

// ---------------- qmd_search ----------------

export interface SearchInput {
  collection: string;
  query: string;
  limit?: number;
  intent?: string;
  rerank?: boolean;
}

export interface SearchOutput {
  results: HybridQueryResult[];
}

export async function qmdSearch(store: QMDStore, input: SearchInput): Promise<SearchOutput> {
  if (!isValidCollectionName(input.collection)) {
    throw new CollectionError(`invalid collection name: ${JSON.stringify(input.collection)}`);
  }
  const results = await store.search({
    query: input.query,
    collection: input.collection,
    limit: input.limit,
    intent: input.intent,
    rerank: input.rerank,
  });
  return { results };
}

// ---------------- qmd_get ----------------

export interface GetInput {
  collection: string;
  path: string;
  include_body?: boolean;
  from_line?: number;
  max_lines?: number;
}

export type GetOutput =
  | { found: true; doc: DocumentResult; body: string | null }
  | { found: false; error: DocumentNotFound };

export async function qmdGet(
  store: QMDStore,
  dataRoot: string,
  input: GetInput,
): Promise<GetOutput> {
  const abs = resolveCollectionPath(dataRoot, input.collection, input.path);
  const result = await store.get(abs, { includeBody: false });
  if ("error" in result) {
    return { found: false, error: result };
  }
  let body: string | null = null;
  if (input.include_body !== false) {
    body = await store.getDocumentBody(abs, {
      fromLine: input.from_line,
      maxLines: input.max_lines,
    });
  }
  return { found: true, doc: result, body };
}

// ---------------- qmd_multi_get ----------------

export interface MultiGetInput {
  collection: string;
  pattern: string;
  include_body?: boolean;
  max_bytes?: number;
}

export interface MultiGetOutput {
  docs: MultiGetResult[];
  errors: string[];
}

export async function qmdMultiGet(
  store: QMDStore,
  dataRoot: string,
  input: MultiGetInput,
): Promise<MultiGetOutput> {
  if (!isValidCollectionName(input.collection)) {
    throw new CollectionError(`invalid collection name: ${JSON.stringify(input.collection)}`);
  }
  const root = path.resolve(dataRoot, input.collection);
  // Anchor the user's glob inside the collection root so it can't reach outside.
  const scoped = path.posix.join(root.replaceAll(path.sep, "/"), input.pattern);
  return store.multiGet(scoped, {
    includeBody: input.include_body !== false,
    maxBytes: input.max_bytes,
  });
}

// ---------------- qmd_status ----------------

export type StatusOutput = IndexStatus;

export async function qmdStatus(store: QMDStore): Promise<StatusOutput> {
  return store.getStatus();
}

// ---------------- qmd_update ----------------

export interface UpdateInput {
  collection?: string;
}

export interface UpdateOutput {
  collections: number;
  indexed: number;
  updated: number;
  unchanged: number;
  removed: number;
  needsEmbedding: number;
  embedded: boolean;
}

export async function qmdUpdate(store: QMDStore, input: UpdateInput = {}): Promise<UpdateOutput> {
  if (input.collection !== undefined && !isValidCollectionName(input.collection)) {
    throw new CollectionError(`invalid collection name: ${JSON.stringify(input.collection)}`);
  }
  const opts = input.collection ? { collections: [input.collection] } : undefined;
  const r = await store.update(opts);
  let embedded = false;
  if (r.needsEmbedding > 0) {
    await store.embed();
    embedded = true;
  }
  return { ...r, embedded };
}
