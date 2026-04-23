#!/usr/bin/env bash
# ============================================================
# deploy.sh — Mission Control Dashboard → GitHub Pages
# Rob Lobster 🦞 | Joe Lynch Operations
#
# Usage:
#   ./deploy.sh [--repo owner/repo] [--branch gh-pages] [--init]
#
# Options:
#   --repo    GitHub repo (default: auto-detect from git remote)
#   --branch  Target branch (default: main — use gh-pages for separate branch)
#   --init    Force re-initialize git repo even if .git exists
#   --dry-run Show what would happen, don't actually push
#
# First-time setup:
#   1. Create a GitHub repo (e.g., joe-lynch/mission-control)
#   2. Run: ./deploy.sh --repo joe-lynch/mission-control --init
#   3. Enable GitHub Pages on the repo (Settings → Pages → Source: main branch / root)
#   4. Your dashboard will be live at: https://joe-lynch.github.io/mission-control/
#
# After first deploy, just run: ./deploy.sh
# To update data only:          ./scripts/update-status.sh --push
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$SCRIPT_DIR"

# ─── Defaults ──────────────────────────────────────────────
REPO=""
BRANCH="main"
FORCE_INIT=false
DRY_RUN=false
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ─── Parse args ────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)    REPO="$2"; shift 2 ;;
    --branch)  BRANCH="$2"; shift 2 ;;
    --init)    FORCE_INIT=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

log()    { echo "  [$(date '+%H:%M:%S')] $*"; }
ok()     { echo "  ✅ $*"; }
warn()   { echo "  ⚠️  $*"; }
err()    { echo "  ❌ $*" >&2; }
dryrun() { echo "  [DRY-RUN] $*"; }

echo ""
echo "🦞 Mission Control Dashboard Deploy"
echo "════════════════════════════════════"
echo ""

# ─── Sanity checks ─────────────────────────────────────────
if ! command -v git &>/dev/null; then
  err "git not found"
  exit 1
fi

if ! command -v gh &>/dev/null; then
  warn "gh CLI not found — you'll need to push manually or install: brew install gh"
fi

# ─── Auto-detect repo ──────────────────────────────────────
cd "$DASHBOARD_DIR"

if [[ -z "$REPO" && -d ".git" ]]; then
  REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
  if [[ "$REMOTE_URL" =~ github\.com[:/]([^/]+/[^/.]+)(\.git)?$ ]]; then
    REPO="${BASH_REMATCH[1]}"
    log "Auto-detected repo: $REPO"
  fi
fi

if [[ -z "$REPO" ]]; then
  warn "No repo specified. Run with --repo owner/reponame"
  warn "Example: ./deploy.sh --repo joe-lynch/mission-control --init"
  echo ""
  echo "  You can still open the dashboard locally:"
  echo "  cd $DASHBOARD_DIR && python3 -m http.server 8080"
  echo "  Then open: http://localhost:8080"
  echo ""
  exit 0
fi

REPO_URL="https://github.com/${REPO}.git"
PAGES_URL="https://$(echo "$REPO" | cut -d'/' -f1).github.io/$(echo "$REPO" | cut -d'/' -f2)/"

echo "  Repo:     $REPO"
echo "  URL:      $REPO_URL"
echo "  Branch:   $BRANCH"
echo "  Live at:  $PAGES_URL"
echo ""

# ─── Initialize git repo ───────────────────────────────────
if [[ "$FORCE_INIT" == true || ! -d ".git" ]]; then
  log "Initializing git repository..."

  if [[ "$DRY_RUN" == true ]]; then
    dryrun "git init && git remote add origin $REPO_URL"
  else
    if [[ -d ".git" ]]; then
      log "Removing existing .git and re-initializing..."
      rm -rf .git
    fi

    git init
    git remote add origin "$REPO_URL"
    ok "Git repository initialized"

    # Create .gitignore
    cat > .gitignore << 'EOF'
data/update.log
.DS_Store
*.swp
node_modules/
EOF
    ok "Created .gitignore"
  fi
