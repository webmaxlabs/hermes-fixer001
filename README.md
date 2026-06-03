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
