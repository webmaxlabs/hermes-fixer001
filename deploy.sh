#!/usr/bin/env bash
set -euo pipefail
REMOTE="${INBOX_WATCHER_REMOTE:-agent001}"
REMOTE_DIR="${INBOX_WATCHER_REMOTE_DIR:-/home/agent001/services/inbox-watcher}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "==> rsync source to $REMOTE:$REMOTE_DIR"
ssh "$REMOTE" "mkdir -p '$REMOTE_DIR' && mkdir -p \$HOME/inbox-watcher"
rsync -az --delete \
  --exclude '.venv/' --exclude 'data/' --exclude 'findings/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.git/' \
  --exclude 'docs/' --exclude 'NOTES-agentmail.md' \
  "$REPO_DIR/" "$REMOTE:$REMOTE_DIR/"
ssh "$REMOTE" bash -s <<EOF
set -euo pipefail
cd "$REMOTE_DIR"
if command -v uv >/dev/null 2>&1; then
  [[ -x .venv/bin/python ]] || uv venv --python 3.11
  source .venv/bin/activate; uv pip install -e .
else
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  source .venv/bin/activate; pip install --quiet --upgrade pip; pip install --quiet -e .
fi
EOF
ssh "$REMOTE" "chmod +x '$REMOTE_DIR/run.sh' '$REMOTE_DIR/digest.sh' '$REMOTE_DIR/heartbeat.sh'"
echo "==> done. Next: create \$HOME/.config/inbox-watcher/.env (chmod 600), then smoke test:"
echo "      cd $REMOTE_DIR && ./run.sh && ./digest.sh"
