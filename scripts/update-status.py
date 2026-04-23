#!/usr/bin/env python3
"""
Mission Control Status Updater
================================
Pulls REAL data from openclaw cron + session files to build status.json.

Usage:
  python3 scripts/update-status.py          # update data/status.json
  python3 scripts/update-status.py --push   # update + git commit + push
"""

import json
import os
import sys
import subprocess
import time
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent.parent
DATA_DIR        = BASE_DIR / "data"
OUTPUT_FILE     = DATA_DIR / "status.json"

SESSIONS_DIR    = Path.home() / ".openclaw/agents/main/sessions"
SESSIONS_JSON   = SESSIONS_DIR / "sessions.json"
HERMES_SESS_DIR = Path.home() / ".hermes/sessions"

# ─── Constants ────────────────────────────────────────────────────────
ACTIVE_THRESHOLD_MS  = 5  * 60 * 1000   # 5 min  → "active"
SUBAGENT_WINDOW_MS   = 30 * 60 * 1000   # 30 min → show subagent

# ─── Model costs ($/M tokens: input, output) ──────────────────────────
MODEL_COSTS = {
    "claude-opus-4-6":    (15.00, 75.00),
    "claude-sonnet-4-6":  ( 3.00, 15.00),
    "gpt-5.4-mini":       ( 0.40,  1.60),
    "gpt-5.4-nano":       ( 0.15,  0.60),
    "gpt-4.1-mini":       ( 0.40,  1.60),
    "gpt-4.1":            ( 2.00,  8.00),
    "gemini-2.5-flash":   ( 0.15,  0.60),
    "gemini-2.5-pro":     ( 1.25, 10.00),
    "kimi-k2":            ( 0.40,  2.00),
}

FREE_MARKERS = ("free", "gemma", "qwen", "llama", "mistral", "nvidia",
                "tencent", "openchat", "gemini-flash-free")


# ══════════════════════════════════════════════════════════════════════
# ─── Helpers ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def now_ms() -> int:
    return int(time.time() * 1000)

def ms_to_iso(ms) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

def is_free_model(model: str) -> bool:
    ml = model.lower()
    return any(m in ml for m in FREE_MARKERS)

def get_model_cost_estimate(model: str, duration_ms: Optional[int]) -> float:
    """Rough $/run estimate from model + last duration."""
    if is_free_model(model):
        return 0.0
    ml = model.lower()
    duration_s = (duration_ms or 10_000) / 1000
    est_tokens = min(150_000, max(500, duration_s * 150))
    for key, (in_c, out_c) in MODEL_COSTS.items():
        if key in ml:
            cost = (est_tokens * 0.35 * in_c + est_tokens * 0.65 * out_c) / 1_000_000
            return round(max(0.0005, cost), 5)
    return round(est_tokens * 2.5 / 1_000_000, 5)

def normalize_model(model_id: str) -> str:
    """Normalize model ID for grouping in charts."""
    ml = model_id.lower()
    if "claude-opus"   in ml: return "anthropic/claude-opus-4-6"
    if "claude-sonnet" in ml: return "anthropic/claude-sonnet-4-6"
    if "gpt-5.4-mini"  in ml: return "openai/gpt-5.4-mini"
    if "gpt-5.4-nano"  in ml: return "openai/gpt-5.4-nano"
    if "gpt-4.1-mini"  in ml: return "openai/gpt-4.1-mini"
    if "gpt-4.1"       in ml: return "openai/gpt-4.1"
    if "gemma"         in ml: return "google/gemma-4-31b:free"
    if "qwen"          in ml: return "qwen/qwen3-coder:free"
    if "kimi" in ml or "moonshot" in ml: return "moonshot/kimi-k2"
    if "gemini-2.5-pro"   in ml: return "google/gemini-2.5-pro"
    if "gemini-2.5-flash" in ml: return "google/gemini-2.5-flash"
    if "tencent" in ml: return "tencent/hy3:free"
    return model_id

