# HERMY

> **Build status:** Build 14 is a **local integration scaffold**. It is not
> production-ready. Live operation requires a separately running CUA MCP
> server and a real Linux/KVM CubeSandbox or E2B-compatible deployment.
> iPhone and mobile devices can only be client UIs — they cannot run the
> server components.

HERMY is an integration scaffold for running Hermes with two separate
execution backends:

- CUA for GUI and computer-use actions.
- CubeSandbox, through an E2B-compatible API, for code and shell execution.

This repository is not a fully merged fork of Hermes, CUA, or CubeSandbox.
It is a bundled source archive plus a small local integration layer. The
integration code lives in `cube_bridge/`, `controller/`, `config/`, `scripts/`,
and `tests/`.

## What Is Vendored

This repo currently includes these upstream source trees:

- `hermes-agent-2026.4.23/`
- `cua-main/`
- `CubeSandbox-master/`

Treat those directories as upstream snapshots. HERMY packaging only installs
the local integration packages:

- `cube_bridge`
- `controller`

Hermes can be run from the vendored source tree or installed separately. CUA
source is vendored, but the CUA MCP server must run as its own process.
CubeSandbox source is vendored, but live Cube execution requires a real
Linux/KVM Cube deployment or another E2B-compatible Cube API endpoint plus a
valid `CUBE_TEMPLATE_ID`.

## Architecture

```text
User / Hermes
  -> HERMY CUA MCP proxy (stdio) -> CUA MCP HTTP server (GUI only)
  -> HERMY Cube MCP stdio bridge
       -> RuntimeController
       -> Policy
       -> Cube/E2B-compatible sandbox API
       -> /workspace
```

Hermes must connect to CUA through the HERMY CUA MCP proxy (`hermy-cua-mcp`).
The proxy allowlists safe GUI tools and blocks shell/file tools before they
reach Hermes. Hermes must connect to Cube through the HERMY Cube MCP bridge
(`hermy-cube-mcp`). Cube is the only HERMY code and shell execution backend.

Do not connect Hermes directly to the raw CUA HTTP MCP endpoint. Direct
connection bypasses HERMY's tool filter and allows Hermes to see shell/file
tools. If you need direct access for local development only, mark that
configuration explicitly as unsafe/dev-only and do not use it in any
environment where the desktop matters.

## Current Scope

HERMY currently provides:

- A packageable Cube MCP bridge in `cube_bridge/cube_mcp_server.py`.
- A `RuntimeController` that routes code operations to Cube and applies policy.
- A conservative policy layer for command, timeout, output, and workspace path
  checks.
- JSONL audit logging with optional fail-closed mode.
- A Hermes config template for CUA HTTP MCP plus HERMY Cube stdio MCP.
- Unit tests for the local integration layer.
- A standalone doctor script for environment checks.
- Session persistence: `RuntimeController` writes `hermy_sessions.json` on
  every session change and recovers sessions (marked stale) on restart.
- `scripts/verify_cua_proxy.py`: CUA proxy tool-filter verification script.
- `scripts/verify_cube_bridge.py`: Cube bridge live verification stub (pending
  full implementation — see ROADMAP in that file).

HERMY does not provide:

- A one-command full Hermes, CUA, and Cube launcher.
- A complete CubeSandbox deployment flow.
- A production security boundary by itself.
- Proof that your live CUA desktop or live Cube cluster is healthy.

## Install HERMY Integration Package

Use Python 3.11 or newer for the HERMY package. Use Python 3.12 for an
integrated HERMY + Hermes + CUA runtime because the vendored CUA workspace
requires Python `>=3.12,<3.14`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The install exposes:

```bash
hermy-cube-mcp
```

The doctor is intentionally kept as a standalone source script:

```bash
python scripts/hermy_doctor.py --help
```

## Start CUA Server

CUA must run separately and expose MCP over HTTP. The helper script starts
`cua-computer-server` with MCP enabled:

```bash
scripts/start_cua_server.sh
```

Defaults:

```bash
CUA_HOST=127.0.0.1
CUA_PORT=8000
CUA_WIDTH=1280
CUA_HEIGHT=720
```

CUA should control a disposable or isolated desktop session when safety
matters. HERMY does not make your host desktop safe. Keep CUA GUI-only unless
you have deliberately isolated the desktop and changed the policy for that
purpose.

## Start Or Point To Cube

Cube live execution requires a running CubeSandbox deployment with Linux/KVM
support, or another E2B-compatible Cube API, plus a valid template ID. Cube is
the only intended HERMY code and shell execution backend.

Set the required environment variables:

```bash
export E2B_API_URL=http://<cube-api-host>:3000
export E2B_API_KEY=dummy
export CUBE_TEMPLATE_ID=<template-id>
export CUBE_WORKSPACE_DIR=/workspace
```

