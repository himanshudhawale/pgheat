"""Immutable SQLite persistence for PostgreSQL partition samples."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pgheat.errors import StoreError
from pgheat.models import PartitionSample, Source


SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    database_name TEXT NOT NULL,
    database_oid INTEGER NOT NULL,
    server_version_num INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    collected_at TEXT NOT NULL,
    partition_count INTEGER NOT NULL,
    UNIQUE(source_id, collected_at)
);

CREATE TABLE IF NOT EXISTS partition_samples (
    collection_id INTEGER NOT NULL REFERENCES collections(collection_id),
    source_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    database_oid INTEGER NOT NULL,
    relid INTEGER NOT NULL,
    relfilenode INTEGER NOT NULL,
    parent_relid INTEGER NOT NULL,
    parent_schema_name TEXT NOT NULL,
    partition_schema_name TEXT NOT NULL,
    parent_name TEXT NOT NULL,
    partition_name TEXT NOT NULL,
    total_relation_bytes INTEGER NOT NULL,
    seq_scan INTEGER NOT NULL,
    idx_scan INTEGER NOT NULL,
    n_tup_ins INTEGER NOT NULL,
    n_tup_upd INTEGER NOT NULL,
    n_tup_del INTEGER NOT NULL,
    heap_blks_read INTEGER NOT NULL,
    heap_blks_hit INTEGER NOT NULL,
    idx_blks_read INTEGER NOT NULL,
    idx_blks_hit INTEGER NOT NULL,
    toast_blks_read INTEGER NOT NULL,
    toast_blks_hit INTEGER NOT NULL,
    last_seq_scan TEXT,
    last_idx_scan TEXT,
    PRIMARY KEY(collection_id, relid)
);

CREATE INDEX IF NOT EXISTS partition_samples_lookup
ON partition_samples(
    source_id, partition_schema_name, partition_name, collected_at
);

CREATE INDEX IF NOT EXISTS partition_samples_parent
ON partition_samples(source_id, parent_schema_name, parent_name, collected_at);
"""

INSERT_SAMPLE = """
INSERT INTO partition_samples (
    collection_id, source_id, collected_at, database_oid, relid, relfilenode,
    parent_relid, parent_schema_name, partition_schema_name, parent_name,
    partition_name,
    total_relation_bytes, seq_scan, idx_scan, n_tup_ins, n_tup_upd, n_tup_del,
    heap_blks_read, heap_blks_hit, idx_blks_read, idx_blks_hit,
    toast_blks_read, toast_blks_hit, last_seq_scan, last_idx_scan
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
)
"""


