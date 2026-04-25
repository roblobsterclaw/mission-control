#!/usr/bin/env python3
"""
refresh-mission-control.py
Rob Lobster — Mission Control Data Refresher

Scans the workspace for recent files and activity, then generates
mission-control-data.json for dashboard consumption.
Now includes BOTH Rob (OpenClaw) and Hermes agent data.

Usage:
    python3 refresh-mission-control.py
    python3 refresh-mission-control.py --output /path/to/mission-control-data.json

Cron (daily at 6am):
    0 6 * * * cd /Users/joemac/.openclaw/workspace && python3 refresh-mission-control.py
"""

import os
import json
import sys
import datetime
import subprocess
from pathlib import Path

WORKSPACE = Path("/Users/joemac/.openclaw/workspace")
HERMES_LOG_DIR = Path("/Users/joemac/.hermes/logs")
ROB_LOG_DIR = Path("/Users/joemac/.openclaw/logs")
SHARED_WORKSPACE = WORKSPACE / "workspace-shared"
OUTPUT_FILE = WORKSPACE / "mission-control-data.json"

# Override output path from CLI arg
if len(sys.argv) > 2 and sys.argv[1] == "--output":
    OUTPUT_FILE = Path(sys.argv[2])

SCAN_DIRS = [
    WORKSPACE / "reports",
    WORKSPACE / "projects",
]

EXCLUDE_DIRS = {
    "node_modules", ".next", "__pycache__", ".git", "out", ".DS_Store"
}

DOC_EXTENSIONS = {".docx", ".md", ".html", ".pdf", ".txt"}

CATEGORY_RULES = [
    ("investing", "Investing"),
    ("rebolt", "ReBolt"),
    ("world-cup-pool", "World Cup Pool"),
    ("lobster-press", "Lobster Press"),
    ("tlc", "TLC"),
    ("daily", "Reports"),
    ("hermes", "Reports"),
    ("social-media", "Other"),
    ("personal", "Other"),
    ("reports/", "Reports"),
]

def categorize(path_str: str) -> str:
    p = path_str.lower()
    for keyword, cat in CATEGORY_RULES:
        if keyword in p:
            return cat
    return "Other"

def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    else:
        return f"{n/1024/1024:.1f} MB"

