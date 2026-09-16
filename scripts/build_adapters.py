"""
Build agent-agnostic adapters from the canonical Hermes skill.

Reads .hermes/skills/fde-workflow.md (the single source of truth) and
emits loader files for Claude Code, Cursor, Cline, GitHub Copilot,
Continue.dev, OpenCode, and Codex. The Markdown body is shared — only
the frontmatter and surrounding scaffolding differ.

Idempotent: re-running produces identical output (deterministic).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".hermes" / "skills" / "fde-workflow.md"


def _parse_canonical():
    if not SRC.is_file():
        sys.exit(f"error: canonical skill not found at {SRC}")
    raw = SRC.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    if not m:
        sys.exit("error: canonical skill missing YAML frontmatter")
    front, body = m.group(1), m.group(2)
    fm = {}
    for line in front.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_hermes():
    """Already in place; just verify it still parses."""
    assert SRC.is_file(), "Hermes source missing"
    return SRC


def write_claude_code():
    out = ROOT / ".claude" / "skills" / NAME / "SKILL.md"
    body_text = (
        f"---\n"
        f"name: {NAME}\n"
        f"description: {DESCRIPTION}\n"
        f"---\n\n"
        f"# {fm.get('name', 'FDE Workflow')}\n\n"
        f"This skill applies to any task that is FDE-shaped: named customer,\n"
        f"external delivery, contracted SLA. It enforces a four-phase loop\n"
        f"(Discovery -> Architecture -> Build -> ROI Evaluation) and refuses\n"
        f"to write code until a named customer, metric M, baseline, target,\n"
        f"and SLA are on paper.\n\n"
        f"{body.strip()}\n"
    )
    _write(out, body_text)
    return out


def write_cursor():
    out = ROOT / ".cursor" / "rules" / f"{NAME}.mdc"
    body_text = (
        f"---\n"
        f"description: {DESCRIPTION}\n"
        f"globs:\n"
        f"  - 'engagements/**'\n"
        f"  - '.hermes.md'\n"
        f"  - 'tests/test_fde_eval.py'\n"
        f"  - 'fde/**'\n"
        f"alwaysApply: false\n"
        f"---\n\n"
        f"# {NAME}\n\n"
        f"When working in this repository, follow the four-phase FDE loop below\n"
        f"instead of jumping straight to code. The loop is non-negotiable for\n"
        f"FDE-shaped tasks (named customer, contracted SLA).\n\n"
        f"{body.strip()}\n"
    )
    _write(out, body_text)
    return out


def write_cline():
    out = ROOT / ".clinerules" / f"{NAME}.md"
    preamble = (
        f"# FDE Workflow (auto-loaded by Cline/Roo-Code)\n\n"
        f"This rule applies whenever the task is FDE-shaped: a named customer,\n"
        f"external delivery, or contracted SLA. Follow the four-phase loop\n"
        f"below before writing any code.\n\n"
        f"**Source of truth:** `.hermes/skills/fde-workflow.md` (kept in\n"
        f"sync by `scripts/build_adapters.py`).\n\n---\n\n"
    )
    _write(out, preamble + body.strip() + "\n")
    return out


def write_github_copilot():
    out = ROOT / ".github" / "instructions" / f"{NAME}.instructions.md"
    body_text = (
        f"---\n"
        f"applyTo: '**'\n"
        f"description: {DESCRIPTION}\n"
        f"---\n\n"
        f"# FDE Workflow\n\n"
        f"Apply this rule to every change in this repository. The FDE loop\n"
        f"is mandatory for any work tied to a customer outcome: refuse to\n"
        f"write code until Discovery is signed.\n\n"
        f"{body.strip()}\n"
    )
    _write(out, body_text)
    return out


def write_continue():
    out = ROOT / ".continue" / "rules" / f"{NAME}.md"
    body_text = (
        f"---\n"
        f"name: {NAME}\n"
        f"description: {DESCRIPTION}\n"
        f"version: 1.0.0\n"
        f"---\n\n"
        f"# {NAME}\n\n"
        f"Always apply this rule when the task touches a customer-facing\n"
        f"deliverable in this repository. The four-phase FDE loop below\n"
        f"must run end-to-end before any code is shipped.\n\n"
        f"{body.strip()}\n"
    )
    _write(out, body_text)
    return out


def write_opencode():
    out = ROOT / ".opencode" / "command" / f"{NAME}.md"
    body_text = (
        f"---\n"
        f"description: {DESCRIPTION}\n"
        f"agent: build\n"
        f"---\n\n"
        f"# /{NAME}\n\n"
        f"Run the four-phase FDE workflow. Refuse to write code until a\n"
        f"named customer, metric M, baseline, target, and SLA are on paper.\n\n"
        f"{body.strip()}\n"
    )
    _write(out, body_text)
    return out


def write_codex():
    out = ROOT / "AGENTS.md"
    body_text = (
        f"# AGENTS.md — Instructions for AI agents in this repository\n\n"
        f"This file is auto-discovered by Codex CLI and other agents that\n"
        f"follow the AGENTS.md convention. It mirrors the FDE workflow\n"
        f"skill so every agent in this repo behaves the same way.\n\n"
        f"> Source of truth: `.hermes/skills/fde-workflow.md`. Re-generate\n"
        f"> via `python scripts/build_adapters.py` after editing the source.\n\n"
        f"---\n\n"
        f"{body.strip()}\n\n---\n\n"
        f"## Pointer to scoring harness\n\n"
        f"Any agent in this repo can score an engagement log by running:\n\n"
        f"```bash\n"
        f"python -m fde score <engagement>.log.json\n"
        f"```\n\n"
        f"The harness is a black-box evaluator (`tests/test_fde_eval.py`)\n"
        f"that scores on four weighted axes (Business 35% / SLA 30% /\n"
        f"Latency trend 15% / Error rate 20%) and returns a decision:\n"
        f"`scale | iterate | cut`.\n"
    )
    _write(out, body_text)
    return out


ADAPTERS = [
    ("Hermes",          write_hermes),
    ("Claude Code",     write_claude_code),
    ("Cursor",          write_cursor),
    ("Cline/Roo",       write_cline),
    ("GitHub Copilot",  write_github_copilot),
    ("Continue.dev",    write_continue),
    ("OpenCode",        write_opencode),
    ("Codex/AGENTS.md", write_codex),
]


def main():
    global fm, body, NAME, DESCRIPTION
    fm, body = _parse_canonical()
    NAME = fm.get("name", "fde-workflow")
    DESCRIPTION = fm.get(
        "description",
        "Forward Deployed Engineer workflow: Discovery -> Architecture "
        "-> Build -> ROI Evaluation with a named customer and contracted SLA.",
    )
    written = []
    for label, fn in ADAPTERS:
        try:
            p = fn()
            written.append((label, p))
            print(f"  ok  {label:18s} -> {p.relative_to(ROOT)}  "
                  f"({p.stat().st_size} bytes)")
        except Exception as e:
            print(f"  FAIL {label}: {e}", file=sys.stderr)
            return 1
    print(f"\nwrote {len(written)} adapter files from {SRC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())