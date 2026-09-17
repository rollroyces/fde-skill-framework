"""
Tests for the pre-commit engagement-log validator.

Exercises the script as a subprocess against temp files to confirm:
  - Valid engagement logs pass (exit 0).
  - Malformed JSON fails (exit 1, clear error).
  - Missing top-level keys fail.
  - Wrong types (e.g. post_ga_log as a dict) fail.
  - Non-engagement files are silently skipped.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pre_commit_validate.py"

VALID_LOG = {
    "engagement": "test-2026-01-01",
    "discovery": {
        "sponsor": "Test Sponsor",
        "metric": {"name": "p99_ms", "baseline": 100, "target": 50,
                   "date": "2026-12-31"},
        "sla": {"p99_ms": 500},
        "constraints": ["GDPR"],
        "stakeholders": ["a", "b"],
        "roi_inputs": {"value_per_unit": 1, "volume_per_year": 1,
                       "cost_ceiling_usd": 1},
    },
    "post_ga_log": [{"week": 1, "p99_ms": 400, "error_rate": 0.001,
                     "availability_pct": 99.9}],
}


class TestValidator(unittest.TestCase):
    """Run the script as a real subprocess to mirror how pre-commit invokes it."""

    def _run(self, *paths: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, paths)],
            capture_output=True, text=True)

    def test_valid_log_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ok.log.json"
            f.write_text(json.dumps(VALID_LOG))
            r = self._run(f)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")

    def test_malformed_json_fails(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "bad.log.json"
            f.write_text("{not valid json")
            r = self._run(f)
            self.assertEqual(r.returncode, 1)
            self.assertIn("invalid JSON", r.stderr)

    def test_missing_top_level_keys_fails(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "missing.log.json"
            broken = {"engagement": "x", "discovery": {}}  # no post_ga_log
            f.write_text(json.dumps(broken))
            r = self._run(f)
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing top-level keys", r.stderr)
            self.assertIn("post_ga_log", r.stderr)

    def test_missing_discovery_keys_fails(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "no-disc.log.json"
            broken = {
                "engagement": "x",
                "discovery": {"sponsor": "Y"},  # only one key
                "post_ga_log": [],
            }
            f.write_text(json.dumps(broken))
            r = self._run(f)
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing discovery keys", r.stderr)

    def test_post_ga_log_wrong_type_fails(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "wrong-type.log.json"
            broken = {
                "engagement": "x",
                "discovery": {**VALID_LOG["discovery"]},
                "post_ga_log": "not a list",  # type error
            }
            f.write_text(json.dumps(broken))
            r = self._run(f)
            self.assertEqual(r.returncode, 1)
            self.assertIn("post_ga_log must be a list", r.stderr)

    def test_non_log_json_files_are_skipped(self):
        """Files without .log.json extension are silently ignored."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config.json"   # NOT a log
            f.write_text("not even json")
            r = self._run(f)
            self.assertEqual(r.returncode, 0)

    def test_mixed_valid_and_invalid_fails(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "good.log.json"
            good.write_text(json.dumps(VALID_LOG))
            bad = Path(d) / "bad.log.json"
            bad.write_text("{malformed")
            r = self._run(good, bad)
            self.assertEqual(r.returncode, 1,
                             "should fail because bad.log.json is invalid")

    def test_real_engagement_logs_all_pass(self):
        """Smoke test: every real engagement in engagements/ passes."""
        logs = sorted((ROOT / "engagements").glob("*.log.json"))
        if not logs:
            self.skipTest("no real engagement logs to validate")
        r = self._run(*logs)
        self.assertEqual(r.returncode, 0,
                        f"real engagement logs failed validation: {r.stderr}")


if __name__ == "__main__":
    unittest.main()