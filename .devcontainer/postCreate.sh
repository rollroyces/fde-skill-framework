#!/usr/bin/env bash
# Codespace / devcontainer post-create setup.
#
# What this does:
#   1. Regenerates every agent adapter from the canonical Hermes skill,
#      so the skill files are guaranteed up-to-date.
#   2. Runs the full test suite as a smoke check — if this fails, the
#      Codespace is broken and the user should file an issue.
#   3. Installs `hypothesis` so the property-based tests run.
#
# Everything else is stdlib-only by design; the framework has zero
# runtime dependencies.
set -euo pipefail

echo "==> FDE Skill Framework — post-create setup"
echo

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "1/3 Regenerating agent adapters from canonical skill..."
python3 "$ROOT/scripts/build_adapters.py"
echo

echo "2/3 Installing hypothesis (optional, for property-based tests)..."
python3 -m pip install --quiet hypothesis || echo "  (hypothesis install failed; property tests will skip)"
echo

echo "3/3 Running full test suite as smoke check..."
python3 -m unittest discover -s tests
echo

echo "==> Setup complete. Try:"
echo "    python -m fde --help"
echo "    python -m fde score /path/to/engagement.log.json"
echo "    python scripts/build_adapters.py    # regenerate adapters"