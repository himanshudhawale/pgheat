# ADR-0001: External collector first

- **Status:** accepted
- **Date:** 2026-07-18

## Context

Accurate executor-level instrumentation could be implemented as a PostgreSQL
server extension. Custom extensions provide deep access but require native code,
server installation, version-specific maintenance, and privileges unavailable
on many managed PostgreSQL services.

The initial product only needs relation identity, cumulative table statistics,
I/O statistics, size, and periodic history. PostgreSQL exposes those inputs
through standard SQL views.

## Decision

The first pgheat implementation will be an external collector using the
PostgreSQL wire protocol and standard catalog/statistics queries.

It will not require shared libraries, preload configuration, background workers,
or custom planner/executor hooks.

## Consequences

### Positive

- Compatible with a wider range of managed PostgreSQL deployments.
- Failure of pgheat cannot crash the database server.
- Installation and upgrades remain independent of PostgreSQL binaries.
- A read-only privilege model is possible.
- Collection logic can be tested against multiple PostgreSQL versions.

### Negative

- Statistics are cumulative and asynchronously flushed.
- Query fingerprints cannot be mapped exactly to accessed partitions.
- Repeated block accesses are counts, not unique-block telemetry.
- Sampling introduces a tradeoff between resolution and overhead.

## Revisit criteria

Consider an optional server extension only after the external collector is
validated and a concrete requirement cannot be satisfied through standard SQL.
The external collector must remain a supported deployment mode.
