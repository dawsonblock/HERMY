#!/usr/bin/env bash

# HERMY does not deploy CubeSandbox. Cube live execution requires a real
# CubeSandbox Linux/KVM deployment or another E2B-compatible Cube API.
#
# This helper only supports a local development CubeAPI process when you
# explicitly opt in. It does not start CubeMaster, Cubelet, networking,
# templates, KVM, or the full production data plane.

set -euo pipefail

if [[ "${HERMY_ALLOW_DEV_CUBE_API:-}" != "1" ]]; then
  cat >&2 <<'MSG'
HERMY does not start a complete CubeSandbox deployment.

Use CubeSandbox's deployment flow first, then point HERMY at it:

  export E2B_API_URL=http://<cube-api-host>:3000
  export E2B_API_KEY=dummy
  export CUBE_TEMPLATE_ID=<template-id>

For local CubeAPI component development only, set:

  export HERMY_ALLOW_DEV_CUBE_API=1
  export CUBE_API_REPO=/path/to/CubeSandbox-master/CubeAPI
  scripts/start_cube_api.sh
MSG
  exit 2
fi

if [[ -z "${CUBE_API_REPO:-}" ]]; then
  echo "CUBE_API_REPO must point to CubeSandbox-master/CubeAPI." >&2
  exit 1
fi

cd "$CUBE_API_REPO"
echo "Starting CubeAPI component only from $CUBE_API_REPO"
exec cargo run --release
