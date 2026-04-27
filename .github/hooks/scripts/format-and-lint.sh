#!/usr/bin/env bash
# .github/hooks/scripts/format-and-lint.sh
# Runs black, isort, and flake8 over Python files modified in the working tree.
# Called by the Stop hook at end of an agent session.

set -uo pipefail

VENV_PYTHON=".venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "HOOK SKIP: .venv not found — skipping format/lint."
    exit 0
fi

# Collect unstaged + staged modified/added Python files
UNSTAGED=$(git diff --name-only --diff-filter=ACMR 2>/dev/null | grep '\.py$' || true)
STAGED=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.py$' || true)
FILES=$(echo -e "${UNSTAGED}\n${STAGED}" | sort -u | while read -r f; do [ -f "$f" ] && echo "$f"; done)

if [ -z "$FILES" ]; then
    echo "HOOK SKIP: no modified Python files."
    exit 0
fi

COUNT=$(echo "$FILES" | wc -l | tr -d ' ')

echo "HOOK: formatting ${COUNT} file(s) with black..."
echo "$FILES" | xargs "$VENV_PYTHON" -m black --quiet 2>&1

echo "HOOK: sorting imports with isort..."
echo "$FILES" | xargs "$VENV_PYTHON" -m isort --quiet 2>&1

echo "HOOK: linting with flake8..."
echo "$FILES" | xargs "$VENV_PYTHON" -m flake8 2>&1 || echo "HOOK WARN: flake8 reported issues (see above)."

# Always exit 0 so the hook never blocks the session from ending
exit 0
