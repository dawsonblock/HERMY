# Supported Platform Matrix

CubeSandbox is **server-side KVM infrastructure**. This document defines what is
supported, what is not, and what the honest readiness verdict is for each
deployment target.

---

## Supported (tested deployment target)

| Target | Status | Notes |
|---|---|---|
| x86_64 Linux, bare-metal, KVM exposed | ✅ Supported | Primary target. `/dev/kvm` must be accessible. |
| x86_64 Linux, dedicated VM, KVM nested | ✅ Supported | Nested KVM must be enabled on the host hypervisor. |
| x86_64 Linux, single-node all-in-one | ✅ Supported | Use one-click `up.sh` in control role. |
| x86_64 Linux, multi-node (control + compute) | ✅ Supported | One control node + N compute nodes via `up-compute.sh`. |

## Not supported

| Target | Status | Reason |
|---|---|---|
| macOS (any architecture) | ❌ Not supported | No `/dev/kvm`, no Linux kernel, no TAP device support. |
| Windows | ❌ Not supported | No KVM, no Linux ABI, no TAP. |
| ARM / AArch64 hosts | ❌ Not supported | eBPF programs and cubevs are compiled for x86_64 only. |
| Shared cloud VMs without KVM passthrough | ❌ Not supported | Most shared cloud VMs do not expose `/dev/kvm`. Use a bare-metal or KVM-enabled cloud instance. |
| iPhone / Android / mobile devices | ❌ No server component | Mobile devices interact with CubeSandbox **only** as clients through the remote E2B-compatible REST API (`cube-api`). No server process runs on a mobile device. |
| Containers without KVM passthrough | ⚠️ Not tested | Running inside a container requires `/dev/kvm` bind-mounted and a privileged network namespace. Not validated. |

## Minimum hardware requirements (per node)

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | x86_64, 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| Storage | XFS at `/data/cubelet` | SSD, 100+ GB |
| KVM | `/dev/kvm` must exist | Bare-metal preferred |
| Network | 1 Gbps Ethernet | 10 Gbps for multi-node |

---

## Component readiness

| Component | Readiness | Notes |
|---|---|---|
| `CubeMaster` | Local MVP | Coordinates sandbox scheduling. Not HA. |
| `Cubelet` | Local MVP | Manages sandbox lifecycle on each node. |
| `CubeAPI` | Local MVP | E2B-compatible REST API. No auth by default — set `AUTH_CALLBACK_URL` before exposing publicly. |
| `network-agent` | **Local-node MVP** | TAP/cubevs/HostProxy. Not VPC/ENI/CubeGW parity. See `network-agent/README.md`. |
| `CubeShim` | Local MVP | containerd shim and cube-runtime. |
| `agent` (guest agent) | Local MVP | Runs inside the VM guest. |
| One-click deployment | Local MVP | Single-node validated. Multi-node deployment is documented but not CI-tested. |

---

## Known limitations

- `network-agent` does **not** implement VPC, ENI, SubENI, CubeGW, or tunnel-group orchestration.
  These are out of scope for the open-source MVP.
- CubeAPI binds `0.0.0.0:3000` by default. Set `AUTH_CALLBACK_URL` before exposing on a network.
  See `CubeAPI/src/middleware/auth.rs` and the startup warning in logs.
- No HA or leader election. Single control-plane failure loses sandbox scheduling.
- State recovery is local-disk only; no distributed state store.
- This repository is a **work in progress**. Do not treat it as production-ready
  without independent security and operational review.

---

## Production readiness verdict

> **Not production-ready as of this release.**
>
> CubeSandbox is a functional single-node and small-cluster MVP suitable for
> local development, experimentation, and building on top of. It requires
> independent security review, operational hardening, and HA work before use
> in a production environment serving untrusted workloads.
