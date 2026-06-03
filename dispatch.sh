#!/usr/bin/env bash
# Cron entry: dry-run dispatch pass (logs signed payloads; never calls GitHub in Phase A).
set -euo pipefail
SERVICE_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${INBOX_WATCHER_ENV_FILE:-$HOME/.config/inbox-watcher/.env}"
[[ -f "$ENV_FILE" ]] || { echo "$(date -u +%FT%TZ) ERROR env file not found: $ENV_FILE" >&2; exit 3; }
set -a; source "$ENV_FILE"; set +a
cd "$SERVICE_DIR"; source .venv/bin/activate
export PYTHONPATH="$SERVICE_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m inbox_watcher.dispatcher