def cron_schedule_to_human(schedule: dict) -> tuple:
    """Returns (human_label, raw_expr)."""
    kind = schedule.get("kind", "")
    if kind == "cron":
        expr = schedule.get("expr", "")
        labels = {
            "*/30 * * * *": "Every 30 min",
            "0 * * * *":    "Every hour",
            "0 0 * * *":    "Daily midnight",
            "0 5 * * *":    "Daily 5 AM ET",
            "0 6 * * *":    "Daily 6 AM",
            "0 8 * * *":    "Daily 8 AM ET",
            "0 10 * * 1":   "Mon 10 AM ET",
            "0 10 * * 3":   "Wed 10 AM ET",
            "0 11 * * 0":   "Sun 11 AM ET",
        }
        return labels.get(expr, f"cron: {expr}"), expr
    elif kind == "every":
        ms   = schedule.get("everyMs", 0)
        hrs  = ms / 3_600_000
        mins = ms / 60_000
        if hrs == int(hrs) and hrs >= 1:
            return f"Every {int(hrs)}h", f"every:{int(hrs)}h"
        return f"Every {int(mins)}m", f"every:{int(mins)}m"
    elif kind == "at":
        at = schedule.get("at", "")
        return f"Once: {at[:10]}", at
    return kind, kind

def recommend_model(job_name: str, model: str) -> tuple:
    """Returns (recommended_model, reason_string)."""
    ml = model.lower()
    nl = job_name.lower()

    if is_free_model(model):
        return model, "Free model — zero cost for this job ✅"

    if any(k in nl for k in ("creator", "morning", "mission task", "unicorn", "monitor", "ttd", "scout")):
        if "sonnet" in ml:
            return model, "Complex creative/analysis — Sonnet is already optimal ✅"
        if "opus" in ml:
            return "anthropic/claude-sonnet-4-6", "Opus overkill even for complex tasks — Sonnet is 5× cheaper"
        return "anthropic/claude-sonnet-4-6", "Complex reasoning tasks need Sonnet-level quality"

    if any(k in nl for k in ("refresh", "backup", "publisher", "scheduled post", "gmail", "token", "delete")):
        return "openrouter/google/gemma-4-31b-it:free", "Simple execution task — free model saves 100% of cost"

    if "opus" in ml:
        return "anthropic/claude-sonnet-4-6", "Opus is overkill in cron context — Sonnet saves 5×"
    if "sonnet" in ml:
        return "openai/gpt-5.4-mini", "Routine workload — GPT-5.4-mini costs 10× less with similar results"

    return model, "Current model appears appropriate for this workload"

def infer_project(name: str) -> str:
    n = name.lower()
    if "lobster press" in n or "publisher" in n or "creator" in n:
        return "lobster-press"
    if "world cup" in n:
        return "world-cup-pool"
    if "ttd" in n or "mission task" in n or "morning" in n:
        return "ttd"
    if "unicorn" in n:
        return "unicorn-factory"
    if "monitor" in n:
        return "monitoring"
    if "gmail" in n or "token" in n or "delete" in n:
        return "system"
    return "system"


# ══════════════════════════════════════════════════════════════════════
# ─── Session helpers ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def load_sessions() -> dict:
    try:
        with open(SESSIONS_JSON) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load sessions.json: {e}", file=sys.stderr)
        return {}

def get_session_file_mtime(session_id: str) -> Optional[int]:
    """Latest mtime of any JSONL belonging to this session."""
    best = None
    for pat in (f"{session_id}.jsonl", f"{session_id}-topic-*.jsonl"):
        for f in glob.glob(str(SESSIONS_DIR / pat)):
            try:
                mt = int(os.path.getmtime(f) * 1000)
                if best is None or mt > best:
                    best = mt
            except:
                pass
    return best

def get_session_ctime(session_id: str) -> Optional[int]:
    """Creation time (first timestamp in JSONL, or ctime)."""
    for pat in (f"{session_id}.jsonl", f"{session_id}-topic-*.jsonl"):
        for f in glob.glob(str(SESSIONS_DIR / pat)):
            try:
                with open(f, encoding="utf-8", errors="ignore") as fp:
                    first = fp.readline()
                if first:
                    rec = json.loads(first)
                    ts  = rec.get("timestamp")
                    if ts:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        return int(dt.timestamp() * 1000)
                return int(os.path.getctime(f) * 1000)
            except:
                pass
    return None

