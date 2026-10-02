#!/usr/bin/env bash
# backfill_leaguepedia.sh -- ingest all league-season slices, politely.
#
# Usage (from repo root, Git Bash):  bash scripts/backfill_leaguepedia.sh
# Resumable: lp-ingest skips already-fetched (table, league, season) slices,
# so rerunning after a rate-limit stall or Ctrl+C is safe and cheap.
# Leaguepedia rate-limit cooldowns can outlast the connector's 90s backoff:
# this loop sleeps 120s between slices and keeps going on failure.
# Logs to data/logs/lp_backfill.log. Expect 1-2 sittings total.

set -u
cd "$(dirname "$0")/.."
RQ=".venv/Scripts/riftquant.exe"
LOG="data/logs/lp_backfill.log"
mkdir -p data/logs

# Scope: games from 2020 onward (user directive 2026-08-21, QUESTIONS.md Q2).
SLICES=(
  "lck 2025" "lec 2025" "lck 2024" "lec 2024" "lck 2023" "lec 2023"
  "lpl 2026" "lpl 2025" "lpl 2024" "lpl 2023"
  "lcs 2026" "lcs 2025" "lcs 2024" "lcs 2023"
  "worlds 2025" "worlds 2024" "worlds 2023"
  "msi 2026" "msi 2025" "msi 2024" "msi 2023"
  "first_stand 2026" "first_stand 2025"
  "lck 2022" "lec 2022" "lpl 2022" "lcs 2022" "worlds 2022" "msi 2022"
  "lck 2021" "lec 2021" "lpl 2021" "lcs 2021" "worlds 2021" "msi 2021"
  "lck 2020" "lec 2020" "lpl 2020" "lcs 2020" "worlds 2020" "msi 2020"
)

echo "=== lp backfill start $(date -u +%FT%TZ) ===" >> "$LOG"
for entry in "${SLICES[@]}"; do
  league="${entry% *}"; season="${entry#* }"
  echo "--- $(date -u +%FT%TZ) lp-ingest $league $season ---" >> "$LOG"
  "$RQ" lp-ingest --league "$league" --season "$season" >> "$LOG" 2>&1 \
    || echo "$(date -u +%FT%TZ) SLICE FAILED (rerun later): $league $season" >> "$LOG"
  sleep 120
done
echo "=== lp backfill pass complete $(date -u +%FT%TZ) ===" >> "$LOG"
echo "Done. Rerun this script once more to catch rate-limited slices, then:"
echo "  $RQ validate-m1"
