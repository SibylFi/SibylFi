#!/usr/bin/env bash
#
# SibylFi pre-submission compliance check.
# Mirrors .claude/skills/hackathon-compliance/SKILL.md.
#
# Usage: bash scripts/compliance-check.sh

set -euo pipefail

cd "$(dirname "$0")/.."

red()    { printf "\033[31m%s\033[0m\n" "$1"; }
green()  { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }

errors=0
warnings=0

err()  { red "  [FAIL] $1"; errors=$((errors + 1)); }
ok()   { green "  [OK] $1"; }
warn() { yellow "  [WARN] $1"; warnings=$((warnings + 1)); }

echo
echo "== Required files =="
[[ -f README.md ]]                    && ok "README.md"              || err "README.md missing"
[[ -f FEEDBACK.md ]]                  && ok "FEEDBACK.md"            || err "FEEDBACK.md missing (required for Uniswap)"
[[ -f ARCHITECTURE.md || -d specs ]]  && ok "Architecture or /specs" || err "Need ARCHITECTURE.md or /specs/"
[[ -d specs/prompts ]]                && ok "/specs/prompts/"        || err "/specs/prompts/ missing"
[[ -d .claude/skills ]]               && ok ".claude/skills/"        || err ".claude/skills/ missing"

echo
echo "== FEEDBACK.md content quality =="
if [[ -f FEEDBACK.md ]]; then
  lines=$(wc -l < FEEDBACK.md)
  if [[ $lines -lt 30 ]]; then
    err "FEEDBACK.md only $lines lines; too brief, looks generic"
  else
    ok "FEEDBACK.md has $lines lines"
  fi
  if grep -qiE "(redefining|next.generation|gateway|powering the future)" FEEDBACK.md; then
    warn "FEEDBACK.md contains cliche phrases"
  fi
fi

echo
echo "== /specs/prompts/ has content =="
if [[ -d specs/prompts ]]; then
  count=$(find specs/prompts -type f | wc -l)
  if [[ $count -eq 0 ]]; then
    warn "/specs/prompts/ is empty; AI involvement reviewers may flag this"
  else
    ok "/specs/prompts/ has $count file(s)"
  fi
fi

echo
echo "== No secrets in git =="
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  err ".env IS TRACKED IN GIT; remove with 'git rm --cached .env'"
else
  ok ".env not tracked"
fi

if git log --all -p 2>/dev/null | grep -qE "PRIVATE.KEY.*0x[0-9a-fA-F]{60,}"; then
  err "private key visible in git log history"
else
  ok "no private keys in git history"
fi

echo
echo "== Commit cadence (last 7 days) =="
if git rev-parse --git-dir >/dev/null 2>&1; then
  authors_recent=$(git log --since="7 days ago" --format="%an" | sort -u | wc -l)
  commits_recent=$(git log --since="7 days ago" --oneline | wc -l)
  if [[ $authors_recent -lt 3 ]]; then
    warn "only $authors_recent author(s) committed in last 7d (target: 5 across team)"
  else
    ok "$authors_recent authors committed in last 7d"
  fi
  if [[ $commits_recent -lt 30 ]]; then
    warn "only $commits_recent commit(s) in last 7d; looks thin"
  else
    ok "$commits_recent commits in last 7d"
  fi
fi

echo
echo "== Largest commit size =="
if git rev-parse --git-dir >/dev/null 2>&1; then
  largest=$(
    git log --since="14 days ago" --format="%H" | head -50 | while read -r sha; do
      lines=$(git show --stat "$sha" 2>/dev/null | tail -1 | grep -oE '[0-9]+ insertions' | grep -oE '[0-9]+' || echo 0)
      echo "$lines"
    done | sort -n | tail -1
  )
  if [[ -n "$largest" && "$largest" -gt 2000 ]]; then
    warn "largest recent commit: $largest insertions (>2000 looks AI-generated)"
  else
    ok "largest recent commit: ${largest:-0} insertions"
  fi
fi

echo
if [[ $errors -gt 0 ]]; then
  red "$errors error(s), $warnings warning(s)"
  exit 1
else
  green "All compliance checks passed. ($warnings warning(s))"
  exit 0
fi
