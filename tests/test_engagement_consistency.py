"""
Enforce that every engagement log has a sibling markdown narrative and
that the two stay in sync.

Engagement artifacts live in `engagements/<name>.{log.json,md}`. The JSON
is what `python -m fde score` reads; the markdown is the human narrative
(Discovery, Architecture, Build log, ROI evaluation). A contributor who
updates one without the other would silently drift them — and the
scoring harness would happily score a JSON whose narrative says the
opposite thing.

Five invariants are enforced for every tracked `<name>.log.json` in
`engagements/`:

  1. Sibling `<name>.md` exists in the same directory.
  2. The markdown contains a `## ROI evaluation` section.
  3. The markdown's ROI evaluation mentions the decision word that matches
     the harness's verdict (parsed by re-running `evaluate()` on the JSON).
     A clear diff is printed when they disagree.
  4. The JSON's `post_ga_log` length equals the number of weekly entries in
     the markdown's `## Build (ship log)` section (lines starting with
     `- YYYY-MM-DD` or `- <date>:`).
  5. The engagement name in the JSON matches the markdown's
     `# Engagement: <name>, <date>` header.

Only **tracked** engagement files are checked. Untracked drafts in
`engagements/` (e.g. WIP files from a sibling branch that haven't been
committed yet) are ignored — running this locally should not fail because
of unrelated in-progress work. CI sees only tracked files.

A property-based fuzzer mutates a known-good baseline and asserts the
checker catches every mutation. The fuzzer is wrapped in the same
`HAS_HYPOTHESIS` shim as `test_properties.py`, so the framework's
zero-dep contract is preserved when hypothesis is absent.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Reuse the harness that `python -m fde score` uses, so the consistency
# check can't drift from the CLI's verdict.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import test_fde_eval as harness  # noqa: E402

ENGAGEMENTS_DIR = ROOT / "engagements"

# Decision words we look for in the markdown. They match the harness's
# {scale, iterate, cut} set in upper-case form (the canonical markdown
# phrasing is "Decision: SCALE/ITERATE/CUT").
_DECISION_WORDS = {"scale", "iterate", "cut"}

# Lines that count as a "weekly entry" in the Build (ship log) section.
# Accepts "- YYYY-MM-DD" or "- <date>:" where <date> is anything that's
# followed by a colon (the markdown uses "- 2026-09-23: vertical slice...").
_BUILD_ENTRY_RE = re.compile(r"^\s*-\s+\S[^:]*:\s+\S")

try:
    import hypothesis.strategies as _real_st
    from hypothesis import given as _real_given
    from hypothesis import settings as _real_settings
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

if not HAS_HYPOTHESIS:
    # Same shim pattern as test_properties.py: stubs so the module loads
    # even when hypothesis isn't installed. The fuzzer class is wrapped
    # with @unittest.skipUnless, so it won't actually run.
    class _StStrategies:
        def __getattr__(self, name):
            def _stub(*_a, **_kw):
                return self
            return _stub

    st = _StStrategies()

    def given(*_a, **_kw):
        def deco(fn):
            return fn
        return deco

    def settings(*_a, **_kw):
        def deco(fn):
            return fn
        return deco
else:
    st = _real_st
    given = _real_given
    settings = _real_settings


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _tracked_engagement_files(root: Path):
    """Return the set of engagement files tracked by git, relative to root.

    Uses the repo root (not the engagements dir) as the git cwd so that
    `git ls-files engagements/` resolves correctly regardless of where
    the test is run from.

    Falls back to None (sentinel: check everything) if `git ls-files`
    fails — better to over-check than silently skip.
    """
    # root is engagements/; the repo root is its parent.
    repo_root = root.resolve().parent
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "engagements/"],
            cwd=repo_root, text=True, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None  # sentinel: check everything
    return set(out.splitlines())


def _engagement_pairs(root: Path):
    """Yield (log_path, md_path, name) for tracked .log.json under root.

    Sorted by stem so failures are reproducible. Untracked files are
    skipped so a developer with WIP drafts in another branch's working
    tree doesn't see spurious failures here.
    """
    tracked = _tracked_engagement_files(root)
    for log_path in sorted(root.glob("*.log.json")):
        # root is the engagements dir itself; tracked paths are repo-
        # relative (e.g. "engagements/foo.log.json"), so prepend the
        # directory name.
        rel = (root.name + "/" + log_path.name)
        if tracked is not None and rel not in tracked:
            continue
        name = log_path.name[: -len(".log.json")]
        md_path = log_path.with_name(name + ".md")
        yield log_path, md_path, name


def _extract_roi_section(md_text: str) -> str:
    """Return the body of the `## ROI evaluation` section, or "" if absent."""
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^##\s+ROI evaluation\b", line):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^##\s+", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _extract_build_section(md_text: str) -> str:
    """Return the body of the `## Build` section, or "" if absent."""
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Build\b", line):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^##\s+", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


# Lines that look like a post-GA telemetry bullet. A bullet is "weekly
# telemetry" iff it (a) starts with `-` and (b) reports at least one of
# the three measured quantities: p99 latency, error rate, availability.
# Release milestones (vertical slice, GA, postmortem, etc.) do NOT match
# this filter — they're real and important but they're not weekly entries.
_WEEKLY_TELEMETRY_RE = re.compile(
    r"\b(p99[_ ]?(ms|latency)?|error[_ ]?rate|availability|error[_ ]?budget)\b",
    re.IGNORECASE,
)


def _count_build_entries(build_section: str) -> int:
    """Count weekly post-GA telemetry bullets in a `## Build` section.

    A bullet qualifies iff it matches the basic `- <text>: <text>` shape
    AND mentions at least one of the measured quantities (p99 latency,
    error rate, availability) ANYWHERE in the bullet — including
    continuation lines, since the dogfood engagement wraps bullets
    across multiple lines. Release-milestone bullets ("vertical slice
    live", "GA", "postmortem", etc.) are intentionally excluded only when
    they don't report telemetry; if a milestone bullet happens to
    include p99/availability numbers (e.g. "vertical slice live,
    p99=720ms") it's still counted.
    """
    basic_re = re.compile(r"^\s*-\s+\S[^:]*:\s+\S")
    n = 0
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal n
        if not current_lines:
            return
        joined = "\n".join(current_lines)
        if basic_re.match(current_lines[0]) and _WEEKLY_TELEMETRY_RE.search(joined):
            n += 1
        current_lines.clear()

    for ln in build_section.splitlines():
        if ln.lstrip().startswith("- "):
            _flush()
            current_lines.append(ln)
        elif current_lines and ln.strip() == "":
            _flush()
        elif current_lines:
            current_lines.append(ln)
    _flush()
    return n


def _extract_decision_from_markdown(roi_section: str):
    """Return the decision word found in the ROI section, or None.

    Looks for `Decision: <WORD>` (case-insensitive). Returns the lower-case
    version so it can be compared against the harness's verdict.
    """
    m = re.search(r"\*\*Decision:\s*(\w+)\*\*", roi_section, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # Fallback: any standalone ALL-CAPS decision word in the section.
    m = re.search(r"\b(SCALE|ITERATE|CUT)\b", roi_section)
    if m:
        return m.group(1).lower()
    return None


def _check_pair(log_path: Path, md_path: Path, name: str) -> list[str]:
    """Run all five invariants; return a list of human-readable failures."""
    failures: list[str] = []

    # 1. Sibling markdown exists.
    if not md_path.is_file():
        failures.append(
            f"[{name}] missing sibling markdown: {md_path.name} "
            f"(expected every `*.log.json` to have a `*.md` narrative)"
        )
        # Without the markdown we can't check anything else.
        return failures

    md_text = md_path.read_text(encoding="utf-8")
    try:
        log_obj = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        failures.append(f"[{name}] invalid JSON in {log_path.name}: {e}")
        return failures

    # 2. ROI evaluation section present.
    roi_section = _extract_roi_section(md_text)
    if not roi_section:
        failures.append(
            f"[{name}] markdown is missing the `## ROI evaluation` section"
        )

    # 3. Decision in markdown matches the harness verdict.
    if roi_section:
        md_decision = _extract_decision_from_markdown(roi_section)
        try:
            rep = harness.evaluate(log_obj)
            harness_decision = rep.decision
        except Exception as e:  # noqa: BLE001
            harness_decision = None
            rep = None
            failures.append(
                f"[{name}] harness.evaluate() raised {type(e).__name__}: {e}"
            )

        if md_decision is None:
            failures.append(
                f"[{name}] markdown ROI section has no decision word "
                f"(expected one of {sorted(_DECISION_WORDS)})"
            )
        elif md_decision not in _DECISION_WORDS:
            failures.append(
                f"[{name}] markdown decision `{md_decision}` is not one of "
                f"{sorted(_DECISION_WORDS)}"
            )
        elif harness_decision is None:
            # evaluate() failed and already added a failure above; nothing
            # more to say.
            pass
        elif md_decision != harness_decision:
            assert rep is not None  # harness_decision came from rep
            failures.append(
                f"[{name}] decision drift: markdown says "
                f"`{md_decision.upper()}` but `python -m fde score` says "
                f"`{harness_decision.upper()}` "
                f"(overall={rep.overall:.1f}/100). "
                f"Either fix the JSON so the harness matches, or fix the "
                f"markdown's `**Decision: ...**` line."
            )

    # 4. post_ga_log length == build-entry count.
    log_entries = log_obj.get("post_ga_log", [])
    log_len = len(log_entries) if isinstance(log_entries, list) else 0
    build_section = _extract_build_section(md_text)
    if not build_section:
        failures.append(
            f"[{name}] markdown is missing the `## Build` section "
            f"(needed to cross-check weekly entry count)"
        )
        md_count = 0
    else:
        md_count = _count_build_entries(build_section)

    if log_len != md_count:
        failures.append(
            f"[{name}] weekly-entry count drift: JSON `post_ga_log` has "
            f"{log_len} entries but markdown `## Build` lists {md_count} "
            f"(`- YYYY-MM-DD...` / `- <date>: ...` bullets). "
            f"Add a week to whichever side is short, or remove one."
        )

    # 5. JSON `engagement` field matches markdown header.
    json_name = log_obj.get("engagement", "")
    header_re = re.compile(
        r"^#\s+Engagement:\s*([^,]+),\s*(\S+)", re.MULTILINE
    )
    m = header_re.search(md_text)
    if not m:
        failures.append(
            f"[{name}] markdown is missing the `# Engagement: <name>, <date>` "
            f"header (needed to cross-check engagement id)"
        )
    else:
        md_name = m.group(1).strip()
        if md_name != json_name:
            failures.append(
                f"[{name}] engagement-id drift: JSON `engagement` is "
                f"`{json_name}` but markdown header says `{md_name}`"
            )

    return failures


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

class TestEngagementConsistency(unittest.TestCase):
    """Walk engagements/ and assert every <name>.log.json is consistent."""

    def test_every_engagement_log_has_consistent_markdown(self):
        all_failures: list[str] = []
        examined = 0
        for log_path, md_path, name in _engagement_pairs(ENGAGEMENTS_DIR):
            examined += 1
            all_failures.extend(_check_pair(log_path, md_path, name))

        if all_failures:
            header = (
                f"\n{len(all_failures)} engagement-consistency violation(s) "
                f"across {examined} engagement(s):\n"
            )
            self.fail(header + "\n".join(f"  - {f}" for f in all_failures))

        self.assertGreaterEqual(
            examined, 1,
            "no engagements/*.log.json files found — the consistency check "
            "needs at least one engagement to validate"
        )


# --------------------------------------------------------------------------- #
# Fuzzer: mutate GOOD_RUN and assert the checker catches each mutation.
# --------------------------------------------------------------------------- #

# A minimal but realistic engagement + matching markdown that scores
# "scale". Used as the seed for the property-based fuzzer.
GOOD_LOG = {
    "engagement": "fuzz-test-engagement",
    "discovery": {
        "sponsor": "Fuzz Sponsor, VP Eng",
        "metric": {"name": "p99_latency_ms",
                   "baseline": 800, "target": 200, "date": "2026-12-31"},
        "sla": {"p99_ms": 500, "availability_pct": 99.9,
                "error_budget_pct": 0.1},
        "constraints": ["GDPR"],
        "stakeholders": ["a", "b", "c"],
        "roi_inputs": {"value_per_unit": 10,
                       "volume_per_year": 10000,
                       "cost_ceiling_usd": 100000},
    },
    "post_ga_log": [
        {"week": w, "p99_ms": 400.0 - w * 5,
         "error_rate": 0.0001, "availability_pct": 99.95,
         "metric_value": 800 - w * 20}
        for w in range(1, 5)
    ],
}

GOOD_MD_TEMPLATE = """\
# Engagement: {name}, 2026-12-31

## 0. Engagement metadata
... (synthetic; the fuzzer doesn't read this body)

## Build (ship log)
{build_entries}

## ROI evaluation (final, post-GA)
- baseline=800, now=505 target achieved
- SLA met
- Cost under budget

**Decision: {decision}**
"""


def _render_good_md(decision: str = "SCALE", entry_count: int = 4,
                    name: str = "fuzz-test-engagement") -> str:
    # Each bullet must mention at least one telemetry keyword (p99 /
    # availability / error_rate) so it counts as a post-GA telemetry
    # bullet under the consistency check, matching the JSON weeks.
    entries = "\n".join(
        f"- 2026-09-{i:02d}: week {i} post-GA — p99=400ms, "
        f"error_rate=0.0001, availability=99.95% (under target)."
        for i in range(1, entry_count + 1)
    )
    return GOOD_MD_TEMPLATE.format(name=name, build_entries=entries,
                                   decision=decision)


# Mutation strategies. Each one returns a (log_obj, md_text, expected_to_fail)
# tuple where expected_substr names the invariant the mutation breaks.

def _mutate_engagement_name(log_obj, md_text):
    log_obj = json.loads(json.dumps(log_obj))
    log_obj["engagement"] = log_obj["engagement"] + "-mismatched"
    return log_obj, md_text, "engagement-id drift"


def _mutate_decision_word(log_obj, md_text):
    new_md = re.sub(r"\*\*Decision:\s*\w+\*\*",
                    "**Decision: ITERATE**", md_text)
    return log_obj, new_md, "decision drift"


def _mutate_post_ga_length(log_obj, md_text):
    log_obj = json.loads(json.dumps(log_obj))
    log_obj["post_ga_log"] = log_obj["post_ga_log"][:-1]  # drop last week
    return log_obj, md_text, "weekly-entry count drift"


def _mutate_remove_roi_section(log_obj, md_text):
    new_md = re.sub(r"## ROI evaluation[^\n]*\n.*?(?=\n## |\Z)",
                    "", md_text, count=1, flags=re.DOTALL)
    return log_obj, new_md, "ROI evaluation"


def _mutate_remove_build_section(log_obj, md_text):
    new_md = re.sub(r"## Build[^\n]*\n.*?(?=\n## |\Z)",
                    "", md_text, count=1, flags=re.DOTALL)
    return log_obj, new_md, "Build"


def _mutate_missing_sibling_md(log_obj, md_text):
    # Signal "no markdown file" via a sentinel value; the test handler
    # deletes the file when it sees this.
    return log_obj, "__DELETE_MD__", "missing sibling markdown"


# Hypothesis strategy: pick one of the mutations.
mutations = st.sampled_from([
    _mutate_engagement_name,
    _mutate_decision_word,
    _mutate_post_ga_length,
    _mutate_remove_roi_section,
    _mutate_remove_build_section,
    _mutate_missing_sibling_md,
])


@unittest.skipUnless(HAS_HYPOTHESIS,
                     "hypothesis not installed — run "
                     "`pip install hypothesis` to enable fuzzer")
class TestConsistencyFuzzer(unittest.TestCase):
    """Mutate GOOD_RUN and assert the checker catches every mutation."""

    @given(mutations)
    @settings(max_examples=50, deadline=None)
    def test_mutations_are_caught(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            log_path = tmpdir / "fuzz-test-engagement.log.json"
            md_path = tmpdir / "fuzz-test-engagement.md"

            log_path.write_text(json.dumps(GOOD_LOG, indent=2))
            md_path.write_text(_render_good_md())

            log_obj, mutated_md, expected_substr = mutate(
                json.loads(json.dumps(GOOD_LOG)),
                md_path.read_text(),
            )

            if mutated_md == "__DELETE_MD__":
                # Sibling-missing mutation: delete the markdown file.
                md_path.unlink()
            else:
                md_path.write_text(mutated_md)

            log_path.write_text(json.dumps(log_obj, indent=2))

            failures = _check_pair(log_path, md_path, "fuzz-test-engagement")

            # The mutation must produce at least one failure, and that
            # failure must mention what we broke.
            self.assertTrue(
                failures,
                f"mutation {mutate.__name__} was NOT caught by the "
                f"consistency checker (this is a bug in the checker)"
            )
            joined = "\n".join(failures)
            self.assertIn(
                expected_substr, joined,
                f"mutation {mutate.__name__} caught, but the failure "
                f"message doesn't mention the broken invariant. "
                f"Expected substring `{expected_substr}` in:\n{joined}"
            )

    def test_good_run_passes(self):
        """Sanity check: the seed itself is consistent."""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            log_path = tmpdir / "fuzz-test-engagement.log.json"
            md_path = tmpdir / "fuzz-test-engagement.md"
            log_path.write_text(json.dumps(GOOD_LOG, indent=2))
            md_path.write_text(_render_good_md())

            failures = _check_pair(log_path, md_path, "fuzz-test-engagement")
            self.assertEqual(
                failures, [],
                f"good run produced unexpected failures: {failures}"
            )


if __name__ == "__main__":
    if not HAS_HYPOTHESIS:
        print("hypothesis not installed — fuzzer will be skipped. "
              "Run `pip install hypothesis` to enable it.")
    unittest.main()
