from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from postgres_mcp.server import AccessMode
from postgres_mcp.server import execute_sql
from postgres_mcp.server import format_error_response
from postgres_mcp.sql.sql_driver import SqlDriver


def test_format_error_response_raises_tool_error():
    """Errors must raise ToolError so MCP marks isError=true."""
    with pytest.raises(ToolError, match="boom"):
        format_error_response("boom")


@pytest.mark.asyncio
async def test_execute_sql_truncates_oversized_result():
    """Restricted mode returns a truncation envelope when row count exceeds max_rows."""
    rows = [SqlDriver.RowResult(cells={"id": i}) for i in range(5)]
    mock_driver = MagicMock()
    mock_driver.max_rows = 3
    mock_driver.execute_query = AsyncMock(return_value=rows)

    with patch("postgres_mcp.server.get_sql_driver", AsyncMock(return_value=mock_driver)):
        result = await execute_sql("SELECT id FROM t")

    text = result[0].text
    assert "truncated" in text
    assert "max_rows" in text
    assert "3" in text


@pytest.mark.asyncio
async def test_execute_sql_validation_failure_is_tool_error():
    """Refused writes must surface as ToolError, not a successful text payload."""
    mock_driver = MagicMock()
    mock_driver.max_rows = 1000
    mock_driver.execute_query = AsyncMock(side_effect=ValueError("Error validating query"))

    with (
        patch("postgres_mcp.server.current_access_mode", AccessMode.RESTRICTED),
        patch("postgres_mcp.server.get_sql_driver", AsyncMock(return_value=mock_driver)),
    ):
        with pytest.raises(ToolError, match="Error validating query"):
            await execute_sql("CREATE TABLE t(i int)")
