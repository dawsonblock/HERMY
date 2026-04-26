#!/usr/bin/env bash

# Run the local HERMY test suite without third-party pytest plugin autoload.
# This avoids hangs or side effects from globally installed pytest plugins.

set -euo pipefail

python -m compileall -q controller cube_bridge scripts tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
