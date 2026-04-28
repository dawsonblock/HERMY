#!/usr/bin/env bash
# audit-required-paths.sh — verify every path referenced by build/deploy scripts exists.
#
# Usage:
#   ./scripts/audit-required-paths.sh [REPO_ROOT]
#   ./scripts/audit-required-paths.sh --strict [REPO_ROOT]
#
# Exit codes:
#   0  all required paths present
#   1  one or more required paths missing
#
# Options:
#   --strict   exit immediately on the first missing path (default: report all, then exit 1)
#
# REPO_ROOT defaults to the directory that contains this script's parent.
# When run from CI the working directory is the repository root.

set -euo pipefail

STRICT=0
REPO_ROOT=""

for arg in "$@"; do
  case "${arg}" in
    --strict)
      STRICT=1
      ;;
    -*)
      echo "Unknown option: ${arg}" >&2
      exit 2
      ;;
    *)
      REPO_ROOT="${arg}"
      ;;
  esac
done

if [[ -z "${REPO_ROOT}" ]]; then
  # Resolve relative to this script's location: scripts/ is one level below root.
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

if [[ ! -d "${REPO_ROOT}" ]]; then
  echo "ERROR: REPO_ROOT does not exist: ${REPO_ROOT}" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Required directories — every path that a build or deploy script cd-s into
# or copies from. Paths are relative to REPO_ROOT.
# ---------------------------------------------------------------------------
REQUIRED_DIRS=(
  # network-agent — full expected layout
  "CubeSandbox-master/network-agent"
  "CubeSandbox-master/network-agent/cmd/network-agent"
  "CubeSandbox-master/network-agent/api/v1"
  "CubeSandbox-master/network-agent/internal"
  "CubeSandbox-master/network-agent/internal/service"
  "CubeSandbox-master/network-agent/internal/grpcserver"
  "CubeSandbox-master/network-agent/internal/httpserver"
  "CubeSandbox-master/network-agent/internal/fdserver"

  # network-agent proto sync target in Cubelet
  "CubeSandbox-master/Cubelet/pkg/networkagentclient/pb"

  # shared libraries that network-agent depends on
  "CubeSandbox-master/CubeNet/cubevs"
  "CubeSandbox-master/cubelog"

  # Go components
  "CubeSandbox-master/CubeMaster"
  "CubeSandbox-master/CubeMaster/cmd/cubemaster"
  "CubeSandbox-master/CubeMaster/cmd/cubemastercli"
  "CubeSandbox-master/Cubelet"
  "CubeSandbox-master/Cubelet/cmd/cubelet"
  "CubeSandbox-master/Cubelet/cmd/cubecli"
  "CubeSandbox-master/Cubelet/config"
  "CubeSandbox-master/Cubelet/dynamicconf"

  # Rust components
  "CubeSandbox-master/CubeAPI"
  "CubeSandbox-master/CubeShim"
  "CubeSandbox-master/agent"

  # Deploy scripts and templates
  "CubeSandbox-master/deploy/one-click"
  "CubeSandbox-master/deploy/one-click/scripts/one-click"
  "CubeSandbox-master/configs/single-node"
)

# ---------------------------------------------------------------------------
# Required files — individual files that build/deploy scripts reference by path.
# ---------------------------------------------------------------------------
REQUIRED_FILES=(
  # network-agent source files
  "CubeSandbox-master/network-agent/Makefile"
  "CubeSandbox-master/network-agent/go.mod"

  # proto contract — canonical source and Cubelet sync target must both exist
  "CubeSandbox-master/network-agent/api/v1/network_agent.proto"
  "CubeSandbox-master/Cubelet/pkg/networkagentclient/pb/network_agent.proto"

  # shared library entry points
  "CubeSandbox-master/CubeNet/cubevs/cubevs.go"
  "CubeSandbox-master/cubelog/log.go"

  # configs referenced by deploy scripts
  "CubeSandbox-master/configs/single-node/network-agent.yaml"
  "CubeSandbox-master/configs/single-node/cubelet.yaml"
  "CubeSandbox-master/configs/single-node/cubemaster.yaml"
  "CubeSandbox-master/Cubelet/config/config.toml"

  # top-level build entry points
  "CubeSandbox-master/Makefile"

  # one-click build and deploy scripts
  "CubeSandbox-master/deploy/one-click/build-release-bundle.sh"
  "CubeSandbox-master/deploy/one-click/build-release-bundle-builder.sh"
  "CubeSandbox-master/deploy/one-click/install.sh"
  "CubeSandbox-master/deploy/one-click/scripts/one-click/up.sh"
  "CubeSandbox-master/deploy/one-click/scripts/one-click/up-compute.sh"
  "CubeSandbox-master/deploy/one-click/lib/common.sh"
)

# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------
FAILURES=0

check_path() {
  local kind="$1"   # "dir" or "file"
  local rel="$2"
  local full="${REPO_ROOT}/${rel}"

  if [[ "${kind}" == "dir" ]]; then
    if [[ -d "${full}" ]]; then
      printf '  PASS  [dir]  %s\n' "${rel}"
      return 0
    fi
  else
    if [[ -f "${full}" ]]; then
      printf '  PASS  [file] %s\n' "${rel}"
      return 0
    fi
  fi

  printf '  FAIL  [%s] MISSING: %s\n' "${kind}" "${rel}" >&2
  FAILURES=$(( FAILURES + 1 ))

  if [[ "${STRICT}" -eq 1 ]]; then
    echo "Aborting (--strict mode)." >&2
    exit 1
  fi
}

echo "audit-required-paths: checking ${REPO_ROOT}"
echo ""

echo "=== Required directories ==="
for rel in "${REQUIRED_DIRS[@]}"; do
  check_path "dir" "${rel}"
done

echo ""
echo "=== Required files ==="
for rel in "${REQUIRED_FILES[@]}"; do
  check_path "file" "${rel}"
done

echo ""
if [[ "${FAILURES}" -eq 0 ]]; then
  echo "audit-required-paths: ALL PASSED (${#REQUIRED_DIRS[@]} dirs, ${#REQUIRED_FILES[@]} files)"
  exit 0
else
  echo "audit-required-paths: FAILED — ${FAILURES} missing path(s)" >&2
  exit 1
fi
