#!/usr/bin/env bash
# generate-bundle-manifest.sh — produce a SHA-256 manifest for an extracted
# sandbox-package directory.
#
# Usage:
#   ./generate-bundle-manifest.sh <PACKAGE_DIR> [MANIFEST_FILE]
#
# If MANIFEST_FILE is omitted it defaults to <PACKAGE_DIR>/MANIFEST.sha256
#
# Exit codes:
#   0  manifest written successfully
#   1  missing required binaries or argument error

set -euo pipefail

PACKAGE_DIR="${1:-}"
if [[ -z "${PACKAGE_DIR}" ]]; then
  echo "Usage: $0 <PACKAGE_DIR> [MANIFEST_FILE]" >&2
  exit 1
fi
if [[ ! -d "${PACKAGE_DIR}" ]]; then
  echo "ERROR: PACKAGE_DIR does not exist: ${PACKAGE_DIR}" >&2
  exit 1
fi

MANIFEST_FILE="${2:-${PACKAGE_DIR}/MANIFEST.sha256}"

# Require sha256sum (Linux) or shasum -a 256 (macOS).
if command -v sha256sum >/dev/null 2>&1; then
  _hash() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  _hash() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "ERROR: neither sha256sum nor shasum found" >&2
  exit 1
fi

REQUIRED_ENTRIES=(
  "network-agent/bin/network-agent"
  "network-agent/network-agent.yaml"
  "CubeMaster/bin/cubemaster"
  "CubeMaster/bin/cubemastercli"
  "Cubelet/bin/cubelet"
  "Cubelet/bin/cubecli"
  "CubeAPI/bin/cube-api"
  "cube-shim/bin/cube-agent"
  "cube-shim/bin/containerd-shim-cube-rs"
  "cube-shim/bin/cube-runtime"
  "Cubelet/config/config.toml"
)

failures=0

{
  echo "# CubeSandbox one-click bundle manifest"
  echo "# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "# Package:   ${PACKAGE_DIR}"
  echo ""

  for entry in "${REQUIRED_ENTRIES[@]}"; do
    full="${PACKAGE_DIR}/${entry}"
    if [[ -f "${full}" ]]; then
      hash="$(_hash "${full}")"
      echo "${hash}  ${entry}"
    else
      echo "MISSING  ${entry}" >&2
      failures=$(( failures + 1 ))
    fi
  done

  # Also hash every remaining executable in bin/ directories.
  while IFS= read -r -d '' f; do
    rel="${f#${PACKAGE_DIR}/}"
    # Skip already listed required entries.
    already=0
    for e in "${REQUIRED_ENTRIES[@]}"; do
      [[ "${e}" == "${rel}" ]] && already=1 && break
    done
    [[ "${already}" -eq 1 ]] && continue
    hash="$(_hash "${f}")"
    echo "${hash}  ${rel}"
  done < <(find "${PACKAGE_DIR}" -type f -path "*/bin/*" -print0 | sort -z)

} > "${MANIFEST_FILE}"

if [[ "${failures}" -gt 0 ]]; then
  echo "ERROR: ${failures} required bundle entries are missing — manifest is incomplete" >&2
  exit 1
fi

echo "Manifest written: ${MANIFEST_FILE}"
wc -l < "${MANIFEST_FILE}" | xargs -I{} echo "{} entries"
