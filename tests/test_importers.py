"""
Tests for the metrics ingest adapters.

Each importer is exercised against a realistic synthetic fixture and
asserts:

1. The output JSON has the expected engagement-log shape.
2. Discovery fields are LEFT BLANK (importer must not invent them).
3. The number of imported weeks matches the data.
4. ISO-week bucketing is correct (samples in week N land in week N).
5. Error cases (malformed input, no FDE metrics) raise clear errors.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fde.importers import import_csv, import_datadog, import_prometheus
import test_fde_eval as harness  # noqa: E402


def _ts(year, month, day, hour=12):
    """Helper: convert a date to a unix timestamp (seconds)."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc)
               .timestamp())


class TestPrometheus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "prom.json"
        self.out_path = Path(self.tmp.name) / "out.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data):
        self.in_path.write_text(json.dumps(data))

    def test_basic_import_buckets_by_iso_week(self):
        # Two samples in 2024-W18 (Apr 29 – May 5), two in 2024-W19
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms"},
                 "values": [
                     [_ts(2024, 5, 1), "468.3"],
                     [_ts(2024, 5, 3), "459.7"],
                     [_ts(2024, 5, 8), "450.0"],
                     [_ts(2024, 5, 10), "445.0"],
                 ]},
            ]},
        })
        summary = import_prometheus(self.in_path, self.out_path,
                                     engagement="acme-2024-05-15")
        self.assertEqual(summary["weeks"], 2)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(out["engagement"], "acme-2024-05-15")
        # W18 should be week 18 (May 1 is a Wednesday in 2024)
        self.assertEqual(out["post_ga_log"][0]["week"], 18)
        # Mean of 468.3 + 459.7 = 464.0
        self.assertAlmostEqual(out["post_ga_log"][0]["p99_ms"], 464.0,
                               places=1)

    def test_discovery_fields_left_blank(self):
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms"},
                 "values": [[_ts(2024, 5, 1), "468.3"]]},
            ]},
        })
        import_prometheus(self.in_path, self.out_path)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(out["discovery"]["sponsor"], "")
        self.assertEqual(out["discovery"]["metric"]["baseline"], None)
        self.assertEqual(out["discovery"]["metric"]["target"], None)
        # Critical: importer must NOT fabricate Discovery data.
        # A user (or sponsor) fills these in, not a script.

    def test_query_failed_raises_value_error(self):
        self._write({"status": "error", "error": "bad query"})
        with self.assertRaises(ValueError) as ctx:
            import_prometheus(self.in_path, self.out_path)
        self.assertIn("Prometheus query failed", str(ctx.exception))

    def test_no_fde_metrics_raises(self):
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "http_requests_total"},
                 "values": [[_ts(2024, 5, 1), "1000"]]},
            ]},
        })
        with self.assertRaises(ValueError) as ctx:
            import_prometheus(self.in_path, self.out_path)
        self.assertIn("No FDE-named metrics", str(ctx.exception))

    def test_imported_log_is_scorable(self):
        """Smoke test: the imported log + filled Discovery produces a
        valid scorecard via the harness."""
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms"},
                 "values": [[_ts(2024, 5, i), "450"] for i in range(1, 8)]},
                {"metric": {"__name__": "fde_error_rate"},
                 "values": [[_ts(2024, 5, i), "0.0001"] for i in range(1, 8)]},
                {"metric": {"__name__": "fde_availability_pct"},
                 "values": [[_ts(2024, 5, i), "99.95"] for i in range(1, 8)]},
            ]},
        })
        import_prometheus(self.in_path, self.out_path)
        out = json.loads(self.out_path.read_text())
        # Fill in minimal Discovery so we can score
        out["discovery"] = {
            "sponsor": "Jane Doe, VP Ops",
            "metric": {"name": "p99_latency_ms", "baseline": 800,
                       "target": 200, "date": "2024-12-31"},
            "sla": {"p99_ms": 500, "availability_pct": 99.9,
                    "error_budget_pct": 0.1},
            "constraints": ["GDPR"],
            "stakeholders": ["a", "b", "c"],
            "roi_inputs": {"value_per_unit": 10, "volume_per_year": 10000,
                           "cost_ceiling_usd": 100000},
        }
        rep = harness.evaluate(out)
        # With all weeks compliant + perfect Discovery, expect ~100
        self.assertGreaterEqual(rep.overall, 95.0,
            f"imported log should score high when Discovery is filled, "
            f"got {rep.overall}")


