/**
 * Process entry point.
 *
 *  1. Open the qmd store (sqlite cache + inline empty collections config).
 *  2. CollectionSync scans /data, adds collections, runs initial update + embed.
 *  3. Start the MCP HTTP server.
 *  4. On SIGTERM/SIGINT, stop the watcher, close the server, close the store.
 */

import { mkdirSync } from "node:fs";
import path from "node:path";

<<<<<<< HEAD
console.log(`[dewey-qmd] data=${DATA_ROOT} db=${DB_PATH} listen=${MCP_HOST}:${MCP_PORT}${MCP_PATH}`);
=======
import { createStore } from "@tobilu/qmd";

import { CACHE_DIR, DATA_ROOT, DB_PATH } from "./config.js";
import { CollectionSync } from "./sync.js";
import { startHttpServer } from "./server.js";

async function main() {
  mkdirSync(CACHE_DIR, { recursive: true });
  mkdirSync(path.dirname(DB_PATH), { recursive: true });

  console.log(`[dewey-qmd] data=${DATA_ROOT} db=${DB_PATH}`);

  const store = await createStore({
    dbPath: DB_PATH,
    config: { collections: {} },
  });

  const sync = new CollectionSync({ store });
  await sync.start();

  const server = await startHttpServer(store, DATA_ROOT);

  const shutdown = async (signal: string) => {
    console.log(`[dewey-qmd] received ${signal}, shutting down`);
    try {
      await sync.stop();
      await server.close();
      await store.close();
      process.exit(0);
    } catch (e) {
      console.error("[dewey-qmd] shutdown error", e);
      process.exit(1);
    }
  };
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((e) => {
  console.error("[dewey-qmd] fatal", e);
  process.exit(1);
});
>>>>>>> c033d84 (Add MCP tools and HTTP server (Phase 2 / Step 3))
