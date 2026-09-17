#!/usr/bin/env python3
"""
Pre-commit hook: validate every engagements/*.log.json before it's
committed. Catches:

  - malformed JSON (parse error)
  - missing required fields (engagement, discovery, post_ga_log)
  - wrong types (e.g. post_ga_log is not a list)

This runs in <100ms locally and gives instant feedback instead of
waiting for GitHub Actions to flag the issue. Install with:

    pip install pre-commit
    pre-commit install

Then `git commit` will refuse to proceed if any engagement log is invalid.

Bypassing the hook for a one-off commit: `git commit --no-verify`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_TOP_KEYS = {"engagement", "discovery", "post_ga_log"}
REQUIRED_DISCOVERY_KEYS = {"sponsor", "metric", "sla", "constraints",
                           "stakeholders", "roi_inputs"}


def validate_one(path: Path) -> list[str]:
    """Return a list of error messages (empty = valid)."""
    errors: list[str] = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"  - {path}: invalid JSON: {e}"]

    if not isinstance(data, dict):
        return [f"  - {path}: top-level must be an object, got {type(data).__name__}"]

    missing = REQUIRED_TOP_KEYS - data.keys()
    if missing:
        errors.append(f"  - {path}: missing top-level keys: {sorted(missing)}")

    if "discovery" in data and isinstance(data["discovery"], dict):
        d_missing = REQUIRED_DISCOVERY_KEYS - data["discovery"].keys()
        if d_missing:
            errors.append(
                f"  - {path}: missing discovery keys: {sorted(d_missing)}")

    if "post_ga_log" in data and not isinstance(data["post_ga_log"], list):
        errors.append(
            f"  - {path}: post_ga_log must be a list, "
            f"got {type(data['post_ga_log']).__name__}")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: pre_commit_validate.py <file1.json> [file2.json ...]",
              file=sys.stderr)
        return 2
    all_errors: list[str] = []
    for arg in argv[1:]:
        p = Path(arg)
        if not p.name.endswith(".log.json"):
            continue  # not an engagement log
        all_errors.extend(validate_one(p))
    if all_errors:
        print("engagement-log validation failed:", file=sys.stderr)
        for e in all_errors:
            print(e, file=sys.stderr)
        print("\nBypass with `git commit --no-verify` if you're sure.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))