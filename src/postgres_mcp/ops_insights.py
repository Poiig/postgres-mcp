"""Read-only ops insights: sizes, duplicate indexes, autovacuum, bloat, quals, settings.

Extension-gated helpers call check_extension before querying.
"""

from __future__ import annotations

from typing import Any
from typing import Literal

from .sql import SafeSqlDriver
from .sql import SqlDriver
from .sql.extension_utils import check_extension

# Common tuning knobs only; avoid dumping all of pg_settings into the model.
_SETTINGS_WHITELIST = (
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "hash_mem_multiplier",
    "max_connections",
    "random_page_cost",
    "effective_io_concurrency",
    "maintenance_io_concurrency",
    "max_parallel_workers",
    "max_parallel_workers_per_gather",
    "max_worker_processes",
    "checkpoint_timeout",
    "max_wal_size",
    "min_wal_size",
    "wal_compression",
    "track_io_timing",
    "track_activities",
    "track_counts",
    "log_min_duration_statement",
    "shared_preload_libraries",
    "autovacuum",
    "autovacuum_max_workers",
    "autovacuum_naptime",
    "autovacuum_vacuum_threshold",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_analyze_threshold",
    "autovacuum_analyze_scale_factor",
    "autovacuum_vacuum_cost_delay",
    "autovacuum_vacuum_cost_limit",
    "autovacuum_work_mem",
)


