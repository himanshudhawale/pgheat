"""PostgreSQL partition-statistics collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from pgheat.errors import CollectionError, ConfigurationError
from pgheat.models import PartitionSample, Source


MINIMUM_SERVER_VERSION = 160000

PARTITION_QUERY = """
WITH leaf_partitions AS (
    SELECT
        child.oid AS relid,
        pg_partition_root(child.oid) AS parent_relid
    FROM pg_class AS child
    WHERE child.relispartition
      AND child.relkind = 'r'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_inherits AS descendants
          WHERE descendants.inhparent = child.oid
      )
)
SELECT
    leaf.relid,
    COALESCE(pg_relation_filenode(leaf.relid), 0)::bigint AS relfilenode,
    leaf.parent_relid,
    parent_namespace.nspname AS parent_schema_name,
    partition_namespace.nspname AS partition_schema_name,
    parent.relname AS parent_name,
    partition.relname AS partition_name,
    pg_total_relation_size(leaf.relid)::bigint AS total_relation_bytes,
    COALESCE(table_stats.seq_scan, 0)::bigint AS seq_scan,
    COALESCE(table_stats.idx_scan, 0)::bigint AS idx_scan,
    COALESCE(table_stats.n_tup_ins, 0)::bigint AS n_tup_ins,
    COALESCE(table_stats.n_tup_upd, 0)::bigint AS n_tup_upd,
    COALESCE(table_stats.n_tup_del, 0)::bigint AS n_tup_del,
    COALESCE(io_stats.heap_blks_read, 0)::bigint AS heap_blks_read,
    COALESCE(io_stats.heap_blks_hit, 0)::bigint AS heap_blks_hit,
    COALESCE(io_stats.idx_blks_read, 0)::bigint AS idx_blks_read,
    COALESCE(io_stats.idx_blks_hit, 0)::bigint AS idx_blks_hit,
    COALESCE(io_stats.toast_blks_read, 0)::bigint AS toast_blks_read,
    COALESCE(io_stats.toast_blks_hit, 0)::bigint AS toast_blks_hit,
    table_stats.last_seq_scan,
    table_stats.last_idx_scan
FROM leaf_partitions AS leaf
JOIN pg_class AS partition ON partition.oid = leaf.relid
JOIN pg_namespace AS partition_namespace
  ON partition_namespace.oid = partition.relnamespace
JOIN pg_class AS parent ON parent.oid = leaf.parent_relid
JOIN pg_namespace AS parent_namespace
  ON parent_namespace.oid = parent.relnamespace
LEFT JOIN pg_stat_all_tables AS table_stats
  ON table_stats.relid = leaf.relid
LEFT JOIN pg_statio_all_tables AS io_stats
  ON io_stats.relid = leaf.relid
WHERE (%(parent_oid)s::oid IS NULL OR leaf.parent_relid = %(parent_oid)s::oid)
ORDER BY
    parent_namespace.nspname,
    parent.relname,
    partition_namespace.nspname,
    partition.relname
"""


@dataclass(frozen=True, slots=True)
class Collection:
    """A complete collection cycle ready for immutable persistence."""

    source: Source
    collected_at: datetime
    samples: tuple[PartitionSample, ...]


def collect(
    dsn: str,
    *,
    parent: str | None = None,
    source_id: str | None = None,
) -> Collection:
    """Capture one consistent sample of every selected leaf partition."""

    if not dsn.strip():
        raise ConfigurationError(
            "PostgreSQL DSN is required through --dsn or PGHEAT_DSN"
        )

    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SET LOCAL stats_fetch_consistency = 'snapshot'"
                )
                cursor.execute(
                    """
                    SELECT
                        clock_timestamp() AS collected_at,
                        current_database() AS database_name,
                        database.oid::bigint AS database_oid,
                        current_setting('server_version_num')::integer
                            AS server_version_num
                    FROM pg_database AS database
                    WHERE database.datname = current_database()
                    """
                )
                metadata = cursor.fetchone()
                if metadata is None:
                    raise CollectionError("current database metadata was not found")

                version = int(metadata["server_version_num"])
                if version < MINIMUM_SERVER_VERSION:
                    raise CollectionError(
                        f"PostgreSQL 16 or newer is required; server reports "
                        f"{_format_version(version)}"
                    )

                parent_oid = _resolve_parent(cursor, parent)
                cursor.execute(PARTITION_QUERY, {"parent_oid": parent_oid})
                rows = cursor.fetchall()

        host = connection.info.host or "local-socket"
        port = int(connection.info.port)
        database_name = str(metadata["database_name"])
        resolved_source_id = source_id or f"{host}:{port}/{database_name}"
        if not resolved_source_id.strip():
            raise ConfigurationError("--source must not be empty")

        source = Source(
            source_id=resolved_source_id,
            host=host,
            port=port,
            database_name=database_name,
            database_oid=int(metadata["database_oid"]),
            server_version_num=version,
        )
        collected_at = metadata["collected_at"]
        samples = tuple(
            _sample_from_row(
                row,
                source_id=resolved_source_id,
                database_oid=source.database_oid,
                collected_at=collected_at,
            )
            for row in rows
        )
        return Collection(source, collected_at, samples)


def _resolve_parent(
    cursor: psycopg.Cursor[dict[str, object]],
    parent: str | None,
) -> int | None:
    if parent is None:
        return None
    cursor.execute(
        """
        SELECT relation.oid::bigint
        FROM pg_class AS relation
        WHERE relation.oid = to_regclass(%s)
          AND relation.relkind = 'p'
        """,
        (parent,),
    )
    row = cursor.fetchone()
    if row is None:
        raise CollectionError(
            f"partitioned parent {parent!r} was not found or is not "
            f"a declaratively partitioned table"
        )
    return int(row["oid"])


def _sample_from_row(
    row: dict[str, object],
    *,
    source_id: str,
    database_oid: int,
    collected_at: datetime,
) -> PartitionSample:
    relfilenode = int(row["relfilenode"])
    if relfilenode == 0:
        raise CollectionError(
            f"partition {row['partition_schema_name']}."
            f"{row['partition_name']} has no physical relation file identity"
        )
    return PartitionSample(
        source_id=source_id,
        collected_at=collected_at,
        database_oid=database_oid,
        relid=int(row["relid"]),
        relfilenode=relfilenode,
        parent_relid=int(row["parent_relid"]),
        parent_schema_name=str(row["parent_schema_name"]),
        partition_schema_name=str(row["partition_schema_name"]),
        parent_name=str(row["parent_name"]),
        partition_name=str(row["partition_name"]),
        total_relation_bytes=int(row["total_relation_bytes"]),
        seq_scan=int(row["seq_scan"]),
        idx_scan=int(row["idx_scan"]),
        n_tup_ins=int(row["n_tup_ins"]),
        n_tup_upd=int(row["n_tup_upd"]),
        n_tup_del=int(row["n_tup_del"]),
        heap_blks_read=int(row["heap_blks_read"]),
        heap_blks_hit=int(row["heap_blks_hit"]),
        idx_blks_read=int(row["idx_blks_read"]),
        idx_blks_hit=int(row["idx_blks_hit"]),
        toast_blks_read=int(row["toast_blks_read"]),
        toast_blks_hit=int(row["toast_blks_hit"]),
        last_seq_scan=row["last_seq_scan"],
        last_idx_scan=row["last_idx_scan"],
    )


def _format_version(version: int) -> str:
    major = version // 10000
    minor = (version % 10000) // 100
    return f"{major}.{minor}"