`scripts/start_cube_api.sh` is not a Cube deployment tool. It refuses to run by
default because CubeAPI alone is not enough. For local CubeAPI component
development only:

```bash
export HERMY_ALLOW_DEV_CUBE_API=1
export CUBE_API_REPO=/path/to/CubeSandbox-master/CubeAPI
scripts/start_cube_api.sh
```

You still need CubeMaster, Cubelet, networking, templates, and KVM for real
sandbox execution.

## Run Doctor

After installing dependencies and exporting Cube variables:

```bash
python scripts/hermy_doctor.py
```

To verify the config text and vendored Hermes' resolved CLI tool registry
without live CUA or Cube:

```bash
python scripts/hermy_doctor.py --skip-env --hermes-tool-registry
```

To test CUA only:

```bash
python scripts/hermy_doctor.py --skip-env --live-cua \
  --cua-url http://127.0.0.1:8000/mcp
```

To test Cube API reachability only:

```bash
python scripts/hermy_doctor.py --live-cube --cube-url "$E2B_API_URL"
```

To test both live backends without mutating a Cube sandbox:

```bash
python scripts/hermy_doctor.py --live \
  --cua-url http://127.0.0.1:8000/mcp \
  --cube-url "$E2B_API_URL"
```

To run the opt-in live Cube smoke test:

```bash
python scripts/hermy_doctor.py --live-cube-smoke
```

`--live-cube-smoke` creates a Cube sandbox, writes and reads
`/workspace/hermy_probe.txt`, runs a shell probe, runs a Python probe, verifies
that `/etc/passwd` writes are rejected by HERMY policy, and destroys the
sandbox. It requires a real Cube/E2B-compatible deployment. The older
`--live-smoke` flag remains as an alias for CUA live checks, Cube API
reachability, and Cube smoke checks.

## Manual Startup Order

HERMY does not provide a supervisor yet. Start the pieces in this order:

```bash
# 1. Start an isolated CUA desktop/MCP server.
scripts/start_cua_server.sh

# 2. Start or point to a real Cube/E2B-compatible deployment.
export E2B_API_URL=http://<cube-api-host>:3000
export E2B_API_KEY=dummy
export CUBE_TEMPLATE_ID=<template-id>

# 3. Verify local config and Hermes tool resolution.
python scripts/hermy_doctor.py --skip-env --hermes-tool-registry

# 4. Verify live backends as needed.
python scripts/hermy_doctor.py --live-cua --live-cube

# 5. Run Hermes with config/hermes_config_template.yaml adapted to your environment.
```

CUA isolation and Cube deployment remain operator responsibilities.

## Run Tests

```bash
pytest
```

Recommended clean-environment command:

```bash
scripts/test_local.sh
```

The same fallback is available as:

```bash
PYTHON=python3.12 scripts/run_local_tests.sh
```

These tests are local integration-layer tests. Default tests do not require live CUA, live Cube, KVM, Docker, API keys, or network.
Use live doctor modes only when you deliberately want to test running infrastructure.

## Configure Hermes

Use `config/hermes_config_template.yaml` as the starting point:

```yaml
platform_toolsets:
  cli: ["web", "browser", "vision", "image_gen", "skills", "todo", "memory", "session_search", "clarify", "cua", "cube"]

mcp_servers:
  # Route CUA through the HERMY proxy so shell/file tools are blocked.
  cua:
    command: "hermy-cua-mcp"
    args: []
    timeout: 60
    connect_timeout: 10
    env:
      HERMY_UPSTREAM_CUA_URL: "http://127.0.0.1:8000/mcp"

  cube:
    command: "hermy-cube-mcp"
    args: []
    timeout: 120
    connect_timeout: 10
    env:
      E2B_API_URL: "http://127.0.0.1:3000"
      E2B_API_KEY: "dummy"
      CUBE_TEMPLATE_ID: "<your-cube-template-id>"
      CUBE_WORKSPACE_DIR: "/workspace"
      HERMY_MAX_CODE_BYTES: "200000"
      HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION: "0"
```

The important rule is that Hermes host-side execution tools stay disabled.
Use Hermes-supported `platform_toolsets.cli` configuration to exclude
`terminal`, `file`, and `code_execution`. Do not rely on
`terminal.backend: "none"` as a safety control; that backend is not known to be
a supported Hermes backend in the vendored snapshot. Shell commands, Python
code, and sandbox file operations should go through the HERMY Cube MCP bridge.

## Cube MCP Tools

The bridge exposes these tool functions:

- `cube_health`
- `cube_create`
- `cube_list_sessions`
- `cube_run_command`
- `cube_run_python`
- `cube_read_file`
- `cube_write_file`
- `cube_destroy`
- `cube_destroy_all`

Tool responses use a structured shape similar to:

```json
{
  "ok": true,
  "sandbox_id": "sbx-...",
  "stdout": "...",
  "stderr": "",
  "exit_code": 0,
  "error": null
}
```

