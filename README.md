# pgheat

Explainable hot, warm, and cold partition classification for PostgreSQL.

> **Status:** design phase. pgheat does not move or delete data. The first
> release will observe PostgreSQL statistics and produce read-only findings.

PostgreSQL already records useful counters for every leaf partition because
each partition is a physical relation. Those counters are cumulative, can
reset, and do not answer operational questions by themselves:

- Which partitions are active now rather than historically?
- Is a partition read-heavy, write-heavy, or merely cached?
- Has a cold partition become active again?
- Is there enough evidence to recommend a storage change?

pgheat will sample the built-in counters, calculate activity over explicit time
windows, retain history, and explain every temperature classification.

## Intended experience

```text
$ pgheat top --parent public.events --window 24h

PARTITION        STATE  READS/H  WRITES/H  LAST ACCESS  CONFIDENCE
events_2026_07   HOT      8,412       936  4s ago       high
events_2026_06   WARM       284         0  18m ago      high
events_2025_12   COLD         2         0  11d ago      medium
events_2024_01   DORMANT      0         0  124d ago     high

$ pgheat explain public.events_2025_12

State: COLD
Why:
  - 2 scans during the last 30 days
  - no writes during the last 30 days
  - 0.03% estimated block touches per hour
  - observed continuously for 45 days
Recommendation: collect 15 more days before considering archival
```

The values above illustrate the planned interface; they are not produced by an
implementation yet.

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

## Initial scope

pgheat will target PostgreSQL 16 and newer and inspect declaratively partitioned
tables. The first useful milestone includes:

1. Periodic snapshots of per-partition table and I/O counters.
2. Reset-safe delta calculation between samples.
3. Historical read, write, and recency signals.
4. Explainable `HOT`, `WARM`, `COLD`, and `DORMANT` classifications.
5. A CLI for ranking and explaining partitions.

Seasonality detection, storage recommendations, dashboards, and cold-storage
integrations come later.

## Documentation

- [Product scope](docs/product.md)
- [Architecture](docs/architecture.md)
- [Metric semantics](docs/metrics.md)
- [Roadmap](docs/roadmap.md)
- [ADR-0001: external collector first](docs/decisions/0001-external-collector-first.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache-2.0
