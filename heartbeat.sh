#!/usr/bin/env bash
# Self-monitor: Slack alarm if the ingest hasn't run in THRESHOLD_HOURS.
set -euo pipefail
ENV_FILE="${INBOX_WATCHER_ENV_FILE:-$HOME/.config/inbox-watcher/.env}"
HEARTBEAT="${INBOX_WATCHER_HEARTBEAT_PATH:-$HOME/inbox-watcher/.last-run}"
THRESHOLD_HOURS=1
[[ -f "$ENV_FILE" ]] || { echo "ERROR env file not found: $ENV_FILE" >&2; exit 3; }
set -a; source "$ENV_FILE"; set +a
if [[ ! -f "$HEARTBEAT" ]]; then AGE_HOURS=999; else
  NOW_S=$(date +%s); HB_S=$(stat -c %Y "$HEARTBEAT" 2>/dev/null || stat -f %m "$HEARTBEAT")
  AGE_HOURS=$(( (NOW_S - HB_S) / 3600 )); fi
if (( AGE_HOURS < THRESHOLD_HOURS )); then echo "heartbeat OK (age ${AGE_HOURS}h)"; exit 0; fi
TEXT="[URGENT] inbox-watcher ingest has not run in ${AGE_HOURS}h — check agent001:~/inbox-watcher/run.log"
curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" -H "Content-Type: application/json" \
  -d "$(printf '{"channel":"%s","text":%s}' "${SLACK_DIGEST_CHANNEL}" "$(printf '%s' "$TEXT" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')")" >/dev/null
echo "heartbeat ALARM sent (age ${AGE_HOURS}h)"
