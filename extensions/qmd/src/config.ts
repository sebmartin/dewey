/**
 * Runtime configuration for the qmd extension.
 *
 * Mirrors dewey's env-var conventions so paths line up across containers when
 * the same /data and /cache volumes are bind-mounted from the host.
 */

import path from "node:path";

export const DATA_ROOT = process.env.DATA_ROOT ?? "/data";
export const CACHE_DIR = process.env.QMD_CACHE_DIR ?? "/cache";
export const DB_PATH = path.join(CACHE_DIR, "qmd.sqlite");

export const MCP_PORT = Number(process.env.QMD_MCP_PORT ?? 8181);
export const MCP_HOST = process.env.QMD_MCP_HOST ?? "0.0.0.0";
export const MCP_PATH = process.env.QMD_MCP_PATH ?? "/mcp";

export const DEFAULT_PATTERN = process.env.QMD_DEFAULT_PATTERN ?? "**/*.md";

/** Debounce window (ms) for collapsing rapid file-change bursts before reindex. */
export const REINDEX_DEBOUNCE_MS = Number(process.env.QMD_REINDEX_DEBOUNCE_MS ?? 1500);

/** Dewey's collection-name regex — kept in sync with src/dewey/paths.py. */
export const COLLECTION_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

export function isValidCollectionName(name: string): boolean {
  return COLLECTION_NAME_RE.test(name);
}
