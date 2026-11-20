<div align="center">

<img src="assets/postgres-mcp-pro.png" alt="Postgres MCP Pro Logo" width="600"/>

[English](README.md) · [中文文档](README.zh-CN.md)

<h3>带索引调优、执行计划、健康检查与安全 SQL 的 Postgres MCP Server</h3>

</div>

## 关于本仓库

本仓库（[Poiig/postgres-mcp](https://github.com/Poiig/postgres-mcp)）是 **[crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)**（Crystal DBA 的 Postgres MCP Pro）的维护型 fork。

上游能力很强：能看执行计划、用假设索引做推演、给索引建议、做健康检查。不过正式发版停在 2025 年 5 月左右，直接按上游 PyPI `0.3.0` 安装会踩依赖坑。本 fork 在保留原功能的前提下做了可落地修复。

| 问题 | 上游 | 本 fork |
|------|------|---------|
| `pglast` `7.2` / `7.11` 已从 PyPI 下架，安装失败或回退到 `0.1.0` | [issue #237](https://github.com/crystaldba/postgres-mcp/issues/237) | 依赖改为 `pglast>=7.20,<8`（当前会解析到可用的 7.x，如 `7.24`） |
| 默认可读写，容易误伤生产库 | 文档建议手动加 `--access-mode=restricted` | **默认 `restricted`**；`unrestricted` 启动会打安全告警 |
| 中文说明 | 无 | 本文档 |

上游仍可关注的相关改动：

- [PR #238](https://github.com/crystaldba/postgres-mcp/pull/238)：放开 `pglast>=7.20,<8`
- [PR #193](https://github.com/crystaldba/postgres-mcp/pull/193)：默认改为 restricted
- [PR #200](https://github.com/crystaldba/postgres-mcp/pull/200)：限制 `FROM` 中的危险函数
- [Issue #243](https://github.com/crystaldba/postgres-mcp/issues/243)：restricted 模式行数上限
- [Issue #244](https://github.com/crystaldba/postgres-mcp/issues/244)：SQL 失败应正确标记 `isError`

## 功能概览

- **数据库健康**：索引、连接、缓冲池、vacuum、序列、复制延迟等
- **索引调优**：基于工作负载搜索候选索引
- **查询计划**：`EXPLAIN`，可用 hypopg 做假设索引推演
- **Schema 智能**：给 Agent 提供生成 SQL 所需的结构上下文
- **安全执行**：`restricted` 只读 + SQL 解析校验；需要写库时再显式开 `unrestricted`

传输方式支持 stdio、SSE、streamable-http。

更多设计背景见上游博客：[Announcing Postgres MCP Server Pro](https://www.crystaldba.ai/blog/post/announcing-postgres-mcp-server-pro)。

## 快速开始

### 前置条件

1. 可用的 Postgres 连接串（可用 `psql` / pgAdmin 验证）
2. Docker，或 Python 3.12+

### 推荐：从本 fork 用 `uvx` 跑（Cursor / Claude Desktop）

不要直接依赖上游 PyPI `postgres-mcp==0.3.0`（会因 `pglast` 下架装不上，或静默回退到没有 `--access-mode` 的旧版）。

```json
{
  "mcpServers": {
    "postgres": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Poiig/postgres-mcp",
        "postgres-mcp",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

> 未传 `--access-mode` 时，本 fork 也默认是 `restricted`。需要改库结构 / 写数据时，再显式改成 `--access-mode=unrestricted`。

### Docker（上游镜像）

```bash
docker pull crystaldba/postgres-mcp
```

```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "DATABASE_URI",
        "crystaldba/postgres-mcp",
        "--access-mode=restricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

容器内会自动把 `localhost` 映射到宿主机（macOS/Windows 用 `host.docker.internal`，Linux 用桥接网关）。

### 源码安装

```bash
git clone https://github.com/Poiig/postgres-mcp.git
cd postgres-mcp
uv sync
uv run postgres-mcp "postgres://user:password@localhost:5432/dbname" --access-mode=restricted
```

## 访问模式

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `restricted`（默认） | 只读事务 + SQL 安全解析 + 执行超时 | 共享库、生产只读排查、默认推荐 |
| `unrestricted` | 可执行任意 SQL（含 DDL/DML） | 仅可信开发库；启动会打 `[SECURITY]` 告警 |

Agent 读到的网页、工单、邮件内容可能带提示注入；在 `unrestricted` 下这些内容可能直接驱动 `execute_sql`，因此默认不要开可写。

## 可选扩展

要做索引建议与更完整的性能分析，建议在库上启用：

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;
```

云托管 Postgres（RDS / Azure / Cloud SQL）通常已提供扩展，直接 `CREATE EXTENSION` 即可。自建实例可能还要把 `pg_stat_statements` 写进 `shared_preload_libraries`，并按发行版安装 `hypopg`。

## 常用提问示例

- 「检查一下我的数据库健康状况，有没有明显问题？」
- 「最慢的 SQL 是哪些？怎么加速？」
- 「应用整体很慢，从数据库侧帮我找瓶颈。」
- 「分析工作负载并给出索引建议。」
- 「帮我优化这条 SQL：`SELECT * FROM orders JOIN ...`」

## MCP 工具一览

| 工具 | 作用 |
|------|------|
| `list_schemas` | 列出 schema |
| `list_objects` | 列出表 / 视图 / 序列 / 扩展 |
| `get_object_details` | 对象详情（列、约束、索引等） |
| `execute_sql` | 执行 SQL；restricted 下只读 |
| `explain_query` | 执行计划；可叠加假设索引 |
| `get_top_queries` | 基于 `pg_stat_statements` 的慢查询 |
| `analyze_workload_indexes` | 按工作负载给索引建议 |
| `analyze_query_indexes` | 针对给定 SQL 列表给索引建议 |
| `analyze_db_health` | 综合健康检查 |

## SSE 传输

```bash
docker run -p 8000:8000 \
  -e DATABASE_URI=postgresql://username:password@localhost:5432/dbname \
  crystaldba/postgres-mcp --access-mode=restricted --transport=sse
```

客户端配置示例（Cursor `mcp.json`）：

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

## 与原项目的关系

- 原作者 / 上游： [Crystal DBA](https://www.crystaldba.ai) · [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)
- 本 fork： [Poiig/postgres-mcp](https://github.com/Poiig/postgres-mcp)
- 许可证：MIT（见 [LICENSE](LICENSE)）

更完整的英文技术说明（索引搜索算法、健康检查设计、安全模型等）见 [README.md](README.md)。
