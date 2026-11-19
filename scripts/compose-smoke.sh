#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Use a dedicated project and an ephemeral host port to coexist with a dev stack.
export API_PORT=0
project="api-sentinel-smoke-$$"
compose=(docker compose --project-name "$project")
command -v docker >/dev/null || { echo "Docker with Compose v2 is required" >&2; exit 127; }
trap '"${compose[@]}" down' EXIT
"${compose[@]}" config --quiet
"${compose[@]}" up --build --wait --wait-timeout 90
published=$("${compose[@]}" port api 8000)
[[ "$published" == 127.0.0.1:* ]]
curl --noproxy '*' --fail --silent --show-error --max-time 5 "http://$published/health/live" |
  python3 -c 'import json, sys; sys.exit(json.load(sys.stdin) != {"status": "ok"})'