class OpsInsights:
    """Bundle common read-only ops queries for thin MCP tool wrappers."""

    def __init__(self, sql_driver: SqlDriver):
        self.sql_driver = sql_driver

    async def _extension_gate(self, name: str) -> dict[str, Any] | None:
        """Return an install hint when the extension is missing; else None."""
        status = await check_extension(self.sql_driver, name, include_messages=True, message_type="plain")
        if status.is_installed:
            return None
        return {
            "error": f"extension_required:{name}",
            "extension": name,
            "is_available": status.is_available,
            "default_version": status.default_version,
            "message": status.message or f"Extension {name} is required",
        }

    async def list_relation_sizes(
        self,
        schema_name: str | None = None,
        limit: int = 50,
        include_databases: bool = False,
    ) -> dict[str, Any]:
        """Top tables by size; optionally list database sizes on the instance."""
        lim = max(1, min(int(limit), 500))
        where = [
            "n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')",
            "n.nspname NOT LIKE 'pg_temp_%'",
            "n.nspname NOT LIKE 'pg_toast_temp_%'",
            # r=table m=matview; partition parents are often 0 bytes
            "c.relkind IN ('r', 'm')",
        ]
        params: list[Any] = []
        if schema_name:
            where.append("n.nspname = {}")
            params.append(schema_name)
        params.append(lim)
        rows = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT
                n.nspname AS schema,
                c.relname AS table,
                c.relkind::text AS kind,
                pg_table_size(c.oid) AS table_bytes,
                pg_indexes_size(c.oid) AS indexes_bytes,
                pg_total_relation_size(c.oid) AS total_bytes,
                pg_size_pretty(pg_table_size(c.oid)) AS table_size,
                pg_size_pretty(pg_indexes_size(c.oid)) AS indexes_size,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE {" AND ".join(where)}
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT {{}}
            """,
            params,
        )
        out: dict[str, Any] = {
            "filters": {"schema_name": schema_name, "limit": lim},
            "tables": [dict(r.cells) for r in (rows or [])],
        }
        if include_databases:
            dbs = await self.sql_driver.execute_query(
                """
                SELECT
                    d.datname AS database,
                    pg_catalog.pg_get_userbyid(d.datdba) AS owner,
                    CASE WHEN pg_catalog.has_database_privilege(d.datname, 'CONNECT')
                         THEN pg_catalog.pg_database_size(d.datname)
                         ELSE NULL END AS size_bytes,
                    CASE WHEN pg_catalog.has_database_privilege(d.datname, 'CONNECT')
                         THEN pg_catalog.pg_size_pretty(pg_catalog.pg_database_size(d.datname))
                         ELSE 'No Access' END AS size
                FROM pg_catalog.pg_database d
                WHERE d.datname NOT IN ('template0', 'template1')
                ORDER BY size_bytes DESC NULLS LAST
                LIMIT 51
                """
            )
            db_rows = [dict(r.cells) for r in (dbs or [])]
            # Fetch one extra row so we can tell a full page from truncation.
            out["databases_truncated"] = len(db_rows) > 50
            out["databases"] = db_rows[:50]
        return out

    async def list_duplicate_indexes(
        self,
        schema_name: str | None = "public",
        match: str = "exact",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Duplicate indexes: exact definition match, or shared leading column+opclass."""
        lim = max(1, min(int(limit), 500))
        schema = schema_name or "public"
        if match == "leading":
            # indkey[0]=0 means an expression column; skip those for leading match.
            rows = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                """
                SELECT
                    n.nspname || '.' || t.relname AS table,
                    array_agg(i.relname ORDER BY i.relname) AS indexes,
                    array_agg(pg_get_indexdef(ind.indexrelid) ORDER BY i.relname) AS definitions,
                    COUNT(*) AS dup_count
                FROM pg_index ind
                JOIN pg_class t ON t.oid = ind.indrelid
                JOIN pg_class i ON i.oid = ind.indexrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = {}
                  AND ind.indisvalid
                  AND ind.indkey[0] <> 0
                GROUP BY n.nspname, t.relname, ind.indkey[0], ind.indclass[0]
                HAVING COUNT(*) > 1
                ORDER BY n.nspname, t.relname
                LIMIT {}
                """,
                [schema, lim],
            )
        else:
            # Exact match: opclass + columns + expressions + predicate.
            rows = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                """
                SELECT
                    n.nspname || '.' || t.relname AS table,
                    array_agg(i.relname ORDER BY i.relname) AS indexes,
                    array_agg(pg_get_indexdef(ind.indexrelid) ORDER BY i.relname) AS definitions,
                    COUNT(*) AS dup_count
                FROM pg_index ind
                JOIN pg_class t ON t.oid = ind.indrelid
                JOIN pg_class i ON i.oid = ind.indexrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = {}
                  AND ind.indisvalid
                GROUP BY
                    n.nspname,
                    t.relname,
                    ind.indclass::text,
                    ind.indkey::text,
                    COALESCE(ind.indexprs::text, ''),
                    COALESCE(ind.indpred::text, '')
                HAVING COUNT(*) > 1
                ORDER BY n.nspname, t.relname
                LIMIT {}
                """,
                [schema, lim],
            )
        items = [dict(r.cells) for r in (rows or [])]
        return {
            "filters": {"schema_name": schema, "match": match if match in ("exact", "leading") else "exact", "limit": lim},
            "count": len(items),
            "duplicates": items,
            "note": "Duplicates are not always safe to drop; confirm constraints and workloads first.",
        }

    async def get_autovacuum_info(
        self,
        schema_name: str | None = None,
        dead_ratio: float = 0.2,
        min_tuples: int = 50,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Autovacuum settings, high dead-tuple tables, and recent cleanup."""
        lim = max(1, min(int(limit), 200))
        ratio = max(0.0, min(float(dead_ratio), 1.0))
        min_t = max(0, int(min_tuples))
        settings = await self.sql_driver.execute_query(
            """
            SELECT name, setting, unit, short_desc, context, source
            FROM pg_settings
            WHERE name LIKE 'autovacuum%' OR name IN ('maintenance_work_mem')
            ORDER BY name
            """
        )
        where = ["schemaname NOT IN ('pg_catalog', 'information_schema')"]
        hot_params: list[Any] = []
        if schema_name:
            where.append("schemaname = {}")
            hot_params.append(schema_name)
        hot_params.extend([min_t, ratio, lim])
        hot = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT
                schemaname AS schema,
                relname AS table,
                n_live_tup,
                n_dead_tup,
                CASE WHEN n_live_tup + n_dead_tup > 0
                     THEN ROUND((n_dead_tup::numeric / (n_live_tup + n_dead_tup)) * 100, 2)
                     ELSE 0 END AS dead_pct,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                autovacuum_count,
                autoanalyze_count
            FROM pg_stat_user_tables
            WHERE {" AND ".join(where)}
              AND (n_live_tup + n_dead_tup) > {{}}
              AND CASE WHEN n_live_tup + n_dead_tup > 0
                       THEN n_dead_tup::float8 / (n_live_tup + n_dead_tup)
                       ELSE 0 END > {{}}
            ORDER BY n_dead_tup DESC
            LIMIT {{}}
            """,
            hot_params,
        )
        recent_params: list[Any] = []
        recent_schema = ""
        if schema_name:
            recent_schema = "AND schemaname = {}"
            recent_params.append(schema_name)
        recent_params.append(lim)
        recent = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT
                schemaname AS schema,
                relname AS table,
                n_live_tup,
                n_dead_tup,
                last_autovacuum,
                last_autoanalyze,
                autovacuum_count
            FROM pg_stat_user_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
              {recent_schema}
            ORDER BY last_autovacuum DESC NULLS LAST
            LIMIT {{}}
            """,
            recent_params,
        )
        return {
            "settings": [dict(r.cells) for r in (settings or [])],
            "high_dead_tuple_tables": [dict(r.cells) for r in (hot or [])],
            "recent_autovacuum": [dict(r.cells) for r in (recent or [])],
            "filters": {
                "schema_name": schema_name,
                "dead_ratio": ratio,
                "min_tuples": min_t,
                "limit": lim,
            },
            "note": "High dead-tuple ratio means vacuum is due; VACUUM FULL/repack still needs a maintenance window.",
        }

    async def get_table_bloat(
        self,
        schema_name: str,
        table_name: str,
        approx: bool = True,
    ) -> dict[str, Any]:
        """Single-table bloat via pgstattuple (approx or exact)."""
        gate = await self._extension_gate("pgstattuple")
        if gate:
            return gate
        if not schema_name or not table_name:
            return {"error": "invalid_relation", "message": "schema_name and table_name are required"}
        # quote_ident keeps mixed-case / odd names valid as regclass.
        fn = "pgstattuple_approx" if approx else "pgstattuple"
        rows = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT
                quote_ident({{}}) || '.' || quote_ident({{}}) AS relation,
                s.*
            FROM {fn}((quote_ident({{}}) || '.' || quote_ident({{}}))::regclass) AS s
            """,
            [schema_name, table_name, schema_name, table_name],
        )
        if not rows:
            return {
                "error": "empty_result",
                "relation": f"{schema_name}.{table_name}",
                "function": fn,
            }
        cells = dict(rows[0].cells)
        relation = cells.pop("relation", f"{schema_name}.{table_name}")
        table_len = float(cells.get("table_len") or 0)
        # approx uses approx_tuple_len; exact uses tuple_len
        tuple_len = float(cells.get("tuple_len") or cells.get("approx_tuple_len") or 0)
        bloat = None
        if table_len > 0 and tuple_len >= 0:
            bloat = round(1.0 - (tuple_len / table_len), 4)
        return {
            "relation": relation,
            "function": fn,
            "stats": cells,
            "bloat_estimate": bloat,
            "note": (
                "bloat ≈ 1 - live_tuple_space / table_len (includes dead tuples and free space); "
                "not an automatic VACUUM FULL trigger. Cloud RDS may need vendor support for pgstattuple."
            ),
        }

    async def list_qual_stats(self, limit: int = 50, min_filter: int = 50) -> dict[str, Any]:
        """pg_qualstats predicates plus optional index advisor suggestions."""
        gate = await self._extension_gate("pg_qualstats")
        if gate:
            return gate
        lim = max(1, min(int(limit), 200))
        min_f = max(0, int(min_filter))
        pretty = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            "SELECT * FROM pg_qualstats_pretty LIMIT {}",
            [lim],
        )
        advisors: list[Any] = []
        try:
            adv = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                """
                SELECT v::text AS suggestion
                FROM json_array_elements(
                    pg_qualstats_index_advisor(min_filter => {})->'indexes'
                ) v
                ORDER BY v::text
                LIMIT {}
                """,
                [min_f, lim],
            )
            advisors = [dict(r.cells) for r in (adv or [])]
        except Exception as e:
            # Advisor may be unavailable; predicate list is still useful.
            advisors = [{"error": str(e)}]
        return {
            "extension": "pg_qualstats",
            "predicates": [dict(r.cells) for r in (pretty or [])],
            "index_suggestions": advisors,
            "filters": {"limit": lim, "min_filter": min_f},
            "note": "Stats since last reset/restart; low sample_rate means sampling, not full traffic.",
        }

    async def list_settings(self, names: list[str] | None = None) -> dict[str, Any]:
        """Whitelist-only read of key settings; names is intersected with the whitelist."""
        allowed = set(_SETTINGS_WHITELIST)
        if names:
            wanted = [n for n in names if n in allowed]
            if not wanted:
                return {
                    "error": "no_allowed_names",
                    "message": "None of the requested names are on the whitelist",
                    "whitelist": sorted(allowed),
                }
        else:
            wanted = list(_SETTINGS_WHITELIST)
        # Names come from the whitelist only, never free-form SQL.
        in_list = ", ".join("'" + n.replace("'", "''") + "'" for n in wanted)
        rows = await self.sql_driver.execute_query(
            f"""
            SELECT name, setting, unit, short_desc, context, source, pending_restart
            FROM pg_settings
            WHERE name IN ({in_list})
            ORDER BY name
            """
        )
        return {
            "count": len(rows or []),
            "settings": [dict(r.cells) for r in (rows or [])],
            "whitelist": sorted(allowed),
        }

    async def list_index_usage(
        self,
        schema_name: str | None = None,
        table_name: str | None = None,
        unused_only: bool = False,
        max_scans: int = 50,
        require_table_activity: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Index usage from pg_stat_user_indexes since stats_reset."""
        lim = max(1, min(int(limit), 500))
        scans_cap = max(0, int(max_scans))
        where = ["ui.schemaname IS NOT NULL"]
        params: list[Any] = []
        if schema_name:
            where.append("ui.schemaname = {}")
            params.append(schema_name)
        if table_name:
            where.append("ui.relname = {}")
            params.append(table_name)
        if unused_only:
            where.append("NOT i.indisunique")
            where.append("NOT i.indisprimary")
            where.append("ui.idx_scan <= {}")
            params.append(scans_cap)
            if require_table_activity:
                where.append("(COALESCE(ut.seq_scan, 0) + COALESCE(ut.idx_scan, 0)) > 0")
        params.append(lim)
        rows = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT
                ui.schemaname AS schema,
                ui.relname AS table,
                ui.indexrelname AS index,
                pg_relation_size(ui.indexrelid) AS size_bytes,
                pg_size_pretty(pg_relation_size(ui.indexrelid)) AS size,
                ui.idx_scan,
                ui.idx_tup_read,
                ui.idx_tup_fetch,
                ut.seq_scan AS table_seq_scan,
                ut.idx_scan AS table_idx_scan,
                CASE WHEN COALESCE(ut.seq_scan, 0) + COALESCE(ut.idx_scan, 0) = 0 THEN NULL
                     ELSE ROUND(100.0 * ut.idx_scan / (ut.seq_scan + ut.idx_scan), 2)
                END AS table_index_usage_pct,
                i.indisunique AS is_unique,
                i.indisprimary AS is_primary,
                i.indisvalid AS is_valid,
                LEFT(pg_get_indexdef(ui.indexrelid), 240) AS definition_preview
            FROM pg_stat_user_indexes ui
            JOIN pg_index i ON i.indexrelid = ui.indexrelid
            LEFT JOIN pg_stat_user_tables ut ON ut.relid = ui.relid
            WHERE {" AND ".join(where)}
            ORDER BY ui.idx_scan ASC, pg_relation_size(ui.indexrelid) DESC, ui.indexrelname
            LIMIT {{}}
            """,
            params,
        )
        items = [dict(r.cells) for r in (rows or [])]
        ctx_rows = await self.sql_driver.execute_query(
            """
            SELECT
              (SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()) AS stats_reset,
              (SELECT COUNT(*) FROM pg_stat_user_indexes) AS user_index_count,
              (SELECT COUNT(*) FROM pg_stat_user_indexes WHERE idx_scan = 0) AS zero_scan_index_count,
              (SELECT COUNT(*) FROM pg_stat_user_tables) AS user_table_count,
              (SELECT COUNT(*) FROM pg_stat_user_tables
               WHERE COALESCE(seq_scan, 0) + COALESCE(idx_scan, 0) = 0) AS never_accessed_table_count
            """
        )
        stats_ctx = dict(ctx_rows[0].cells) if ctx_rows else {}
        return {
            "filters": {
                "schema_name": schema_name,
                "table_name": table_name,
                "unused_only": unused_only,
                "max_scans": scans_cap if unused_only else None,
                "require_table_activity": require_table_activity if unused_only else None,
                "limit": lim,
            },
            "stats_context": {
                **stats_ctx,
                "note": (
                    "idx_scan is cumulative since stats_reset (or create/restore). "
                    "Zero scans on never-accessed tables do not mean redundant indexes. "
                    "unused_only defaults to tables that have been accessed."
                ),
            },
            "count": len(items),
            "indexes": items,
        }

    async def list_active_queries(
        self,
        min_duration_seconds: float = 0,
        mode: Literal["running", "waiting", "all"] = "running",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Current activity snapshot from pg_stat_activity (current database)."""
        lim = max(1, min(int(limit), 200))
        where = ["pid <> pg_backend_pid()", "datname = current_database()", "state IS NOT NULL"]
        params: list[Any] = []
        if mode == "running":
            where.append("state = 'active'")
            where.append("wait_event IS NULL")
        elif mode == "waiting":
            where.append("wait_event IS NOT NULL")
        if min_duration_seconds and min_duration_seconds > 0:
            where.append("EXTRACT(EPOCH FROM (now() - query_start)) >= {}")
            params.append(float(min_duration_seconds))
        params.append(lim)
        rows = await SafeSqlDriver.execute_param_query(
            self.sql_driver,
            f"""
            SELECT pid, usename, application_name, client_addr::text AS client,
                   state, wait_event_type, wait_event,
                   ROUND(EXTRACT(EPOCH FROM (now() - query_start))::numeric, 2) AS last_query_age_sec,
                   LEFT(query, 500) AS query
            FROM pg_stat_activity
            WHERE {" AND ".join(where)}
            ORDER BY query_start NULLS LAST
            LIMIT {{}}
            """,
            params,
        )
        items = [dict(r.cells) for r in (rows or [])]
        return {
            "filters": {
                "min_duration_seconds": min_duration_seconds,
                "mode": mode,
                "limit": lim,
            },
            "count": len(items),
            "sessions": items,
        }

    async def get_blocking_queries(self) -> dict[str, Any]:
        """Current blocked/blocking pairs via pg_blocking_pids (slim snapshot)."""
        rows = await self.sql_driver.execute_query(
            """
            SELECT
                blocked.pid AS blocked_pid,
                blocked.usename AS blocked_user,
                blocked.state AS blocked_state,
                ROUND(EXTRACT(EPOCH FROM (now() - blocked.query_start))::numeric, 2) AS blocked_age_sec,
                LEFT(blocked.query, 500) AS blocked_query,
                blocking.pid AS blocking_pid,
                blocking.usename AS blocking_user,
                blocking.state AS blocking_state,
                ROUND(EXTRACT(EPOCH FROM (now() - blocking.query_start))::numeric, 2) AS blocking_age_sec,
                LEFT(blocking.query, 500) AS blocking_query,
                blocked.wait_event_type,
                blocked.wait_event
            FROM pg_stat_activity blocked
            CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocker(pid)
            JOIN pg_stat_activity blocking ON blocking.pid = blocker.pid
            WHERE blocked.datname = current_database()
            ORDER BY blocked.query_start NULLS LAST
            LIMIT 100
            """
        )
        items = [dict(r.cells) for r in (rows or [])]
        return {
            "count": len(items),
            "blocking": items,
            "note": "Snapshot of current lock waits only; empty means no active blocking in this database.",
        }
