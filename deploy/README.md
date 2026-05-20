# Dewey — Phase 1 deploy

Boots Caddy (TLS), mcp-proxy (extension aggregator), and dewey (fs tools + commit API).

## First-time setup

```sh
# From repo root
cp deploy/.env.example deploy/.env       # then edit paths
mkdir -p $(grep -E '^(DATA|TMP)_DIR' deploy/.env | cut -d= -f2)
mkdir -p secrets
openssl rand -hex 32 > secrets/dewey_token.txt   # or whatever you prefer
```

## Bring up the stack

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build -d
```

Caddy listens on `:443` (and `:80` for HTTP→HTTPS redirect). For local dev the
default `deploy/Caddyfile` uses `local_certs` against `localhost`. For production,
edit the Caddyfile per the inline comment block.

## Smoke test

```sh
uv run python deploy/smoke.py \
  --url https://localhost \
  --token "$(cat secrets/dewey_token.txt)" \
  --insecure          # local self-signed only; drop in prod
```

Should print `PASS — Phase 1 stack is healthy`.

## Wire into Claude Code

```jsonc
{
  "mcpServers": {
    "dewey": {
      "type": "http",
      "url": "https://your-hostname.example.com/mcp",
      "headers": { "Authorization": "Bearer <contents of secrets/dewey_token.txt>" }
    }
  }
}
```

For a local-dev (self-signed) URL you'll need to trust Caddy's local CA — see
`caddy trust` or import the cert from the `caddy_data` volume.

## Tear down

```sh
docker compose -f deploy/docker-compose.yml down
```

Volumes (`caddy_data`, `caddy_config`) persist by default; add `-v` to remove them.
