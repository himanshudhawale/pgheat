# Roadmap

The roadmap advances from trustworthy observation to optional integrations.
Each milestone must remain useful without the next one.

## M0: specification

- [x] Define product boundaries and safety principles.
- [x] Document source statistics and metric limitations.
- [x] Define the external-collector architecture.
- [ ] Validate metric assumptions against PostgreSQL 16, 17, and 18.
- [ ] Create a reproducible partitioned workload fixture.

## M1: collector

- Discover databases, partitioned parents, and leaf partitions.
- Capture consistent raw samples.
- Persist samples locally.
- Detect counter resets, collection gaps, and relation identity changes.
- Add `collect` and `doctor` commands.

## M2: interval analysis

- Calculate reset-safe deltas and rates.
- Retain separate read, write, cache, and recency signals.
- Add `top` and `history` commands.
- Replay stored samples deterministically in tests.

## M3: explainable classification

- Add configurable observation windows and thresholds.
- Emit `HOT`, `WARM`, `COLD`, `DORMANT`, and `UNKNOWN`.
- Report evidence quality and confidence.
- Add `explain` and machine-readable JSON output.

## M4: workload patterns

- Detect reheating events.
- Detect daily, weekly, and monthly seasonality.
- Warn when a proposed cold classification conflicts with a recurring pattern.
- Compare classifications across rolling windows.

## M5: advisory integrations

- Estimate storage occupied by cold candidates.
- Model possible tablespace or object-storage savings.
- Export recommendations for existing archival systems.
- Keep execution opt-in and outside the default read-only path.

## Explicitly deferred

- Automatic partition movement or deletion.
- Transparent object-storage querying.
- A custom PostgreSQL table access method.
- Query-plan hooks requiring a server extension.
