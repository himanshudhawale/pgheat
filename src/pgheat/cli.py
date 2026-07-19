"""Command-line interface for pgheat."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import psycopg

from pgheat import __version__
from pgheat.analysis import classify, derive_interval
from pgheat.collector import collect
from pgheat.doctor import diagnose
from pgheat.errors import PgheatError, StoreError
from pgheat.models import (
    Classification,
    PartitionSample,
    Thresholds,
)
from pgheat.store import SampleStore


DEFAULT_STORE = str(Path.home() / ".pgheat" / "pgheat.db")
STATE_ORDER = {
    "HOT": 0,
    "WARM": 1,
    "UNKNOWN": 2,
    "COLD": 3,
    "DORMANT": 4,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgheat",
        description=(
            "Explainable hot, warm, and cold partition classification "
            "for PostgreSQL"
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--store",
        default=os.environ.get("PGHEAT_STORE", DEFAULT_STORE),
        help=f"SQLite history path (default: {DEFAULT_STORE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    collect_parser = commands.add_parser(
        "collect",
        help="capture one immutable partition-statistics sample",
    )
    _add_dsn(collect_parser)
    collect_parser.add_argument(
        "--source",
        help="stable source name; defaults to HOST:PORT/DATABASE",
    )
    collect_parser.add_argument(
        "--parent",
        help="limit collection to one SCHEMA.PARTITIONED_TABLE",
    )

    doctor_parser = commands.add_parser(
        "doctor",
        help="check PostgreSQL version, settings, privileges, and partitions",
    )
    _add_dsn(doctor_parser)

    top_parser = commands.add_parser(
        "top",
        help="rank the latest classification for observed partitions",
    )
    _add_source_filter(top_parser)
    _add_analysis_options(top_parser)
    top_parser.add_argument(
        "--parent",
        help="limit results to SCHEMA.PARTITIONED_TABLE",
    )
    top_parser.add_argument("--limit", type=_positive_int, default=20)

    history_parser = commands.add_parser(
        "history",
        help="show derived intervals for one SCHEMA.PARTITION",
    )
    history_parser.add_argument("partition")
    _add_source_filter(history_parser)
    history_parser.add_argument(
        "--max-gap",
        type=_duration,
        default=timedelta(days=1),
        help="largest compatible sample gap (default: 1d)",
    )

    explain_parser = commands.add_parser(
        "explain",
        help="explain the latest classification for one SCHEMA.PARTITION",
    )
    explain_parser.add_argument("partition")
    _add_source_filter(explain_parser)
    _add_analysis_options(explain_parser)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            return _collect(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "top":
            return _top(args)
        if args.command == "history":
            return _history(args)
        if args.command == "explain":
            return _explain(args)
        parser.error(f"unknown command {args.command!r}")
    except (PgheatError, psycopg.Error, sqlite3.Error) as error:
        print(f"pgheat: {error}", file=sys.stderr)
        return 1
    return 2


def _collect(args: argparse.Namespace) -> int:
    collection = collect(
        args.dsn,
        parent=args.parent,
        source_id=args.source,
    )
    with SampleStore(args.store) as store:
        collection_id = store.save_collection(
            collection.source,
            collection.samples,
            collected_at=collection.collected_at,
        )
    result = {
        "collection_id": collection_id,
        "source": collection.source.source_id,
        "collected_at": collection.collected_at.isoformat(),
        "partitions": len(collection.samples),
        "store": args.store,
    }
    if args.json:
        _print_json(result)
    else:
        print(
            f"collected {result['partitions']} partitions from "
            f"{result['source']} into {result['store']} "
            f"(collection {collection_id})"
        )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    checks = diagnose(args.dsn)
    if args.json:
        _print_json([asdict(check) for check in checks])
    else:
        rows = [
            (check.status.upper(), check.name, check.detail)
            for check in checks
        ]
        _print_table(("STATUS", "CHECK", "DETAIL"), rows)
    return 1 if any(check.status == "fail" for check in checks) else 0


def _top(args: argparse.Namespace) -> int:
    with SampleStore(args.store) as store:
        source = store.resolve_source(args.source)
        samples = store.load_samples(
            source.source_id,
            parent=args.parent,
        )
    if not samples:
        raise StoreError("no partition samples match the requested filters")

    classifications = [
        classify(
            group,
            thresholds=_thresholds(args),
            maximum_gap=args.max_gap,
            window=args.window,
        )
        for group in _group_samples(samples).values()
    ]
    classifications.sort(
        key=lambda item: (
            STATE_ORDER[item.state],
            -item.block_touches_per_hour,
            -item.writes_per_hour,
            item.latest_sample.qualified_partition,
        )
    )
    classifications = classifications[: args.limit]

    if args.json:
        _print_json([_classification_dict(item) for item in classifications])
    else:
        rows = [
            (
                item.latest_sample.qualified_partition,
                item.state,
                item.confidence,
                f"{item.scans_per_hour:.1f}",
                f"{item.writes_per_hour:.1f}",
                f"{item.block_touches_per_hour:.1f}",
                _display_time(item.last_access),
                _display_duration(item.observation_seconds),
            )
            for item in classifications
        ]
        _print_table(
            (
                "PARTITION",
                "STATE",
                "CONF",
                "SCANS/H",
                "WRITES/H",
                "BLOCKS/H",
                "LAST ACCESS",
                "OBSERVED",
            ),
            rows,
        )
    return 0


def _history(args: argparse.Namespace) -> int:
    with SampleStore(args.store) as store:
        source = store.resolve_source(args.source)
        samples = store.load_samples(
            source.source_id,
            partition=args.partition,
        )
    if not samples:
        raise StoreError(f"no samples found for {args.partition}")

    rows: list[dict[str, object]] = []
    ordered = sorted(samples, key=lambda sample: sample.collected_at)
    if len(ordered) == 1:
        rows.append(
            {
                "start": None,
                "end": ordered[0].collected_at.isoformat(),
                "status": "baseline",
                "detail": "first sample",
            }
        )
    for previous, current in zip(ordered, ordered[1:]):
        result = derive_interval(
            previous,
            current,
            maximum_gap=args.max_gap,
        )
        row: dict[str, object] = {
            "start": previous.collected_at.isoformat(),
            "end": current.collected_at.isoformat(),
            "status": result.status,
            "detail": result.detail,
        }
        if result.interval is not None:
            row.update(
                {
                    "scans": result.interval.scan_delta,
                    "writes": result.interval.write_delta,
                    "physical_read_blocks": (
                        result.interval.physical_read_blocks
                    ),
                    "cache_hit_blocks": result.interval.cache_hit_blocks,
                }
            )
        rows.append(row)

    if args.json:
        _print_json(rows)
    else:
        table_rows = [
            (
                row["end"],
                row["status"],
                row.get("scans", "-"),
                row.get("writes", "-"),
                row.get("physical_read_blocks", "-"),
                row.get("cache_hit_blocks", "-"),
                row["detail"],
            )
            for row in rows
        ]
        _print_table(
            (
                "INTERVAL END",
                "STATUS",
                "SCANS",
                "WRITES",
                "READ BLOCKS",
                "CACHE HITS",
                "DETAIL",
            ),
            table_rows,
        )
    return 0


def _explain(args: argparse.Namespace) -> int:
    with SampleStore(args.store) as store:
        source = store.resolve_source(args.source)
        samples = store.load_samples(
            source.source_id,
            partition=args.partition,
        )
    if not samples:
        raise StoreError(f"no samples found for {args.partition}")

    classification = classify(
        samples,
        thresholds=_thresholds(args),
        maximum_gap=args.max_gap,
        window=args.window,
    )
    if args.json:
        _print_json(_classification_dict(classification))
    else:
        print(
            f"{classification.latest_sample.qualified_partition}: "
            f"{classification.state} "
            f"(confidence: {classification.confidence})"
        )
        print(
            f"Observed: {_display_duration(classification.observation_seconds)}"
        )
        print("Why:")
        for reason in classification.reasons:
            print(f"  - {reason}")
        if classification.warnings:
            print("Warnings:")
            for warning in classification.warnings:
                print(f"  - {warning}")
    return 0


def _group_samples(
    samples: Sequence[PartitionSample],
) -> dict[tuple[str, str, str, str], list[PartitionSample]]:
    groups: dict[
        tuple[str, str, str, str],
        list[PartitionSample],
    ] = defaultdict(list)
    for sample in samples:
        key = (
            sample.parent_schema_name,
            sample.parent_name,
            sample.partition_schema_name,
            sample.partition_name,
        )
        groups[key].append(sample)
    return groups


def _classification_dict(item: Classification) -> dict[str, object]:
    return {
        "source": item.latest_sample.source_id,
        "parent": item.latest_sample.qualified_parent,
        "partition": item.latest_sample.qualified_partition,
        "state": item.state,
        "confidence": item.confidence,
        "observation_seconds": item.observation_seconds,
        "rates": {
            "scans_per_hour": item.scans_per_hour,
            "writes_per_hour": item.writes_per_hour,
            "block_touches_per_hour": item.block_touches_per_hour,
            "physical_reads_per_hour": item.physical_reads_per_hour,
            "cache_hits_per_hour": item.cache_hits_per_hour,
        },
        "last_access": (
            item.last_access.isoformat() if item.last_access is not None else None
        ),
        "reasons": list(item.reasons),
        "warnings": list(item.warnings),
    }


def _thresholds(args: argparse.Namespace) -> Thresholds:
    return Thresholds(
        hot_scans_per_hour=args.hot_scans_per_hour,
        hot_writes_per_hour=args.hot_writes_per_hour,
        hot_block_touches_per_hour=args.hot_blocks_per_hour,
        minimum_observation_seconds=args.minimum_observation.total_seconds(),
        cold_after_seconds=args.cold_after.total_seconds(),
        dormant_after_seconds=args.dormant_after.total_seconds(),
    )


def _add_dsn(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dsn",
        default=os.environ.get("PGHEAT_DSN", ""),
        help="PostgreSQL connection string (or set PGHEAT_DSN)",
    )


def _add_source_filter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        help="source name when the store contains multiple databases",
    )


def _add_analysis_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--window",
        type=_duration,
        default=timedelta(days=90),
        help="recent history used for classification (default: 90d)",
    )
    parser.add_argument(
        "--max-gap",
        type=_duration,
        default=timedelta(days=1),
        help="largest compatible sample gap (default: 1d)",
    )
    parser.add_argument(
        "--minimum-observation",
        type=_duration,
        default=timedelta(minutes=5),
        help="minimum evidence for active-state confidence (default: 5m)",
    )
    parser.add_argument(
        "--cold-after",
        type=_duration,
        default=timedelta(days=7),
        help="inactive observation required for COLD (default: 7d)",
    )
    parser.add_argument(
        "--dormant-after",
        type=_duration,
        default=timedelta(days=30),
        help="inactive observation required for DORMANT (default: 30d)",
    )
    parser.add_argument(
        "--hot-scans-per-hour",
        type=_nonnegative_float,
        default=100.0,
    )
    parser.add_argument(
        "--hot-writes-per-hour",
        type=_nonnegative_float,
        default=100.0,
    )
    parser.add_argument(
        "--hot-blocks-per-hour",
        type=_nonnegative_float,
        default=10_000.0,
    )


def _duration(value: str) -> timedelta:
    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    if len(value) < 2 or value[-1] not in units:
        raise argparse.ArgumentTypeError(
            f"expected duration such as 30s, 5m, 24h, or 7d; received {value!r}"
        )
    try:
        amount = float(value[:-1])
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid duration {value!r}"
        ) from error
    if amount <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    return timedelta(seconds=amount * units[value[-1]])


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _print_table(headers: Sequence[object], rows: Sequence[Sequence[object]]) -> None:
    text_rows = [[str(value) for value in row] for row in rows]
    widths = [
        max(
            len(str(header)),
            *(len(row[index]) for row in text_rows),
        )
        for index, header in enumerate(headers)
    ]
    print(
        "  ".join(
            str(header).ljust(widths[index])
            for index, header in enumerate(headers)
        )
    )
    print("  ".join("-" * width for width in widths))
    for row in text_rows:
        print(
            "  ".join(
                value.ljust(widths[index])
                for index, value in enumerate(row)
            )
        )


def _display_time(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "-"


def _display_duration(seconds: float) -> str:
    if seconds >= 86400:
        return f"{seconds / 86400:.1f}d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"
