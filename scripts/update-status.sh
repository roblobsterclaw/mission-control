#!/usr/bin/env bash
# ============================================================
# update-status.sh — Mission Control Dashboard Data Updater
# Rob Lobster 🦞 | Joe Lynch Operations
#
# Usage:
#   ./scripts/update-status.sh [--push]
#
# Options:
#   --push    Git commit + push to GitHub Pages after update
#
# Requirements:
#   - openclaw CLI in PATH
#   - jq installed (brew install jq)
#   - For --push: git repo configured with GitHub Pages remote
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
STATUS_FILE="$DASHBOARD_DIR/data/status.json"
PUSH_MODE=false
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
LOGFILE="$DASHBOARD_DIR/data/update.log"

# ─── Parse args ────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --push) PUSH_MODE=true ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOGFILE"; }

log "🦞 Mission Control status update starting..."

# ─── Check deps ────────────────────────────────────────────
if ! command -v openclaw &>/dev/null; then
  log "❌ openclaw not found in PATH"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  log "❌ jq not found — install with: brew install jq"
  exit 1
fi

mkdir -p "$DASHBOARD_DIR/data"

# ─── Fetch cron job list ───────────────────────────────────
log "📋 Fetching cron jobs from openclaw..."

# Try JSON output first, fall back to text parsing
CRON_RAW=""
CRON_JSON=""

if openclaw cron list --json &>/dev/null 2>&1; then
  CRON_RAW=$(openclaw cron list --json 2>/dev/null || echo "[]")
  CRON_JSON="$CRON_RAW"
  log "✅ Got JSON output from openclaw cron list"
else
  log "⚠️  No --json flag support — using text parsing mode"
  CRON_RAW=$(openclaw cron list 2>/dev/null || echo "")
  # Build minimal JSON from text output (best-effort)
  CRON_JSON="[]"
fi

# ─── Build jobs array ─────────────────────────────────────
# This merges live openclaw data with our known job metadata.
# If openclaw returns proper JSON, we use it directly and merge.
# Otherwise we use the static metadata from the existing status.json.

log "🔧 Building jobs array..."

# Load existing status for metadata fallback
EXISTING_STATUS="$STATUS_FILE"
if [[ ! -f "$EXISTING_STATUS" ]]; then
  EXISTING_STATUS="$SCRIPT_DIR/../data/status.json"
fi

if [[ -f "$EXISTING_STATUS" ]]; then
  EXISTING_JOBS=$(jq '.jobs' "$EXISTING_STATUS" 2>/dev/null || echo "[]")
  EXISTING_AGENTS=$(jq '.agents' "$EXISTING_STATUS" 2>/dev/null || echo "[]")
  EXISTING_MODEL_USAGE=$(jq '.modelUsage' "$EXISTING_STATUS" 2>/dev/null || echo "{}")
  EXISTING_ALERTS=$(jq '.alerts' "$EXISTING_STATUS" 2>/dev/null || echo "[]")
  EXISTING_PROJECTS=$(jq '.projectHealth' "$EXISTING_STATUS" 2>/dev/null || echo "{}")
else
  log "⚠️  No existing status.json found — using empty baseline"
  EXISTING_JOBS="[]"
  EXISTING_AGENTS="[]"
  EXISTING_MODEL_USAGE="{}"
  EXISTING_ALERTS="[]"
  EXISTING_PROJECTS="{}"
fi

# ─── Merge live data if available ─────────────────────────
JOBS_MERGED="$EXISTING_JOBS"

