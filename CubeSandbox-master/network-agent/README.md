# network-agent

**Status: local-node MVP — not production-ready. Not VPC/ENI/CubeGW parity.**

`network-agent` is the node-local network orchestration component for CubeSandbox.
It runs as a standalone process alongside `Cubelet` on each node and owns all
sandbox network lifecycle operations that were previously embedded in `Cubelet`.

## What is implemented

| Feature | Status |
|---|---|
| `EnsureNetwork` — TAP creation, cubevs registration, ARP/route setup | ✅ |
| `ReleaseNetwork` — TAP teardown, cubevs unregister, proxy cleanup | ✅ |
| `ReconcileNetwork` — reattach cubevs filter, restore routes/ARP | ✅ |
| `GetNetwork` / `ListNetworks` — state query | ✅ |
| TAP pool with recycle-on-release | ✅ |
| Abnormal TAP recovery with quarantine after repeated failures | ✅ |
| HostPort → guest userspace proxy | ✅ |
| State persistence to disk, recovery on restart | ✅ |
| gRPC server (`/tmp/cube/network-agent-grpc.sock`) | ✅ |
| HTTP health probes (`/healthz`, `/readyz`) | ✅ |
| TAP FD server (`/tmp/cube/network-agent-tap.sock`) | ✅ |

## What is NOT in scope for this MVP

- VPC / ENI / SubENI integration
- `networkd` or `CubeGW` tunnel-group orchestration
- Multi-node overlay or cross-host routing
- Production hardening, HA, or observability beyond local logs

## Directory layout

```text
network-agent/
  api/v1/               gRPC proto contract (kept in sync with Cubelet/pkg/networkagentclient/pb/)
  cmd/network-agent/    binary entry point
  internal/
    service/            core network lifecycle logic and unit tests
    grpcserver/         gRPC server wrapping service
    httpserver/         HTTP health probe server
    fdserver/           TAP file-descriptor passing server
  go.mod                Go module (local replace directives for CubeNet/cubevs and cubelog)
  Makefile              build, proto, test targets
```

## Building

```bash
# From the repo root:
make network-agent

# Or from this directory:
make build
```

## Running tests

```bash
cd network-agent
go test ./...
```

## Proto sync

`api/v1/network_agent.proto` is the canonical source.
`Cubelet/pkg/networkagentclient/pb/network_agent.proto` is the synced client copy.
These two files must remain byte-identical. Run `scripts/check-proto-drift.sh` or
`make proto` inside this directory to regenerate and sync.