## Policy Defaults

Policy is intentionally conservative:

- Workspace root defaults to `/workspace`.
- Reads and writes must remain under the workspace root.
- Command `list[str]` input is preferred because policy can validate explicit
  arguments, but the current Cube client converts it to a quoted shell command
  before calling E2B/Cube because no native argv backend has been confirmed.
- Shell control operators are blocked in raw commands.
- Shell control operators require explicit approved-shell mode with a valid
  `approval_id`.
- Shell wrapper execution such as `bash -c ...` is blocked.
- Inline interpreter execution such as `python -c ...` is blocked.
- Dangerous filesystem commands and flags are blocked.
- `cwd` shell wrapping is disabled until native Cube working-directory support
  is confirmed.
- Sandbox internet access is disabled unless `HERMY_ALLOW_INTERNET=1`.
- Default timeout is 60 seconds.
- Maximum timeout is 120 seconds.
- Maximum file write size is 1,000,000 bytes.
- Maximum returned text payload is 200,000 bytes.
- Maximum Python source payload is 200,000 bytes.
- Tool output redaction is enabled by default; secrets and token-like values
  are redacted in audit logs. Set `HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION=1` to
  opt-out (not recommended).

Override these with:

```bash
export CUBE_WORKSPACE_DIR=/workspace
export HERMY_DEFAULT_TIMEOUT_SECONDS=60
export HERMY_MAX_TIMEOUT_SECONDS=120
export HERMY_MAX_FILE_WRITE_BYTES=1000000
export HERMY_MAX_OUTPUT_BYTES=200000
export HERMY_MAX_CODE_BYTES=200000
export HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION=0
export HERMY_ALLOW_INTERNET=0
export CUBE_EVENT_LOG=cube_events.jsonl
export CUBE_STRICT_AUDIT_LOGGING=0
export HERMY_SESSION_FILE=hermy_sessions.json
```

Set `HERMY_SESSION_FILE=none` to disable session persistence entirely.

This policy layer is a baseline, not a complete sandbox security model. The
real security boundary must come from CubeSandbox or another properly isolated
execution backend.

## Path Confinement Limitations

HERMY validates path strings under the workspace root on the host side only.
It cannot detect symlinks that exist *inside* the sandbox filesystem. For
example, if a sandbox contains `/workspace/link -> /etc`, the path string
`/workspace/link/file` passes HERMY policy even though the real target is
outside `/workspace`.

The real confinement boundary must come from CubeSandbox or another properly
isolated execution backend. If symlink escape is a concern:

- Mount `/workspace` with `nosuid,nodev`.
- Use a read-only rootfs outside `/workspace`.
- Validate that the backend rejects symlink traversal at the syscall layer.

See `controller/policy.py` docstring on `validate_workspace_path` and
`tests/test_policy.py` for the documented limitation tests.

## Known Limitations

- **Approval ledger:** `approval_id` proves only string existence. A durable
  ledger binding an approval to a user, action, and expiry is pending. See
  `controller/approval_ledger.py`.
- **Session persistence:** Sessions are persisted to `hermy_sessions.json`
  and recovered as `stale` on restart. Live re-validation against the Cube
  API is not performed automatically.
- **Symlink confinement:** HERMY cannot verify sandbox-internal symlinks.
  Backend must enforce workspace confinement independently.
- **CUA tool schemas:** Proxy tool argument schemas are `**kwargs`. Upstream
  descriptions are injected as docstrings only. FastMCP does not support
  dynamic `inputSchema` injection.
- **Live Cube verification:** `scripts/verify_cube_bridge.py` is a stub.
  Use `python scripts/hermy_doctor.py --live-cube-smoke` for the existing
  opt-in smoke test.
- **No per-user authorization layer.**
- **No sandbox quota system.**
- **No supervisor/launcher** — start CUA, Cube, and Hermes manually.

## Live Verification Checklist

A live environment is ready only after all of these are true:

- Doctor checks pass via `python scripts/hermy_doctor.py`.
- CUA MCP HTTP endpoint is reachable.
- Cube/E2B-compatible API endpoint is reachable.
- `CUBE_TEMPLATE_ID` points to a valid template.
- A Cube sandbox can be created outside Hermes with the E2B client.
- Hermes `platform_toolsets.cli` excludes `terminal`, `file`, and
  `code_execution`.
- Hermes can list both CUA and Cube MCP tools.
- Unknown Cube sandbox IDs are rejected before any backend call is made.
- A Cube sandbox can write and read a file under `/workspace`.
- A write outside `/workspace` is rejected.
- `python scripts/verify_cua_proxy.py` exits 0 (CUA proxy filter verified).
- `python scripts/hermy_doctor.py --live-cube-smoke` passes (opt-in).

Until those live checks pass, HERMY should be considered a clean integration
scaffold, not a working deployed agent runtime.
