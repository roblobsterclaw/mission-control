# 🦞 Rob Lobster — Mission Control

Joe Lynch's autonomous intelligence command center.

**Live:** https://roblobsterclaw.github.io/mission-control

## Screens

- 📡 **Activity Feed** — Real-time log of all agent actions + Agent Health panel
- 📅 **Calendar** — Cron jobs, reminders, and upcoming key dates
- 🎯 **Projects** — 8 business lanes with progress, recent activity, and next actions
- 📄 **Documents** — All reports and docs created by Rob (64+ files, searchable)
- 🔍 **Global Search** — Search across all memories, tasks, documents
- 📋 **Task Board** — Kanban across all verticals
- 🧠 **Memory** — Long-term memory + daily logs
- 👥 **Team** — Agent org chart (Rob 🦞, Hermes 🏛️, Red 🔴)

## Agents

| Agent | Model | Status |
|-------|-------|--------|
| Rob Lobster 🦞 | claude-opus-4-6 | ● Active |
| Hermes 🏛️ | gpt-5.4-mini | ● Active |
| Red 🔴 | claude-sonnet-4 | ◌ Paused |

## Data Refresh

```bash
cd /Users/joemac/.openclaw/workspace
python3 refresh-mission-control.py
bash deploy.sh
```

---
*Built by Rob Lobster 🦞 for Joe Lynch | Tuckerton Group*