else
  log "Git repo already initialized"
  CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "none")
  if [[ "$CURRENT_REMOTE" != "$REPO_URL" && "$CURRENT_REMOTE" != "${REPO_URL%.git}" ]]; then
    log "Updating remote URL..."
    if [[ "$DRY_RUN" == false ]]; then
      git remote set-url origin "$REPO_URL"
    fi
  fi
fi

# ─── Update data before deploy ─────────────────────────────
if [[ -x "$DASHBOARD_DIR/scripts/update-status.sh" ]]; then
  log "Running data update..."
  if [[ "$DRY_RUN" == false ]]; then
    bash "$DASHBOARD_DIR/scripts/update-status.sh" || warn "Data update had errors — using existing data"
  else
    dryrun "bash scripts/update-status.sh"
  fi
else
  warn "update-status.sh not found or not executable — deploying with existing data"
fi

# ─── Stage all files ───────────────────────────────────────
log "Staging files..."

if [[ "$DRY_RUN" == true ]]; then
  dryrun "git add -A"
  echo ""
  echo "  Files that would be deployed:"
  find . -not -path './.git/*' -not -name '.DS_Store' -type f | sort | sed 's/^/    /'
  echo ""
else
  git add -A
  ok "Files staged"
fi

# ─── Check if anything changed ─────────────────────────────
if [[ "$DRY_RUN" == false ]]; then
  if git diff --cached --quiet; then
    log "No changes to deploy — dashboard is up to date"
    echo ""
    echo "  🌐 Dashboard is live at: $PAGES_URL"
    echo ""
    exit 0
  fi
fi

# ─── Commit ────────────────────────────────────────────────
COMMIT_MSG="🦞 Mission Control deploy: $TIMESTAMP"

if [[ "$DRY_RUN" == true ]]; then
  dryrun "git commit -m \"$COMMIT_MSG\""
else
  # Check if this is the first commit
  if git rev-parse HEAD &>/dev/null 2>&1; then
    git commit -m "$COMMIT_MSG"
  else
    git commit -m "🦞 Mission Control: initial deploy"
  fi
  ok "Changes committed"
fi

# ─── Push ──────────────────────────────────────────────────
log "Pushing to GitHub ($BRANCH branch)..."

if [[ "$DRY_RUN" == true ]]; then
  dryrun "git push -u origin $BRANCH"
else
  if git push -u origin "$BRANCH" 2>&1; then
    ok "Pushed to GitHub"
  else
    warn "Push failed — trying force push (use caution)"
    echo ""
    echo "  If this is a new repo with no commits yet, try:"
    echo "  git push -u origin $BRANCH --force"
    echo ""
    read -p "  Force push? (y/N): " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
      git push -u origin "$BRANCH" --force
      ok "Force pushed to GitHub"
    else
      err "Push cancelled"
      exit 1
    fi
  fi
fi

# ─── Enable GitHub Pages (if gh CLI available) ─────────────
if command -v gh &>/dev/null && [[ "$DRY_RUN" == false ]]; then
  log "Enabling GitHub Pages via gh CLI..."
  if gh api "repos/${REPO}/pages" \
    --method POST \
    -f source='{"branch":"'"$BRANCH"'","path":"/"}' \
    --silent 2>/dev/null; then
    ok "GitHub Pages enabled"
  else
    # Pages may already be enabled
    log "Pages already enabled or needs manual activation"
  fi
fi

# ─── Done ──────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  🦞 Mission Control Dashboard Deployed!  ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  🌐 Live URL:    $PAGES_URL"
echo "  📁 Repo:        https://github.com/$REPO"
echo ""
echo "  ⏱  GitHub Pages may take 1-3 minutes to activate on first deploy."
echo ""
echo "  📊 To update data:  ./scripts/update-status.sh --push"
echo "  🔁 Add to cron:     */5 * * * * cd $DASHBOARD_DIR && ./scripts/update-status.sh --push"
echo ""
echo "  To open locally:"
echo "  cd $DASHBOARD_DIR && python3 -m http.server 8080"
echo "  http://localhost:8080"
echo ""
