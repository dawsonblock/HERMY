# HERMY

HERMY is an integration scaffold for running Hermes with two separate
execution backends:

- CUA for GUI and computer-use actions.
- CubeSandbox, through an E2B-compatible API, for code and shell execution.

This repository is not a fully merged fork of Hermes, CUA, or CubeSandbox.
It is a bundled source archive plus a small local integration layer. The
integration code lives in `cube_bridge/`, `controller/`, `config/`, `scripts/`,
and `tests/`.

## What Is Vendored

The archive includes upstream source trees:

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
Linux/KVM Cube deployment or another E2B-compatible Cube API endpoint.

## Architecture

```text
User / Hermes
  -> CUA MCP HTTP server for GUI actions
  -> HERMY Cube MCP stdio bridge
       -> RuntimeController
       -> Policy
       -> Cube/E2B-compatible sandbox API
       -> /workspace
```

Hermes should connect to CUA directly over HTTP MCP. Hermes should connect to
Cube through the local HERMY stdio MCP bridge. CUA is GUI-only unless you have
deliberately isolated it for a broader role. Cube is the only HERMY code and
shell execution backend.

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

HERMY does not provide:

- A one-command full Hermes, CUA, and Cube launcher.
- A complete CubeSandbox deployment flow.
- A production security boundary by itself.
- Proof that your live CUA desktop or live Cube cluster is healthy.

## Install HERMY Integration Package

Use Python 3.11 or newer.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
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
matters. HERMY does not make your host desktop safe.

## Start Or Point To Cube

Cube live execution requires a running CubeSandbox deployment with KVM support,
or another E2B-compatible Cube API.

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

To include TCP reachability checks for CUA and Cube:

```bash
python scripts/hermy_doctor.py --live \
  --cua-url http://127.0.0.1:8000/mcp \
  --cube-url "$E2B_API_URL"
```

The live checks only verify basic TCP reachability. They do not create a Cube
sandbox or prove that CUA tools execute correctly.

## Run Tests

```bash
pytest
```

These tests are local integration-layer tests. They do not require a live CUA
server or a live Cube deployment.

## Configure Hermes

Use `config/hermes_config_template.yaml` as the starting point:

```yaml
mcp_servers:
  cua:
    url: "http://127.0.0.1:8000/mcp"
    timeout: 60
    connect_timeout: 10

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

terminal:
  backend: "none"
```

The important rule is that Hermes local terminal execution stays disabled.
Shell commands, Python code, and sandbox file operations should go through the
HERMY Cube MCP bridge.

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
- Command argv mode is preferred when callers can supply `list[str]`.
- Shell control operators are blocked in raw commands.
- Shell control operators require explicit approved-shell mode.
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

Override these with:

```bash
export CUBE_WORKSPACE_DIR=/workspace
export HERMY_DEFAULT_TIMEOUT_SECONDS=60
export HERMY_MAX_TIMEOUT_SECONDS=120
export HERMY_MAX_FILE_WRITE_BYTES=1000000
export HERMY_MAX_OUTPUT_BYTES=200000
export HERMY_ALLOW_INTERNET=0
export CUBE_EVENT_LOG=cube_events.jsonl
export CUBE_STRICT_AUDIT_LOGGING=0
```

This policy layer is a baseline, not a complete sandbox security model. The
real security boundary must come from CubeSandbox or another properly isolated
execution backend.

## Live Verification Checklist

A live environment is ready only after all of these are true:

- Doctor checks pass via `python scripts/hermy_doctor.py`.
- CUA MCP HTTP endpoint is reachable.
- Cube/E2B-compatible API endpoint is reachable.
- `CUBE_TEMPLATE_ID` points to a valid template.
- A Cube sandbox can be created outside Hermes with the E2B client.
- Hermes is configured with `terminal.backend: "none"`.
- Hermes can list both CUA and Cube MCP tools.
- Unknown Cube sandbox IDs are rejected before any backend call is made.
- A Cube sandbox can write and read a file under `/workspace`.
- A write outside `/workspace` is rejected.

Until those live checks pass, HERMY should be considered a clean integration
scaffold, not a working deployed agent runtime.
