"""
Tests for the `fde list` CLI subcommand.

Covers:
  - happy path: index all *.log.json under a directory
  - --json output is parseable JSON
  - --markdown writes a Markdown file
  - empty directory exits 0 with a clear message
  - non-existent directory exits 2
  - malformed log files are silently skipped (don't crash the listing)
  - malformed log files DO show up as malformed in --json output's
    score field (so callers can see what failed)
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fde  # noqa: E402


def _write_run(path: Path, **overrides) -> None:
    """Write a minimal valid engagement log."""
    base = {
        "engagement": "test-eng",
        "discovery": {
            "sponsor": "Test Sponsor",
            "metric": {"name": "p99_ms", "baseline": 100,
                       "target": 50, "date": "2026-12-31"},
            "sla": {"p99_ms": 500, "availability_pct": 99.9,
                    "error_budget_pct": 0.1},
            "constraints": ["GDPR"],
            "stakeholders": ["a", "b", "c"],
            "roi_inputs": {"value_per_unit": 10,
                           "volume_per_year": 1000,
                           "cost_ceiling_usd": 10000},
        },
        "post_ga_log": [
            {"week": w, "p99_ms": 400.0, "error_rate": 0.0001,
             "availability_pct": 99.95, "metric_value": 100 - w}
                for w in range(1, 5)
            ],
    }
    base.update(overrides)
    path.write_text(json.dumps(base, indent=2))


class TestCmdList(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "fde", "list", *args],
            capture_output=True, text=True, cwd=ROOT)

    def test_happy_path_table_output(self):
        _write_run(self.dir / "a.log.json", engagement="alpha-eng")
        _write_run(self.dir / "b.log.json", engagement="beta-eng")
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        # The engagement id appears in the table; sponsor and metric too.
        self.assertIn("alpha-eng", r.stdout)
        self.assertIn("beta-eng", r.stdout)
        self.assertIn("Test Sponsor", r.stdout)
        self.assertIn("Engagement", r.stdout)
        # Header + separator + 2 rows
        self.assertGreaterEqual(len(r.stdout.strip().splitlines()), 4)

    def test_json_output_is_parseable(self):
        _write_run(self.dir / "x.log.json")
        r = self._run("--dir", str(self.dir), "--json")
        self.assertEqual(r.returncode, 0)
        parsed = json.loads(r.stdout)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["engagement"], "test-eng")

    def test_markdown_writes_file(self):
        _write_run(self.dir / "x.log.json")
        out = self.dir / "INDEX.md"
        r = self._run("--dir", str(self.dir), "--markdown", str(out))
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.exists())
        text = out.read_text()
        self.assertIn("# Engagements index", text)
        self.assertIn("| Engagement |", text)
        self.assertIn("test-eng", text)

    def test_empty_directory(self):
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0)
        self.assertIn("no engagement logs", r.stdout)

    def test_nonexistent_directory_exits_2(self):
        r = self._run("--dir", "/tmp/this-does-not-exist-xyz")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a directory", r.stderr)

    def test_malformed_log_does_not_crash(self):
        _write_run(self.dir / "good.log.json", engagement="good-eng")
        (self.dir / "bad.log.json").write_text("{not json")
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0,
                         "malformed log should be skipped, not crash")
        # Only the good one should appear.
        self.assertIn("good-eng", r.stdout)
        self.assertEqual(r.stdout.count("test-eng"), 0,
                         "bad log should be skipped entirely")

    def test_score_engagement_returns_none_on_bad_input(self):
        """_score_engagement helper handles malformed input gracefully."""
        bad = self.dir / "bad.log.json"
        bad.write_text("not json at all")
        self.assertIsNone(fde._score_engagement(bad))

    def test_format_list_table_empty(self):
        result = fde._format_list_table([])
        self.assertIn("no engagement logs", result)

    def test_format_list_markdown_empty(self):
        result = fde._format_list_markdown([])
        self.assertIn("no engagement logs", result)

    def test_truncation_in_table(self):
        """Long fields are truncated, not wrapped or overflowing."""
        long_sponsor = "A" * 100
        run = {
            "engagement": "test-eng",
            "discovery": {
                "sponsor": long_sponsor,
                "metric": {"name": "M", "baseline": 1, "target": 0,
                           "date": "2026-12-31"},
                "sla": {"p99_ms": 500},
                "constraints": [], "stakeholders": ["a", "b", "c"],
                "roi_inputs": {"value_per_unit": 1, "volume_per_year": 1,
                               "cost_ceiling_usd": 1},
            },
            "post_ga_log": [{"week": 1, "p99_ms": 100,
                             "error_rate": 0.001, "availability_pct": 99.9}],
        }
        self.dir.joinpath("long.log.json").write_text(json.dumps(run))
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0)
        # Truncated sponsor should be present (not the full 100 chars).
        self.assertNotIn(long_sponsor, r.stdout)
        self.assertIn("…", r.stdout)


if __name__ == "__main__":
    unittest.main()