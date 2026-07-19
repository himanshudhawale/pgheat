"""Test data builders."""

from __future__ import annotations

from datetime import UTC, datetime

from pgheat.models import PartitionSample, Source


def source() -> Source:
    return Source(
        source_id="test:5432/postgres",
        host="test",
        port=5432,
        database_name="postgres",
        database_oid=5,
        server_version_num=160000,
    )


def sample(
    *,
    collected_at: datetime | None = None,
    relid: int = 100,
    relfilenode: int = 200,
    seq_scan: int = 0,
    idx_scan: int = 0,
    n_tup_ins: int = 0,
    n_tup_upd: int = 0,
    n_tup_del: int = 0,
    heap_blks_read: int = 0,
    heap_blks_hit: int = 0,
    idx_blks_read: int = 0,
    idx_blks_hit: int = 0,
    toast_blks_read: int = 0,
    toast_blks_hit: int = 0,
) -> PartitionSample:
    timestamp = collected_at or datetime(2026, 1, 1, tzinfo=UTC)
    return PartitionSample(
        source_id="test:5432/postgres",
        collected_at=timestamp,
        database_oid=5,
        relid=relid,
        relfilenode=relfilenode,
        parent_relid=50,
        parent_schema_name="public",
        partition_schema_name="public",
        parent_name="events",
        partition_name="events_2026_01",
        total_relation_bytes=8192 * 100,
        seq_scan=seq_scan,
        idx_scan=idx_scan,
        n_tup_ins=n_tup_ins,
        n_tup_upd=n_tup_upd,
        n_tup_del=n_tup_del,
        heap_blks_read=heap_blks_read,
        heap_blks_hit=heap_blks_hit,
        idx_blks_read=idx_blks_read,
        idx_blks_hit=idx_blks_hit,
        toast_blks_read=toast_blks_read,
        toast_blks_hit=toast_blks_hit,
    )
