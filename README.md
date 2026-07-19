# pgheat

Explainable hot, warm, and cold partition classification for PostgreSQL.

> **Status:** alpha. pgheat collects and analyzes PostgreSQL statistics. It
> does not move, detach, or delete data.

PostgreSQL already records useful counters for every leaf partition because
each partition is a physical relation. Those counters are cumulative, can
reset, and do not answer operational questions by themselves:

- Which partitions are active now rather than historically?
- Is a partition read-heavy, write-heavy, or merely cached?
- Has a cold partition become active again?
- Is there enough evidence to recommend a storage change?

pgheat will sample the built-in counters, calculate activity over explicit time
windows, retain history, and explain every temperature classification.

## Example output

```text
$ pgheat top --parent public.events --window 24h

PARTITION              STATE  CONF    SCANS/H  WRITES/H  BLOCKS/H
public.events_2026_07  HOT    medium  8412.0   936.0     48210.0
public.events_2026_06  WARM   medium  12.0     0.0       384.0

$ pgheat explain public.events_2025_12

public.events_2025_12: COLD (confidence: high)
Observed: 30.0d
Why:
  - no measured activity for 30.0d
```

Values depend on the configured boundaries and collected workload.

## Install

pgheat requires Python 3.11 or newer and PostgreSQL 16 or newer.

```shell
git clone https://github.com/himanshudhawale/pgheat
cd pgheat
python -m pip install -e .
```

Provide the connection string through the environment rather than shell
history:

```shell
export PGHEAT_DSN='postgresql://pgheat@localhost/app'
pgheat doctor
```

On PowerShell:

```powershell
$env:PGHEAT_DSN = 'postgresql://pgheat@localhost/app'
pgheat doctor
```

## Collect and analyze

Each collection is an immutable baseline or observation. At least two
collections are required to calculate activity:

```shell
pgheat collect
# Wait for the desired sampling interval or run application workload.
pgheat collect

pgheat top
pgheat history public.events_2026_01
pgheat explain public.events_2026_01
```

The default SQLite history is `~/.pgheat/pgheat.db`. Override it globally:

```shell
pgheat --store ./pgheat.db collect
pgheat --store ./pgheat.db --json top
```

Classifications use the most recent 90 days by default. All boundaries are
visible CLI options:

```shell
pgheat top \
  --window 90d \
  --hot-scans-per-hour 100 \
  --hot-writes-per-hour 100 \
  --hot-blocks-per-hour 10000 \
  --cold-after 7d \
  --dormant-after 30d
```

`HOT` and `WARM` indicate measured activity. `COLD` and `DORMANT` require a
continuous inactive observation window. `UNKNOWN` means pgheat does not have
enough compatible evidence.

## Principles

- **Explain classifications.** Never emit an unexplained score.
- **Measure deltas.** Raw lifetime counters do not represent current heat.
- **Treat observable resets as missing evidence.** A detected counter reset
  must not make a partition look cold.
- **Keep dimensions separate.** Read heat, write heat, recency, and cache
  behavior describe different operational risks.
- **Recommend before automating.** Initial releases will never move, detach, or
  delete partitions.
- **Work with managed PostgreSQL.** The initial collector will use standard SQL
  views and require no custom server extension.

## Implemented scope

pgheat targets PostgreSQL 16 and newer and inspects declaratively partitioned
tables. The current release includes:

1. Periodic snapshots of per-partition table and I/O counters.
2. Reset-safe delta calculation between samples.
3. Historical read, write, and recency signals.
4. Explainable `HOT`, `WARM`, `COLD`, and `DORMANT` classifications.
5. A CLI for ranking and explaining partitions.

It also provides `doctor`, text and JSON output, source selection for
multi-database stores, configurable lookback windows, and explicit reset/gap
history.

Seasonality detection, storage recommendations, dashboards, and cold-storage
integrations remain future work.

## Documentation

- [Product scope](docs/product.md)
- [Architecture](docs/architecture.md)
- [Metric semantics](docs/metrics.md)
- [Roadmap](docs/roadmap.md)
- [ADR-0001: external collector first](docs/decisions/0001-external-collector-first.md)
- [ADR-0002: Python implementation](docs/decisions/0002-python-implementation.md)
- [Development](docs/development.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache-2.0