def check_process_running(grep_pattern: str) -> bool:
    """Check if a process matching grep_pattern is running via pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", grep_pattern],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def read_log_tail(log_path: Path, lines: int = 50) -> list:
    """Read last N lines from a log file."""
    if not log_path.exists():
        return []
    try:
        content = log_path.read_text(errors="ignore").splitlines()
        return content[-lines:]
    except OSError:
        return []

def get_rob_health() -> dict:
    """Check Rob (OpenClaw) gateway status and recent errors."""
    gateway_online = check_process_running("openclaw-gateway")

    # Also try openclaw gateway status command
    if not gateway_online:
        try:
            result = subprocess.run(
                ["openclaw", "gateway", "status"],
                capture_output=True, text=True, timeout=5
            )
            if "running" in result.stdout.lower() or result.returncode == 0:
                gateway_online = True
        except Exception:
            pass

    errors = read_log_tail(ROB_LOG_DIR / "gateway.err.log", 20)
    # Filter to non-empty lines
    errors = [e.strip() for e in errors if e.strip()]

    return {
        "gateway_online": gateway_online,
        "errors": errors[-5:],  # Last 5 errors
        "log_file": str(ROB_LOG_DIR / "gateway.err.log"),
        "checked_at": datetime.datetime.now().isoformat(),
    }

def get_hermes_health() -> dict:
    """Check Hermes gateway status and recent errors."""
    gateway_online = check_process_running("hermes.*gateway")

    agent_log = read_log_tail(HERMES_LOG_DIR / "agent.log", 100)
    gateway_log = read_log_tail(HERMES_LOG_DIR / "gateway.log", 50)
    errors = read_log_tail(HERMES_LOG_DIR / "errors.log", 20)

    # Filter non-empty
    errors = [e.strip() for e in errors if e.strip()]

    # Get last activity timestamp from agent log
    last_activity = None
    for line in reversed(agent_log):
        if line.strip():
            last_activity = line.strip()[:100]
            break

    return {
        "gateway_online": gateway_online,
        "agent_log_tail": agent_log[-20:],
        "gateway_log_tail": gateway_log[-10:],
        "errors": errors[-5:],
        "last_activity": last_activity,
        "log_files": {
            "agent": str(HERMES_LOG_DIR / "agent.log"),
            "gateway": str(HERMES_LOG_DIR / "gateway.log"),
            "errors": str(HERMES_LOG_DIR / "errors.log"),
        },
        "checked_at": datetime.datetime.now().isoformat(),
    }

def parse_hermes_activity(agent_log_lines: list) -> list:
    """Parse Hermes agent.log lines into activity entries."""
    activities = []
    for line in agent_log_lines:
        if not line.strip():
            continue
        activities.append({
            "agent": "hermes",
            "time": line[:19] if len(line) >= 19 else "unknown",
            "type": "📡",
            "typeLabel": "Hermes",
            "desc": line.strip()[:200],
            "status": "success",
            "vertical": "Infrastructure",
        })
    return activities[-50:]

def get_shared_handoffs() -> list:
    """Read handoffs from shared workspace."""
    handoffs_dir = SHARED_WORKSPACE / "handoffs"
    handoffs = []
    if not handoffs_dir.exists():
        return handoffs
    for f in sorted(handoffs_dir.glob("*.md"), reverse=True)[:10]:
        try:
            stat = f.stat()
            content = f.read_text(errors="ignore")
            handoffs.append({
                "file": f.name,
                "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "preview": content[:200],
                "size": fmt_size(stat.st_size),
            })
        except OSError:
            continue
    return handoffs

def get_taskboard() -> dict:
    """Read taskboard.json from shared workspace."""
    taskboard_file = SHARED_WORKSPACE / "taskboard.json"
    if taskboard_file.exists():
        try:
            return json.loads(taskboard_file.read_text())
        except Exception:
            pass
    return None

def scan_documents():
    docs = []
    for base_dir in SCAN_DIRS:
        if not base_dir.exists():
            continue
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() not in DOC_EXTENSIONS:
                    continue
                try:
                    stat = fpath.stat()
                    rel_path = str(fpath.relative_to(WORKSPACE))
                    category = categorize(rel_path)
                    docs.append({
                        "name": fname,
                        "path": str(fpath.relative_to(WORKSPACE).parent) + "/",
                        "full_path": str(fpath),
                        "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                        "size": fmt_size(stat.st_size),
                        "size_bytes": stat.st_size,
                        "cat": category,
                        "ext": fpath.suffix.lstrip(".").lower(),
                    })
                except (PermissionError, OSError):
                    continue
    docs.sort(key=lambda d: d["size_bytes"], reverse=False)
    docs.sort(key=lambda d: d["date"], reverse=True)
    return docs

def scan_memory_files():
    memory_dir = WORKSPACE / "memory"
    if not memory_dir.exists():
        return []
    files = []
    for f in sorted(memory_dir.glob("*.md"), reverse=True):
        try:
            stat = f.stat()
            files.append({
                "name": f.name,
                "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                "size": fmt_size(stat.st_size),
            })
        except OSError:
            continue
    return files[:30]

def get_agent_status(rob_health: dict, hermes_health: dict) -> list:
    """Build agent status using real process check results."""
    agents = []

    rob_status = "online" if rob_health["gateway_online"] else "offline"
    agents.append({
        "name": "Rob Lobster 🦞",
        "harness": "OpenClaw",
        "model": "claude-opus-4-6",
        "telegram": "@RobLobster_bot",
        "role": "Main / Chief of Staff",
        "status": rob_status,
        "gateway": "active" if rob_health["gateway_online"] else "down",
        "cronJobs": 12,
        "memoryMB": 148,
        "last_checked": datetime.datetime.now().isoformat(),
    })

    hermes_status = "online" if hermes_health["gateway_online"] else "offline"
    agents.append({
        "name": "Hermes 🏛️",
        "harness": "Hermes Agent (Nous Research)",
        "model": "gpt-4o-mini",
        "telegram": "@HermesJFL_bot",
        "role": "Assistant / Monitor / Backup",
        "status": hermes_status,
        "gateway": "active" if hermes_health["gateway_online"] else "down",
        "cronJobs": 4,
        "memoryMB": 62,
        "last_checked": datetime.datetime.now().isoformat(),
    })

    agents.append({
        "name": "Red 🔴",
        "harness": "OpenClaw (Vault)",
        "model": "claude-sonnet-4",
        "telegram": "N/A",
        "role": "Vault Agent (Joe's email — exclusive)",
        "status": "paused",
        "gateway": "inactive",
        "cronJobs": 0,
        "memoryMB": 0,
        "last_checked": datetime.datetime.now().isoformat(),
    })

    return agents

def get_recent_activity():
    """Pull recent activity from memory files."""
    activity = []
    memory_dir = WORKSPACE / "memory"
    if not memory_dir.exists():
        return activity

    today = datetime.date.today()
    for days_back in range(3):
        date = today - datetime.timedelta(days=days_back)
        daily_file = memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
        if daily_file.exists():
            try:
                content = daily_file.read_text(errors="ignore")
                activity.append({
                    "date": str(date),
                    "file": daily_file.name,
                    "preview": content[:500].replace("\n", " ").strip(),
                    "size": fmt_size(daily_file.stat().st_size),
                    "agent": "rob",
                })
            except OSError:
                continue
    return activity

def get_project_file_counts():
    lanes = {
        "TLC": 0, "Surfbox": 0, "Investing": 0, "ReBolt": 0,
        "Real Estate": 0, "Colorant": 0, "Personal": 0, "Infrastructure": 0
    }
    docs = scan_documents()
    cat_map = {
        "TLC": "TLC", "Investing": "Investing", "ReBolt": "ReBolt",
        "World Cup Pool": "Infrastructure", "Lobster Press": "Infrastructure",
        "Reports": "Infrastructure", "Other": "Infrastructure"
    }
    for d in docs:
        mapped = cat_map.get(d["cat"], "Infrastructure")
        if mapped in lanes:
            lanes[mapped] += 1
    return lanes

def main():
    print(f"🦞 Rob Lobster — Mission Control Refresh (v3.0 — Dual Agent)")
    print(f"   Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Workspace: {WORKSPACE}")
    print()

    print("🏥 Checking Rob (OpenClaw) health...")
    rob_health = get_rob_health()
    print(f"   Rob gateway: {'✅ Online' if rob_health['gateway_online'] else '❌ Offline'}")
    print(f"   Recent errors: {len(rob_health['errors'])}")

    print("🏛️  Checking Hermes health...")
    hermes_health = get_hermes_health()
    print(f"   Hermes gateway: {'✅ Online' if hermes_health['gateway_online'] else '❌ Offline'}")
    print(f"   Agent log lines: {len(hermes_health['agent_log_tail'])}")
    print(f"   Recent errors: {len(hermes_health['errors'])}")

    print("📄 Scanning documents...")
    docs = scan_documents()
    print(f"   Found {len(docs)} documents")

    print("🧠 Scanning memory files...")
    memory = scan_memory_files()
    print(f"   Found {len(memory)} daily logs")

    print("👥 Building agent status...")
    agents = get_agent_status(rob_health, hermes_health)
    for a in agents:
        print(f"   {a['name']}: {a['status']}")

    print("📡 Scanning recent activity...")
    activity = get_recent_activity()
    print(f"   Found {len(activity)} recent daily logs")

    print("📋 Reading shared task board...")
    taskboard = get_taskboard()
    if taskboard:
        total_tasks = sum(len(v) for v in taskboard.values() if isinstance(v, list))
        print(f"   Found {total_tasks} tasks in taskboard.json")
    else:
        print("   No taskboard.json found")

    print("📨 Checking shared handoffs...")
    handoffs = get_shared_handoffs()
    print(f"   Found {len(handoffs)} handoff files")

    print("📊 Counting project files...")
    project_counts = get_project_file_counts()

    print("📡 Parsing Hermes activity...")
    hermes_activities = parse_hermes_activity(hermes_health.get("agent_log_tail", []))
    print(f"   Parsed {len(hermes_activities)} Hermes activity entries")

    # Build output data
    data = {
        "meta": {
            "generated_at": datetime.datetime.now().isoformat(),
            "generated_by": "refresh-mission-control.py v3.0",
            "workspace": str(WORKSPACE),
            "version": "3.0",
        },
        "agents": agents,
        "rob_health": rob_health,
        "hermes_health": hermes_health,
        "taskboard": taskboard,
        "handoffs": handoffs,
        "hermes_activities": hermes_activities,
        "documents": {
            "total": len(docs),
            "by_category": {},
            "recent": docs[:50],
            "all": docs,
        },
        "memory": {
            "daily_logs": memory,
            "total_logs": len(memory),
        },
        "recent_activity": activity,
        "project_file_counts": project_counts,
        "stats": {
            "total_docs": len(docs),
            "total_memory_files": len(memory),
            "agents_online": sum(1 for a in agents if a["status"] == "online"),
            "rob_online": rob_health["gateway_online"],
            "hermes_online": hermes_health["gateway_online"],
        }
    }

    # Count by category
    for d in docs:
        cat = d["cat"]
        data["documents"]["by_category"][cat] = data["documents"]["by_category"].get(cat, 0) + 1

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print()
    print(f"✅ Done! Output written to: {OUTPUT_FILE}")
    print(f"   Total documents: {len(docs)}")
    print(f"   Categories: {dict(data['documents']['by_category'])}")
    print(f"   Rob gateway: {'Online' if rob_health['gateway_online'] else 'Offline'}")
    print(f"   Hermes gateway: {'Online' if hermes_health['gateway_online'] else 'Offline'}")
    print()
    print("💡 To deploy dashboard:")
    print("   bash deploy.sh")

if __name__ == "__main__":
    main()
