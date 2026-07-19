"""Tests for local analysis CLI commands."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pgheat.cli import main
from pgheat.store import SampleStore
from tests.helpers import sample, source


class CLITests(unittest.TestCase):
    def test_top_emits_machine_readable_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "history.db"
            first_time = datetime(2026, 1, 1, tzinfo=UTC)
            second_time = first_time + timedelta(hours=1)
            with SampleStore(store_path) as store:
                store.save_collection(
                    source(),
                    [sample(collected_at=first_time)],
                    collected_at=first_time,
                )
                store.save_collection(
                    source(),
                    [sample(collected_at=second_time, seq_scan=120)],
                    collected_at=second_time,
                )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(
                    [
                        "--store",
                        str(store_path),
                        "--json",
                        "top",
                    ]
                )

            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result[0]["state"], "HOT")
            self.assertEqual(result[0]["partition"], "public.events_2026_01")

    def test_explain_requires_existing_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "history.db"
            with SampleStore(store_path) as store:
                timestamp = datetime(2026, 1, 1, tzinfo=UTC)
                store.save_collection(
                    source(),
                    [sample(collected_at=timestamp)],
                    collected_at=timestamp,
                )

            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(
                    [
                        "--store",
                        str(store_path),
                        "explain",
                        "public.missing",
                    ]
                )

            self.assertEqual(status, 1)
            self.assertIn("no samples found", error.getvalue())


if __name__ == "__main__":
    unittest.main()
