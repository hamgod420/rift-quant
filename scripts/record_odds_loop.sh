#!/usr/bin/env bash
# record_odds_loop.sh -- keep the Polymarket odds recorder running forever.
#
# Usage (from repo root, Git Bash):  bash scripts/record_odds_loop.sh
# Ctrl+C to stop. Restarts the recorder if it exits (network blip, crash),
# re-running discovery each cycle so newly listed matches get picked up.
# Data lands in data/raw/odds/polymarket/<date>.jsonl.gz (append-only).
#
# Every week of prices is unbackfillable history -- ideally this runs 24/7
# on an always-on box. See docs/QUESTIONS.md Q17/Q27.

set -u
cd "$(dirname "$0")/.."
RQ=".venv/Scripts/riftquant.exe"
LOG="data/logs/record_odds_loop.log"
mkdir -p data/logs

echo "=== odds loop start $(date -u +%FT%TZ) ===" >> "$LOG"
while true; do
  "$RQ" record-odds --interval 30 --duration 3600 >> "$LOG" 2>&1
  echo "$(date -u +%FT%TZ) recorder cycle ended (exit $?); restarting in 10s" >> "$LOG"
  sleep 10
done
