#!/usr/bin/env bash
# check-proto-drift.sh — verify the network-agent proto canonical source and the
# Cubelet client sync copy are byte-identical.
#
# Usage:
#   ./scripts/check-proto-drift.sh [REPO_ROOT]
#
# Exit codes:
#   0  files are identical
#   1  drift detected
#   2  one or both files are missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

SRC="${REPO_ROOT}/CubeSandbox-master/network-agent/api/v1/network_agent.proto"
DST="${REPO_ROOT}/CubeSandbox-master/Cubelet/pkg/networkagentclient/pb/network_agent.proto"

if [[ ! -f "${SRC}" ]]; then
  echo "FAIL: canonical proto missing: ${SRC}" >&2
  exit 2
fi
if [[ ! -f "${DST}" ]]; then
  echo "FAIL: Cubelet sync proto missing: ${DST}" >&2
  exit 2
fi

if diff -q "${SRC}" "${DST}" >/dev/null 2>&1; then
  echo "PASS: proto files are in sync"
  echo "  src: ${SRC}"
  echo "  dst: ${DST}"
  exit 0
else
  echo "FAIL: proto drift detected between:" >&2
  echo "  src: ${SRC}" >&2
  echo "  dst: ${DST}" >&2
  echo "" >&2
  diff "${SRC}" "${DST}" >&2 || true
  echo "" >&2
  echo "To fix: run 'make proto' inside CubeSandbox-master/network-agent/" >&2
  exit 1
fi
