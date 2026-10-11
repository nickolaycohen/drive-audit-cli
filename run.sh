#!/usr/bin/env bash
# ==============================================================================
# run.sh — Drive Audit & Storage Orchestrator Launcher
# ==============================================================================
# Navigates to the project directory, activates the virtual environment if present,
# and launches the main interactive Python CLI orchestrator.
# ==============================================================================

set -e

# Resolve project directory regardless of where the script is called from
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Activate virtual environment if available
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"
elif [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
fi

# Execute the primary CLI orchestrator, passing any optional CLI arguments
exec python3 python/drive_audit_finder.py "$@"
