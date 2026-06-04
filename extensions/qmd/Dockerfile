FROM node:22-bookworm-slim AS builder

# Build toolchain for native modules: better-sqlite3, sqlite-vec, node-llama-cpp
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps in a cacheable layer
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts=false

# Build the TS sources
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# Strip dev dependencies for the runtime image
RUN npm prune --omit=dev


FROM node:22-bookworm-slim AS runtime

# Runtime libs only — native compilation already done in the builder stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

# Non-root runtime user. /cache is the persistent volume mount point.
RUN useradd -r -u 1002 -m -d /home/qmd qmd \
    && mkdir -p /cache \
    && chown -R qmd:qmd /app /cache /home/qmd
USER qmd

# qmd writes its sqlite + GGUF model cache here.
ENV HOME=/home/qmd \
    QMD_CACHE_DIR=/cache \
    NODE_ENV=production

EXPOSE 8181

CMD ["node", "dist/main.js"]
