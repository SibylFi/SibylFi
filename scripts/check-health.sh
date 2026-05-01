#!/usr/bin/env bash
#
# SibylFi pre-recording health check.
# Runs through the fragility checklist from the vps-deployment skill.
#
# Usage: bash scripts/check-health.sh

set -euo pipefail

cd "$(dirname "$0")/.."

red()    { printf "\033[31m%s\033[0m\n" "$1"; }
green()  { printf "\033[32m%s\033[0m\n" "$1"; }

fail=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    green "  [OK] $name"
  else
    red "  [FAIL] $name"
    fail=$((fail + 1))
  fi
}

dir_has_content() {
  local dir="$1"
  [[ -d "$dir" ]] && [[ -n "$(find "$dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]
}

env_not_tracked() {
  ! git ls-files --error-unmatch .env >/dev/null 2>&1
}

echo
echo "== Service health =="
check "orchestrator /api/health"      curl -fs http://localhost:7100/api/health
check "research-meanrev /"            curl -fs http://localhost:7101/
check "research-momentum /"           curl -fs http://localhost:7102/
check "research-news /"               curl -fs http://localhost:7103/
check "trading-agent /"               curl -fs http://localhost:7104/
check "risk-agent /"                  curl -fs http://localhost:7105/
check "validator-agent /status"       curl -fs http://localhost:7106/status
check "sidecar-0gstorage /health"     curl -fs http://localhost:7000/health

echo
echo "== Repo compliance =="
check "README.md present"             test -f README.md
check "FEEDBACK.md present"           test -f FEEDBACK.md
check "ARCHITECTURE.md present"       test -f ARCHITECTURE.md
check "/specs/ has content"           dir_has_content specs
check "/specs/prompts/ has content"   dir_has_content specs/prompts
check ".claude/skills/ has content"   dir_has_content .claude/skills
check ".env not in git"               env_not_tracked

echo
echo "== Pinned ABI integrity =="
check "erc8004-v1-abi.json valid JSON" python3 -c "import json; json.load(open('contracts/erc8004-v1-abi.json'))"
check "deployed-addresses.json valid"  python3 -c "import json; json.load(open('contracts/deployed-addresses.json'))"

echo
if [[ $fail -eq 0 ]]; then
  green "All checks passed."
  exit 0
else
  red "$fail check(s) failed."
  exit 1
fi
