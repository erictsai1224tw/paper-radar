#!/bin/bash
# Container entrypoint — starts supercronic (rootless cron) in background
# then exec's the given CMD (default `sleep infinity`).
#
# Agents register cron entries by dropping files under agents/<name>/cron/.
# This script discovers all *.crontab files and launches one supercronic
# process per file so failures in one agent don't kill others.

set -e

shopt -s nullglob
for crontab_file in /app/agents/*/cron/*.crontab; do
    echo "[entrypoint] starting supercronic for ${crontab_file}"
    supercronic -passthrough-logs "${crontab_file}" &
done
shopt -u nullglob

exec "$@"
