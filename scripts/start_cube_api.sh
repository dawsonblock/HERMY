#!/usr/bin/env bash

# Placeholder script for starting CubeSandbox API.
#
# CubeSandbox requires a full deployment with KVM, CubeMaster,
# CubeAPI and associated services.  This script provides a hint for
# launching the CubeAPI component in development mode.

set -euo pipefail

if [ -z "${CUBE_API_REPO:-}" ]; then
  echo "Please set CUBE_API_REPO to the path of your CubeSandbox/CubeAPI repository." >&2
  exit 1
fi

cd "$CUBE_API_REPO"
echo "Starting CubeAPI with default settings..."

# You may need to adjust RUST_LOG and other environment variables.  See
# the CubeSandbox documentation for details.
exec cargo run --release