"""Tests for stdio connection-pool lifecycle: orphan watchdog and clean exit.

Cover the behavior that stops the server from leaking connections against the
database role when its MCP client is force-killed without closing stdin.
"""

import asyncio
import sys
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_exit_if_orphaned_closes_pool_before_exiting():
    """Once orphaned, close the pool before hard-exiting."""
    from postgres_mcp import server

    order = []
    close_mock = AsyncMock(side_effect=lambda: order.append("close"))
    exit_mock = MagicMock(side_effect=lambda code: order.append(("exit", code)))

    with (
        patch("postgres_mcp.server.os.getppid", return_value=1),
        patch("postgres_mcp.server.db_connection.close", close_mock),
        patch("postgres_mcp.server.os._exit", exit_mock),
    ):
        await server.exit_if_orphaned(poll_interval=0.001)

    assert order == ["close", ("exit", 0)]


@pytest.mark.asyncio
async def test_exit_if_orphaned_waits_until_orphaned():
    """While the parent is alive, keep polling without closing or exiting."""
    from postgres_mcp import server

    ppids = iter([1234, 1234, 1])  # alive twice, then reparented to init

    def fake_getppid():
        return next(ppids)

    close_mock = AsyncMock()
    exit_mock = MagicMock()

    with (
        patch("postgres_mcp.server.os.getppid", side_effect=fake_getppid),
        patch("postgres_mcp.server.db_connection.close", close_mock),
        patch("postgres_mcp.server.os._exit", exit_mock),
    ):
        await server.exit_if_orphaned(poll_interval=0.001)

    close_mock.assert_awaited_once()
    exit_mock.assert_called_once_with(0)


async def _run_main_capturing_tasks(transport, created):
    """Run main() and record tasks spawned via asyncio.ensure_future."""
    from postgres_mcp.server import main

    real_ensure_future = asyncio.ensure_future

    def spy(coro, *args, **kwargs):
        task = real_ensure_future(coro, *args, **kwargs)
        created.append(task)
        return task

    original_argv = sys.argv
    sys.argv = ["postgres_mcp", "postgresql://user:password@localhost/db", f"--transport={transport}"]
    try:
        with (
            patch("postgres_mcp.server.os.getppid", return_value=99999),
            patch("postgres_mcp.server.db_connection.pool_connect", AsyncMock()),
            patch("postgres_mcp.server.db_connection.close", AsyncMock()),
            patch("postgres_mcp.server.mcp.run_stdio_async", AsyncMock()),
            patch("postgres_mcp.server.mcp.run_sse_async", AsyncMock()),
            patch("postgres_mcp.server.mcp.run_streamable_http_async", AsyncMock()),
            patch("postgres_mcp.server.asyncio.ensure_future", side_effect=spy),
        ):
            await main()
    finally:
        sys.argv = original_argv


@pytest.mark.asyncio
async def test_stdio_starts_watchdog_and_cancels_it_on_clean_exit():
    """stdio starts one watchdog and cancels it when the transport returns."""
    created = []
    await _run_main_capturing_tasks("stdio", created)

    assert len(created) == 1, "stdio should start exactly one watchdog task"
    with pytest.raises(asyncio.CancelledError):
        await created[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
async def test_non_stdio_transports_do_not_start_watchdog(transport):
    """Orphan watchdog is stdio-only; HTTP transports must not start it."""
    created = []
    await _run_main_capturing_tasks(transport, created)

    assert created == [], f"{transport} must not start the orphan watchdog"
