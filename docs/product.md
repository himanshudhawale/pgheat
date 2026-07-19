# Product scope

## Problem

PostgreSQL exposes cumulative activity counters per relation. A leaf partition
is a relation, so operators can inspect its scans, tuple changes, and block I/O.
The database does not retain a time series of those values or classify
partitions by current activity.

Looking only at raw totals is unsafe. An old partition can have the largest
scan count while receiving no current traffic. A statistics reset can make a
busy partition appear unused. A monthly reporting partition can look dormant
between scheduled runs.

## Users

- Database administrators evaluating partition retention and storage policies.
- Platform engineers operating PostgreSQL fleets.
- SREs investigating uneven partition activity.
- Extension and archival-tool authors needing an explainable heat signal.

## Goals

1. Measure recent partition activity using standard PostgreSQL statistics.
2. Preserve enough history to distinguish lifetime totals from current heat.
3. Classify activity without hiding the contributing signals.
4. Detect insufficient or invalid evidence.
5. Produce recommendations that require operator approval.

## Non-goals for the first release

- Moving partitions between tablespaces.
- Exporting data to object storage.
- Detaching, dropping, compressing, or restoring partitions.
- Intercepting or rewriting application queries.
- Replacing PostgreSQL monitoring platforms.
- Claiming row-level or unique-block access precision.

## First-release requirements

### Discovery

- Discover leaf partitions through `pg_partition_tree`.
- Record the parent, relation OID, relation file identity, schema, and name.
- Detect partitions created, detached, dropped, or rewritten between samples.

### Collection

- Capture related statistics in one consistent transaction.
- Store the observation timestamp and source-database identity.
- Preserve raw counters so calculations can be reproduced.
- Recognize counter decreases and collection gaps.

### Analysis

- Calculate rates only between compatible samples.
- Track read, write, recency, and cache signals separately.
- Use configurable observation windows.
- Explain the evidence behind every state.
- Report confidence based on observation duration and sample quality.

### Safety

- Use a read-only database role where supported.
- Never execute partition DDL.
- Never infer coldness from missing data.
- Make all recommendations advisory.

## Success criteria

The first release is useful when it can run against a reproducible partitioned
workload and:

- distinguish actively read, actively written, and inactive partitions;
- detect observable PostgreSQL statistics resets without false cold
  classifications;
- explain each result using stored samples; and
- produce the same result when historical samples are replayed.
