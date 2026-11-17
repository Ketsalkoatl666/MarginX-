#!/usr/bin/env bash
# MarginX: safe, best-effort update check. Run only before GUI startup.
set -u
PROJECT="${HOME}/marginx"
LOG="${PROJECT}/update.log"
cd "$PROJECT" || exit 0
printf '\n=== MarginX update: %s ===\n' "$(date -Is)" >> "$LOG"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a Git checkout; skipping." >> "$LOG"
  exit 0
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Tracked local changes present; skipping." >> "$LOG"
  exit 0
fi
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=5'
if timeout 25 git pull --ff-only >> "$LOG" 2>&1; then
  echo "Update check successful." >> "$LOG"
else
  echo "No update applied (offline/authentication/error)." >> "$LOG"
fi
exit 0
