"""
Tests for the `fde stats` CLI subcommand.

Covers:
  - happy path: 3+ engagements, decision distribution, score range
  - --json output shape (engagement_count, decisions, missing_field_counts)
  - empty directory
  - non-existent directory exits 2
  - malformed logs are skipped (not crashed on)
  - missing-field labels match what `fde doctor` shows
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fde  # noqa: E402


def _write_run(path: Path, *, engagement: str = "test-eng",
               sponsor: str = "Test Sponsor",
               fill_roi: bool = True,
               fill_constraints: bool = True,
               target_date: str = "2026-12-31",
               weeks: int = 4,
               stakeholders: int = 3) -> None:
    """Write a minimal valid engagement log."""
    base = {
        "engagement": engagement,
        "discovery": {
            "sponsor": sponsor,
            "metric": {"name": "p99_ms", "baseline": 100,
                       "target": 50, "date": target_date},
            "sla": {"p99_ms": 500, "availability_pct": 99.9,
                    "error_budget_pct": 0.1},
            "constraints": ["GDPR"] if fill_constraints else [],
            "stakeholders": [f"person-{i}" for i in range(stakeholders)],
            "roi_inputs": ({"value_per_unit": 10, "volume_per_year": 1000,
                            "cost_ceiling_usd": 10000}
                           if fill_roi else {}),
        },
        "post_ga_log": [
            {"week": w, "p99_ms": 400.0, "error_rate": 0.0001,
             "availability_pct": 99.95, "metric_value": 100 - w}
            for w in range(1, weeks + 1)
        ],
    }
    path.write_text(json.dumps(base, indent=2))


class TestCmdStats(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "fde", "stats", *args],
            capture_output=True, text=True, cwd=ROOT)

    def test_empty_directory(self):
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0)
        self.assertIn("no engagement logs", r.stdout)

    def test_nonexistent_directory_exits_2(self):
        r = self._run("--dir", "/tmp/this-does-not-exist-xyz")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a directory", r.stderr)

    def test_happy_path_text_output(self):
        _write_run(self.dir / "a.log.json", engagement="alpha")
        _write_run(self.dir / "b.log.json", engagement="beta")
        _write_run(self.dir / "c.log.json", engagement="gamma",
                   fill_roi=False)
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        out = r.stdout
        self.assertIn("3 engagements", out)
        self.assertIn("Decision distribution:", out)
        self.assertIn("scale", out)
        self.assertIn("iterate", out)
        self.assertIn("cut", out)
        self.assertIn("Overall score:", out)
        self.assertIn("Most-common missing Discovery fields:", out)

    def test_json_output_shape(self):
        _write_run(self.dir / "a.log.json")
        _write_run(self.dir / "b.log.json")
        r = self._run("--dir", str(self.dir), "--json")
        self.assertEqual(r.returncode, 0)
        payload = json.loads(r.stdout)
        for key in ("engagement_count", "decisions", "weeks_total",
                    "overall_avg", "overall_min", "overall_max",
                    "missing_field_counts"):
            self.assertIn(key, payload)
        self.assertEqual(payload["engagement_count"], 2)
        self.assertEqual(set(payload["decisions"].keys()),
                         {"scale", "iterate", "cut"})

    def test_malformed_log_is_skipped(self):
        _write_run(self.dir / "good.log.json")
        (self.dir / "bad.log.json").write_text("not json")
        r = self._run("--dir", str(self.dir))
        self.assertEqual(r.returncode, 0,
                         "malformed log should be skipped, not crash")

    def test_missing_discovery_labels_match_doctor(self):
        """The labels in stats output use the same vocabulary as fde doctor,
        so users don't have to learn two different naming schemes."""
        _write_run(self.dir / "x.log.json", fill_roi=False,
                   sponsor="", fill_constraints=False, stakeholders=1)
        r = self._run("--dir", str(self.dir))
        out = r.stdout
        # All four "missing" labels this fixture triggers must appear.
        for label in ("ROI value_per_unit", "ROI volume_per_year",
                      "ROI cost_ceiling_usd", "constraints documented",
                      ">=3 stakeholders named", "sponsor name"):
            self.assertIn(label, out,
                          f"expected {label!r} in stats output")

    def test_real_engagements_produce_stats(self):
        """Smoke test: the three dogfood engagements aggregate without error."""
        eng_dir = ROOT / "engagements"
        r = self._run("--dir", str(eng_dir))
        self.assertEqual(r.returncode, 0)
        self.assertIn("3 engagements", r.stdout)


class TestMissingFieldsHelper(unittest.TestCase):

    def test_empty_run_is_missing_everything(self):
        missing = fde._missing_discovery_fields({"discovery": {}})
        self.assertGreater(len(missing), 0)

    def test_full_run_has_zero_missing(self):
        run = {
            "discovery": {
                "sponsor": "Jane Doe",
                "metric": {"name": "m", "baseline": 100, "target": 50,
                           "date": "2026-12-31"},
                "sla": {"p99_ms": 500},
                "constraints": ["GDPR"],
                "stakeholders": ["a", "b", "c"],
                "roi_inputs": {"value_per_unit": 1, "volume_per_year": 1,
                               "cost_ceiling_usd": 1},
            }
        }
        missing = fde._missing_discovery_fields(run)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()