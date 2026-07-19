# Development

## Requirements

- Python 3.11 or newer
- PostgreSQL 16 or newer for live collection

Install the package in editable mode:

```shell
python -m pip install -e .
```

Run the deterministic local tests:

```shell
python -m unittest discover -v
```

The tests use temporary SQLite databases and require no running PostgreSQL
server. The SQL fixture at `tests/fixtures/workload.sql` creates a small
partitioned workload for live collector validation.

## Live validation

Load the fixture into a disposable PostgreSQL 16+ database:

```shell
psql "$PGHEAT_DSN" -f tests/fixtures/workload.sql
pgheat doctor
pgheat --store ./fixture.db collect --parent public.events

psql "$PGHEAT_DSN" -c \
  "SELECT count(*) FROM events WHERE occurred_at < '2026-02-01'"

pgheat --store ./fixture.db collect --parent public.events
pgheat --store ./fixture.db top --parent public.events
```

The January partition should show read activity after the second collection.
Exact rates depend on PostgreSQL statistics flush timing and cache state.

## Project layout

```text
src/pgheat/collector.py  PostgreSQL discovery and sampling
src/pgheat/store.py      immutable SQLite history
src/pgheat/analysis.py   interval derivation and classification
src/pgheat/doctor.py     capability diagnostics
src/pgheat/cli.py        command-line interface
tests/                   deterministic tests and workload fixture
```
