# Architecture

## Overview

The first pgheat release is an external collector and analyzer. It connects as
a normal PostgreSQL client and does not load code into the database server.

```text
+----------------------+       +----------------------+
| PostgreSQL           |       | pgheat              |
|                      | SQL   |                     |
| pg_partition_tree    +------>+ collector           |
| pg_stat_all_tables   |       | delta engine        |
| pg_statio_all_tables |       | classifier          |
| pg_class/catalogs    |       | CLI                 |
+----------------------+       +----------+-----------+
                                           |
                                           v
                                +----------------------+
                                | sample store         |
                                | raw counters         |
                                | derived intervals    |
                                | classifications      |
                                +----------------------+
```

## Components

### Collector

The collector discovers leaf partitions and captures catalog identity, size,
table counters, and I/O counters. A collection cycle uses a short transaction:

```sql
BEGIN READ ONLY;
SET LOCAL stats_fetch_consistency = 'snapshot';
-- Read identity and statistics views.
COMMIT;
```

Snapshot consistency prevents different queries in the cycle from observing
different statistics generations. Statistics still arrive asynchronously from
PostgreSQL backends, so a sample is an operational observation rather than a
transactional statement audit. Materializing a complete statistics snapshot can
also be expensive in databases with very large object counts; collection
overhead must be measured as part of the workload fixture.

### Sample store

The store retains immutable raw samples. The initial implementation may use
SQLite for a single collector. Its logical model must remain portable:

```text
server
database
relation_identity
sample
sample_counter
derived_interval
classification
```

Raw samples are never overwritten by derived results. This allows classifier
changes to replay the same evidence.

### Delta engine

The delta engine compares adjacent compatible samples. Samples are incompatible
when:

- a counter decreases;
- a relation OID now identifies a different relation;
- the partition was rewritten or recreated;
- the elapsed interval exceeds the configured maximum gap; or
- either sample is incomplete.

An incompatible pair starts a new baseline. It does not produce a zero-activity
interval.

### Classifier

The classifier consumes derived intervals over an operator-selected window. It
retains independent read, write, recency, and cache signals and emits:

- state;
- confidence;
- observation window;
- contributing evidence; and
- warnings that weaken the result.

Classification thresholds are configuration, not universal constants.

### CLI

The planned CLI supports discovery, ranking, history, and explanation:

```text
pgheat collect
pgheat top
pgheat history SCHEMA.PARTITION
pgheat explain SCHEMA.PARTITION
pgheat doctor
```

`doctor` will identify disabled statistics, insufficient privileges, resets,
large collection gaps, and unsupported PostgreSQL versions.

## Deployment model

The collector can run as a local process, container, or scheduled job. One
logical collector owns a `(server, database)` sampling stream to avoid duplicate
or conflicting histories.

Credentials should grant connection, catalog visibility, and statistics access
only. Membership in PostgreSQL's predefined `pg_monitor` or
`pg_read_all_stats` role provides the intended statistics visibility without
superuser access. Provider-specific managed-service restrictions must be
reported by `doctor`.

## Failure behavior

- **Database unavailable:** record a collection gap; do not synthesize samples.
- **Partial query failure:** reject the collection cycle.
- **Collector restart:** continue from persisted samples.
- **Statistics reset:** begin a new baseline.
- **Partition DDL:** close the old identity and begin a new one.
- **Clock movement:** use UTC wall time for display and monotonic elapsed time
  within a running collector where available.

## Future extension boundary

A server extension could eventually provide exact executor-level relation
attribution or lower-overhead telemetry. That is intentionally outside the
first release because managed PostgreSQL services commonly restrict custom
server extensions.
