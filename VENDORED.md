# Vendored Upstream Trees

This repository bundles three upstream source trees as read-only snapshots.
They are **not** HERMY-owned code and must not be modified as part of HERMY
development.

| Directory | Upstream project | Role |
| --- | --- | --- |
| `hermes-agent-2026.4.23/` | Hermes agent | LLM agent runtime that HERMY configures |
| `cua-main/` | CUA (Computer Use Agent) | GUI automation; runs as a separate HTTP MCP server process |
| `CubeSandbox-master/` | CubeSandbox | Linux/KVM sandbox backend; requires a real deployment |

## HERMY-owned code

All HERMY integration code lives exclusively in:

```text
controller/       Policy, audit logging, runtime controller
cube_bridge/      Cube MCP bridge (hermy-cube-mcp entry point)
cua_bridge/       CUA MCP proxy (hermy-cua-mcp entry point)
config/           Hermes config template
scripts/          Doctor script and startup helpers
tests/            Unit and governance tests for the HERMY layer
```

## Dependency boundary rule

HERMY-owned packages (`controller`, `cube_bridge`, `cua_bridge`) must not
import from vendored upstream internals directly. If integration with a
vendored tree is needed, write an explicit adapter module in the appropriate
HERMY package and document the dependency in that adapter.

CI should fail if `cube_bridge`, `cua_bridge`, or `controller` import symbols
from `hermes-agent-2026.4.23`, `cua-main`, or `CubeSandbox-master` without
going through such an adapter.

## Updating vendored trees

To update an upstream snapshot:

1. Replace the relevant directory with the new upstream release.
2. Run `pytest` to confirm the HERMY integration layer still passes.
3. Update this file with the new version/commit reference.
4. Update `README.md` if any integration wiring changes.
