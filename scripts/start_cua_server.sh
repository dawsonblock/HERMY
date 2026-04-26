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

echo "Starting CUA computer server on $CUA_HOST:$CUA_PORT (${CUA_WIDTH}x${CUA_HEIGHT})"

exec cua-computer-server \
  --host "$CUA_HOST" \
  --port "$CUA_PORT" \
  --width "$CUA_WIDTH" \
  --height "$CUA_HEIGHT" \
  --mcp
