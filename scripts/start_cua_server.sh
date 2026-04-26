#!/usr/bin/env bash

# Helper script to run the CUA computer server with MCP enabled.
# CUA should be treated as the GUI/computer-use backend. Do not use
# it for shell/code execution unless you run it in a deliberately
# isolated desktop environment.

set -euo pipefail

CUA_HOST="${CUA_HOST:-127.0.0.1}"
CUA_PORT="${CUA_PORT:-8000}"
CUA_WIDTH="${CUA_WIDTH:-1280}"
CUA_HEIGHT="${CUA_HEIGHT:-720}"

command -v cua-computer-server >/dev/null || {
  echo "cua-computer-server not found. Install/start CUA first." >&2
  exit 1
}

CUA_HELP="$(cua-computer-server --help 2>&1 || true)"
if [ -n "$CUA_HELP" ]; then
  for flag in --host --port --width --height --mcp; do
    if ! printf '%s\n' "$CUA_HELP" | grep -q -- "$flag"; then
      echo "Warning: cua-computer-server help did not advertise $flag; validate this vendored CUA version before live use." >&2
    fi
  done
fi

echo "Starting CUA computer server on $CUA_HOST:$CUA_PORT (${CUA_WIDTH}x${CUA_HEIGHT})"
echo "Expected CUA MCP URL: http://$CUA_HOST:$CUA_PORT/mcp"

exec cua-computer-server \
  --host "$CUA_HOST" \
  --port "$CUA_PORT" \
  --width "$CUA_WIDTH" \
  --height "$CUA_HEIGHT" \
  --mcp
