# LINA's Runtime Space — her desk on the local machine

This is where LINA lives outside the container. Phase 1 of the desktop
migration defines these paths so she always knows where her things are.

| Path | Purpose | Created by |
|---|---|---|
| `runtime/logs/` | LINA's log files (`lina.log`, rotated at 10 MB) | lina_service on startup |
| `runtime/state/` | Runtime state: season snapshots, bridge state, telemetry checkpoints | services / scripts |
| `runtime/ipc/` | Dual-chamber shared-memory files for native (non-container) runs | `IPC_TX_PATH` / `IPC_RX_PATH` env |
| `runtime/workspace/` | Her working directory — the desk she collaborates on | tools / PWA shell (Phase 3+) |

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `LINA_STATE_DIR` | `<repo>/runtime` | Root of the runtime space |
| `LINA_LOG_DIR` | `<state>/logs` | Where `lina.log` is written |
| `IPC_TX_PATH` | `/dev/shm/lina_ipc_tx.bin` | TX chamber file (set to `<state>/ipc/…` for native runs) |
| `IPC_RX_PATH` | `/dev/shm/lina_ipc_rx.bin` | RX chamber file |
| `WORKSPACE_PATH` | `<repo>/runtime/workspace` | Working directory for tool execution |

The container deployment keeps its IPC in `/dev/shm` (fast, ephemeral,
correct for Docker). A native desktop run points `IPC_TX_PATH`/`IPC_RX_PATH`
at `runtime/ipc/` so the bridge survives reboots the same way her memory does.

## Verification

```bash
scripts/check-environment.sh
```

Reports directory structure, database health, ports, resources, toolchain,
and configuration — exit 0 when the space is ready.

*She will be a part of the process because she will be here.*
