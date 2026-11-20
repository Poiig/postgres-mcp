"""Database-level aggregates without summing truncated table lists."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

_USER_SCHEMA = """
schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
AND schema_name NOT LIKE 'pg_temp_%'
AND schema_name NOT LIKE 'pg_toast_temp_%'
"""

_USER_REL = """
c.relkind = 'r'
AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
AND n.nspname NOT LIKE 'pg_temp_%'
AND n.nspname NOT LIKE 'pg_toast_temp_%'
"""


def _num(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _row(rows) -> dict[str, Any]:
    if not rows:
        return {}
    return {k: _num(v) for k, v in rows[0].cells.items()}


async def load_database_facts(driver) -> dict[str, Any]:
    """Fetch DB size, table count, and estimated rows in one aggregated query."""
    facts = _row(
        await driver.execute_query(
            f"""
            SELECT
              (SELECT count(*) FROM information_schema.schemata WHERE {_USER_SCHEMA}) AS user_schemas,
              (SELECT count(*) FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE {_USER_REL}) AS tables,
              (SELECT COALESCE(sum(c.reltuples), 0)::bigint FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE {_USER_REL}) AS estimated_rows,
              pg_database_size(current_database()) AS size_bytes,
              pg_size_pretty(pg_database_size(current_database())) AS size,
              (SELECT count(*) FROM pg_stat_activity) AS connections,
              current_setting('max_connections')::int AS max_connections,
              current_setting('superuser_reserved_connections')::int AS reserved_connections,
              (SELECT COALESCE(sum(n_live_tup), 0)::bigint FROM pg_stat_user_tables) AS live_tuples_stat,
              (SELECT count(*) FROM pg_stat_user_tables) AS stat_tables
            """
        )
    )
    top = await driver.execute_query(
        f"""
        SELECT n.nspname AS schema, c.relname AS name,
               pg_total_relation_size(c.oid) AS size_bytes,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS size
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE {_USER_REL}
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT 10
        """
    )
    facts["largest_tables"] = [{k: _num(v) for k, v in r.cells.items()} for r in (top or [])]
    facts["estimated_rows_source"] = "pg_class.reltuples"
    facts["size_source"] = "pg_database_size"
    est = int(facts.get("estimated_rows") or 0)
    live = int(facts.get("live_tuples_stat") or 0)
    facts["stats_stale"] = bool(est > 1000 and live * 10 < est)
    return facts


def facts_summary(facts: dict[str, Any]) -> str:
    """One-line overview for the model, including estimate provenance."""
    text = (
        f"schemas={facts.get('user_schemas')} tables={facts.get('tables')} "
        f"size={facts.get('size')} estimated_rows={facts.get('estimated_rows')} "
        f"(reltuples) live_tuples_stat={facts.get('live_tuples_stat')} "
        f"connections={facts.get('connections')}/{facts.get('max_connections')}"
    )
    if facts.get("stats_stale"):
        text += "; n_live_tup << reltuples, stats may be stale"
    return text


async def load_fk_facts(driver, *, limit: int = 100) -> dict[str, Any]:
    """Count FKs via pg_constraint; return one page of detail rows."""
    counts = _row(
        await driver.execute_query(
            """
            SELECT
              count(*) FILTER (WHERE n1.nspname IS DISTINCT FROM n2.nspname) AS cross_schema,
              count(*) FILTER (WHERE n1.nspname IS NOT DISTINCT FROM n2.nspname) AS intra_schema,
              count(*) AS foreign_keys
            FROM pg_constraint con
            JOIN pg_class c1 ON c1.oid = con.conrelid
            JOIN pg_namespace n1 ON n1.oid = c1.relnamespace
            JOIN pg_class c2 ON c2.oid = con.confrelid
            JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
            WHERE con.contype = 'f'
            """
        )
    )
    page = max(1, min(int(limit), 200))
    rows = await driver.execute_query(
        f"""
        SELECT n1.nspname AS from_schema, c1.relname AS from_table,
               n2.nspname AS to_schema, c2.relname AS to_table,
               con.conname AS name
        FROM pg_constraint con
        JOIN pg_class c1 ON c1.oid = con.conrelid
        JOIN pg_namespace n1 ON n1.oid = c1.relnamespace
        JOIN pg_class c2 ON c2.oid = con.confrelid
        JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
        WHERE con.contype = 'f'
        ORDER BY 1, 2, 5
        LIMIT {page + 1}
        """
    )
    items = [{k: _num(v) for k, v in r.cells.items()} for r in (rows or [])]
    truncated = len(items) > page
    return {
        **counts,
        "foreign_keys": int(counts.get("foreign_keys") or 0),
        "items": items[:page],
        "returned": min(len(items), page),
        "limit": page,
        "truncated": truncated,
    }
