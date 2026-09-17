"""
Tests for `fde doctor` — the WHY-explainer subcommand.

Doctor walks the same Report the harness returns, but adds two things
the scorecard hides:

  1. It names the SPECIFIC weeks that breached SLA, not just a count.
  2. It ends every section with a concrete next action.

Exit codes follow the usual fde convention: 0 healthy, 1 actionable
issues, 2 file/JSON unreadable. The tests below lock that contract.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Make `fde` and the harness importable the way the CLI sees them.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fde                                  # noqa: E402
import test_fde_eval as harness               # noqa: E402


def _write_run(run: dict) -> str:
    """Drop a run JSON in a temp file, return its path."""
    fd, path = tempfile.mkstemp(suffix=".log.json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(run, f)
    except Exception:
        os.unlink(path)
        raise
    return path


def _captured_run(args: list) -> tuple:
    """Invoke the doctor CLI subcommand with stdout/stderr captured.

    Returns (exit_code, stdout, stderr)."""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    ns = fde.build_parser().parse_args(args)
    with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
        rc = fde.cmd_doctor(ns)
    return rc, buf_out.getvalue(), buf_err.getvalue()


class TestDoctorExitCodes(unittest.TestCase):
    def test_good_run_exits_zero_and_says_no_missing(self):
        """GOOD_RUN is the canonical healthy engagement. Doctor must:
        - exit 0
        - mention 'no missing fields' in the Discovery section
        - not list any actionable issues."""
        path = _write_run(harness.GOOD_RUN)
        try:
            rc, out, err = _captured_run(["doctor", path])
            self.assertEqual(rc, 0,
                             f"healthy run should exit 0, got {rc}; "
                             f"stderr={err!r}")
            self.assertIn("no missing fields", out)
            # Decision should reflect a healthy run.
            self.assertIn("SCALE", out)
            # Discovery section must NOT list any missing checks (the
            # marker is the dash-bullet list under the Discovery heading).
            disc_section = out.split("Discovery:", 1)[1].split("\n", 1)[0]
            self.assertNotIn(" - ", disc_section,
                             f"healthy Discovery should have no bullet "
                             f"items; got {disc_section!r}")
        finally:
            os.unlink(path)

    def test_bad_run_exits_one_and_lists_all_twelve_missing(self):
        """BAD_RUN is sourced from engagements/initech-shadow-it-2026-09-16,
        which has sponsor + 1 stakeholder but is missing the bulk of
        Discovery (9 of 12 checks). Doctor must:
          - exit 1
          - report the count of missing fields accurately
          - name which weeks breached SLA.
        """
        path = _write_run(harness.BAD_RUN)
        try:
            rc, out, err = _captured_run(["doctor", path])
            self.assertEqual(rc, 1,
                             f"bad run should exit 1, got {rc}; "
                             f"stderr={err!r}")
            # 9 of 12 — sponsor + 1 stakeholder + sponsor_named are
            # the only Discovery fields the initech fixture fills.
            self.assertIn("missing 9 of 12", out,
                          "doctor must report missing count")
            # Spot-check the labels that ARE missing in the initech
            # fixture (sponsor + SLA p99 + metric name are filled,
            # so 9 of 12 are missing). Labels live in fde._BUSINESS_CHECK_LABELS.
            expected_labels = [
                "metric baseline", "metric target", "metric target date",
                "metric target differs from baseline",
                ">=3 stakeholders named", "constraints documented",
                "ROI value_per_unit", "ROI volume_per_year",
                "ROI cost_ceiling_usd",
            ]
            for label in expected_labels:
                self.assertIn(label, out,
                              f"missing-field label {label!r} absent "
                              f"from doctor output:\n{out}")
            # BAD_RUN has 4 post-GA weeks all breaching.
            self.assertIn("weeks [1, 2, 3, 4]", out)
            self.assertIn("CUT", out)
        finally:
            os.unlink(path)

    def test_synthetic_sla_breaches_names_specific_weeks(self):
        """A run with a healthy Discovery but two weeks breaching p99 must:
        - exit 1
        - name the two breaching weeks explicitly (not just a count)."""
        synthetic = {
            "engagement": "synthetic-2026-09-16",
            "discovery": {
                "sponsor": "Test Sponsor, VP",
                "metric": {"name": "test_metric", "baseline": 100,
                           "target": 50, "date": "2026-12-31"},
                "sla": {"p99_ms": 500, "availability_pct": 99.9,
                        "error_budget_pct": 0.1},
                "constraints": ["test-constraint"],
                "stakeholders": ["A (sponsor)", "B (daily)", "C (security)"],
                "roi_inputs": {"value_per_unit": 10,
                               "volume_per_year": 1000,
                               "cost_ceiling_usd": 50000},
            },
            "post_ga_log": [
                {"week": 1, "p99_ms": 480, "error_rate": 0.0001,
                 "availability_pct": 99.95},
                {"week": 2, "p99_ms": 700, "error_rate": 0.0001,
                 "availability_pct": 99.95},
                {"week": 3, "p99_ms": 490, "error_rate": 0.0001,
                 "availability_pct": 99.95},
                {"week": 4, "p99_ms": 650, "error_rate": 0.0001,
                 "availability_pct": 99.5},
            ],
        }
        path = _write_run(synthetic)
        try:
            rc, out, err = _captured_run(["doctor", path])
            self.assertEqual(rc, 1,
                             f"synthetic with breaches should exit 1, got "
                             f"{rc}; stderr={err!r}")
            # Both breached weeks should be named.
            self.assertIn("[2, 4]", out,
                          f"expected breached weeks [2, 4] in output, got "
                          f"snippet:\n{out}")
            # Discovery should be clean (no missing fields).
            self.assertIn("no missing fields", out)
            # At least one next-action suggestion must be present.
            self.assertIn("-> next:", out)
        finally:
            os.unlink(path)

    def test_missing_file_exits_two(self):
        rc, out, err = _captured_run(
            ["doctor", "/tmp/this-file-does-not-exist-xyz.json"])
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)

    def test_malformed_json_exits_two(self):
        """File exists but contains invalid JSON."""
        fd, path = tempfile.mkstemp(suffix=".log.json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("{not valid json at all")
            rc, out, err = _captured_run(["doctor", path])
            self.assertEqual(rc, 2)
            self.assertIn("not valid JSON", err)
        finally:
            os.unlink(path)

    def test_json_flag_emits_parseable_json_report(self):
        """`--json` must produce a JSON document parseable by json.loads."""
        path = _write_run(harness.GOOD_RUN)
        try:
            rc, out, err = _captured_run(["doctor", path, "--json"])
            self.assertEqual(rc, 0)
            # Whole stdout must be parseable JSON.
            payload = json.loads(out)
            # Expected top-level keys.
            self.assertEqual(
                sorted(payload.keys()),
                sorted(["engagement", "overall", "decision", "business",
                        "sla", "latency", "errors", "reasons"]),
            )
            # Per-axis health booleans are the contract used by the exit
            # code; lock them here so a future refactor can't silently
            # change the rule.
            self.assertTrue(payload["business"]["healthy"])
            self.assertTrue(payload["sla"]["healthy"])
            self.assertTrue(payload["latency"]["healthy"])
            self.assertTrue(payload["errors"]["healthy"])
            # Decision reflects the healthy fixture.
            self.assertEqual(payload["decision"], "scale")
            # Breach-week maps are always present (even when empty).
            self.assertIn("breach_weeks", payload["sla"])
            self.assertEqual(payload["sla"]["breach_weeks"],
                             {"p99": [], "error_rate": [],
                              "availability": []})
        finally:
            os.unlink(path)


class TestDoctorOnDogfood(unittest.TestCase):
    """Smoke test against the repo's bundled dogfood engagement log."""

    DOGFOOD = (ROOT / "engagements"
               / "mrnavax-codonpair-v0.14.0-2026-09-16.log.json")

    def test_dogfood_exits_zero(self):
        if not self.DOGFOOD.exists():
            self.skipTest(f"dogfood log not present: {self.DOGFOOD}")
        rc, out, err = _captured_run(["doctor", str(self.DOGFOOD)])
        self.assertEqual(rc, 0)
        self.assertIn("SCALE", out)


class TestDoctorOutputBudget(unittest.TestCase):
    """Doctor output is supposed to fit a typical terminal without
    scrolling. Lock the budget so future additions don't spam."""

    def test_output_fits_in_30_lines(self):
        """Even on the maximally-bad BAD_RUN, doctor stays bounded."""
        path = _write_run(harness.BAD_RUN)
        try:
            rc, out, err = _captured_run(["doctor", path])
            line_count = out.count("\n") + 1
            self.assertLessEqual(
                line_count, 35,
                f"doctor output too long ({line_count} lines); "
                f"meant to fit a terminal:\n{out}")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()