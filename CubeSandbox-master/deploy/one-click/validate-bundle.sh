#!/usr/bin/env bash
# validate-bundle.sh — verify a one-click dist tarball or extracted package
# contains all required binaries and configs, and optionally validates SHA-256
# hashes against a MANIFEST.sha256 file.
#
# Usage:
#   ./validate-bundle.sh <DIST_TAR_OR_PACKAGE_DIR> [--manifest MANIFEST_FILE]
#
# Exit codes:
#   0  bundle is valid
#   1  one or more checks failed
#   2  bad arguments or missing tooling

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET="${1:-}"
MANIFEST_FILE=""

shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST_FILE="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${TARGET}" ]]; then
  echo "Usage: $0 <DIST_TAR_OR_PACKAGE_DIR> [--manifest MANIFEST_FILE]" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Resolve package directory
# ---------------------------------------------------------------------------
TMPDIR_CREATED=""
if [[ -f "${TARGET}" && "${TARGET}" == *.tar.gz ]]; then
  EXTRACT_DIR="$(mktemp -d)"
  TMPDIR_CREATED="${EXTRACT_DIR}"
  echo "Extracting ${TARGET} → ${EXTRACT_DIR} ..."
  tar -C "${EXTRACT_DIR}" -xzf "${TARGET}"
  # The tarball contains a dist dir which itself contains assets/package/sandbox-package.tar.gz
  INNER_PKG="$(find "${EXTRACT_DIR}" -name 'sandbox-package.tar.gz' -print -quit 2>/dev/null || true)"
  if [[ -n "${INNER_PKG}" ]]; then
    PKG_DIR="${EXTRACT_DIR}/sandbox-package"
    mkdir -p "${PKG_DIR}"
    tar -C "${PKG_DIR}" -xzf "${INNER_PKG}"
  else
    PKG_DIR="${EXTRACT_DIR}"
  fi
elif [[ -d "${TARGET}" ]]; then
  PKG_DIR="${TARGET}"
else
  echo "ERROR: TARGET is neither a .tar.gz file nor a directory: ${TARGET}" >&2
  exit 2
fi

cleanup() {
  if [[ -n "${TMPDIR_CREATED}" ]]; then
    rm -rf "${TMPDIR_CREATED}"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Required entries: path relative to PKG_DIR, description
# ---------------------------------------------------------------------------
declare -A REQUIRED_ENTRIES=(
  ["network-agent/bin/network-agent"]="network-agent binary"
  ["network-agent/network-agent.yaml"]="network-agent config"
  ["CubeMaster/bin/cubemaster"]="cubemaster binary"
  ["CubeMaster/bin/cubemastercli"]="cubemastercli binary"
  ["Cubelet/bin/cubelet"]="cubelet binary"
  ["Cubelet/bin/cubecli"]="cubecli binary"
  ["CubeAPI/bin/cube-api"]="cube-api binary"
  ["cube-shim/bin/cube-agent"]="cube-agent binary"
  ["cube-shim/bin/containerd-shim-cube-rs"]="containerd-shim binary"
  ["cube-shim/bin/cube-runtime"]="cube-runtime binary"
  ["Cubelet/config/config.toml"]="cubelet config"
)

failures=0

echo "=== Validating bundle: ${PKG_DIR} ==="
echo ""
echo "--- Required entries ---"
for rel in "${!REQUIRED_ENTRIES[@]}"; do
  desc="${REQUIRED_ENTRIES[$rel]}"
  full="${PKG_DIR}/${rel}"
  if [[ -f "${full}" ]]; then
    if [[ "${full}" == */bin/* ]] && [[ ! -x "${full}" ]]; then
      printf "  WARN  [not-executable] %s (%s)\n" "${rel}" "${desc}"
    else
      printf "  PASS  %s (%s)\n" "${rel}" "${desc}"
    fi
  else
    printf "  FAIL  MISSING: %s (%s)\n" "${rel}" "${desc}" >&2
    failures=$(( failures + 1 ))
  fi
done

# ---------------------------------------------------------------------------
# Optional manifest hash check
# ---------------------------------------------------------------------------
if [[ -n "${MANIFEST_FILE}" ]]; then
  echo ""
  echo "--- SHA-256 manifest check: ${MANIFEST_FILE} ---"
  if [[ ! -f "${MANIFEST_FILE}" ]]; then
    echo "  FAIL  manifest file not found: ${MANIFEST_FILE}" >&2
    failures=$(( failures + 1 ))
  else
    if command -v sha256sum >/dev/null 2>&1; then
      _verify() { (cd "${PKG_DIR}" && sha256sum -c "${MANIFEST_FILE}" 2>&1); }
    elif command -v shasum >/dev/null 2>&1; then
      _verify() { (cd "${PKG_DIR}" && shasum -a 256 -c "${MANIFEST_FILE}" 2>&1); }
    else
      echo "  SKIP  sha256sum/shasum not available — skipping hash verification" >&2
      _verify() { echo "skipped"; }
    fi
    # Only verify non-comment, non-MISSING lines.
    tmp_manifest="$(mktemp)"
    grep -v '^#' "${MANIFEST_FILE}" | grep -v '^$' | grep -v '^MISSING' > "${tmp_manifest}" || true
    if (cd "${PKG_DIR}" && sha256sum -c "${tmp_manifest}" >/dev/null 2>&1); then
      echo "  PASS  all hashes match"
    else
      echo "  FAIL  hash mismatch(es) detected:" >&2
      (cd "${PKG_DIR}" && sha256sum -c "${tmp_manifest}" 2>&1 | grep FAILED || true) >&2
      failures=$(( failures + 1 ))
    fi
    rm -f "${tmp_manifest}"
  fi
fi

echo ""
if [[ "${failures}" -eq 0 ]]; then
  echo "validate-bundle: PASSED"
  exit 0
else
  echo "validate-bundle: FAILED — ${failures} issue(s)" >&2
  exit 1
fi
