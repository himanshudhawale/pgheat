"""Data models shared by collection, persistence, and analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


COUNTER_FIELDS = (
    "seq_scan",
    "idx_scan",
    "n_tup_ins",
    "n_tup_upd",
    "n_tup_del",
    "heap_blks_read",
    "heap_blks_hit",
    "idx_blks_read",
    "idx_blks_hit",
    "toast_blks_read",
    "toast_blks_hit",
)


@dataclass(frozen=True, slots=True)
class Source:
    """A PostgreSQL database observed by one logical sampling stream."""

    source_id: str
    host: str
    port: int
    database_name: str
    database_oid: int
    server_version_num: int


@dataclass(frozen=True, slots=True)
class PartitionSample:
    """One immutable observation of a leaf partition's cumulative counters."""

    source_id: str
    collected_at: datetime
    database_oid: int
    relid: int
    relfilenode: int
    parent_relid: int
    parent_schema_name: str
    partition_schema_name: str
    parent_name: str
    partition_name: str
    total_relation_bytes: int
    seq_scan: int
    idx_scan: int
    n_tup_ins: int
    n_tup_upd: int
    n_tup_del: int
    heap_blks_read: int
    heap_blks_hit: int
    idx_blks_read: int
    idx_blks_hit: int
    toast_blks_read: int
    toast_blks_hit: int
    last_seq_scan: datetime | None = None
    last_idx_scan: datetime | None = None

    @property
    def qualified_parent(self) -> str:
        return f"{self.parent_schema_name}.{self.parent_name}"

    @property
    def qualified_partition(self) -> str:
        return f"{self.partition_schema_name}.{self.partition_name}"

    @property
    def last_read(self) -> datetime | None:
        values = [
            value
            for value in (self.last_seq_scan, self.last_idx_scan)
            if value is not None
        ]
        return max(values, default=None)

    def counters(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in COUNTER_FIELDS}


@dataclass(frozen=True, slots=True)
class Interval:
    """Activity derived from two compatible cumulative samples."""

    previous: PartitionSample
    current: PartitionSample
    elapsed_seconds: float
    scan_delta: int
    write_delta: int
    physical_read_blocks: int
    cache_hit_blocks: int

    @property
    def block_touches(self) -> int:
        return self.physical_read_blocks + self.cache_hit_blocks

    @property
    def scans_per_hour(self) -> float:
        return self.scan_delta * 3600 / self.elapsed_seconds

    @property
    def writes_per_hour(self) -> float:
        return self.write_delta * 3600 / self.elapsed_seconds

    @property
    def block_touches_per_hour(self) -> float:
        return self.block_touches * 3600 / self.elapsed_seconds

    @property
    def physical_reads_per_hour(self) -> float:
        return self.physical_read_blocks * 3600 / self.elapsed_seconds

    @property
    def cache_hits_per_hour(self) -> float:
        return self.cache_hit_blocks * 3600 / self.elapsed_seconds


@dataclass(frozen=True, slots=True)
class Derivation:
    """Result of comparing adjacent samples."""

    status: str
    detail: str
    interval: Interval | None = None


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Operator-visible boundaries used by the initial classifier."""

    hot_scans_per_hour: float = 100.0
    hot_writes_per_hour: float = 100.0
    hot_block_touches_per_hour: float = 10_000.0
    minimum_observation_seconds: float = 300.0
    cold_after_seconds: float = 7 * 24 * 3600.0
    dormant_after_seconds: float = 30 * 24 * 3600.0


@dataclass(frozen=True, slots=True)
class Classification:
    """An explainable classification over contiguous valid evidence."""

    state: str
    confidence: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    observation_seconds: float
    scans_per_hour: float
    writes_per_hour: float
    block_touches_per_hour: float
    physical_reads_per_hour: float
    cache_hits_per_hour: float
    last_access: datetime | None
    latest_sample: PartitionSample
