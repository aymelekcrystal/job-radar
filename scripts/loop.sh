#!/usr/bin/env bash
# Keeps scanning every 15 minutes inside one workflow run, then starts the next run itself.
# GitHub's own "schedule" trigger turned out to fire only every few hours for this repo,
# so the hourly schedule is only a watchdog that restarts this loop if it ever stops.
set -u
ARGS="${1:-}"
WF="radar.yml"

save() {
  git add docs/jobs.json docs/desc.json data
  git diff --cached --quiet && return 0
  git commit -q -m "radar: update"
  git pull -q --rebase --autostash || { git rebase --abort 2>/dev/null; git pull -q --no-rebase -X ours || true; }
  git push -q || true
}

git config user.name "job-radar"
git config user.email "job-radar@users.noreply.github.com"

if [ -n "$ARGS" ]; then                       # manual one-off run with arguments
  python radar.py $ARGS; rc=$?
  save
  exit $rc
fi

others() {
  gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$WF/runs?status=in_progress&per_page=20" \
    --jq "[.workflow_runs[] | select(.id != $GITHUB_RUN_ID)] | length" 2>/dev/null || echo 0
}
tries=1; [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ] && tries=6
for i in $(seq 1 $tries); do
  [ "$(others)" = "0" ] && break
  [ "$i" = "$tries" ] && { echo "another run is already looping; nothing to do"; exit 0; }
  sleep 30
done

sig() { git rev-parse HEAD:scripts/loop.sh HEAD:.github/workflows/$WF HEAD:requirements.txt 2>/dev/null | tr '\n' ' '; }
START_SIG="$(sig)"
END=$(( $(date +%s) + 5*3600 + 15*60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  git pull -q --rebase --autostash || true     # pick up config/code changes between scans
  if [ "$(sig)" != "$START_SIG" ]; then echo "loop definition changed; restarting"; break; fi
  python radar.py || echo "scan failed (continuing)"
  save
  hour=$(TZ=America/New_York date +%-H)
  step=900; { [ "$hour" -ge 23 ] || [ "$hour" -lt 7 ]; } && step=3600   # hourly overnight
  now=$(date +%s); wait=$(( step - now % step ))
  [ "$wait" -lt 120 ] && wait=$(( wait + step ))
  sleep "$wait"
done
gh workflow run "$WF" --ref main && echo "next run started"
