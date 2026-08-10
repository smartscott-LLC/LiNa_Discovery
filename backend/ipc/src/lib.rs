//! ipc_bridge — LINA/Triton dual-chamber zero-copy IPC bridge.
//!
//! Chamber A (TX): outgoing requests, Python → Rust → network.
//! Chamber B (RX): incoming context, network → Rust → Python.
//!
//! Both chambers are fixed-size, 64-byte aligned memory-mapped files with
//! lock-free SPSC ring buffers tracked by atomic head/tail counters.

pub mod ipc;

use pyo3::prelude::*;

use ipc::bridge::IPCBridge;

/// Python module: `import ipc_bridge`.
#[pymodule]
fn _ipc_bridge(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<IPCBridge>()?;
    m.add_class::<ipc::bridge::ChamberView>()?;
    Ok(())
}
