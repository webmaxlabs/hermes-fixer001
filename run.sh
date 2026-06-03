#!/usr/bin/env bash
# Cron entry: one ingest cycle.
set -euo pipefail
SERVICE_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${INBOX_WATCHER_ENV_FILE:-$HOME/.config/inbox-watcher/.env}"
mkdir -p "$HOME/inbox-watcher"
[[ -f "$ENV_FILE" ]] || { echo "$(date -u +%FT%TZ) ERROR env file not found: $ENV_FILE" >&2; exit 3; }
set -a; source "$ENV_FILE"; set +a
cd "$SERVICE_DIR"; source .venv/bin/activate
export PYTHONPATH="$SERVICE_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m inbox_watcher
