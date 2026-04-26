# Hermes, CUA and CubeSandbox Integration

This repository bundles three upstream projects—**Hermes Agent**, **CUA**
and **CubeSandbox**—plus a small integration layer intended to stitch
them together into a cohesive stack. The upstream source trees are
present in this archive, but they still remain separate services with
clear boundaries. The local glue code, configuration templates and
scripts provide the intended control path between them.

## Overview

* **Hermes Agent** acts as the orchestrator and planner.  It is not
  included here; you should install it via `pip install hermes-agent`
  and run it independently.  Hermes communicates with external
  services through the [MCP protocol](https://github.com/intentionet/mcp).

* **CUA** (Computer Use Automation) provides
  screenshot, click, typing and other GUI operations via a
  WebSocket/HTTP interface.  This repository assumes you install
  `cua-computer-server` yourself and exposes the server on localhost.

* **CubeSandbox** supplies hardened, KVM‑backed sandboxes for
  executing untrusted commands.  The sandbox exposes an
  [E2B‑compatible](https://e2b.dev/) API.  You must deploy
  CubeSandbox on a Linux host with virtualization support.  This
  integration does not build or install Cube for you; it only
  provides a small bridge to translate between MCP and the E2B API.

The pieces are joined together by the `cube_mcp_server.py` script,
which implements a minimal MCP server backed by the `e2b-code-interpreter`
client library.  Hermes can call this server to create, run and
destroy Cube sandboxes.  A simple policy layer and event logger are
included to demonstrate how you might enforce safety rules and record
activity.

## Directory layout

```
integration/
  README.md               # this file
  cube_bridge/
    cube_mcp_server.py    # MCP bridge for CubeSandbox
    requirements.txt      # Python dependencies for the bridge
  config/
    hermes_config_template.yaml  # sample Hermes configuration
    hermes_prompt.md      # prompt injection rules and operator instructions
  controller/
    runtime_controller.py # skeleton for a runtime controller
    policy.py             # example policy enforcement module
    event_logger.py       # simple JSONL event logger
  scripts/
    start_cua_server.sh   # helper to run CUA computer server
    start_cube_api.sh     # hint for starting CubeSandbox API
  tests/
    test_cube_bridge.py   # minimal tests for the bridge
    test_policy.py        # tests for the policy module
```

The tests are simple and meant as examples; they assume CubeSandbox
and Hermes are not running.  You can run them with `pytest` after
installing the dependencies listed in `cube_bridge/requirements.txt`.

## Quick start

1. **Install CUA and start the server**.  On the machine where you
   want to control a desktop, run:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install "cua-computer-server[mcp]"
   # Run the server on an isolated desktop, e.g. via VNC or nested X11
   cua-computer-server \
     --host 127.0.0.1 --port 8000 \
     --width 1024 --height 768
   ```

2. **Deploy CubeSandbox**.  Follow the instructions in the
   `CubeSandbox` repository to deploy the CubeAPI and supporting
   services.  Make sure you can create and run sandboxes via the
   E2B Python client:

   ```bash
   python -c "from e2b_code_interpreter import Sandbox; print(Sandbox.create(template='<template-id>').commands.run('echo ok').stdout)"
   ```

3. **Install the bridge**.  On the machine where Hermes runs:

   ```bash
   python3 -m venv .venv-bridge
   source .venv-bridge/bin/activate
   pip install -r cube_bridge/requirements.txt
   # Set environment variables for Cube API
   export E2B_API_URL=http://<cube-api-host>:<port>
   export E2B_API_KEY=<dummy-key>
   export CUBE_TEMPLATE_ID=<template-id>
   python cube_bridge/cube_mcp_server.py
   ```

   The server will listen on the default MCP port (3641).  You can
   override the host/port via environment variables:

   ```bash
   export MCP_HOST=0.0.0.0
   export MCP_PORT=9000
   python cube_bridge/cube_mcp_server.py
   ```

4. **Configure Hermes**.  Copy `config/hermes_config_template.yaml`
   somewhere under your Hermes config path and adjust values for your
   environment (e.g. the CUA MCP URL, the Cube bridge command and
   environment variables, timeouts).  Add a top‑level section like:

   ```yaml
   mcp_servers:
     cua:
       url: "http://127.0.0.1:8000/mcp"
     cube:
       command: "python"
       args:
         - "/path/to/integration/cube_bridge/cube_mcp_server.py"
       env:
         E2B_API_URL: "http://<cube-api-host>:<port>"
         E2B_API_KEY: "<dummy-key>"
         CUBE_TEMPLATE_ID: "<template-id>"
   terminal:
     backend: "none"
   ```

5. **Run Hermes**.  Start Hermes with the modified configuration
   file and test the integrated environment.  Use CUA for GUI tasks
   (screenshots, clicks, typing) and Cube for code execution and
   untrusted commands.

## Security considerations

This integration intentionally separates concerns:

* Hermes never runs shell commands directly on your host.  It uses
  CubeSandbox for untrusted execution.
* CUA controls a desktop environment via a remote display (VNC or
  nested X11) rather than your primary machine.  Use a VM or
  container to host the CUA server for extra safety.
* The `policy.py` module shows how to enforce simple rules such as
  blocking certain commands and restricting file writes.  Adapt it to
  your needs before running any real workloads.

Always audit the commands Hermes generates and the environment
variables passed to CubeSandbox.  This integration is provided as an
example; you are responsible for hardening it for production use.
