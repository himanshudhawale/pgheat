"""Tests for reset-safe interval derivation and classification."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from pgheat.analysis import classify, derive_interval
from pgheat.models import Thresholds
from tests.helpers import sample


T0 = datetime(2026, 1, 1, tzinfo=UTC)


class DeriveIntervalTests(unittest.TestCase):
    def test_derives_independent_activity_dimensions(self) -> None:
        previous = sample(
            collected_at=T0,
            seq_scan=10,
            idx_scan=20,
            n_tup_ins=5,
            heap_blks_read=100,
            heap_blks_hit=200,
        )
        current = sample(
            collected_at=T0 + timedelta(hours=1),
            seq_scan=12,
            idx_scan=25,
            n_tup_ins=8,
            n_tup_upd=2,
            heap_blks_read=110,
            heap_blks_hit=240,
            idx_blks_read=4,
            idx_blks_hit=6,
        )

        result = derive_interval(
            previous,
            current,
            maximum_gap=timedelta(hours=2),
        )

        self.assertEqual(result.status, "ok")
        assert result.interval is not None
        self.assertEqual(result.interval.scan_delta, 7)
        self.assertEqual(result.interval.write_delta, 5)
        self.assertEqual(result.interval.physical_read_blocks, 14)
        self.assertEqual(result.interval.cache_hit_blocks, 46)
        self.assertEqual(result.interval.block_touches, 60)
        self.assertEqual(result.interval.scans_per_hour, 7)

    def test_counter_decrease_starts_new_baseline(self) -> None:
        result = derive_interval(
            sample(collected_at=T0, seq_scan=10),
            sample(collected_at=T0 + timedelta(minutes=1), seq_scan=1),
            maximum_gap=timedelta(hours=1),
        )

        self.assertEqual(result.status, "counter_reset")
        self.assertIsNone(result.interval)
        self.assertIn("seq_scan decreased", result.detail)

    def test_relation_rewrite_breaks_identity(self) -> None:
        result = derive_interval(
            sample(collected_at=T0, relfilenode=200),
            sample(
                collected_at=T0 + timedelta(minutes=1),
                relfilenode=201,
            ),
            maximum_gap=timedelta(hours=1),
        )

        self.assertEqual(result.status, "identity_changed")
        self.assertIsNone(result.interval)

    def test_large_collection_gap_is_not_zero_activity(self) -> None:
        result = derive_interval(
            sample(collected_at=T0),
            sample(collected_at=T0 + timedelta(days=2)),
            maximum_gap=timedelta(days=1),
        )

        self.assertEqual(result.status, "collection_gap")
        self.assertIsNone(result.interval)


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = Thresholds(
            hot_scans_per_hour=100,
            hot_writes_per_hour=100,
            hot_block_touches_per_hour=10_000,
            minimum_observation_seconds=300,
            cold_after_seconds=7 * 86400,
            dormant_after_seconds=30 * 86400,
        )

    def test_one_sample_is_unknown(self) -> None:
        result = classify(
            [sample(collected_at=T0)],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=1),
        )

        self.assertEqual(result.state, "UNKNOWN")
        self.assertEqual(result.confidence, "low")

    def test_hot_state_names_triggering_boundary(self) -> None:
        result = classify(
            [
                sample(collected_at=T0, seq_scan=0),
                sample(
                    collected_at=T0 + timedelta(hours=1),
                    seq_scan=120,
                ),
            ],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=1),
        )

        self.assertEqual(result.state, "HOT")
        self.assertTrue(any("scan rate" in reason for reason in result.reasons))

    def test_activity_below_hot_boundary_is_warm(self) -> None:
        result = classify(
            [
                sample(collected_at=T0),
                sample(
                    collected_at=T0 + timedelta(hours=1),
                    idx_scan=2,
                ),
            ],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=1),
        )

        self.assertEqual(result.state, "WARM")
        self.assertEqual(result.scans_per_hour, 2)

    def test_inactivity_requires_full_cold_window(self) -> None:
        result = classify(
            [
                sample(collected_at=T0),
                sample(collected_at=T0 + timedelta(days=2)),
            ],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=10),
        )

        self.assertEqual(result.state, "UNKNOWN")
        self.assertIn("shorter than the cold boundary", result.reasons[0])

    def test_contiguous_evidence_after_reset_can_be_cold(self) -> None:
        result = classify(
            [
                sample(collected_at=T0, seq_scan=100),
                sample(collected_at=T0 + timedelta(hours=1), seq_scan=0),
                sample(collected_at=T0 + timedelta(days=8), seq_scan=0),
            ],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=10),
        )

        self.assertEqual(result.state, "COLD")
        self.assertTrue(any("seq_scan decreased" in item for item in result.warnings))

    def test_activity_older_than_window_does_not_keep_partition_warm(self) -> None:
        result = classify(
            [
                sample(collected_at=T0, seq_scan=0),
                sample(collected_at=T0 + timedelta(days=1), seq_scan=1),
                sample(collected_at=T0 + timedelta(days=22), seq_scan=1),
                sample(collected_at=T0 + timedelta(days=30), seq_scan=1),
            ],
            thresholds=self.thresholds,
            maximum_gap=timedelta(days=10),
            window=timedelta(days=10),
        )

        self.assertEqual(result.state, "COLD")
        self.assertEqual(result.scans_per_hour, 0)


if __name__ == "__main__":
    unittest.main()
