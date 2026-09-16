"""
Validate the agent-agnostic adapter files.

Each adapter has a YAML frontmatter with different keys (Hermes uses
`name`, Claude Code uses `name`, Cursor uses `description` + `globs`,
Copilot uses `applyTo`, etc.). This test parses every adapter and
asserts:

1. Frontmatter is present and parses as YAML.
2. Required keys per format are present.
3. The Markdown body contains the canonical four-phase loop names.
4. The build script is deterministic (re-running produces identical bytes).

This catches frontmatter typos and silent drift between adapters.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_adapters  # noqa: E402

# Each adapter's expected file path and required frontmatter keys.
# (path, [required_keys], [forbidden_keys], marker_phrases_in_body)
ADAPTERS = [
    (
        ".hermes/skills/fde-workflow.md",
        ["name", "description"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".claude/skills/fde-workflow/SKILL.md",
        ["name", "description"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".cursor/rules/fde-workflow.mdc",
        ["description", "globs"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".clinerules/fde-workflow.md",
        [],
        [],  # Cline/Roo has no frontmatter — plain markdown
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".github/instructions/fde-workflow.instructions.md",
        ["applyTo", "description"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".continue/rules/fde-workflow.md",
        ["name", "description"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        ".opencode/command/fde-workflow.md",
        ["description"],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
    (
        "AGENTS.md",
        [],
        [],
        ["Discovery", "Architecture", "Build", "ROI Evaluation"],
    ),
]


def _parse_frontmatter(text: str):
    """Minimal YAML frontmatter parser for the keys we actually use.

    Avoids pulling in PyYAML as a test dependency. Handles scalars, lists
    (one per line, indented, starting with `-`), and `applyTo: '**'`.
    Sufficient for asserting required keys exist.
    """
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    parsed = {}
    current_key = None
    for line in fm.splitlines():
        if line.startswith("  - "):
            if current_key is not None:
                parsed.setdefault(current_key, []).append(
                    line[4:].strip().strip('"').strip("'"))
        elif ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v == "":
                current_key = k
                parsed[k] = []
            else:
                current_key = k
                parsed[k] = v
    return parsed


class TestAdapters(unittest.TestCase):

    def setUp(self):
        # Re-run the build script so we test the current source, not a
        # stale on-disk copy. Output must be byte-identical to what's
        # already on disk (determinism check).
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_adapters.py")],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"build_adapters.py failed: {result.stderr}")

    def _assert_adapter(self, rel_path, required, forbidden, markers):
        path = ROOT / rel_path
        self.assertTrue(path.is_file(), f"missing adapter: {rel_path}")
        text = path.read_text()
        if required or forbidden:
            fm = _parse_frontmatter(text)
            self.assertIsNotNone(fm,
                f"{rel_path}: no YAML frontmatter")
            for key in required:
                self.assertIn(key, fm,
                    f"{rel_path}: missing required frontmatter key '{key}'")
            for key in forbidden:
                self.assertNotIn(key, fm,
                    f"{rel_path}: forbidden frontmatter key '{key}' present")
        for phrase in markers:
            self.assertIn(phrase, text,
                f"{rel_path}: canonical loop phrase '{phrase}' missing")

    def test_all_adapters_present_and_parsed(self):
        for rel, req, forbid, markers in ADAPTERS:
            with self.subTest(adapter=rel):
                self._assert_adapter(rel, req, forbid, markers)

    def test_canonical_source_unchanged(self):
        """The build script must not modify the source of truth."""
        src = ROOT / ".hermes" / "skills" / "fde-workflow.md"
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_adapters.py")],
            capture_output=True)
        after = hashlib.sha256(src.read_bytes()).hexdigest()
        self.assertEqual(before, after,
                         "build_adapters.py modified the source skill")

    def test_build_is_idempotent(self):
        """Re-running the builder produces byte-identical adapters."""
        before = {}
        for rel, *_ in ADAPTERS:
            p = ROOT / rel
            if p.is_file():
                before[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_adapters.py")],
            capture_output=True)
        after = {}
        for rel, *_ in ADAPTERS:
            p = ROOT / rel
            self.assertTrue(p.is_file(),
                            f"adapter vanished after rebuild: {rel}")
            after[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(before, after,
                         "build_adapters.py is non-deterministic")

    def test_globs_in_cursor_rule_cover_fde_paths(self):
        """Cursor's globs must include the FDE working paths so the rule
        activates when an agent touches an engagement file."""
        path = ROOT / ".cursor" / "rules" / "fde-workflow.mdc"
        fm = _parse_frontmatter(path.read_text())
        self.assertIsNotNone(fm)
        globs = fm.get("globs", [])
        self.assertIsInstance(globs, list)
        self.assertTrue(any("engagements" in g for g in globs),
                        f"globs must cover engagements/: {globs}")
        self.assertTrue(any(".hermes.md" in g for g in globs),
                        f"globs must cover .hermes.md: {globs}")

    def test_copilot_applyTo_is_wildcard(self):
        path = ROOT / ".github" / "instructions" / "fde-workflow.instructions.md"
        fm = _parse_frontmatter(path.read_text())
        self.assertEqual(fm.get("applyTo"), "**",
                         "Copilot rule must apply to all files")


if __name__ == "__main__":
    unittest.main()