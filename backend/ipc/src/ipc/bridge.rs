//! PyO3 bindings: the `IPCBridge` and zero-copy `ChamberView` classes.

use std::os::raw::c_int;
use std::path::PathBuf;

use pyo3::exceptions::{PyBufferError, PyRuntimeError};
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use ipc_core::buffer::{ChamberRing, CHAMBER_PAYLOAD};

/// Default shared-memory directory (tmpfs — survives inside containers).
const SHM_DIR: &str = "/dev/shm";
const TX_FILENAME: &str = "lina_ipc_tx.bin";
const RX_FILENAME: &str = "lina_ipc_rx.bin";

#[derive(Clone, Copy, PartialEq, Eq)]
enum ChamberKind {
    Tx,
    Rx,
}

/// The dual-chamber IPC bridge.
///
/// Chamber A (TX) carries outgoing requests: Python → Rust → network.
/// Chamber B (RX) carries incoming context: network → Rust → Python.
///
/// Allocation is best-effort: if the shared-memory files cannot be created,
/// the bridge still constructs with `available() == False` so the caller can
/// log and continue without it (fallback mode, never a crash).
#[pyclass(module = "ipc_bridge._ipc_bridge", name = "IPCBridge")]
pub struct IPCBridge {
    tx: Option<ChamberRing>,
    rx: Option<ChamberRing>,
    tx_path: PathBuf,
    rx_path: PathBuf,
}

impl IPCBridge {
    fn create() -> Self {
        let dir = if std::path::Path::new(SHM_DIR).is_dir() {
            PathBuf::from(SHM_DIR)
        } else {
            std::env::temp_dir()
        };
        let tx_path = dir.join(TX_FILENAME);
        let rx_path = dir.join(RX_FILENAME);

        match (
            ChamberRing::create(&tx_path, "tx"),
            ChamberRing::create(&rx_path, "rx"),
        ) {
            (Ok(tx), Ok(rx)) => IPCBridge {
                tx: Some(tx),
                rx: Some(rx),
                tx_path,
                rx_path,
            },
            (tx, rx) => {
                // Fallback mode — log loudly, keep serving without the bridge.
                let err = match (&tx, &rx) {
                    (Err(e), _) => e.to_string(),
                    (_, Err(e)) => e.to_string(),
                    _ => "unknown allocation error".to_string(),
                };
                eprintln!(
                    "[ipc_bridge] dual-chamber allocation failed ({err}); \
                     running without the bridge"
                );
                IPCBridge {
                    tx: tx.ok(),
                    rx: rx.ok(),
                    tx_path,
                    rx_path,
                }
            }
        }
    }

    fn ring<'a>(ring: &'a Option<ChamberRing>, what: &str) -> PyResult<&'a ChamberRing> {
        ring.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err(format!("{what} chamber unavailable")))
    }

    fn ring_mut<'a>(
        ring: &'a mut Option<ChamberRing>,
        what: &str,
    ) -> PyResult<&'a mut ChamberRing> {
        ring.as_mut()
            .ok_or_else(|| PyRuntimeError::new_err(format!("{what} chamber unavailable")))
    }
}

#[pymethods]
impl IPCBridge {
    #[new]
    #[pyo3(signature = ())]
    fn new() -> Self {
        Self::create()
    }

    /// True when both chambers were allocated successfully.
    fn available(&self) -> bool {
        self.tx.is_some() && self.rx.is_some()
    }

    fn tx_path(&self) -> String {
        self.tx_path.to_string_lossy().into_owned()
    }

    fn rx_path(&self) -> String {
        self.rx_path.to_string_lossy().into_owned()
    }

    fn capacity(&self) -> usize {
        CHAMBER_PAYLOAD
    }

    /// Push one message into the TX chamber (producer side).
    fn push_tx(&mut self, data: &[u8]) -> PyResult<()> {
        let ring = Self::ring_mut(&mut self.tx, "tx")?;
        ring.push(data)
            .map_err(|e| PyRuntimeError::new_err(format!("TX push: {e}")))
    }

    /// Pop one message from the TX chamber (consumer side — Triton / loopback).
    fn pop_tx(&mut self) -> PyResult<Option<Vec<u8>>> {
        let ring = Self::ring_mut(&mut self.tx, "tx")?;
        Ok(ring.pop())
    }

    /// Push one message into the RX chamber (producer side — Triton / loopback).
    fn push_rx(&mut self, data: &[u8]) -> PyResult<()> {
        let ring = Self::ring_mut(&mut self.rx, "rx")?;
        ring.push(data)
            .map_err(|e| PyRuntimeError::new_err(format!("RX push: {e}")))
    }

    /// Pop one message from the RX chamber (consumer side).
    fn pop_rx(&mut self) -> PyResult<Option<Vec<u8>>> {
        let ring = Self::ring_mut(&mut self.rx, "rx")?;
        Ok(ring.pop())
    }