def has_lock_file(session_id: str) -> bool:
    for pat in (f"{session_id}.jsonl.lock", f"{session_id}-topic-*.jsonl.lock"):
        if glob.glob(str(SESSIONS_DIR / pat)):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════
# ─── Build: agents ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def build_agents(sessions: dict) -> list:
    now = now_ms()
    agents = []

    # ── Rob / Main ────────────────────────────────────────────────────
    main_keys = [k for k in sessions
                 if k.startswith("agent:main:")
                 and "subagent" not in k
                 and "cron"     not in k]

    main_updated = 0
    main_session = None
    for key in main_keys:
        s = sessions[key]
        u = s.get("updatedAt", 0)
        if u > main_updated:
            main_updated = u
            main_session = s

    # Also check JSONL mtime for accuracy
    if main_session:
        sid  = main_session.get("sessionId")
        fmts = get_session_file_mtime(sid) if sid else None
        if fmts and fmts > main_updated:
            main_updated = fmts

    main_active   = (now - main_updated) < ACTIVE_THRESHOLD_MS if main_updated else False
    main_elapsed  = int((now - main_updated) / 60_000) if main_updated else 0

    main_task = None
    if main_session:
        origin = main_session.get("origin", {})
        lbl    = main_session.get("label") or origin.get("label", "")
        if lbl and lbl not in ("openclaw-tui", f"Joseph Lynch id:8612618386"):
            main_task = lbl
        elif main_active:
            main_task = "Active conversation with Joe"

    # ── Sub-agents of Main ───────────────────────────────────────────
    subagent_keys = [k for k in sessions if "agent:main:subagent:" in k]
    subagents = []

    for key in subagent_keys:
        s       = sessions[key]
        updated = s.get("updatedAt", 0)
        if (now - updated) > SUBAGENT_WINDOW_MS:
            continue

        sa_uuid     = key.split("agent:main:subagent:")[-1]
        sa_id       = sa_uuid[:8]
        session_id  = s.get("sessionId", "")

        started_ms  = get_session_ctime(session_id)  if session_id else None
        last_mtime  = get_session_file_mtime(session_id) if session_id else None

        # Running = has lock file OR JSONL touched within 3 minutes
        is_running = False
        if session_id:
            if has_lock_file(session_id):
                is_running = True
            elif last_mtime and (now - last_mtime) < (3 * 60 * 1000):
                is_running = True

        if started_ms and last_mtime:
            duration_sec = max(0, int((last_mtime - started_ms) / 1000))
        else:
            duration_sec = max(0, int((now - updated) / 1000))

        raw_model = (s.get("model")
                     or s.get("modelOverride")
                     or s.get("modelId")
                     or "unknown")

        # Normalize "sonnet" → full model name
        if raw_model.lower() == "sonnet":
            raw_model = "anthropic/claude-sonnet-4-6"
        elif raw_model.lower() == "opus":
            raw_model = "anthropic/claude-opus-4-6"

        label = s.get("label") or "Subagent Task"

        subagents.append({
            "id":              sa_id,
            "task":            label,
            "model":           raw_model,
            "status":          "running" if is_running else "completed",
            "durationSeconds": duration_sec,
            "startedAt":       ms_to_iso(started_ms or updated),
            "completedAt":     ms_to_iso(last_mtime) if not is_running else None,
        })

    # Sort: running first, then most recent
    subagents.sort(key=lambda x: (
        0 if x["status"] == "running" else 1,
        -(datetime.fromisoformat(
            x["startedAt"].replace("Z", "+00:00")
          ).timestamp() if x["startedAt"] else 0)
    ))

    agents.append({
        "id":             "main",
        "name":           "Rob Lobster 🦞",
        "status":         "active" if main_active else "idle",
        "model":          "anthropic/claude-opus-4-6",
        "currentTask":    main_task if main_active else None,
        "elapsedMinutes": main_elapsed if main_active else 0,
        "subagents":      subagents,
    })

    # ── Hermes ────────────────────────────────────────────────────────
    hermes_updated = 0
    hermes_task    = None

    if HERMES_SESS_DIR.exists():
        files = list(HERMES_SESS_DIR.glob("*.jsonl"))
        if files:
            latest = max(files, key=lambda f: os.path.getmtime(f))
            hermes_updated = int(os.path.getmtime(latest) * 1000)
            stem   = latest.stem   # YYYYMMDD_HHMMSS_UUID
            parts  = stem.split("_")
            if len(parts) >= 2:
                date_str = parts[0]
                time_str = parts[1]
                hermes_task = (
                    f"Last session: {date_str[:4]}-{date_str[4:6]}-{date_str[6:]} "
                    f"{time_str[:2]}:{time_str[2:4]} UTC"
                )

    hermes_active = (now - hermes_updated) < ACTIVE_THRESHOLD_MS if hermes_updated else False
    hermes_elapsed = int((now - hermes_updated) / 60_000) if hermes_active and hermes_updated else 0

    agents.append({
        "id":             "hermes",
        "name":           "Hermes",
        "status":         "active" if hermes_active else "idle",
        "model":          "openai/gpt-5.4-mini",
        "currentTask":    hermes_task,
        "elapsedMinutes": hermes_elapsed,
        "subagents":      [],
    })

    # ── Red / Vault ───────────────────────────────────────────────────
    vault_dir     = Path.home() / ".openclaw/agents/vault/sessions"
    vault_updated = 0
    vault_task    = None

    if vault_dir.exists():
        vfiles = list(vault_dir.glob("*.jsonl"))
        if vfiles:
            latest = max(vfiles, key=lambda f: os.path.getmtime(f))
            vault_updated = int(os.path.getmtime(latest) * 1000)
            vault_task = "Email monitoring"

    vault_active = (now - vault_updated) < ACTIVE_THRESHOLD_MS if vault_updated else False

    agents.append({
        "id":             "vault",
        "name":           "Red 🔴",
        "status":         "active" if vault_active else "idle",
        "model":          "ollama/gemma4:e4b",
        "currentTask":    vault_task if vault_active else None,
        "elapsedMinutes": 0,
        "subagents":      [],
    })

    return agents


