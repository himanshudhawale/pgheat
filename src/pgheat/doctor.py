"""PostgreSQL capability and configuration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from pgheat.collector import MINIMUM_SERVER_VERSION, _format_version
from pgheat.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class Check:
    """One diagnostic check with an operator-facing explanation."""

    name: str
    status: str
    detail: str


def diagnose(dsn: str) -> tuple[Check, ...]:
    """Inspect whether a PostgreSQL database can support safe collection."""

    if not dsn.strip():
        raise ConfigurationError(
            "PostgreSQL DSN is required through --dsn or PGHEAT_DSN"
        )

    checks: list[Check] = []
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_setting('server_version_num')::integer
                        AS server_version_num,
                    current_setting('track_counts') AS track_counts,
                    current_setting('stats_fetch_consistency', true)
                        AS stats_fetch_consistency,
                    current_user AS current_user
                """
            )
            settings = cursor.fetchone()
            assert settings is not None

            version = int(settings["server_version_num"])
            checks.append(
                Check(
                    "server-version",
                    "pass" if version >= MINIMUM_SERVER_VERSION else "fail",
                    f"PostgreSQL {_format_version(version)}"
                    + (
                        ""
                        if version >= MINIMUM_SERVER_VERSION
                        else "; version 16 or newer is required"
                    ),
                )
            )

            track_counts = str(settings["track_counts"])
            checks.append(
                Check(
                    "track-counts",
                    "pass" if track_counts == "on" else "fail",
                    f"track_counts={track_counts}",
                )
            )

            cursor.execute(
                """
                SELECT
                    current_setting('is_superuser') = 'on' AS is_superuser,
                    pg_has_role(current_user, 'pg_monitor', 'member')
                        AS has_pg_monitor,
                    pg_has_role(current_user, 'pg_read_all_stats', 'member')
                        AS has_read_all_stats
                """
            )
            roles = cursor.fetchone()
            assert roles is not None
            has_monitoring_role = any(
                bool(roles[name])
                for name in (
                    "is_superuser",
                    "has_pg_monitor",
                    "has_read_all_stats",
                )
            )
            checks.append(
                Check(
                    "monitoring-role",
                    "pass" if has_monitoring_role else "warn",
                    (
                        f"{settings['current_user']} has full statistics access"
                        if has_monitoring_role
                        else f"{settings['current_user']} is not a member of "
                        f"pg_monitor or pg_read_all_stats"
                    ),
                )
            )

            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE relation.relkind = 'p')
                        AS partitioned_tables,
                    count(*) FILTER (
                        WHERE relation.relispartition
                          AND relation.relkind = 'r'
                    ) AS leaf_partitions
                FROM pg_class AS relation
                """
            )
            partitions = cursor.fetchone()
            assert partitions is not None
            leaf_count = int(partitions["leaf_partitions"])
            checks.append(
                Check(
                    "partitions",
                    "pass" if leaf_count > 0 else "warn",
                    f"{partitions['partitioned_tables']} partitioned tables; "
                    f"{leaf_count} leaf partitions",
                )
            )

            cursor.execute(
                """
                SELECT count(*)::bigint AS visible_relations
                FROM pg_stat_all_tables
                """
            )
            stats = cursor.fetchone()
            assert stats is not None
            checks.append(
                Check(
                    "statistics-views",
                    "pass",
                    f"{stats['visible_relations']} relations visible through "
                    f"pg_stat_all_tables",
                )
            )

    return tuple(checks)
