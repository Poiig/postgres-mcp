<div align="center">

<img src="assets/postgresql-mcp-pro.png" alt="PostgreSQL MCP Pro Logo" width="600"/>

[中文](README.md) · [English](README.en.md)

<h3>PostgreSQL MCP Pro</h3>
<p>索引调优 · 执行计划 · 健康检查 · 安全 SQL · 运维洞察</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/postgresql-mcp-pro)](https://pypi.org/project/postgresql-mcp-pro/)
[![GitHub Release](https://img.shields.io/github/v/release/Poiig/postgresql-mcp-pro)](https://github.com/Poiig/postgresql-mcp-pro/releases)
[![GHCR](https://img.shields.io/badge/GHCR-postgresql--mcp--pro-blue)](https://github.com/Poiig/postgresql-mcp-pro/pkgs/container/postgresql-mcp-pro)

</div>

## 这是什么

**PostgreSQL MCP Pro**（CLI / PyPI：`postgresql-mcp-pro`）是面向 Cursor / Claude 等 MCP 客户端的 PostgreSQL 助手：能查 schema、跑只读 SQL、看执行计划、做健康检查、给索引建议，并补充表体积、冷索引、活动会话、阻塞等运维能力。

本仓库是 [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) 的维护型 fork：默认只读、修好上游依赖坑，并持续合入有价值的修复。

| 能力 | 说明 |
|------|------|
| 安全默认 | 默认 `--access-mode=restricted`（只读 + SQL 校验）；写库需显式 `unrestricted` |
| 依赖可用 | `pglast>=7.20,<8`，避免上游 PyPI 旧版装不上 |
| 连接更稳 | 归还连接清理 session / HypoPG；stdio 孤儿进程会关池 |
| 运维工具 | 库总览、体积排行、重复/冷索引、autovacuum、活动会话、阻塞等 |

制品：

- **PyPI**：`pip` / `uvx postgresql-mcp-pro`（推荐本机）
- **GitHub Release**：wheel / sdist
- **GHCR**：`ghcr.io/poiig/postgresql-mcp-pro`

---

## 怎么选接入方式

| 方式 | 适用 | 命令形态 |
|------|------|----------|
| **A. uvx / 本地进程（stdio）** | 本机 Cursor，一人一库，最简单 | `uvx postgresql-mcp-pro` |
| **B. Docker（stdio）** | 不想装 Python，本机有 Docker | `docker run -i ...` |
| **C. HTTP（streamable-http）** | 远程 / 多人共用一个服务 | 常驻进程，客户端连 URL |
| SSE | 旧客户端兼容 | 仍可用，优先用 C |

本机日常开发推荐 **A**；集中部署推荐 **C**（并加 `--stateless-http`）。

---

## A. 用 uvx（推荐本机）

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，再在 Cursor `mcp.json`：

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

需要写库时把 `--access-mode=restricted` 改成 `--access-mode=unrestricted`。

已克隆本仓库时：

```bash
uv sync
uv run postgresql-mcp-pro --access-mode=restricted
```

---

## B. 用 Docker（stdio）

```bash
docker pull ghcr.io/poiig/postgresql-mcp-pro:latest
```

Cursor 配置：

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

容器内会把连接串里的 `localhost` 映射到宿主机（macOS/Windows：`host.docker.internal`）。

也可用密钥文件：

```bash
docker run -i --rm \
  -v /path/to/database-uri:/run/secrets/database-uri:ro \
  -e DATABASE_URI_FILE=/run/secrets/database-uri \
  ghcr.io/poiig/postgresql-mcp-pro:latest --access-mode=restricted
```

---

## C. HTTP：streamable-http（推荐远程）

先在服务器启动（默认监听本机；对局域网开放时请自行加反代 / 鉴权 / TLS，不要裸奔公网）：

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

本机开发也可用：

```bash
uv run postgresql-mcp-pro \
  --access-mode=restricted \
  --transport=streamable-http \
  --stateless-http \
  --streamable-http-host=127.0.0.1 \
  --streamable-http-port=8000
```

客户端连 `http://<host>:8000/mcp`（以实际 MCP 客户端要求为准）。

### SSE（兼容）

```bash
uv run postgresql-mcp-pro --transport=sse --sse-host=0.0.0.0 --sse-port=8000
```

新部署优先 **streamable-http + `--stateless-http`**。

---

## 常用参数

```bash
uv run postgresql-mcp-pro --access-mode=unrestricted
uv run postgresql-mcp-pro --access-mode=restricted --max-rows=500
```

---

## 工具一览（节选）

| 工具 | 说明 |
|------|------|
| `list_schemas` / `list_objects` / `get_object_details` | 浏览 schema |
| `execute_sql` | 执行 SQL（restricted 下只读校验） |
| `explain_query` | 执行计划 |
| `analyze_db_health` / `analyze_query_indexes` / `analyze_workload_indexes` | 健康与索引 |
| `get_top_queries` | 慢查询（需 `pg_stat_statements`） |
| `get_database_overview` / `list_table_sizes` | 库总览 / 体积 |
| `list_duplicate_indexes` / `list_index_usage` | 重复 / 冷索引 |
| `get_autovacuum_overview` / `get_table_bloat` | 清理与膨胀 |
| `list_qual_stats` | 谓词统计（需 `pg_qualstats`） |
| `list_settings` | 关键参数白名单 |
| `list_active_queries` / `get_blocking_queries` | 活动会话 / 阻塞 |

建议扩展：`pg_stat_statements`、`hypopg`（索引推演）。

---

## 发布与版本

打 tag 触发 [Release workflow](.github/workflows/release.yml)：

```bash
git tag v1.0.0
git push origin v1.0.0
```

产出：

- PyPI：`postgresql-mcp-pro`
- GitHub Release：`postgresql_mcp_pro-*.whl` / `.tar.gz`
- 镜像：`ghcr.io/poiig/postgresql-mcp-pro:1.0.0` 与 `:latest`

也可在 Actions 里用 `workflow_dispatch` 填版本号手动发版。

---

## 许可与上游

- 许可证：[MIT](LICENSE)
- 上游：[crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)
- 本仓库：[Poiig/postgresql-mcp-pro](https://github.com/Poiig/postgresql-mcp-pro)

更细的英文说明见 [README.en.md](README.en.md)。