class SampleStore:
    """Owns the local SQLite history used by analysis commands."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def __enter__(self) -> SampleStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def save_collection(
        self,
        source: Source,
        samples: Iterable[PartitionSample],
        *,
        collected_at: datetime,
    ) -> int:
        materialized = list(samples)
        for sample in materialized:
            if sample.source_id != source.source_id:
                raise StoreError(
                    f"sample source {sample.source_id!r} does not match "
                    f"{source.source_id!r}"
                )
            if sample.collected_at != collected_at:
                raise StoreError("all samples must share the collection timestamp")

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO sources (
                    source_id, host, port, database_name, database_oid,
                    server_version_num, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    host = excluded.host,
                    port = excluded.port,
                    database_name = excluded.database_name,
                    database_oid = excluded.database_oid,
                    server_version_num = excluded.server_version_num
                """,
                (
                    source.source_id,
                    source.host,
                    source.port,
                    source.database_name,
                    source.database_oid,
                    source.server_version_num,
                    collected_at.isoformat(),
                ),
            )
            cursor = self.connection.execute(
                """
                INSERT INTO collections (
                    source_id, collected_at, partition_count
                ) VALUES (?, ?, ?)
                """,
                (
                    source.source_id,
                    collected_at.isoformat(),
                    len(materialized),
                ),
            )
            collection_id = int(cursor.lastrowid)
            self.connection.executemany(
                INSERT_SAMPLE,
                (
                    (
                        collection_id,
                        sample.source_id,
                        sample.collected_at.isoformat(),
                        sample.database_oid,
                        sample.relid,
                        sample.relfilenode,
                        sample.parent_relid,
                        sample.parent_schema_name,
                        sample.partition_schema_name,
                        sample.parent_name,
                        sample.partition_name,
                        sample.total_relation_bytes,
                        sample.seq_scan,
                        sample.idx_scan,
                        sample.n_tup_ins,
                        sample.n_tup_upd,
                        sample.n_tup_del,
                        sample.heap_blks_read,
                        sample.heap_blks_hit,
                        sample.idx_blks_read,
                        sample.idx_blks_hit,
                        sample.toast_blks_read,
                        sample.toast_blks_hit,
                        _iso(sample.last_seq_scan),
                        _iso(sample.last_idx_scan),
                    )
                    for sample in materialized
                ),
            )
        return collection_id

    def list_sources(self) -> list[Source]:
        rows = self.connection.execute(
            """
            SELECT source_id, host, port, database_name, database_oid,
                   server_version_num
            FROM sources
            ORDER BY source_id
            """
        ).fetchall()
        return [
            Source(
                source_id=row["source_id"],
                host=row["host"],
                port=row["port"],
                database_name=row["database_name"],
                database_oid=row["database_oid"],
                server_version_num=row["server_version_num"],
            )
            for row in rows
        ]

    def resolve_source(self, source_id: str | None) -> Source:
        sources = self.list_sources()
        if source_id is not None:
            for source in sources:
                if source.source_id == source_id:
                    return source
            raise StoreError(f"source {source_id!r} was not found in {self.path}")
        if not sources:
            raise StoreError(f"no samples have been collected in {self.path}")
        if len(sources) > 1:
            names = ", ".join(source.source_id for source in sources)
            raise StoreError(f"multiple sources found; choose --source from: {names}")
        return sources[0]

    def load_samples(
        self,
        source_id: str,
        *,
        parent: str | None = None,
        partition: str | None = None,
    ) -> list[PartitionSample]:
        clauses = ["source_id = ?"]
        parameters: list[object] = [source_id]
        if parent is not None:
            schema, name = _split_qualified(parent)
            clauses.extend(["parent_schema_name = ?", "parent_name = ?"])
            parameters.extend([schema, name])
        if partition is not None:
            schema, name = _split_qualified(partition)
            clauses.extend(["partition_schema_name = ?", "partition_name = ?"])
            parameters.extend([schema, name])

        rows = self.connection.execute(
            f"""
            SELECT *
            FROM partition_samples
            WHERE {' AND '.join(clauses)}
            ORDER BY partition_schema_name, partition_name, collected_at
            """,
            parameters,
        ).fetchall()
        return [_sample_from_row(row) for row in rows]

    def _migrate(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise StoreError(
                f"store schema {current} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if current == 0:
            with self.connection:
                self.connection.executescript(SCHEMA)
                self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _sample_from_row(row: sqlite3.Row) -> PartitionSample:
    return PartitionSample(
        source_id=row["source_id"],
        collected_at=datetime.fromisoformat(row["collected_at"]),
        database_oid=row["database_oid"],
        relid=row["relid"],
        relfilenode=row["relfilenode"],
        parent_relid=row["parent_relid"],
        parent_schema_name=row["parent_schema_name"],
        partition_schema_name=row["partition_schema_name"],
        parent_name=row["parent_name"],
        partition_name=row["partition_name"],
        total_relation_bytes=row["total_relation_bytes"],
        seq_scan=row["seq_scan"],
        idx_scan=row["idx_scan"],
        n_tup_ins=row["n_tup_ins"],
        n_tup_upd=row["n_tup_upd"],
        n_tup_del=row["n_tup_del"],
        heap_blks_read=row["heap_blks_read"],
        heap_blks_hit=row["heap_blks_hit"],
        idx_blks_read=row["idx_blks_read"],
        idx_blks_hit=row["idx_blks_hit"],
        toast_blks_read=row["toast_blks_read"],
        toast_blks_hit=row["toast_blks_hit"],
        last_seq_scan=_datetime(row["last_seq_scan"]),
        last_idx_scan=_datetime(row["last_idx_scan"]),
    )


def _split_qualified(value: str) -> tuple[str, str]:
    parts = value.split(".", maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise StoreError(f"expected SCHEMA.NAME, received {value!r}")
    return parts[0], parts[1]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None
