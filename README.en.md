<div align="center">

<img src="assets/postgresql-mcp-pro.png" alt="PostgreSQL MCP Pro Logo" width="600"/>

[中文](README.md) · [English](README.en.md)

<h3>PostgreSQL MCP Pro</h3>
<p>Index tuning · Explain plans · Health checks · Safe SQL · Ops insights</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/postgresql-mcp-pro)](https://pypi.org/project/postgresql-mcp-pro/)
[![GitHub Release](https://img.shields.io/github/v/release/Poiig/postgresql-mcp-pro)](https://github.com/Poiig/postgresql-mcp-pro/releases)
[![GHCR](https://img.shields.io/badge/GHCR-postgresql--mcp--pro-blue)](https://github.com/Poiig/postgresql-mcp-pro/pkgs/container/postgresql-mcp-pro)

</div>

## Overview

**PostgreSQL MCP Pro** (`postgresql-mcp-pro`) is an MCP server for PostgreSQL: schema exploration, safe SQL, explain plans, health checks, index advice, plus day-2 ops tools (sizes, cold indexes, sessions, blocking queries).

This repository is a maintained fork of [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) with a restricted-by-default access mode, dependency fixes, connection-pool hardening, and extra ops tools.

Artifacts:

- **PyPI**: `uvx postgresql-mcp-pro` (recommended locally)
- **GitHub Releases**: wheel / sdist
- **GHCR**: `ghcr.io/poiig/postgresql-mcp-pro`

## Choose a transport

| Mode | Best for | How |
|------|----------|-----|
| **A. uvx / local stdio** | Local Cursor, simplest | `uvx postgresql-mcp-pro` |
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
        "postgresql-mcp-pro",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

Use `--access-mode=unrestricted` only on trusted databases.

From a checkout:

```bash
uv sync
uv run postgresql-mcp-pro --access-mode=restricted
```

## B. Docker (stdio)

```bash
docker pull ghcr.io/poiig/postgresql-mcp-pro:latest
```

```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DATABASE_URI",
        "ghcr.io/poiig/postgresql-mcp-pro:latest",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

## C. streamable-http (recommended for remote)

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URI=postgresql://username:password@host:5432/dbname \
  ghcr.io/poiig/postgresql-mcp-pro:latest \
  --access-mode=restricted \
  --transport=streamable-http \
  --stateless-http \
  --streamable-http-host=0.0.0.0 \
  --streamable-http-port=8000
```

Use `--stateless-http` so abandoned sessions do not grow server memory. Protect the endpoint (bind locally, reverse proxy, TLS, auth)—do not expose it publicly without controls.

### SSE (legacy)

```bash
uv run postgresql-mcp-pro --transport=sse --sse-host=0.0.0.0 --sse-port=8000
```

Prefer **streamable-http + `--stateless-http`** for new HTTP deployments.

## Release

Tagging `v*` runs the Release workflow: PyPI, GitHub Release assets, and `ghcr.io/poiig/postgresql-mcp-pro:<version>` / `:latest`.

## License & upstream

- License: [MIT](LICENSE)
- Upstream: [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)
- This fork: [Poiig/postgresql-mcp-pro](https://github.com/Poiig/postgresql-mcp-pro)
