"""
CLI smoke tests — exercise the fde CLI wrapper against the same evaluator
the pytest suite asserts against. Catches drift between the CLI and the
harness (e.g. CLI importing a stale module path).
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

# Make the package importable as `fde` and the harness importable as
# `test_fde_eval` from the CLI's perspective.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                 # so `import fde` works
sys.path.insert(0, str(ROOT / "tests"))       # CLI's own bootstrap

import fde                                  # noqa: E402
import test_fde_eval as harness               # noqa: E402


class TestScore(unittest.TestCase):
    def test_good_run_decision_scale(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(harness.GOOD_RUN, f)
            path = f.name
        try:
            ns = fde.build_parser().parse_args(["score", path])
            rc = fde.cmd_score(ns)
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_bad_run_decision_cut(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(harness.BAD_RUN, f)
            path = f.name
        try:
            ns = fde.build_parser().parse_args(["score", path])
            rc = fde.cmd_score(ns)
            self.assertEqual(rc, 0)        # not strict → exit 0
            ns2 = fde.build_parser().parse_args(["score", path, "--strict"])
            self.assertEqual(fde.cmd_score(ns2), 1)   # strict → exit 1
        finally:
            os.unlink(path)

    def test_missing_file(self):
        ns = fde.build_parser().parse_args(
            ["score", "/tmp/does-not-exist-xyz.json"])
        self.assertEqual(fde.cmd_score(ns), 2)


class TestInit(unittest.TestCase):
    def test_init_writes_md_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            ns = fde.build_parser().parse_args(
                ["init", "globex", "--date", "2026-09-16", "--dir", d])
            self.assertEqual(fde.cmd_init(ns), 0)
            md = Path(d) / "globex-2026-09-16.md"
            log = Path(d) / "globex-2026-09-16.log.json"
            self.assertTrue(md.exists())
            self.assertTrue(log.exists())
            self.assertIn("globex", md.read_text())
            log_data = json.loads(log.read_text())
            self.assertEqual(log_data["engagement"], "globex-2026-09-16")
            self.assertEqual(log_data["post_ga_log"], [])

    def test_init_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            ns = fde.build_parser().parse_args(
                ["init", "globex", "--dir", d])
            self.assertEqual(fde.cmd_init(ns), 0)
            again = fde.build_parser().parse_args(
                ["init", "globex", "--dir", d])
            self.assertEqual(fde.cmd_init(again), 2)
            force = fde.build_parser().parse_args(
                ["init", "globex", "--dir", d, "--force"])
            self.assertEqual(fde.cmd_init(force), 0)


class TestLogWeek(unittest.TestCase):
    def test_log_week_appends_and_rescores(self):
        with tempfile.TemporaryDirectory() as d:
            # First init so the log skeleton exists with valid discovery.
            init_ns = fde.build_parser().parse_args(
                ["init", "acme", "--date", "2026-09-16", "--dir", d])
            fde.cmd_init(init_ns)
            log_path = str(Path(d) / "acme-2026-09-16.log.json")

            # Feed four weekly entries via stdin so the parser exits cleanly.
            inputs = iter([
                "480", "0.0003", "99.92", "180",
                "470", "0.0002", "99.93", "170",
                "460", "0.0002", "99.94", "160",
                "455", "0.0002", "99.95", "150",
            ])
            with patch("builtins.input", lambda *_a, **_kw: next(inputs)):
                for _ in range(4):
                    ns = fde.build_parser().parse_args(
                        ["log-week", log_path])
                    self.assertEqual(fde.cmd_log_week(ns), 0)

            log_data = json.loads(Path(log_path).read_text())
            self.assertEqual(len(log_data["post_ga_log"]), 4)
            self.assertEqual(log_data["post_ga_log"][0]["week"], 1)
            self.assertEqual(log_data["post_ga_log"][3]["week"], 4)


class TestWatch(unittest.TestCase):
    def test_watch_once_scores(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(harness.GOOD_RUN, f)
            path = f.name
        try:
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ns = fde.build_parser().parse_args(
                    ["watch", path, "--once"])
                self.assertEqual(fde.cmd_watch(ns), 0)
            self.assertIn("SCALE", buf.getvalue())
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()