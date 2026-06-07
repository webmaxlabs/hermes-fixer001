# inbox-watcher

Polls `fixer001@agentmail.to` (forwarded `alerts@webmaxlabs.com`), authenticates
vendor alerts, classifies by priority, and posts a daily Slack digest to
`#hermes-digest`. Notify-only (Spec 1). Built on `hermes-watcher-core`.

## Deploy
`./deploy.sh` → rsyncs to `agent001:~/services/inbox-watcher` and installs.
Create `~/.config/inbox-watcher/.env` (chmod 600) from `.env.example`.

## Cron (agent001, `crontab -e`)
```
*/10 * * * * /home/agent001/services/inbox-watcher/run.sh      >> $HOME/inbox-watcher/run.log 2>&1
0    8 * * * /home/agent001/services/inbox-watcher/digest.sh   >> $HOME/inbox-watcher/digest.log 2>&1
17   * * * * /home/agent001/services/inbox-watcher/heartbeat.sh >> $HOME/inbox-watcher/heartbeat.log 2>&1
```

## Dry-run dispatcher (Spec 2 Phase A)

`python -m inbox_watcher.dispatcher` (via `dispatch.sh`) reads the day's findings,
selects actionable ones (priority P1/P2 **and** a resolved allowlisted `repo`),
dedups them through `findings/dispatched.jsonl` (one open dispatch per
`sha256(repo|rule_id)`), and **logs** a signed payload it *would* send. It never
calls GitHub in Phase A; `DISPATCH_MODE=live` raises `NotImplementedError`.

Repo resolution is governed by `config/repo_map.yaml` — the static map is the
security gate, so email can only select among pre-authorized repos. The shipped
slugs are placeholders marked `VERIFY`; populate them from the first real vendor
mail before relying on dispatch.

Cron (America/Phoenix MST), offset from the `*/10` ingest tick:

    5-59/10 * * * * /home/<user>/services/inbox-watcher/dispatch.sh >> /home/<user>/inbox-watcher/dispatch.log 2>&1

Requires `HERMES_FIXER_DISPATCH_SECRET` in `~/.config/inbox-watcher/.env` (chmod 600).

## Phase B: agent001-hosted Codex fixer

When `DISPATCH_MODE=live`, a fixer-eligible finding (P1/P2 + mapped repo + the rule
has `fixer: true`) triggers Codex on a fresh clone and opens a **draft** PR
(`hermes-fixer/<sig>`), labelled `hermes-fixer` + priority. Never merges. Runs
in-process, lockfile-guarded (`fixer.lock`), record-before-emit (a crash leaves the
signature open: no auto-retry, never a double PR). The Codex prompt is built only
from the rule's description + fix_hint + repo — no email text.

`python -m inbox_watcher.dispatcher --reconcile` closes ledger signatures whose PR
merged/closed, re-enabling dispatch on recurrence (cron daily).

Eligibility is opt-in: add `fixer: true` to a rule in `config/rules.yaml`.
