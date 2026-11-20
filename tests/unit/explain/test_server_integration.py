from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytest_asyncio
from mcp.server.fastmcp.exceptions import ToolError

from postgres_mcp.artifacts import ExplainPlanArtifact
from postgres_mcp.artifacts import PlanNode
from postgres_mcp.server import explain_query


@pytest_asyncio.fixture
async def mock_safe_sql_driver():
    """Create a mock SafeSqlDriver for testing."""
    driver = MagicMock()
    return driver


def _plan_artifact(node_type: str = "Seq Scan", execution_time: float | None = None) -> ExplainPlanArtifact:
    tree = PlanNode(
        node_type=node_type,
        total_cost=1.0,
        startup_cost=0.0,
        plan_rows=1,
        plan_width=1,
    )
    return ExplainPlanArtifact(value="{}", plan_tree=tree, execution_time=execution_time)


def _patch_explain_tool(**method_returns):
    """Build an ExplainPlanTool patch whose async methods return plan artifacts."""
    tool = MagicMock()
    tool.explain = AsyncMock(return_value=method_returns.get("explain"))
    tool.explain_analyze = AsyncMock(return_value=method_returns.get("explain_analyze"))
    tool.explain_with_hypothetical_indexes = AsyncMock(
        return_value=method_returns.get("explain_with_hypothetical_indexes")
    )
    return patch("postgres_mcp.server.ExplainPlanTool", return_value=tool)


@pytest.mark.asyncio
async def test_explain_query_integration():
    """Test the entire explain_query tool end-to-end."""
    plan = _plan_artifact("Seq Scan")

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock()),
        _patch_explain_tool(explain=plan),
    ):
        result = await explain_query("SELECT * FROM users", analyze=False, hypothetical_indexes=[])

    assert isinstance(result, list)
    assert "Seq Scan" in result[0].text


@pytest.mark.asyncio
async def test_explain_query_with_analyze_integration():
    """Test the explain_query tool with analyze=True."""
    plan = _plan_artifact("Seq Scan", execution_time=1.23)

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock()),
        _patch_explain_tool(explain_analyze=plan),
    ):
        result = await explain_query("SELECT * FROM users", analyze=True, hypothetical_indexes=[])

    assert isinstance(result, list)
    assert "Execution Time" in result[0].text


@pytest.mark.asyncio
async def test_explain_query_with_hypothetical_indexes_integration():
    """Test the explain_query tool with hypothetical indexes."""
    plan = _plan_artifact("Index Scan")
    test_sql = "SELECT * FROM users WHERE email = 'test@example.com'"
    test_indexes = [{"table": "users", "columns": ["email"]}]

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock(return_value=MagicMock())),
        patch(
            "postgres_mcp.server.check_hypopg_installation_status",
            AsyncMock(return_value=(True, "")),
        ),
        _patch_explain_tool(explain_with_hypothetical_indexes=plan),
    ):
        result = await explain_query(test_sql, analyze=False, hypothetical_indexes=test_indexes)

    assert isinstance(result, list)
    assert "Index Scan" in result[0].text


@pytest.mark.asyncio
async def test_explain_query_missing_hypopg_integration():
    """Test the explain_query tool when hypopg extension is missing."""
    missing_ext_message = "extension is required"
    test_sql = "SELECT * FROM users WHERE email = 'test@example.com'"
    test_indexes = [{"table": "users", "columns": ["email"]}]

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock(return_value=MagicMock())),
        patch(
            "postgres_mcp.server.check_hypopg_installation_status",
            AsyncMock(return_value=(False, missing_ext_message)),
        ),
        _patch_explain_tool(),
    ):
        result = await explain_query(test_sql, analyze=False, hypothetical_indexes=test_indexes)

    assert isinstance(result, list)
    assert missing_ext_message in result[0].text


@pytest.mark.asyncio
async def test_explain_query_error_handling_integration():
    """Tool failures raise ToolError so MCP clients get isError=true."""
    error_message = "Error executing query"

    with patch(
        "postgres_mcp.server.get_sql_driver",
        side_effect=Exception(error_message),
    ):
        with pytest.raises(ToolError, match=error_message):
            await explain_query("INVALID SQL", analyze=False, hypothetical_indexes=[])


@pytest.mark.asyncio
async def test_explain_query_rejects_analyze_with_hypothetical_indexes():
    """analyze + hypothetical indexes is invalid and must surface as ToolError."""
    with patch("postgres_mcp.server.get_sql_driver", AsyncMock()):
        with pytest.raises(ToolError, match="Cannot use analyze and hypothetical indexes together"):
            await explain_query(
                "SELECT 1",
                analyze=True,
                hypothetical_indexes=[{"table": "users", "columns": ["id"]}],
            )
