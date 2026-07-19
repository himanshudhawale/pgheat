"""Reset-safe interval derivation and explainable temperature classification."""

from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from pgheat.models import (
    COUNTER_FIELDS,
    Classification,
    Derivation,
    Interval,
    PartitionSample,
    Thresholds,
)


def derive_interval(
    previous: PartitionSample,
    current: PartitionSample,
    *,
    maximum_gap: timedelta,
) -> Derivation:
    """Derive activity when two samples have continuous, monotonic identity."""

    if previous.source_id != current.source_id or (
        previous.database_oid != current.database_oid
    ):
        return Derivation("identity_changed", "source database identity changed")
    if previous.relid != current.relid:
        return Derivation("identity_changed", "relation OID changed")
    if previous.relfilenode != current.relfilenode:
        return Derivation("identity_changed", "relation file identity changed")

    elapsed = (current.collected_at - previous.collected_at).total_seconds()
    if elapsed <= 0:
        return Derivation(
            "non_monotonic_time",
            "sample timestamp did not advance",
        )
    if elapsed > maximum_gap.total_seconds():
        return Derivation(
            "collection_gap",
            f"sample gap of {elapsed:.0f}s exceeds "
            f"{maximum_gap.total_seconds():.0f}s",
        )

    deltas: dict[str, int] = {}
    for field in COUNTER_FIELDS:
        delta = getattr(current, field) - getattr(previous, field)
        if delta < 0:
            return Derivation(
                "counter_reset",
                f"{field} decreased from {getattr(previous, field)} "
                f"to {getattr(current, field)}",
            )
        deltas[field] = delta

    interval = Interval(
        previous=previous,
        current=current,
        elapsed_seconds=elapsed,
        scan_delta=deltas["seq_scan"] + deltas["idx_scan"],
        write_delta=(
            deltas["n_tup_ins"] + deltas["n_tup_upd"] + deltas["n_tup_del"]
        ),
        physical_read_blocks=(
            deltas["heap_blks_read"]
            + deltas["idx_blks_read"]
            + deltas["toast_blks_read"]
        ),
        cache_hit_blocks=(
            deltas["heap_blks_hit"]
            + deltas["idx_blks_hit"]
            + deltas["toast_blks_hit"]
        ),
    )
    return Derivation("ok", "compatible samples", interval)


