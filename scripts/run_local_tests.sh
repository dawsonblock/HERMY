#!/usr/bin/env bash

# Alias for scripts/test_local.sh
# Kept for backward compatibility.

set -euo pipefail

exec "$(dirname "$0")/test_local.sh" "$@"
