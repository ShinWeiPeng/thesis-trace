#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

required_services=(api collector web postgres origin-gateway cloudflared)
for service in "${required_services[@]}"; do
  if ! grep -Eq "^  ${service}:$" compose.yaml; then
    echo "compose.yaml is missing service: ${service}" >&2
    exit 1
  fi
done

if grep -Eq '^[[:space:]]*ports:' compose.yaml; then
  echo "compose.yaml must not publish host ports during Wave 0" >&2
  exit 1
fi

if grep -Eq 'THESIS_TRACE_WAVE0_DEMO|wave0-owner' compose.yaml; then
  echo "compose.yaml must not enable a fixed development identity" >&2
  exit 1
fi

for service in api collector web postgres origin-gateway; do
  if ! sed -n "/^  ${service}:$/,/^  [[:alnum:]_-]\+:$/p" compose.yaml | grep -q 'healthcheck:'; then
    echo "compose.yaml service ${service} must declare a healthcheck" >&2
    exit 1
  fi
done

if grep -Eqi '(password|token|secret|api[_-]?key)[[:space:]]*:[[:space:]]*[^$<{[:space:]][^[:space:]]*' \
  compose.yaml infra/*.example; then
  echo "possible literal secret found in committed configuration" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose config --quiet
else
  echo "docker compose unavailable; skipped Compose parser validation"
fi

python3 scripts/validate_wave1_platform.py

echo "repository skeleton checks passed"