if [[ "$CRON_JSON" != "[]" && "$CRON_JSON" != "" ]]; then
  # openclaw returned live JSON — attempt to merge lastRun, lastStatus, consecutiveErrors
  # This assumes openclaw cron list --json returns an array with fields:
  # id, lastRun, lastStatus, consecutiveErrors, nextRun, model, enabled
  log "🔄 Merging live cron data..."

  JOBS_MERGED=$(jq -c --argjson live "$CRON_JSON" '
    map(. as $meta |
      ($live | map(select(.id == $meta.id)) | first) as $live_job |
      if $live_job then
        $meta * {
          lastRun:           ($live_job.lastRun // $meta.lastRun),
          lastStatus:        ($live_job.lastStatus // $meta.lastStatus),
          lastDurationMs:    ($live_job.lastDurationMs // $meta.lastDurationMs),
          lastError:         ($live_job.lastError // $meta.lastError),
          consecutiveErrors: ($live_job.consecutiveErrors // $meta.consecutiveErrors),
          nextRun:           ($live_job.nextRun // $meta.nextRun),
          model:             ($live_job.model // $meta.model),
          enabled:           ($live_job.enabled // $meta.enabled)
        }
      else $meta end
    )
  ' <<< "$EXISTING_JOBS")

  log "✅ Merge complete"
fi

# ─── Fetch agent status ────────────────────────────────────
log "🤖 Checking agent status..."

AGENTS_JSON="$EXISTING_AGENTS"

# Try to get live agent info (openclaw sessions or similar)
if openclaw sessions list --json &>/dev/null 2>&1; then
  SESSIONS_RAW=$(openclaw sessions list --json 2>/dev/null || echo "[]")
  if [[ "$SESSIONS_RAW" != "[]" && "$SESSIONS_RAW" != "" ]]; then
    log "✅ Got live session data"
    # Map sessions to our agent format
    AGENTS_JSON=$(jq -c '
      map({
        id:          (.id // "unknown"),
        name:        (.label // .id // "Agent"),
        status:      (if .status == "running" then "active" elif .status == "idle" then "idle" else .status end),
        currentTask: (.currentTask // null),
        model:       (.model // "unknown"),
        elapsedMinutes: (if .startedAt then
          ((now - (.startedAt | fromdateiso8601)) / 60 | floor)
        else null end)
      })
    ' <<< "$SESSIONS_RAW" 2>/dev/null || echo "$EXISTING_AGENTS")
  fi
fi

# ─── Build summary alerts ─────────────────────────────────
log "🚨 Checking for new alerts..."

# Find jobs with 3+ consecutive errors that aren't already in alerts
NEW_ALERTS=$(jq -c --arg ts "$TIMESTAMP" '
  . as $jobs |
  [
    $jobs[] |
    select(.consecutiveErrors >= 3) |
    {
      id:        ("auto-\(.id)"),
      timestamp: $ts,
      severity:  (if .consecutiveErrors >= 10 then "critical" else "warning" end),
      job:       .name,
      message:   "\(.consecutiveErrors) consecutive errors on \(.name). Last: \(.lastError // "unknown")"
    }
  ]
' <<< "$JOBS_MERGED" 2>/dev/null || echo "[]")

# Merge new alerts with existing (deduplicate by job+message)
ALERTS_MERGED=$(jq -c --argjson new "$NEW_ALERTS" '
  . + ($new | map(select(
    . as $na |
    [.[].job] | index($na.job) | not
  )))
  | sort_by(.timestamp) | reverse
  | .[0:20]
' <<< "$EXISTING_ALERTS" 2>/dev/null || echo "$EXISTING_ALERTS")

# ─── Compute model usage summary ──────────────────────────
# In production this would pull from openclaw token logs.
# For now, preserve existing data and update timestamp.
log "📊 Updating model usage stats..."

MODEL_USAGE_FINAL=$(jq -c --arg ts "$TIMESTAMP" '. + {updatedAt: $ts}' <<< "$EXISTING_MODEL_USAGE" 2>/dev/null || echo "$EXISTING_MODEL_USAGE")

# ─── Write status.json ────────────────────────────────────
log "💾 Writing $STATUS_FILE..."

jq -n \
  --arg ts "$TIMESTAMP" \
  --argjson jobs "$JOBS_MERGED" \
  --argjson agents "$AGENTS_JSON" \
  --argjson modelUsage "$MODEL_USAGE_FINAL" \
  --argjson alerts "$ALERTS_MERGED" \
  --argjson projectHealth "$EXISTING_PROJECTS" \
'{
  generatedAt:   $ts,
  jobs:          $jobs,
  agents:        $agents,
  modelUsage:    $modelUsage,
  alerts:        $alerts,
  projectHealth: $projectHealth
}' > "$STATUS_FILE"

log "✅ status.json written ($(wc -c < "$STATUS_FILE") bytes)"

# ─── Git push (optional) ──────────────────────────────────
if [[ "$PUSH_MODE" == true ]]; then
  log "📤 Pushing to GitHub Pages..."

  cd "$DASHBOARD_DIR"

  if [[ ! -d ".git" ]]; then
    log "❌ Not a git repo — run deploy.sh first to initialize"
    exit 1
  fi

  git add data/status.json
  git diff --cached --quiet && {
    log "ℹ️  No changes to commit"
    exit 0
  }

  git commit -m "📊 Status update: $TIMESTAMP"
  git push origin main

  log "✅ Pushed to GitHub Pages"
fi

log "🦞 Update complete! Dashboard data is fresh."
