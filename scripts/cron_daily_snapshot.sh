#!/usr/bin/env bash
# Wrapper for Hermes cron: daily standings snapshot.
# Runs daily_snapshot.py with the project venv; stdout is empty on success
# (silent = no notification), errors go to stderr → cron delivers error alert.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "$PROJECT_DIR/.venv/bin/python3" "$PROJECT_DIR/scripts/daily_snapshot.py"