def classify(
    samples: Sequence[PartitionSample],
    *,
    thresholds: Thresholds,
    maximum_gap: timedelta,
    window: timedelta | None = None,
) -> Classification:
    """Classify the latest contiguous run of compatible sample intervals."""

    if not samples:
        raise ValueError("at least one sample is required")

    ordered = sorted(samples, key=lambda sample: sample.collected_at)
    if window is not None:
        cutoff = ordered[-1].collected_at - window
        ordered = [sample for sample in ordered if sample.collected_at >= cutoff]
    latest = ordered[-1]
    if len(ordered) == 1:
        return _unknown(
            latest,
            reasons=("one sample establishes a baseline but no activity interval",),
            warnings=(),
        )

    contiguous: list[Interval] = []
    warnings: list[str] = []
    for previous, current in zip(ordered, ordered[1:]):
        result = derive_interval(previous, current, maximum_gap=maximum_gap)
        if result.interval is None:
            contiguous.clear()
            warnings.append(result.detail)
            continue
        contiguous.append(result.interval)

    if not contiguous:
        return _unknown(
            latest,
            reasons=("no compatible activity interval is available",),
            warnings=tuple(warnings[-3:]),
        )

    observation_seconds = sum(
        interval.elapsed_seconds for interval in contiguous
    )
    scan_delta = sum(interval.scan_delta for interval in contiguous)
    write_delta = sum(interval.write_delta for interval in contiguous)
    physical_reads = sum(
        interval.physical_read_blocks for interval in contiguous
    )
    cache_hits = sum(interval.cache_hit_blocks for interval in contiguous)
    block_touches = physical_reads + cache_hits

    scans_per_hour = _hourly(scan_delta, observation_seconds)
    writes_per_hour = _hourly(write_delta, observation_seconds)
    touches_per_hour = _hourly(block_touches, observation_seconds)
    physical_reads_per_hour = _hourly(physical_reads, observation_seconds)
    cache_hits_per_hour = _hourly(cache_hits, observation_seconds)

    last_interval_activity = max(
        (
            interval.current.collected_at
            for interval in contiguous
            if interval.scan_delta > 0
            or interval.write_delta > 0
            or interval.block_touches > 0
        ),
        default=None,
    )
    source_last_read = max(
        (
            sample.last_read
            for sample in ordered
            if sample.last_read is not None
        ),
        default=None,
    )
    last_access = max(
        (
            value
            for value in (last_interval_activity, source_last_read)
            if value is not None
        ),
        default=None,
    )

    reasons = (
        f"{scan_delta} scans across {_duration(observation_seconds)}",
        f"{write_delta} row changes across {_duration(observation_seconds)}",
        f"{block_touches} repeated block touches across "
        f"{_duration(observation_seconds)}",
    )

    hot_reasons: list[str] = []
    if scans_per_hour >= thresholds.hot_scans_per_hour:
        hot_reasons.append(
            f"scan rate {scans_per_hour:.1f}/h meets hot boundary "
            f"{thresholds.hot_scans_per_hour:.1f}/h"
        )
    if writes_per_hour >= thresholds.hot_writes_per_hour:
        hot_reasons.append(
            f"write rate {writes_per_hour:.1f}/h meets hot boundary "
            f"{thresholds.hot_writes_per_hour:.1f}/h"
        )
    if touches_per_hour >= thresholds.hot_block_touches_per_hour:
        hot_reasons.append(
            f"block-touch rate {touches_per_hour:.1f}/h meets hot boundary "
            f"{thresholds.hot_block_touches_per_hour:.1f}/h"
        )

    enough_observation = (
        observation_seconds >= thresholds.minimum_observation_seconds
    )
    any_activity = scan_delta > 0 or write_delta > 0 or block_touches > 0

    if hot_reasons:
        state = "HOT"
        reasons = tuple(hot_reasons) + reasons
    elif any_activity:
        state = "WARM"
    elif observation_seconds >= thresholds.dormant_after_seconds:
        state = "DORMANT"
        reasons = (
            f"no measured activity for {_duration(observation_seconds)}",
        )
    elif observation_seconds >= thresholds.cold_after_seconds:
        state = "COLD"
        reasons = (
            f"no measured activity for {_duration(observation_seconds)}",
        )
    else:
        state = "UNKNOWN"
        reasons = (
            f"no activity observed, but {_duration(observation_seconds)} "
            f"is shorter than the cold boundary "
            f"{_duration(thresholds.cold_after_seconds)}",
        )

    if not enough_observation and state in {"HOT", "WARM"}:
        warnings.append(
            f"observation window is shorter than "
            f"{_duration(thresholds.minimum_observation_seconds)}"
        )

    confidence = _confidence(
        state=state,
        observation_seconds=observation_seconds,
        thresholds=thresholds,
        warning_count=len(warnings),
    )
    return Classification(
        state=state,
        confidence=confidence,
        reasons=tuple(reasons),
        warnings=tuple(warnings[-3:]),
        observation_seconds=observation_seconds,
        scans_per_hour=scans_per_hour,
        writes_per_hour=writes_per_hour,
        block_touches_per_hour=touches_per_hour,
        physical_reads_per_hour=physical_reads_per_hour,
        cache_hits_per_hour=cache_hits_per_hour,
        last_access=last_access,
        latest_sample=latest,
    )


def _unknown(
    latest: PartitionSample,
    *,
    reasons: tuple[str, ...],
    warnings: tuple[str, ...],
) -> Classification:
    return Classification(
        state="UNKNOWN",
        confidence="low",
        reasons=reasons,
        warnings=warnings,
        observation_seconds=0,
        scans_per_hour=0,
        writes_per_hour=0,
        block_touches_per_hour=0,
        physical_reads_per_hour=0,
        cache_hits_per_hour=0,
        last_access=latest.last_read,
        latest_sample=latest,
    )


def _hourly(value: int, seconds: float) -> float:
    return value * 3600 / seconds


def _duration(seconds: float) -> str:
    if seconds >= 86400:
        return f"{seconds / 86400:.1f}d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"


def _confidence(
    *,
    state: str,
    observation_seconds: float,
    thresholds: Thresholds,
    warning_count: int,
) -> str:
    if state == "UNKNOWN" or warning_count > 0:
        return "low"
    if observation_seconds < thresholds.minimum_observation_seconds:
        return "low"
    if state in {"COLD", "DORMANT"}:
        return "high"
    if observation_seconds >= thresholds.cold_after_seconds:
        return "high"
    return "medium"
