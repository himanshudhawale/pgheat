# ADR-0002: Python implementation

- **Status:** accepted
- **Date:** 2026-07-18

## Context

The initial pgheat implementation is an external control-plane collector. Its
work consists of PostgreSQL queries, immutable local persistence, interval
analysis, and CLI output. It does not execute in PostgreSQL's process or data
path.

The implementation should be easy to install during the alpha phase, portable
across operating systems, and explicit about its small dependency surface.

## Decision

Implement the first release in Python 3.11 or newer using:

- Psycopg 3 for PostgreSQL connectivity;
- the standard-library `sqlite3` module for sample history;
- the standard-library `argparse` module for the CLI; and
- standard-library `unittest` for deterministic local tests.

## Consequences

### Positive

- No compiler or database-server development headers are required.
- SQLite, CLI parsing, JSON, and tests require no additional packages.
- Psycopg provides PostgreSQL-native types and transaction handling.
- Analysis behavior can be iterated and replayed quickly during alpha.

### Negative

- Python startup and per-row overhead are higher than a compiled collector.
- Packaging a single standalone binary requires an additional release step.
- Large fleets may eventually need bounded concurrency and streaming inserts.

## Revisit criteria

Reconsider the implementation language only after measured collector overhead
or deployment requirements show that Python is the limiting factor. Storage and
analysis contracts must remain stable across any rewrite.