class TestDatadog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "dd.json"
        self.out_path = Path(self.tmp.name) / "out.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_import_with_millisecond_timestamps(self):
        self.in_path.write_text(json.dumps({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[_ts(2024, 5, 1) * 1000, 468.3],
                               [_ts(2024, 5, 3) * 1000, 459.7]]},
                {"metric": "fde.availability_pct",
                 "pointlist": [[_ts(2024, 5, 1) * 1000, 99.95]]},
            ],
        }))
        summary = import_datadog(self.in_path, self.out_path)
        self.assertEqual(summary["weeks"], 1)
        out = json.loads(self.out_path.read_text())
        self.assertIn("p99_ms", out["post_ga_log"][0])
        self.assertIn("availability_pct", out["post_ga_log"][0])

    def test_non_fde_metrics_are_silently_skipped(self):
        self.in_path.write_text(json.dumps({
            "series": [
                {"metric": "http.requests",
                 "pointlist": [[_ts(2024, 5, 1) * 1000, 1000]]},
                {"metric": "fde.error_rate",
                 "pointlist": [[_ts(2024, 5, 1) * 1000, 0.001]]},
            ],
        }))
        summary = import_datadog(self.in_path, self.out_path)
        self.assertEqual(summary["metrics"], ["fde.error_rate"])

    def test_no_fde_metrics_raises(self):
        self.in_path.write_text(json.dumps({
            "series": [{"metric": "x.y", "pointlist": []}],
        }))
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        self.assertIn("No FDE metrics", str(ctx.exception))


class TestCSV(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "metrics.csv"
        self.out_path = Path(self.tmp.name) / "out.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_csv(self):
        self.in_path.write_text(
            "week,p99_ms,error_rate,availability_pct,metric_value\n"
            "1,468.3,0.0003,99.92,200\n"
            "2,459.7,0.0002,99.93,150\n"
            "3,450.0,0.0002,99.94,120\n"
        )
        summary = import_csv(self.in_path, self.out_path)
        self.assertEqual(summary["weeks"], 3)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(out["post_ga_log"][2]["week"], 3)
        # Rows should be sorted ascending by week
        weeks = [r["week"] for r in out["post_ga_log"]]
        self.assertEqual(weeks, sorted(weeks))

    def test_only_week_column_required(self):
        self.in_path.write_text("week\n1\n5\n")
        import_csv(self.in_path, self.out_path)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(len(out["post_ga_log"]), 2)

    def test_missing_week_column_raises(self):
        self.in_path.write_text("p99_ms,error_rate\n468.3,0.0003\n")
        with self.assertRaises(ValueError) as ctx:
            import_csv(self.in_path, self.out_path)
        self.assertIn("missing required columns", str(ctx.exception))

    def test_non_numeric_value_raises_with_line_number(self):
        self.in_path.write_text(
            "week,p99_ms\n"
            "1,468.3\n"
            "2,not-a-number\n"
        )
        with self.assertRaises(ValueError) as ctx:
            import_csv(self.in_path, self.out_path)
        # Row 3 is the bad row (header + 1 good = row 2 is good,
        # row 3 is bad — 1-indexed including header)
        self.assertIn("row 3", str(ctx.exception))
        self.assertIn("p99_ms", str(ctx.exception))

    def test_empty_data_rows_raises(self):
        self.in_path.write_text("week,p99_ms\n")
        with self.assertRaises(ValueError):
            import_csv(self.in_path, self.out_path)


class TestCLIIImport(unittest.TestCase):
    """Verify the `fde import` subcommand parses and executes via the CLI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "in.csv"
        self.out_path = Path(self.tmp.name) / "out.json"
        self.in_path.write_text(
            "week,p99_ms,error_rate,availability_pct\n"
            "1,468.3,0.0003,99.92\n"
            "2,459.7,0.0002,99.93\n"
        )
        sys.path.insert(0, str(ROOT))
        import fde

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_import_csv(self):
        import fde
        ns = fde.build_parser().parse_args(
            ["import", "csv", str(self.in_path), str(self.out_path),
             "--engagement", "test-2026-01-01"])
        rc = fde.cmd_import(ns)
        self.assertEqual(rc, 0)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(out["engagement"], "test-2026-01-01")
        self.assertEqual(len(out["post_ga_log"]), 2)

    def test_cli_import_unknown_source_returns_2(self):
        import fde
        # argparse rejects choices=["prometheus","datadog","csv"] before
        # cmd_import runs, so the parser itself exits with code 2.
        with self.assertRaises(SystemExit) as ctx:
            fde.build_parser().parse_args(
                ["import", "splunk", "/x", "/y"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()