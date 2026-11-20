"""Unit tests for ops insights helpers."""

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from postgres_mcp.catalog_facts import facts_summary
from postgres_mcp.ops_insights import OpsInsights
from postgres_mcp.sql import SafeSqlDriver


class _Row:
    def __init__(self, cells):
        self.cells = cells


@pytest.mark.asyncio
async def test_list_settings_rejects_names_outside_whitelist():
    driver = MagicMock()
    driver.execute_query = AsyncMock()
    data = await OpsInsights(driver).list_settings(names=["totally_fake_setting"])
    assert data["error"] == "no_allowed_names"
    assert "shared_buffers" in data["whitelist"]
    driver.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_settings_intersects_whitelist():
    driver = MagicMock()
    driver.execute_query = AsyncMock(
        return_value=[
            _Row(
                {
                    "name": "work_mem",
                    "setting": "4MB",
                    "unit": None,
                    "short_desc": "",
                    "context": "user",
                    "source": "default",
                    "pending_restart": False,
                }
            )
        ]
    )
    data = await OpsInsights(driver).list_settings(names=["work_mem", "not_allowed"])
    assert data["count"] == 1
    assert data["settings"][0]["name"] == "work_mem"
    sql = driver.execute_query.await_args.args[0]
    assert "work_mem" in sql
    assert "not_allowed" not in sql


@pytest.mark.asyncio
async def test_list_duplicate_indexes_exact_mode():
    driver = MagicMock()
    with patch.object(
        SafeSqlDriver,
        "execute_param_query",
        new=AsyncMock(
            return_value=[
                _Row(
                    {
                        "table": "public.orders",
                        "indexes": ["orders_a", "orders_b"],
                        "definitions": ["CREATE INDEX ...", "CREATE INDEX ..."],
                        "dup_count": 2,
                    }
                )
            ]
        ),
    ):
        data = await OpsInsights(driver).list_duplicate_indexes(schema_name="public", match="exact", limit=10)
    assert data["count"] == 1
    assert data["duplicates"][0]["dup_count"] == 2


@pytest.mark.asyncio
async def test_get_table_bloat_extension_gate():
    driver = MagicMock()
    insights = OpsInsights(driver)
    with patch.object(
        insights,
        "_extension_gate",
        new=AsyncMock(
            return_value={
                "error": "extension_required:pgstattuple",
                "extension": "pgstattuple",
                "message": "need pgstattuple",
            }
        ),
    ):
        data = await insights.get_table_bloat("public", "orders")
    assert data["error"] == "extension_required:pgstattuple"


@pytest.mark.asyncio
async def test_list_active_queries_builds_running_filter():
    driver = MagicMock()
    captured: dict[str, Any] = {}

    async def capture(sql_driver, query, params=None):
        captured["query"] = query
        captured["params"] = params
        return []

    with patch.object(SafeSqlDriver, "execute_param_query", new=AsyncMock(side_effect=capture)):
        await OpsInsights(driver).list_active_queries(mode="running", min_duration_seconds=1.5, limit=10)
    assert "state = 'active'" in captured["query"]
    assert "wait_event IS NULL" in captured["query"]
    assert captured["params"] == [1.5, 10]


def test_facts_summary_marks_stale_stats():
    text = facts_summary(
        {
            "user_schemas": 2,
            "tables": 10,
            "size": "1 GB",
            "estimated_rows": 100000,
            "live_tuples_stat": 100,
            "connections": 3,
            "max_connections": 100,
            "stats_stale": True,
        }
    )
    assert "stats may be stale" in text
