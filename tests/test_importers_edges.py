"""
Real-world edge cases for the Datadog and Prometheus importers.

These tests complement the happy-path coverage in test_importers.py
with scenarios that real Datadog/Prometheus API exports are likely
to exhibit but which the synthetic fixtures there didn't cover:

* Empty / mismatched envelopes (no series, empty pointlist)
* Malformed timestamps (None, string, negative, far-future overflow)
* Mixed FDE / non-FDE metrics in the same dump
* Long engagements spanning 52+ ISO weeks
* Duplicate series per canonical metric (Datadog returns one per
  tag combination; Prometheus returns one per label set)
* Near-miss metric names that the user probably mistyped
* Numeric overflow on values
* Engagement names with special characters

Tests here exercise the public importer API and assert on the
returned summary dict, the on-disk JSON output, and the raised
exceptions. They do not poke at private helpers.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fde.importers import import_datadog, import_prometheus


def _ts_ms(year, month, day, hour=12):
    """Helper: convert a date to a Datadog-style millisecond timestamp."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc)
               .timestamp()) * 1000


def _ts_s(year, month, day, hour=12):
    """Helper: convert a date to a Prometheus-style second timestamp."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc)
               .timestamp())


class DatadogEdgeCases(unittest.TestCase):
    """Edge cases specific to the Datadog v1 API export."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "dd.json"
        self.out_path = Path(self.tmp.name) / "out.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data):
        self.in_path.write_text(json.dumps(data))

    # ----- 1. Empty series list ---------------------------------------- #

    def test_empty_series_list_raises_with_clear_message(self):
        """`{"series": []}` is an unambiguous empty response — we want a
        ValueError that names the symptom, not a confusing downstream
        crash."""
        self._write({"series": []})
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("no series", msg)
        self.assertIn("'series' array is empty", msg)

    def test_missing_series_key_raises(self):
        """A dump without a top-level 'series' key is also empty."""
        self._write({"other_field": 42})
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        self.assertIn("no series", str(ctx.exception))

    def test_non_list_series_raises(self):
        """`"series": "oops"` should fail loudly, not iterate over chars."""
        self._write({"series": "oops"})
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        self.assertIn("must be a list", str(ctx.exception))

    # ----- 2. Empty pointlist ------------------------------------------ #

    def test_series_with_empty_pointlist_is_ignored_not_fatal(self):
        """A series whose `pointlist` is `[]` represents a metric that
        exists but had no data in the queried window. Skip it; don't
        error."""
        self._write({
            "series": [
                {"metric": "fde.p99_ms", "pointlist": []},
                {"metric": "fde.error_rate",
                 "pointlist": [[_ts_ms(2024, 5, 1), 0.001]]},
            ],
        })
        summary = import_datadog(self.in_path, self.out_path)
        self.assertEqual(summary["weeks"], 1)
        self.assertEqual(summary["skipped_empty_series"], 1)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(len(out["post_ga_log"]), 1)
        # The skipped series is not represented in the output — only the
        # metric with data is.
        self.assertIn("error_rate", out["post_ga_log"][0])
        self.assertNotIn("p99_ms", out["post_ga_log"][0])

    def test_all_fde_series_empty_raises_distinct_message(self):
        """When every FDE-named series is empty, raise a distinct error
        so the user knows to widen their time window rather than
        check the metric name."""
        self._write({
            "series": [
                {"metric": "fde.p99_ms", "pointlist": []},
                {"metric": "fde.error_rate", "pointlist": []},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        # Distinct from "no FDE metrics" — this is "FDE names found but
        # every series was empty".
        self.assertIn("empty pointlist", msg)
        self.assertIn("Widen your time window", msg)

    # ----- 3. Malformed timestamps ------------------------------------- #

    def test_negative_timestamp_raises_with_series_and_sample_index(self):
        """Negative timestamps land in 1970 silently if we don't
        catch them — users would see week-1 of 1970 entries and be
        very confused. Fail loudly with the sample index."""
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[_ts_ms(2024, 5, 1), 468.3],
                               [-12345, 999.0]]},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 1", msg)
        self.assertIn("negative", msg)

    def test_none_timestamp_raises_with_series_and_sample_index(self):
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[None, 468.3]]},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 0", msg)
        self.assertIn("None", msg)

    def test_string_timestamp_raises_with_series_and_sample_index(self):
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [["not-a-number", 468.3]]},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 0", msg)
        self.assertIn("not a number", msg)

    def test_far_future_timestamp_raises(self):
        """A timestamp that overflows the datetime year range used to
        crash with 'year 56302 is out of range' deep inside Python.
        Surface it as a ValueError with the sample index instead."""
        # 1e15 ms ≈ year 33658
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[10 ** 15, 468.3]]},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 0", msg)
        # Either "beyond year 9999" or "could not be parsed as a
        # datetime" — both are acceptable surfaces.
        self.assertTrue("beyond year 9999" in msg
                        or "could not be parsed" in msg,
                        msg)

    # ----- 4. Long engagement (52+ ISO weeks) --------------------------- #

    def test_long_engagement_produces_all_weeks_in_order(self):
        """An engagement spanning a full year should produce ~52 weeks
        in ascending order."""
        start = datetime(2023, 1, 2, 12, tzinfo=timezone.utc)  # Monday
        pointlist = []
        for i in range(365):
            t = int((start + timedelta(days=i)).timestamp()) * 1000
            # Cycle a value so the per-week average is meaningful.
            pointlist.append([t, 400.0 + (i % 7) * 10])
        self._write({
            "series": [
                {"metric": "fde.p99_ms", "pointlist": pointlist},
            ],
        })
        summary = import_datadog(self.in_path, self.out_path)
        # 53 ISO weeks is possible at year boundaries; the assertion is
        # "at least 52 and in ascending order".
        self.assertGreaterEqual(summary["weeks"], 52)
        out = json.loads(self.out_path.read_text())
        weeks = [row["week"] for row in out["post_ga_log"]]
        self.assertEqual(weeks, sorted(weeks))
        # Year wrapping should produce both 2022 and 2023 entries —
        # 2023-01-02 is ISO week 1 of 2023.
        self.assertGreaterEqual(weeks[0], 1)
        self.assertLessEqual(weeks[-1], 53)

    # ----- 5. Duplicate series for the same metric --------------------- #

    def test_duplicate_series_merge_into_single_week_bucket(self):
        """Datadog returns one series per tag combination. If the user
        has two series for `fde.p99_ms` covering the same week, both
        must contribute to the per-week average — the second series
        must NOT silently overwrite the first."""
        ts = _ts_ms(2024, 5, 1)
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[ts, 100.0], [ts + 86400000, 200.0]]},
                {"metric": "fde.p99_ms",
                 "pointlist": [[ts, 300.0], [ts + 86400000, 400.0]]},
            ],
        })
        summary = import_datadog(self.in_path, self.out_path)
        # `metrics` should be deduplicated.
        self.assertEqual(summary["metrics"], ["fde.p99_ms"])
        out = json.loads(self.out_path.read_text())
        self.assertEqual(len(out["post_ga_log"]), 1)
        # True merged average: (100 + 200 + 300 + 400) / 4 = 250.
        # Old behaviour (overwrite) would have produced 350.
        self.assertAlmostEqual(out["post_ga_log"][0]["p99_ms"], 250.0,
                               places=1)

    def test_duplicate_series_with_different_metrics_keep_both(self):
        """Duplicate series for one metric must not cause the *other*
        metric to be dropped."""
        ts = _ts_ms(2024, 5, 1)
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[ts, 100.0]]},
                {"metric": "fde.p99_ms",
                 "pointlist": [[ts, 200.0]]},
                {"metric": "fde.error_rate",
                 "pointlist": [[ts, 0.005]]},
            ],
        })
        summary = import_datadog(self.in_path, self.out_path)
        self.assertEqual(sorted(summary["metrics"]),
                         ["fde.error_rate", "fde.p99_ms"])
        out = json.loads(self.out_path.read_text())
        entry = out["post_ga_log"][0]
        self.assertAlmostEqual(entry["p99_ms"], 150.0, places=1)
        self.assertAlmostEqual(entry["error_rate"], 0.005, places=5)

    # ----- 6. Near-miss metric names ----------------------------------- #

    def test_near_miss_metric_warns_but_does_not_fail(self):
        """`fde.p99_latency_ms` is clearly a typo for `fde.p99_ms`.
        Warn to stderr, skip, don't crash the import."""
        self._write({
            "series": [
                {"metric": "fde.p99_latency_ms",
                 "pointlist": [[_ts_ms(2024, 5, 1), 468.3]]},
                {"metric": "fde.error_rate",
                 "pointlist": [[_ts_ms(2024, 5, 1), 0.001]]},
            ],
        })
        buf = io.StringIO()
        with redirect_stderr(buf):
            summary = import_datadog(self.in_path, self.out_path)
        # Import succeeded, error_rate came through, p99 latency did not.
        self.assertEqual(summary["metrics"], ["fde.error_rate"])
        out = json.loads(self.out_path.read_text())
        self.assertNotIn("p99_ms", out["post_ga_log"][0])
        self.assertIn("error_rate", out["post_ga_log"][0])
        # Warning was emitted on stderr naming the typo and the
        # canonical candidate.
        stderr = buf.getvalue()
        self.assertIn("warning", stderr)
        self.assertIn("fde.p99_latency_ms", stderr)
        self.assertIn("fde.p99_ms", stderr)
        # Warning also surfaces in the return value so the CLI can
        # print it.
        self.assertTrue(any("fde.p99_latency_ms" in w
                            for w in summary["warnings"]))

    # ----- 7. Numeric overflow ----------------------------------------- #

    def test_huge_but_finite_value_round_trips(self):
        """`1e308` is representable as a Python float and round-trips
        through json. Verify it doesn't crash and lands in the output."""
        self._write({
            "series": [
                {"metric": "fde.metric_value",
                 "pointlist": [[_ts_ms(2024, 5, 1), 1e308]]},
            ],
        })
        summary = import_datadog(self.in_path, self.out_path)
        self.assertEqual(summary["weeks"], 1)
        out = json.loads(self.out_path.read_text())
        # JSON serialisation may write `1e+308`; just verify the value
        # is in the file and the round-trip preserves magnitude.
        raw_text = self.out_path.read_text()
        self.assertIn("1e", raw_text.lower().replace("+", ""))

    def test_infinite_value_raises(self):
        """`float('inf')` would silently produce `Infinity` in the
        output JSON (invalid per the spec) — reject it."""
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[_ts_ms(2024, 5, 1), float("inf")]]},
            ],
        })
        with self.assertRaises(ValueError) as ctx:
            import_datadog(self.in_path, self.out_path)
        self.assertIn("not finite", str(ctx.exception))

    # ----- 8. Engagement name with special characters ------------------ #

    def test_engagement_name_with_special_characters_preserved(self):
        """Spaces, slashes, and unicode must round-trip verbatim — the
        importer must not munge user-supplied engagement ids."""
        weird = "acme/résumé — 2024/Q2 (pilot)"
        self._write({
            "series": [
                {"metric": "fde.p99_ms",
                 "pointlist": [[_ts_ms(2024, 5, 1), 468.3]]},
            ],
        })
        import_datadog(self.in_path, self.out_path, engagement=weird)
        out = json.loads(self.out_path.read_text())
        self.assertEqual(out["engagement"], weird)