    /// Zero-copy view of the TX payload region (implements the buffer
    /// protocol — wrap in `memoryview(...)` for direct access).
    fn tx_view(slf: PyRef<'_, Self>) -> PyResult<ChamberView> {
        let py = slf.py();
        Ok(ChamberView {
            bridge: slf.into_pyobject(py)?.unbind(),
            kind: ChamberKind::Tx,
        })
    }

    /// Zero-copy view of the RX payload region.
    fn rx_view(slf: PyRef<'_, Self>) -> PyResult<ChamberView> {
        let py = slf.py();
        Ok(ChamberView {
            bridge: slf.into_pyobject(py)?.unbind(),
            kind: ChamberKind::Rx,
        })
    }

    /// Reset both chambers' counters (recovery / tests).
    fn reset(&mut self) {
        if let Some(tx) = &mut self.tx {
            tx.reset();
        }
        if let Some(rx) = &mut self.rx {
            rx.reset();
        }
    }

    /// Live status of both chambers: availability, paths, counters, load.
    fn status(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let d = PyDict::new(py);
        d.set_item("available", self.available())?;
        d.set_item("capacity", CHAMBER_PAYLOAD)?;
        d.set_item("tx_path", self.tx_path())?;
        d.set_item("rx_path", self.rx_path())?;
        let tx = self.tx.as_ref();
        let rx = self.rx.as_ref();
        d.set_item("tx_head", tx.map(ChamberRing::head))?;
        d.set_item("tx_tail", tx.map(ChamberRing::tail))?;
        d.set_item("tx_available_bytes", tx.map(ChamberRing::bytes_available))?;
        d.set_item("rx_head", rx.map(ChamberRing::head))?;
        d.set_item("rx_tail", rx.map(ChamberRing::tail))?;
        d.set_item("rx_available_bytes", rx.map(ChamberRing::bytes_available))?;
        Ok(d.unbind())
    }
}

/// Zero-copy, buffer-protocol view of one chamber's payload region.
///
/// Holds a strong reference to the bridge, so the memory stays valid for as
/// long as any Python-side `memoryview` is alive. Exposes the full 64 KiB
/// payload; frames between `tail % capacity` and `head % capacity` are live
/// data (see `status()` for the counters).
#[pyclass(module = "ipc_bridge._ipc_bridge", name = "ChamberView")]
pub struct ChamberView {
    bridge: Py<IPCBridge>,
    kind: ChamberKind,
}

#[pymethods]
impl ChamberView {
    /// Number of payload bytes exposed (full ring capacity).
    fn __len__(&self) -> usize {
        CHAMBER_PAYLOAD
    }

    fn __repr__(&self) -> String {
        let chamber = match self.kind {
            ChamberKind::Tx => "TX",
            ChamberKind::Rx => "RX",
        };
        format!("<ChamberView {chamber} {CHAMBER_PAYLOAD} bytes>")
    }

    /// Buffer protocol — enables `memoryview(bridge.tx_view())` with zero copies.
    unsafe fn __getbuffer__(
        slf: PyRef<'_, Self>,
        view: *mut ffi::Py_buffer,
        flags: c_int,
    ) -> PyResult<()> {
        let bridge = slf.bridge.try_borrow(slf.py()).map_err(|_| {
            PyBufferError::new_err("bridge is mutably borrowed (push/pop in progress)")
        })?;
        let is_tx = slf.kind == ChamberKind::Tx;
        let ring = match slf.kind {
            ChamberKind::Tx => IPCBridge::ring(&bridge.tx, "tx"),
            ChamberKind::Rx => IPCBridge::ring(&bridge.rx, "rx"),
        }?;

        if view.is_null() {
            return Err(PyBufferError::new_err("null Py_buffer"));
        }

        let writable = flags & ffi::PyBUF_WRITABLE != 0;
        if writable && !is_tx {
            return Err(PyBufferError::new_err("RX chamber is read-only"));
        }

        let (ptr, len) = ring.payload_region();
        (*view).obj = ffi::Py_NewRef(slf.as_ptr());
        (*view).buf = ptr as *mut std::os::raw::c_void;
        (*view).len = len as ffi::Py_ssize_t;
        (*view).readonly = if is_tx { 0 } else { 1 };
        (*view).itemsize = 1;
        (*view).format = std::ptr::null_mut();
        (*view).ndim = 1;
        (*view).shape = std::ptr::null_mut();
        (*view).strides = std::ptr::null_mut();
        (*view).suboffsets = std::ptr::null_mut();
        (*view).internal = std::ptr::null_mut();
        Ok(())
    }

    unsafe fn __releasebuffer__(slf: PyRef<'_, Self>, _view: *mut ffi::Py_buffer) {
        // The view is a direct window into shared memory — nothing to free.
        let _ = slf;
    }
}
