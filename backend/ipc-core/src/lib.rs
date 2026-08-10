//! ipc_core — the LINA/Triton dual-chamber shared-memory substrate.
//!
//! Pure Rust, no Python bindings: this crate is linked by both the PyO3
//! extension (`ipc_bridge`) and the Triton binary, so both sides of the
//! bridge share one implementation of the lock-free SPSC ring.

pub mod buffer;

pub use buffer::{Chamber, ChamberRing, RingError, CHAMBER_PAYLOAD};
