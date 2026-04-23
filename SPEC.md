# Mission Control Dashboard — Spec
*Cron Health + Agent Activity + Model Efficiency Monitor*

## Overview
Single-page GitHub Pages dashboard that gives Joe real-time visibility into every automated job, active agent, model usage, and system health across all OpenClaw projects.

## Deployment
- GitHub Pages: `roblobsterclaw.github.io/mission-control/`
- Auto-refresh: poll status JSON every 60 seconds
- Mobile-first responsive design (Joe checks from phone)

## Data Source
A JSON file (`data/status.json`) updated by a cron job every 5 minutes that runs `openclaw cron list` and formats the output. The dashboard reads this JSON.

Alternatively, the dashboard can call the OpenClaw API directly if we expose it — but for V1, a static JSON updated by cron is simpler and more reliable.

For V1: the dashboard will include a "Refresh" button that triggers a manual data pull, plus auto-refresh every 60 seconds from the JSON.

## Layout — 5 Panels

### Panel 1: Agent Activity Monitor (Top — Full Width)
Visual bar showing all agents and their current state:
- 🟢 **Active** — running a job right now (pulse animation)
- 🟡 **Queued** — job scheduled within next 30 min
- 🟡 **Running** — sub-agent executing
- 🔴 **Failed** — last run errored
- ⚪ **Idle** — nothing scheduled soon

Each agent card shows:
- Agent name (Rob, Red/Hermes, Sub-agent ID)
- Current task name
- Model being used
- Elapsed time (if running)
- Animated progress indicator when active

### Panel 2: Cron Job Health Grid (Main — Left 60%)
Table/card grid of ALL cron jobs with:
- Job name + emoji
- Schedule (cron expression in human-readable)
- Last run: time + status (✅/❌)
- Next run: countdown timer
- Consecutive errors (red badge if > 0)
- **Model dropdown** — current model with ability to change
- **Rob's recommendation** — suggested model + why
- Cost estimate per run
- Click to expand: full error message, run history

Color coding:
- Green border: healthy (0 errors, ran on schedule)
- Yellow border: warning (1-2 errors or overdue)
- Red border: critical (3+ errors or delivery failures)

Sort options: by status (errors first), by next run, by project, by cost

### Panel 3: Model Efficiency Panel (Main — Right 40%)
- Pie chart: token spend by model (last 7 days)
- Bar chart: cost per cron job (identify expensive ones)
- **Model tier legend:**
  - 🔴 Opus — Chief of Staff only
  - 🟠 Sonnet — Complex reasoning
  - 🟡 GPT-5.4-mini — Reports & monitoring
  - 🟢 Kimi/Cheap — Grunt work
  - ⚪ Free (OpenRouter) — Background tasks
- Savings calculator: "If you moved X jobs to free models, you'd save $Y/month"
- **Model selector per job** — dropdown that shows:
  - Current model
  - Available models with cost comparison
  - Rob's pick (highlighted)
  - Joe clicks to change, dashboard writes the update

### Panel 4: Alert Feed (Bottom — Left)
Reverse-chronological feed of:
- Failed runs (with error details)
- Delivery failures
- Jobs that haven't run when expected
- System events (gateway restarts, etc.)

Each alert has:
- Timestamp
- Severity (🔴 Critical / 🟡 Warning / 🔵 Info)
- Job name
- Error message
- "Dismiss" button

### Panel 5: Project Health Summary (Bottom — Right)
Roll-up by project showing:
- Unicorn Factory: last scout, # pipeline ideas, next run
- Lobster Press: posts created/published this week, pending review
- World Cup Pool: last backup, player count
- Morning Reports: streak (consecutive successful deliveries)
- TTD: current version, last print time
- Gmail: last successful check, # emails processed

## Design
- Dark theme matching Unicorn Factory dashboard
- CSS custom properties for theming
- Font: system-ui stack
- Accent: #FF6B35 (Rob Lobster orange)
- Cards with subtle borders and shadows
- Responsive: works on iPhone, iPad, Mac
- No external dependencies — pure HTML/CSS/JS

## Data Schema (status.json)

```json
{
  "generatedAt": "ISO timestamp",
  "jobs": [
    {
      "id": "cron-id",
      "name": "Job Name",
      "project": "unicorn-factory|lobster-press|world-cup-pool|reports|system",
      "enabled": true,
      "schedule": "human readable",
      "scheduleCron": "0 11 * * 0",
      "lastRun": "ISO timestamp",
      "lastStatus": "ok|error",
      "lastDurationMs": 1234,
      "lastError": "error message or null",
      "consecutiveErrors": 0,
      "nextRun": "ISO timestamp",
      "model": "anthropic/claude-sonnet-4-6",
      "recommendedModel": "openai/gpt-5.4-mini",
      "recommendedReason": "Simple script execution — doesn't need reasoning",
      "estimatedCostPerRun": 0.05,
      "deliveryStatus": "delivered|failed|unknown"
    }
  ],
  "agents": [
    {
      "id": "main",
      "name": "Rob Lobster",
      "status": "active|idle",
      "currentTask": "Talking with Joe",
      "model": "anthropic/claude-opus-4-6",
      "sessionKey": "agent:main:..."
    }
  ],
  "modelUsage": {
    "last7days": {
      "anthropic/claude-opus-4-6": { "tokens": 0, "cost": 0 },
      "anthropic/claude-sonnet-4-6": { "tokens": 0, "cost": 0 }
    }
  },
  "alerts": [
    {
      "timestamp": "ISO",
      "severity": "critical|warning|info",
      "job": "job-name",
      "message": "Error details"
    }
  ]
}
```

## Update Script (update-status.py)
Python script that:
1. Runs `openclaw cron list` or reads cron state
2. Formats into status.json
3. Commits and pushes to GitHub Pages repo
4. Runs every 5 minutes via cron job

## Model Selector Feature
When Joe changes a model via the dropdown:
1. Dashboard stores the preference in localStorage immediately (instant UI update)
2. Queues a "model change request" that gets picked up by the next status update
3. The update script reads pending changes and applies them via `openclaw cron update`
4. Confirmation appears in the alert feed

For V1: model changes are manual (Joe tells Rob, Rob updates the cron). Dashboard shows recommendations only.
For V2: live model switching via API.

## Files to Create
- `index.html` — single-page dashboard
- `data/status.json` — auto-updated status data
- `scripts/update-status.py` — cron-driven updater
- `deploy.sh` — GitHub Pages deployment
- `README.md` — project documentation
