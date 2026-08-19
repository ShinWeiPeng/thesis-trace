#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -d frontend/src/generated ]]; then
  echo "frontend/src/generated is missing; generate the OpenAPI client first" >&2
  exit 1
fi

before_manifest="$(mktemp)"
after_manifest="$(mktemp)"
trap 'rm -f "$before_manifest" "$after_manifest"' EXIT
generated_roots=(frontend/src/generated)
if [[ -d backend/src/generated ]]; then
  generated_roots+=(backend/src/generated)
fi

find "${generated_roots[@]}" -type f -print0 \
  | sort -z \
  | xargs -0r sha256sum >"$before_manifest"

if npm --prefix frontend run | grep -Eq '^[[:space:]]+generate:client([[:space:]]|$)'; then
  npm --prefix frontend run generate:client
elif [[ -f scripts/generate-openapi-client.mjs ]]; then
  node scripts/generate-openapi-client.mjs
else
  echo "a deterministic generate:client command or scripts/generate-openapi-client.mjs is required" >&2
  exit 1
fi

generated_roots=(frontend/src/generated)
if [[ -d backend/src/generated ]]; then
  generated_roots+=(backend/src/generated)
fi
find "${generated_roots[@]}" -type f -print0 \
  | sort -z \
  | xargs -0r sha256sum >"$after_manifest"

if ! cmp --silent "$before_manifest" "$after_manifest"; then
  echo "generated API contracts are stale; run npm --prefix frontend run generate:client" >&2
  diff --unified "$before_manifest" "$after_manifest" >&2 || true
  exit 1
fi

echo "generated API contracts are current"
