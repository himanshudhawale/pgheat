# Metric semantics

## Source views

pgheat initially uses:

| Source | Purpose |
| --- | --- |
| `pg_partition_tree` | Discover leaf partitions and ancestry |
| `pg_class`, `pg_namespace` | Resolve relation identity and names |
| `pg_stat_all_tables` | Scans, tuple changes, and last-scan timestamps |
| `pg_statio_all_tables` | Heap, index, and TOAST block reads and hits |
| `pg_total_relation_size` | Normalize activity against stored size |
| `pg_stat_database` | Observe whole-database reset timestamps |

PostgreSQL statistics are cumulative and eventually flushed by individual
backends. They are not an exact query audit.

`pg_stat_database.stats_reset` covers whole-database resets. A call to
`pg_stat_reset_single_table_counters` does not update that timestamp, so
per-relation resets must be detected from counter monotonicity.

## Raw counters

For every leaf partition, a sample records at least:

```text
seq_scan
idx_scan
n_tup_ins
n_tup_upd
n_tup_del
heap_blks_read
heap_blks_hit
idx_blks_read
idx_blks_hit
toast_blks_read
toast_blks_hit
total_relation_bytes
last_seq_scan
last_idx_scan
```

Index counters represent all indexes belonging to the partition when obtained
from `pg_statio_all_tables`.

## Derived interval signals

For compatible samples `previous` and `current`:

```text
elapsed_seconds = current.time - previous.time

scan_delta =
    delta(seq_scan) + delta(idx_scan)

write_delta =
    delta(n_tup_ins) + delta(n_tup_upd) + delta(n_tup_del)

physical_read_blocks =
    delta(heap_blks_read) +
    delta(idx_blks_read) +
    delta(toast_blks_read)

cache_hit_blocks =
    delta(heap_blks_hit) +
    delta(idx_blks_hit) +
    delta(toast_blks_hit)

block_touches = physical_read_blocks + cache_hit_blocks
```

Rates divide these deltas by `elapsed_seconds`. Size-normalized rates may divide
block touches by the partition's stored block estimate.

`block_touches` does **not** mean unique blocks. The same block can be counted
many times, so pgheat must not describe this value as partition coverage.

## Temperature dimensions

pgheat does not begin with one opaque heat score.

### Read heat

Evidence includes scan rate, block-touch rate, size-normalized block-touch rate,
and time since the most recent recorded scan.

### Write heat

Evidence includes inserted, updated, and deleted tuple rates. A partition can
be write-hot even if application reads are rare.

### Cache behavior

Physical reads and cache hits remain distinct. A high hit ratio indicates that
PostgreSQL is serving accesses from shared buffers; it does not make the
partition inactive.

### Recency

PostgreSQL 16 and newer expose last sequential and index scan timestamps.
pgheat also retains the last interval with a positive scan, block-touch, or
write delta so that its history survives source-statistics resets.

## States

The first classifier will support:

| State | Meaning |
| --- | --- |
| `HOT` | Sustained activity exceeds the configured hot boundary |
| `WARM` | Meaningful recent activity below the hot boundary |
| `COLD` | Low activity across the required observation window |
| `DORMANT` | No meaningful activity across a longer required window |
| `UNKNOWN` | Evidence is missing, incompatible, or too recent |

`REHEATED` is an event indicating a transition from `COLD` or `DORMANT` to
meaningful activity, not a permanent state.

## Confidence

Confidence reflects evidence quality, not probability that a label is correct.
It considers:

- continuous observation duration;
- percentage of expected samples received;
- resets and incompatible intervals;
- relation-identity continuity; and
- proximity to configured classification boundaries.

A cold-storage recommendation must require both a cold state and sufficient
confidence.

## Known limitations

- Statistics can lag active queries.
- Counters can reset after administrative actions or recovery.
- A reset followed by enough activity between samples can grow a counter past
  its previous value. That reset is not detectable from monotonicity and can
  produce a false activity spike, though it will not produce false coldness.
- A scan count does not describe how much data the scan touched.
- Buffer counters count repeated accesses.
- Prepared statements do not expose parameter values through these views.
- Built-in views do not attribute partition activity to individual query
  fingerprints.
- Short observation windows cannot establish seasonality.
