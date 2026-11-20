<div align="center">

<img src="assets/postgres-mcp-pro.png" alt="Postgres MCP Pro Logo" width="600"/>

[中文](README.md) · [English](README.en.md)

<h3>Postgres MCP Pro</h3>
<p>Index tuning · Explain plans · Health checks · Safe SQL · Ops insights</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/Poiig/postgres-mcp)](https://github.com/Poiig/postgres-mcp/releases)
[![GHCR](https://img.shields.io/badge/GHCR-postgres--mcp--pro-blue)](https://github.com/Poiig/postgres-mcp/pkgs/container/postgres-mcp-pro)

</div>

## Overview

**Postgres MCP Pro** (`postgres-mcp-pro`) is an MCP server for PostgreSQL: schema exploration, safe SQL, explain plans, health checks, index advice, plus day-2 ops tools (sizes, cold indexes, sessions, blocking queries).

This repository is a maintained fork of [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) with a restricted-by-default access mode, dependency fixes, connection-pool hardening, and extra ops tools.

Artifacts are published on **GitHub**:

- Releases: wheel / sdist (on `v*` tags)
- Image: `ghcr.io/poiig/postgres-mcp-pro`

## Choose a transport

| Mode | Best for | How |
|------|----------|-----|
| **A. uvx / local stdio** | Local Cursor, simplest | Client spawns `postgres-mcp-pro` |
| **B. Docker stdio** | No local Python | `docker run -i ...` |
| **C. streamable-http** | Shared / remote server | Long-running process + URL |
| SSE | Legacy clients | Prefer C for new deploys |

## A. uvx (recommended locally)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then in Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "postgres": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Poiig/postgres-mcp",
        "postgres-mcp-pro",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

From a checkout:

```bash
uv sync
uv run postgres-mcp-pro --access-mode=restricted
```

## B. Docker (stdio)

```bash
docker pull ghcr.io/poiig/postgres-mcp-pro:latest
```

```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DATABASE_URI",
        "ghcr.io/poiig/postgres-mcp-pro:latest",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

`localhost` inside the URI is remapped to the Docker host automatically.

Secret file:

```bash
docker run -i --rm \
  -v /path/to/database-uri:/run/secrets/database-uri:ro \
  -e DATABASE_URI_FILE=/run/secrets/database-uri \
  ghcr.io/poiig/postgres-mcp-pro:latest --access-mode=restricted
```

## C. streamable-http (recommended for remote)

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URI=postgresql://username:password@host:5432/dbname \
  ghcr.io/poiig/postgres-mcp-pro:latest \
  --access-mode=restricted \
  --transport=streamable-http \
  --stateless-http \
  --streamable-http-host=0.0.0.0 \
  --streamable-http-port=8000
```

Use `--stateless-http` so abandoned sessions do not grow server memory. Protect the endpoint (bind locally, reverse proxy, TLS, auth)—do not expose it publicly without controls.

### SSE (compat)

```bash
uv run postgres-mcp-pro --transport=sse --sse-host=0.0.0.0 --sse-port=8000
```

```json
{
  "mcpServers": {
    "postgres": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Prefer **streamable-http + `--stateless-http`** for new HTTP deployments.

## Access modes

| Mode | Behavior |
|------|----------|
| `restricted` (default) | Read-only + SQL validation + timeout + `--max-rows` (default 1000) |
| `unrestricted` | Full SQL; logs a `[SECURITY]` warning at startup |

## Tools (summary)

Schema / SQL / explain / top queries / index tuning / `analyze_db_health`, plus ops tools: `get_database_overview`, `list_relation_sizes`, `list_index_usage`, `list_duplicate_indexes`, `get_autovacuum_info`, `list_active_queries`, `get_blocking_queries`, `list_settings`, and extension-gated `get_table_bloat` / `list_qual_stats`.

Useful extensions: `pg_stat_statements`, `hypopg`.

## Release

```bash
git tag v0.4.0
git push origin v0.4.0
```

Produces GitHub Release assets and `ghcr.io/poiig/postgres-mcp-pro:<version>` / `:latest`.

## License & upstream

- License: [MIT](LICENSE)
- Upstream: [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)
- This fork: [Poiig/postgres-mcp](https://github.com/Poiig/postgres-mcp)

Chinese docs (default): [README.md](README.md).