# ══════════════════════════════════════════════════════════════════════
# ─── Build: jobs ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def build_jobs(cron_data: dict) -> list:
    jobs = []
    for job in cron_data.get("jobs", []):
        state   = job.get("state", {})
        payload = job.get("payload", {})
        sched   = job.get("schedule", {})

        schedule_human, schedule_cron = cron_schedule_to_human(sched)

        last_run_ms  = state.get("lastRunAtMs")
        next_run_ms  = state.get("nextRunAtMs")
        last_status  = state.get("lastStatus") or state.get("lastRunStatus")
        consec_err   = state.get("consecutiveErrors", 0)
        duration_ms  = state.get("lastDurationMs")
        model        = payload.get("model", "unknown")

        rec_model, rec_reason = recommend_model(job["name"], model)
        est_cost = get_model_cost_estimate(model, duration_ms)

        # Delivery status
        delivered    = state.get("lastDelivered", False)
        delivery_raw = state.get("lastDeliveryStatus", "")
        if delivery_raw == "delivered" or delivered:
            delivery_status = "delivered"
        elif consec_err > 0:
            delivery_status = "failed"
        elif last_run_ms is None:
            delivery_status = "pending"
        else:
            delivery_status = "pending"

        last_error = None
        if consec_err >= 3:
            last_error = f"{consec_err} consecutive failures — needs investigation"

        jobs.append({
            "id":                job["id"][:8],
            "fullId":            job["id"],
            "name":              job["name"],
            "project":           infer_project(job["name"]),
            "enabled":           job.get("enabled", True),
            "schedule":          schedule_human,
            "scheduleCron":      schedule_cron,
            "lastRun":           ms_to_iso(last_run_ms),
            "lastStatus":        last_status or ("never" if last_run_ms is None else "ok"),
            "lastDurationMs":    duration_ms,
            "lastError":         last_error,
            "consecutiveErrors": consec_err,
            "nextRun":           ms_to_iso(next_run_ms),
            "model":             model,
            "recommendedModel":  rec_model,
            "recommendedReason": rec_reason,
            "estimatedCostPerRun": est_cost,
            "deliveryStatus":    delivery_status,
        })

    return jobs


