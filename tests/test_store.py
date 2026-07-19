"""Tests for immutable SQLite sample persistence."""

from __future__ import annotations

import tempfile
import unittest
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pgheat.errors import StoreError
from pgheat.store import SampleStore
from tests.helpers import sample, source


class SampleStoreTests(unittest.TestCase):
    def test_round_trip_preserves_partition_identity_and_counters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.db"
            first_time = datetime(2026, 1, 1, tzinfo=UTC)
            second_time = first_time + timedelta(minutes=5)

            with SampleStore(path) as store:
                first_id = store.save_collection(
                    source(),
                    [sample(collected_at=first_time, seq_scan=4)],
                    collected_at=first_time,
                )
                second_id = store.save_collection(
                    source(),
                    [sample(collected_at=second_time, seq_scan=9)],
                    collected_at=second_time,
                )
                loaded = store.load_samples(
                    source().source_id,
                    parent="public.events",
                )

            self.assertEqual(first_id, 1)
            self.assertEqual(second_id, 2)
            self.assertEqual([item.seq_scan for item in loaded], [4, 9])
            self.assertEqual(loaded[0].qualified_parent, "public.events")
            self.assertEqual(
                loaded[0].qualified_partition,
                "public.events_2026_01",
            )

    def test_requires_source_selection_when_store_has_multiple_sources(self) -> None:
        with SampleStore(":memory:") as store:
            timestamp = datetime(2026, 1, 1, tzinfo=UTC)
            store.save_collection(
                source(),
                [sample(collected_at=timestamp)],
                collected_at=timestamp,
            )
            other = source()
            other = type(other)(
                source_id="other:5432/postgres",
                host=other.host,
                port=other.port,
                database_name=other.database_name,
                database_oid=other.database_oid,
                server_version_num=other.server_version_num,
            )
            other_sample = replace(
                sample(collected_at=timestamp),
                source_id=other.source_id,
            )
            store.save_collection(
                other,
                [other_sample],
                collected_at=timestamp,
            )

            with self.assertRaisesRegex(StoreError, "multiple sources"):
                store.resolve_source(None)

    def test_duplicate_collection_is_rejected(self) -> None:
        with SampleStore(":memory:") as store:
            timestamp = datetime(2026, 1, 1, tzinfo=UTC)
            store.save_collection(
                source(),
                [sample(collected_at=timestamp)],
                collected_at=timestamp,
            )

            with self.assertRaises(sqlite3.IntegrityError):
                store.save_collection(
                    source(),
                    [sample(collected_at=timestamp)],
                    collected_at=timestamp,
                )


if __name__ == "__main__":
    unittest.main()
