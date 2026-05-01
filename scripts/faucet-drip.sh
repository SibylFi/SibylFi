#!/usr/bin/env bash
#
# Daily faucet drip checklist for SibylFi public wallet addresses on 0G Galileo.
# Call this from cron at 09:00 UTC daily.
#
# This script reads only public *_ADDR values. Private keys stay in .env and are
# never derived from, printed, or passed to wallet tooling here.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo ".env not found"
  exit 1
fi

env_value() {
  local name="$1"
  local value="${!name:-}"
  local line=""

  if [[ -z "$value" ]]; then
    line=$(grep -E "^${name}=" .env | tail -n 1 || true)
    value="${line#*=}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi

  printf "%s" "$value"
}

addresses=()
for var in RESEARCH_MEANREV_ADDR RESEARCH_MOMENTUM_ADDR RESEARCH_NEWS_ADDR \
           TRADING_ADDR RISK_ADDR VALIDATOR_ADDR OG_BROKER_ADDR; do
  addr="$(env_value "$var")"
  if [[ -z "$addr" || "$addr" == 0x000* ]]; then
    echo "skip $var (placeholder)"
    continue
  fi

  addresses+=("$addr")
  echo "$var -> $addr"
done

echo
if [[ ${#addresses[@]} -eq 0 ]]; then
  echo "No public wallet addresses found. Add *_ADDR values to .env."
  exit 1
fi

echo "Visit https://faucet.0g.ai for each address above (0.1 OG / 24h limit)."
echo "Sepolia and Base Sepolia faucets are IP-limited; rotate manually by teammate."
