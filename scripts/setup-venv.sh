#!/bin/bash
# Local-development venv setup for frc-scheduler-server.
#
# Creates ./.venv, installs requirements.txt + requirements-research.txt
# into it. Idempotent — safe to re-run after pulling new code or to
# reinstall after deleting .venv.
#
# Usage:
#   ./scripts/setup-venv.sh            # create or update .venv
#   source .venv/bin/activate          # use it
#   ./scripts/setup-venv.sh --recreate # blow away and start fresh
#
# This venv is for local Stark eval runs and dev. Production
# (OpenShift container) installs requirements separately at build
# time via Containerfile.

set -euo pipefail

cd "$(dirname "$0")/.."   # repo root regardless of where script is invoked

VENV_DIR=".venv"
RECREATE=0
for arg in "$@"; do
    case "$arg" in
        --recreate) RECREATE=1 ;;
        -h|--help)
            echo "Usage: $0 [--recreate]"
            echo "  Creates ./.venv and installs requirements*.txt into it."
            echo "  --recreate: blow away existing venv first."
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2 ; exit 1 ;;
    esac
done

if [[ "$RECREATE" -eq 1 && -d "$VENV_DIR" ]]; then
    echo "Removing existing $VENV_DIR..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating venv in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Using existing $VENV_DIR (pass --recreate to start fresh)"
fi

# Use the venv's python/pip directly — don't require the caller to
# have activated the venv before running this script.
PY="$VENV_DIR/bin/python3"
PIP="$VENV_DIR/bin/pip"

echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

echo "Installing production requirements..."
"$PIP" install --quiet -r requirements.txt

if [[ -s requirements-research.txt ]]; then
    # Only run if non-empty (the file may be a placeholder)
    if grep -qv '^\s*\(#.*\)\?$' requirements-research.txt; then
        echo "Installing research requirements..."
        "$PIP" install --quiet -r requirements-research.txt
    fi
fi

echo ""
echo "Done. To use the venv:"
echo "    source $VENV_DIR/bin/activate"
echo ""
echo "Quick verify:"
"$PY" -c "import fastapi, sqlalchemy, ortools; print('  ✓ fastapi, sqlalchemy, ortools all import')"
echo ""
echo "Run the eval (venv activated):"
echo "    python3 scripts/scheduler_eval/runner.py --fixtures 2023mnmi --adapters frc-scheduler-server,matchmaker --trials 1"