# ══════════════════════════════════════════════════════════════════════
# ─── Build: model usage (from real session JSONL files) ───────────────
# ══════════════════════════════════════════════════════════════════════

def build_model_usage(sessions_dir: Path) -> dict:
    """Scan 7 days of session JSONL files for actual API cost records."""
    model_cost   = {}
    model_input  = {}
    model_output = {}

    cutoff_ms = now_ms() - (7 * 24 * 3600 * 1000)

    try:
        for fname in os.listdir(sessions_dir):
            if not fname.endswith(".jsonl") or "deleted" in fname:
                continue
            fpath = sessions_dir / fname
            try:
                fmtime = int(os.path.getmtime(fpath) * 1000)
                if fmtime < cutoff_ms:
                    continue

                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        try:
                            # Fast pre-check
                            if '"cost"' not in line and '"usage"' not in line:
                                continue
                            rec = json.loads(line)
                            if rec.get("type") != "message":
                                continue
                            msg = rec.get("message", {})
                            if msg.get("role") != "assistant":
                                continue
                            usage     = msg.get("usage", {})
                            cost_data = usage.get("cost", {})
                            total_c   = cost_data.get("total", 0) or 0
                            if total_c <= 0:
                                continue

                            raw_model = (msg.get("model")
                                         or msg.get("modelId")
                                         or "unknown")
                            norm = normalize_model(raw_model)

                            model_cost[norm]   = model_cost.get(norm, 0)   + total_c
                            model_input[norm]  = model_input.get(norm, 0)  + (usage.get("input", 0) or 0)
                            model_output[norm] = model_output.get(norm, 0) + (usage.get("output", 0) or 0)
                        except:
                            pass
            except:
                pass
    except Exception as e:
        print(f"⚠️  Session scan error: {e}", file=sys.stderr)

    last7days = {}
    for model in sorted(model_cost, key=lambda m: -model_cost[m]):
        last7days[model] = {
            "inputTokens":  model_input.get(model, 0),
            "outputTokens": model_output.get(model, 0),
            "cost":         round(model_cost[model], 4),
        }

    total_7d = sum(model_cost.values())

    # Savings: how much came from non-free models (projected monthly)
    paid_7d = sum(c for m, c in model_cost.items() if not is_free_model(m))
    savings_monthly = paid_7d * (30 / 7)

    return {
        "last7days":            last7days,
        "totalCost7days":       round(total_7d, 4),
        "projectedMonthlyCost": round(total_7d * 30 / 7, 2),
        "potentialSavings": {
            "ifFreeModelsUsed": round(savings_monthly, 2),
            "description":      "Potential monthly savings by routing eligible cron jobs to free models",
        },
    }


# ══════════════════════════════════════════════════════════════════════
# ─── Build: alerts ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def build_alerts(jobs: list) -> list:
    alerts = []
    for job in jobs:
        n = job.get("consecutiveErrors", 0)
        if n == 0:
            continue
        sev = "critical" if n >= 5 else "warning"
        alerts.append({
            "id":        f"err-{job['id']}-{n}",
            "severity":  sev,
            "job":       job["name"],
            "message":   f"{n} consecutive error{'s' if n != 1 else ''} — last run failed",
            "timestamp": job.get("lastRun") or datetime.now(timezone.utc).isoformat(),
        })
    return alerts


