<div align="center">

<img src="assets/postgres-mcp-pro.png" alt="Postgres MCP Pro Logo" width="600"/>

[中文](README.md) · [English](README.en.md)

<h3>Postgres MCP Pro</h3>
<p>索引调优 · 执行计划 · 健康检查 · 安全 SQL · 运维洞察</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/Poiig/postgres-mcp-pro)](https://github.com/Poiig/postgres-mcp-pro/releases)
[![GHCR](https://img.shields.io/badge/GHCR-postgres--mcp--pro-blue)](https://github.com/Poiig/postgres-mcp-pro/pkgs/container/postgres-mcp-pro)

</div>

## 这是什么

**Postgres MCP Pro**（CLI：`postgres-mcp-pro`）是面向 Cursor / Claude 等 MCP 客户端的 PostgreSQL 助手：能查 schema、跑只读 SQL、看执行计划、做健康检查、给索引建议，并补充表体积、冷索引、活动会话、阻塞等运维能力。

本仓库是 [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) 的维护型 fork：默认只读、修好上游依赖坑，并持续合入有价值的修复。

| 能力 | 说明 |
|------|------|
| 安全默认 | 默认 `--access-mode=restricted`（只读 + SQL 校验）；写库需显式 `unrestricted` |
| 依赖可用 | `pglast>=7.20,<8`，避免上游 PyPI 旧版装不上 |
| 连接更稳 | 归还连接清理 session / HypoPG；stdio 孤儿进程会关池 |
| 运维工具 | 库总览、体积排行、重复/冷索引、autovacuum、活动会话、阻塞等 |

制品发布在 **GitHub**：

- Release：wheel / sdist（打 `v*` tag 自动构建）
- 镜像：`ghcr.io/poiig/postgres-mcp-pro`

---

## 怎么选接入方式

| 方式 | 适用 | 命令形态 |
|------|------|----------|
| **A. uvx / 本地进程（stdio）** | 本机 Cursor，一人一库，最简单 | 客户端拉起 `postgres-mcp-pro` |
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
        "--from",
        "git+https://github.com/Poiig/postgres-mcp-pro",
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

已安装本仓库时：

```bash
uv sync
uv run postgres-mcp-pro --access-mode=restricted
# 或把 DATABASE_URI 写进环境 / .env
```

从 GitHub Release 装 wheel：

```bash
uvx --from ./postgres_mcp_pro-0.4.0-py3-none-any.whl postgres-mcp-pro
```

---

## B. 用 Docker（stdio）

```bash
docker pull ghcr.io/poiig/postgres-mcp-pro:latest
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

容器内会把连接串里的 `localhost` 映射到宿主机（macOS/Windows：`host.docker.internal`）。

也可用密钥文件：

```bash
docker run -i --rm \
  -v /path/to/database-uri:/run/secrets/database-uri:ro \
  -e DATABASE_URI_FILE=/run/secrets/database-uri \
  ghcr.io/poiig/postgres-mcp-pro:latest --access-mode=restricted
```

---

## C. HTTP：streamable-http（推荐远程）

先在服务器启动（默认监听本机；对局域网开放时请自行加反代 / 鉴权 / TLS，不要裸奔公网）：

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

或：

```bash
uv run postgres-mcp-pro \
  --access-mode=restricted \
  --transport=streamable-http \
  --stateless-http \
  --streamable-http-host=0.0.0.0
```

`--stateless-http`：不在服务端堆积未 DELETE 的会话，避免内存持续上涨。

客户端（支持 streamable HTTP 的 MCP 客户端）连服务地址即可；具体字段以客户端文档为准（常见为 URL + 传输类型）。

### SSE（兼容）

旧客户端仍可用 SSE：

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

新部署优先 **streamable-http + `--stateless-http`**，SSE 仅作兼容。

---

## 访问模式

| 模式 | 行为 | 何时用 |
|------|------|--------|
| `restricted`（默认） | 只读事务 + SQL 解析校验 + 超时 + 默认最多 1000 行 | 共享库 / 生产只读 |
| `unrestricted` | 任意 SQL；启动打 `[SECURITY]` 告警 | 仅可信开发库 |

```bash
# 默认即 restricted；需要写库时：
uv run postgres-mcp-pro --access-mode=unrestricted

# 调整行数上限（0=不限制）
uv run postgres-mcp-pro --access-mode=restricted --max-rows=500
```

---

## MCP 工具

**基础**

| 工具 | 作用 |
|------|------|
| `list_schemas` / `list_objects` / `get_object_details` | 浏览结构 |
| `execute_sql` | 执行 SQL（restricted 下只读） |
| `explain_query` | 执行计划；可叠加假设索引 |
| `get_top_queries` | 慢查询（`pg_stat_statements`） |
| `analyze_workload_indexes` / `analyze_query_indexes` | 索引建议 |
| `analyze_db_health` | 综合健康检查 |

**运维**

| 工具 | 作用 |
|------|------|
| `get_database_overview` | 库总览 |
| `analyze_schema_relationships` | 外键关系 |
| `list_relation_sizes` | 表体积 TOP |
| `list_duplicate_indexes` / `list_index_usage` | 重复 / 冷索引 |
| `get_autovacuum_info` | autovacuum 与死元组 |
| `get_table_bloat` | 单表膨胀（需 `pgstattuple`） |
| `list_qual_stats` | 谓词统计（需 `pg_qualstats`） |
| `list_settings` | 关键参数白名单 |
| `list_active_queries` / `get_blocking_queries` | 活动会话 / 阻塞 |

建议扩展：`pg_stat_statements`、`hypopg`（索引推演）。

---

## 发布与版本

打 tag 触发 [Release workflow](.github/workflows/release.yml)：

```bash
git tag v0.4.0
git push origin v0.4.0
```

产出：

- GitHub Release 附件：`postgres_mcp_pro-*.whl` / `.tar.gz`
- 镜像：`ghcr.io/poiig/postgres-mcp-pro:0.4.0` 与 `:latest`

也可在 Actions 里用 `workflow_dispatch` 填版本号手动发版。

---

## 许可与上游

- 许可证：[MIT](LICENSE)
- 上游：[crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)
- 本仓库：[Poiig/postgres-mcp-pro](https://github.com/Poiig/postgres-mcp-pro)

更细的英文说明见 [README.en.md](README.en.md)。
