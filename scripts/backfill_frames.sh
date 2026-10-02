#!/usr/bin/env bash
# backfill_frames.sh -- long-running frame-archive backfill, priority order.
#
# Usage (from repo root, Git Bash):
#   bash scripts/backfill_frames.sh            # run until done or Ctrl+C
#   BATCH=10 bash scripts/backfill_frames.sh   # bigger per-league batches
#
# Safe to stop and restart anytime: the archiver is idempotent (.done markers)
# and --limit counts only NEWLY archived games. Logs to data/logs/backfill.log.
# Priority: modeling-core leagues and recent seasons first (see docs/ROADMAP).
#
# Rough math (2026-08-21): ~4500 indexed games, ~2-4 min/game polite
# => ~1-2 weeks total runtime. Leave it running in a spare terminal, or wire
# it into Task Scheduler. Progress: ls data/raw/livestats/window | wc -l

set -u
cd "$(dirname "$0")/.."
RQ=".venv/Scripts/riftquant.exe"
BATCH="${BATCH:-5}"
LOG="data/logs/backfill.log"
mkdir -p data/logs

# (league, since) in priority order. LPL omitted: persisted index has ~15
# games total (see QUESTIONS.md Q26 correction) -- nothing to backfill.
PRIORITIES=(
  "lck 2025"
  "lec 2025"
  "worlds 2023"
  "msi 2023"
  "first_stand 2025"
  "lta_cross 2025"
  "lck 2023"
  "lec 2024"
  "lta_n 2025"
  "lcs 2024"
  "lpl 2025"
)

echo "=== backfill start $(date -u +%FT%TZ) batch=$BATCH ===" >> "$LOG"
while true; do
  progressed=0
  for entry in "${PRIORITIES[@]}"; do
    league="${entry% *}"; since="${entry#* }"
    out="$("$RQ" archive-frames --league "$league" --since "$since" --limit "$BATCH" 2>&1)"
    echo "$(date -u +%FT%TZ) [$league>=$since] $out" >> "$LOG"
    # crude progress detection: archiver prints 'archived' for new games
    if echo "$out" | grep -qi "archived"; then
      progressed=1
    fi
  done
  if [ "$progressed" -eq 0 ]; then
    echo "=== backfill COMPLETE $(date -u +%FT%TZ) ===" >> "$LOG"
    echo "Backfill complete."
    break
  fi
done
