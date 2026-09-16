#!/usr/bin/env bash
# Install FDE-skill adapter files into global (per-user) agent config
# directories. Idempotent — re-running just overwrites.
#
# Use this when you want every project on your machine to load the FDE
# workflow skill automatically. For project-scoped install (recommended
# for teams), just clone the repo — the adapter files live at the repo
# root and most agents discover them automatically.
#
# Targets:
#   ~/.claude/skills/fde-workflow/SKILL.md        (Claude Code)
#   ~/.cursor/rules/fde-workflow.mdc              (Cursor)
#   ~/.clinerules/fde-workflow.md                 (Cline / Roo-Code)
#   ~/.continue/rules/fde-workflow.md             (Continue.dev)
#   ~/.opencode/command/fde-workflow.md           (OpenCode)
#   ~/.copilot/instructions/fde-workflow.instructions.md  (Copilot CLI)
#
# Skipped intentionally:
#   ~/.hermes/skills/         (per-project only — see .hermes.md)
#   AGENTS.md                 (per-project only — committed to repo root)

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

copy() {
    local src="$1" dst="$2"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  ok  $dst"
}

# Re-build first so the on-disk adapters match the canonical skill.
echo "Rebuilding adapters from $REPO_ROOT/.hermes/skills/fde-workflow.md"
python3 "$REPO_ROOT/scripts/build_adapters.py"
echo

echo "Installing global adapter files..."
copy "$REPO_ROOT/.claude/skills/fde-workflow/SKILL.md" \
      "$HOME/.claude/skills/fde-workflow/SKILL.md"
copy "$REPO_ROOT/.cursor/rules/fde-workflow.mdc" \
      "$HOME/.cursor/rules/fde-workflow.mdc"
copy "$REPO_ROOT/.clinerules/fde-workflow.md" \
      "$HOME/.clinerules/fde-workflow.md"
copy "$REPO_ROOT/.continue/rules/fde-workflow.md" \
      "$HOME/.continue/rules/fde-workflow.md"
copy "$REPO_ROOT/.opencode/command/fde-workflow.md" \
      "$HOME/.opencode/command/fde-workflow.md"
copy "$REPO_ROOT/.github/instructions/fde-workflow.instructions.md" \
      "$HOME/.copilot/instructions/fde-workflow.instructions.md"

echo
echo "Done. Reload your agent to pick up the new rule."