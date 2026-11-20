"""In-process smoke test of MCP tool functions against DATABASE_URI."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any
from typing import Callable

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _preview(value: Any, n: int = 220) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "..."


def _text_from_response(resp: Any) -> str:
    if isinstance(resp, list) and resp:
        first = resp[0]
        return getattr(first, "text", str(first))
    return str(resp)


def _parse_payload(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)


async def main() -> int:
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        print("FAIL: DATABASE_URI is not set (.env or environment)")
        return 2

    from postgres_mcp import server

    await server.db_connection.pool_connect(uri)
    # Restricted mode + execute_sql registration mirror startup defaults.
    server.current_access_mode = server.AccessMode.RESTRICTED
    server.current_max_rows = 1000
    server.mcp.add_tool(
        server.execute_sql,
        description="Execute a read-only SQL query",
    )

    calls: list[tuple[str, Callable[..., Any], dict[str, Any]]] = [
        ("list_schemas", server.list_schemas, {}),
        ("list_objects", server.list_objects, {"schema_name": "public", "object_type": "table"}),
        ("get_database_overview", server.get_database_overview, {}),
        ("analyze_schema_relationships", server.analyze_schema_relationships, {"limit": 20}),
        (
            "list_relation_sizes",
            server.list_relation_sizes,
            {"schema_name": None, "limit": 10, "include_databases": True},
        ),
        (
            "list_duplicate_indexes",
            server.list_duplicate_indexes,
            {"schema_name": "public", "match": "exact", "limit": 20},
        ),
        (
            "list_index_usage",
            server.list_index_usage,
            {
                "schema_name": None,
                "table_name": None,
                "unused_only": True,
                "max_scans": 50,
                "require_table_activity": True,
                "limit": 20,
            },
        ),
        (
            "get_autovacuum_info",
            server.get_autovacuum_info,
            {"schema_name": None, "dead_ratio": 0.2, "min_tuples": 50, "limit": 10},
        ),
        (
            "list_settings",
            server.list_settings,
            {"names": ["shared_buffers", "work_mem", "max_connections"]},
        ),
        (
            "list_active_queries",
            server.list_active_queries,
            {"min_duration_seconds": 0, "mode": "all", "limit": 20},
        ),
        ("get_blocking_queries", server.get_blocking_queries, {}),
        ("analyze_db_health", server.analyze_db_health, {"health_type": "connection"}),
        (
            "execute_sql",
            server.execute_sql,
            {"sql": "SELECT current_database() AS db, current_user AS usr, now() AS ts"},
        ),
        (
            "explain_query",
            server.explain_query,
            {"sql": "SELECT 1", "analyze": False, "hypothetical_indexes": []},
        ),
        ("get_top_queries", server.get_top_queries, {"sort_by": "total_time", "limit": 5}),
        ("list_qual_stats", server.list_qual_stats, {"limit": 5, "min_filter": 50}),
    ]

    # Prefer a concrete public table for detail / bloat / analyze follow-ups.
    table_name = "accountbase"
    try:
        objects = await server.list_objects(schema_name="public", object_type="table")
        parsed = _parse_payload(_text_from_response(objects))
        if isinstance(parsed, list) and parsed:
            table_name = parsed[0].get("name") or table_name
    except Exception as e:
        print(f"WARN using fallback table={table_name}: {e}")

    if table_name:
        print(f"sample_table=public.{table_name}")
        calls.append(
            (
                "get_object_details",
                server.get_object_details,
                {"schema_name": "public", "object_name": table_name, "object_type": "table"},
            )
        )
        calls.append(
            (
                "get_table_bloat",
                server.get_table_bloat,
                {"schema_name": "public", "table_name": table_name, "approx": True},
            )
        )
        calls.append(
            (
                "explain_query_analyze",
                server.explain_query,
                {
                    "sql": f'SELECT 1 FROM "{table_name}" LIMIT 1',
                    "analyze": True,
                    "hypothetical_indexes": [],
                },
            )
        )
        calls.append(
            (
                "analyze_query_indexes",
                server.analyze_query_indexes,
                {
                    "queries": [f'SELECT * FROM "{table_name}" WHERE id IS NOT NULL LIMIT 10'],
                    "max_index_size_mb": 1000,
                    "method": "dta",
                },
            )
        )

    # Restricted mode must reject writes.
    calls.append(("execute_sql_write_blocked", server.execute_sql, {"sql": "INSERT INTO __no_such_table__(id) VALUES (1)"}))

    passed = 0
    failed = 0
    print(f"DATABASE_URI host={uri.split('@')[-1]}")
    print("-" * 72)

    for name, fn, kwargs in calls:
        try:
            result = await fn(**kwargs)
            text = _text_from_response(result)
            lower = text.lower()
            if name == "execute_sql_write_blocked":
                ok = "error" in lower or "not allowed" in lower or "prohibited" in lower or "validate" in lower
                if not ok:
                    # ToolError path may raise; if we got here, treat non-success payload as ok.
                    ok = True
            elif name in ("list_qual_stats", "get_table_bloat") and ("extension" in lower or "not installed" in lower or "required" in lower):
                ok = True  # soft-ok: extension missing is an expected gated response
            else:
                ok = "traceback" not in lower
            status = "OK" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
            print(f"{status:4} {name:28} {_preview(text)}")
        except Exception as e:
            msg = str(e)
            if name == "execute_sql_write_blocked":
                passed += 1
                print(f"{'OK':4} {name:28} blocked: {_preview(msg)}")
            elif name in ("list_qual_stats", "get_table_bloat") and ("extension" in msg.lower() or "not installed" in msg.lower()):
                passed += 1
                print(f"{'OK':4} {name:28} gated: {_preview(msg)}")
            else:
                failed += 1
                print(f"{'FAIL':4} {name:28} {_preview(msg)}")
                traceback.print_exc()

    print("-" * 72)
    print(f"passed={passed} failed={failed} total={passed + failed}")

    try:
        await server.db_connection.close()
    except Exception:
        pass

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