# ══════════════════════════════════════════════════════════════════════
# ─── Build: project health ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def build_project_health(jobs: list) -> dict:
    # Bucket jobs by project
    by_proj: dict[str, list] = {}
    for j in jobs:
        proj = j.get("project", "system")
        by_proj.setdefault(proj, []).append(j)

    def proj_status(proj_id: str) -> tuple:
        pj = by_proj.get(proj_id, [])
        if not pj:
            return "healthy", "No jobs configured"
        total   = len(pj)
        failing = sum(1 for j in pj if j.get("consecutiveErrors", 0) >= 1)
        ok      = total - failing
        metric  = f"{ok}/{total} jobs healthy"
        if failing == 0:
            return "healthy", metric
        if failing == total:
            return "failed", metric
        return "degraded", metric

    projects = {}

    s, m = proj_status("lobster-press")
    projects["lobster-press"] = {
        "label": "Lobster Press", "emoji": "🦞",
        "status": s, "metric": m,
        "detail": "Auto-creator + scheduled publisher",
    }

    s, m = proj_status("world-cup-pool")
    projects["world-cup-pool"] = {
        "label": "World Cup Pool", "emoji": "⚽",
        "status": s, "metric": m,
        "detail": "Nightly backup + standings",
    }

    s, m = proj_status("ttd")
    projects["ttd"] = {
        "label": "JFL TTD", "emoji": "✅",
        "status": s, "metric": m,
        "detail": "Daily 5 AM briefing + 6 AM morning rundown",
    }

    s, m = proj_status("unicorn-factory")
    projects["unicorn-factory"] = {
        "label": "Unicorn Factory", "emoji": "🦄",
        "status": "active" if s == "healthy" else s,
        "metric": m or "Weekly scout",
        "detail": "Sunday scouting for breakout opportunities",
    }

    s, m = proj_status("monitoring")
    projects["monitoring"] = {
        "label": "Intel Monitors", "emoji": "🔍",
        "status": s, "metric": m or "Weekly monitors",
        "detail": "Alex Finn + Moonshot People weekly pulse",
    }

    s, m = proj_status("system")
    projects["system"] = {
        "label": "System Ops", "emoji": "⚙️",
        "status": s, "metric": m,
        "detail": "Gmail token refresh + RobGmail inbox check",
    }

    return projects


# ══════════════════════════════════════════════════════════════════════
# ─── Git push ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def git_push():
    def run(cmd: list) -> bool:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠️  {' '.join(cmd)}: {r.stderr.strip()}", file=sys.stderr)
            return False
        return True

    ts = datetime.now().strftime("%H:%M:%S")
    ok = (
        run(["git", "add", "data/status.json"])
        and run(["git", "commit", "-m", f"chore: auto-update status.json [{ts}]"])
        and run(["git", "push"])
    )
    if ok:
        print("✅ Pushed to GitHub", file=sys.stderr)
    return ok


# ══════════════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────════════════════════════
# ══════════════════════════════════════════════════════════════════════

def main():
    do_push = "--push" in sys.argv

    print("🔄 Fetching cron jobs from openclaw...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        cron_data = json.loads(result.stdout)
    except Exception as e:
        print(f"⚠️  openclaw cron list failed: {e}", file=sys.stderr)
        cron_data = {"jobs": []}

    print("📂 Loading session registry...", file=sys.stderr)
    sessions = load_sessions()

    print("🏗️  Building status snapshot...", file=sys.stderr)
    jobs    = build_jobs(cron_data)
    agents  = build_agents(sessions)
    usage   = build_model_usage(SESSIONS_DIR)
    alerts  = build_alerts(jobs)
    health  = build_project_health(jobs)

    status = {
        "generatedAt":   datetime.now(timezone.utc).isoformat(),
        "jobs":          jobs,
        "agents":        agents,
        "modelUsage":    usage,
        "alerts":        alerts,
        "projectHealth": health,
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

    # Summary
    running_sa = sum(
        1 for a in agents
        for sa in a.get("subagents", [])
        if sa.get("status") == "running"
    )
    print(f"✅ Written: {OUTPUT_FILE}", file=sys.stderr)
    print(f"   Jobs: {len(jobs)} | Agents: {len(agents)} | "
          f"Sub-agents: {running_sa} running | Alerts: {len(alerts)}",
          file=sys.stderr)

    if do_push:
        git_push()


if __name__ == "__main__":
    main()