# --------------------------------------------------------------------------- #
# Mirror the most important hardening to the Prometheus importer.             #
# --------------------------------------------------------------------------- #


class PrometheusEdgeCases(unittest.TestCase):
    """Edge cases for the Prometheus importer that mirror the same
    hardening applied to Datadog."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.in_path = Path(self.tmp.name) / "prom.json"
        self.out_path = Path(self.tmp.name) / "out.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data):
        self.in_path.write_text(json.dumps(data))

    def test_empty_result_raises(self):
        """Empty result array is the Prometheus equivalent of empty
        series."""
        self._write({"status": "success",
                     "data": {"resultType": "matrix", "result": []}})
        with self.assertRaises(ValueError) as ctx:
            import_prometheus(self.in_path, self.out_path)
        self.assertIn("no series", str(ctx.exception))

    def test_malformed_timestamp_raises_with_indices(self):
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms"},
                 "values": [[_ts_s(2024, 5, 1), "468.3"],
                            [-1, "999.0"]]},
            ]},
        })
        with self.assertRaises(ValueError) as ctx:
            import_prometheus(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 1", msg)
        self.assertIn("negative", msg)

    def test_far_future_timestamp_raises(self):
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms"},
                 "values": [[10 ** 15, "468.3"]]},
            ]},
        })
        with self.assertRaises(ValueError) as ctx:
            import_prometheus(self.in_path, self.out_path)
        msg = str(ctx.exception)
        self.assertIn("series 0", msg)
        self.assertIn("sample 0", msg)
        self.assertTrue("beyond year 9999" in msg
                        or "could not be parsed" in msg, msg)

    def test_duplicate_series_for_same_metric_merge(self):
        """Prometheus returns one series per label set. Two label sets
        for the same metric name must merge, not overwrite."""
        ts = _ts_s(2024, 5, 1)
        self._write({
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {"__name__": "fde_p99_ms",
                            "region": "us-east-1"},
                 "values": [[ts, "100.0"],
                            [ts + 86400, "200.0"]]},
                {"metric": {"__name__": "fde_p99_ms",
                            "region": "eu-west-1"},
                 "values": [[ts, "300.0"],
                            [ts + 86400, "400.0"]]},
            ]},
        })
        summary = import_prometheus(self.in_path, self.out_path)
        # `metrics` deduplicated.
        self.assertEqual(summary["metrics"], ["fde_p99_ms"])
        out = json.loads(self.out_path.read_text())
        self.assertEqual(len(out["post_ga_log"]), 1)
        # True merged average: (100 + 200 + 300 + 400) / 4 = 250.
        self.assertAlmostEqual(out["post_ga_log"][0]["p99_ms"], 250.0,
                               places=1)


if __name__ == "__main__":
    unittest.main()