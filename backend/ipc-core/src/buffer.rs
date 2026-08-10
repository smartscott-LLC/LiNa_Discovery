//! Fixed-size, 64-byte aligned memory-mapped chambers with lock-free SPSC rings.
//!
//! Each chamber is a single file-backed `MmapStruct<Chamber>`:
//!
//! ```text
//!   file offset 0    8       64      72      128                65728
//!                  ┌───────┬───────┬───────┬───────┬──────────────┐
//!                  │ MAGIC │  pad  │ head  │ tail  │   payload    │
//!                  │ (8B)  │ (56B) │ (8B)  │ (56B) │   (64 KiB)   │
//!                  └───────┴───────┴───────┴───────┴──────────────┘
//!                         cache line 0    cache line 1
//! ```
//!
//! `head` (producer-owned) and `tail` (consumer-owned) live in separate
//! cache lines so producer and consumer never false-share. Both are
//! monotonically increasing byte counters; the position inside the ring is
//! `counter % capacity`. Frames are `[u32 little-endian length][payload]`.

use std::fmt;
use std::io;
use std::path::Path;
use std::sync::atomic::Ordering;

use memmap3::{mmap_struct, MmapStruct};

/// Raw payload capacity of one chamber — 64 KiB.
pub const CHAMBER_PAYLOAD: usize = 65536;
/// Framing header — a little-endian u32 message length.
pub const RING_HEADER: usize = 4;

/// Padding that pushes `tail` onto its own cache line (after `head`).
const HEAD_PAD: usize = 56;
/// Padding that pushes the payload onto its own cache line (after `tail`).
const TAIL_PAD: usize = 56;

/// A single IPC chamber.
///
/// `#[mmap_struct]` makes this persistable via `MmapStruct<Chamber>`:
/// `repr(C)`, atomic fields, zero-initialized on creation, magic-byte
/// validated on open. `#[repr(align(64))]` pins the struct (and therefore
/// its head/tail cache lines) to 64-byte boundaries.
#[mmap_struct]
#[repr(align(64))]
pub struct Chamber {
    /// Producer write position — monotonically increasing byte counter.
    #[mmap(atomic)]
    pub head: u64,
    /// Padding — keeps `head` alone on cache line 0.
    #[mmap(raw)]
    _pad_head: [u8; HEAD_PAD],
    /// Consumer read position — monotonically increasing byte counter.
    #[mmap(atomic)]
    pub tail: u64,
    /// Padding — keeps `tail` alone on cache line 1.
    #[mmap(raw)]
    _pad_tail: [u8; TAIL_PAD],
    /// Ring payload — raw bytes, framed by a u32 length prefix.
    #[mmap(raw)]
    pub payload: [u8; CHAMBER_PAYLOAD],
}

/// Errors from ring operations.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RingError {
    /// The ring cannot fit the message without overwriting unconsumed data.
    Full,
    /// The message exceeds the ring capacity.
    TooLarge,
    /// The ring is not mapped (allocation failed — fallback mode).
    Unavailable,
}

impl fmt::Display for RingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RingError::Full => write!(f, "ring buffer full"),
            RingError::TooLarge => write!(f, "message larger than ring capacity"),
            RingError::Unavailable => write!(f, "chamber unavailable"),
        }
    }
}

impl std::error::Error for RingError {}

/// A lock-free SPSC ring over a memory-mapped `Chamber`.
///
/// One process produces (calls `push`), one process consumes (calls `pop`).
/// Synchronization is purely atomic — no locks — via `MmapAtomicU64`
/// head/tail counters that live in shared memory.
pub struct ChamberRing {
    map: MmapStruct<Chamber>,
    name: &'static str,
}

impl ChamberRing {
    /// Create (or recreate) the chamber file at `path` and map it.
    ///
    /// `MmapStruct::create` removes any stale file first, so a crashed
    /// previous run can never leave poisoned head/tail counters behind.
    pub fn create<P: AsRef<Path>>(path: P, name: &'static str) -> io::Result<Self> {
        let map = MmapStruct::<Chamber>::create(path)?;
        Ok(ChamberRing { map, name })
    }

    /// Open an existing chamber file (used by the remote side of the pipe).
    pub fn open<P: AsRef<Path>>(path: P, name: &'static str) -> io::Result<Self> {
        let map = MmapStruct::<Chamber>::open(path)?;
        Ok(ChamberRing { map, name })
    }

    /// Reset both counters to zero (stale-state recovery / tests).
    pub fn reset(&mut self) {
        self.map.head.store(0, Ordering::Relaxed);
        self.map.tail.store(0, Ordering::Relaxed);
    }

    pub fn name(&self) -> &'static str {
        self.name
    }

    pub fn capacity(&self) -> usize {
        CHAMBER_PAYLOAD
    }

    pub fn head(&self) -> u64 {
        self.map.head.load(Ordering::Relaxed)
    }

    pub fn tail(&self) -> u64 {
        self.map.tail.load(Ordering::Relaxed)
    }

    /// Bytes currently in flight (unconsumed).
    pub fn bytes_available(&self) -> u64 {
        self.head() - self.tail()
    }

    pub fn is_empty(&self) -> bool {
        self.head() == self.tail()
    }

    pub fn is_full(&self) -> bool {
        self.bytes_available() >= CHAMBER_PAYLOAD as u64
    }

    /// Raw pointer + length of the payload region — for zero-copy exposure
    /// (memoryview). The region is stable for the lifetime of the mapping.
    pub fn payload_region(&self) -> (*const u8, usize) {
        let chamber: &Chamber = &self.map;
        (chamber.payload.as_ptr(), chamber.payload.len())
    }

    /// Push one framed message (SPSC producer side).
    ///
    /// Memory ordering: reads the consumer's `tail` with Acquire (to see
    /// freed space), publishes payload writes with a Release store on `head`.
    pub fn push(&mut self, data: &[u8]) -> Result<(), RingError> {
        let len = data.len();
        if len > CHAMBER_PAYLOAD - RING_HEADER {
            return Err(RingError::TooLarge);
        }

        let chamber: &mut Chamber = &mut self.map;
        let head = chamber.head.load(Ordering::Relaxed); // own counter
        let tail = chamber.tail.load(Ordering::Acquire); // consumer's freed space
        let used = head - tail;

        if used + (RING_HEADER as u64) + (len as u64) > CHAMBER_PAYLOAD as u64 {
            return Err(RingError::Full);
        }

        let hpos = (head as usize) % CHAMBER_PAYLOAD;
        write_wrap(&mut chamber.payload, hpos, &(len as u32).to_le_bytes());
        write_wrap(
            &mut chamber.payload,
            (hpos + RING_HEADER) % CHAMBER_PAYLOAD,
            data,
        );
        chamber
            .head
            .store(head + RING_HEADER as u64 + len as u64, Ordering::Release);
        Ok(())
    }

    /// Pop one framed message (SPSC consumer side). `None` when empty.
    ///
    /// Memory ordering: reads the producer's `head` with Acquire (to see
    /// committed payload), publishes freed space with a Release store on
    /// `tail`.
    pub fn pop(&mut self) -> Option<Vec<u8>> {
        let chamber: &mut Chamber = &mut self.map;
        let head = chamber.head.load(Ordering::Acquire);
        let tail = chamber.tail.load(Ordering::Relaxed); // own counter
        if head == tail {
            return None;
        }

        let tpos = (tail as usize) % CHAMBER_PAYLOAD;
        let len = read_u32_wrap(&chamber.payload, tpos) as usize;
        if len == 0 || len > CHAMBER_PAYLOAD - RING_HEADER {
            // Corrupt frame — refuse to advance so the pipe does not lose
            // framing. Caller can inspect/stall via status().
            return None;
        }

        let avail = head - tail;
        if avail < RING_HEADER as u64 + len as u64 {
            // Frame not fully committed yet — nothing to consume.
            return None;
        }

        let mut out = vec![0u8; len];
        read_wrap(
            &chamber.payload,
            (tpos + RING_HEADER) % CHAMBER_PAYLOAD,
            &mut out,
        );
        chamber
            .tail
            .store(tail + RING_HEADER as u64 + len as u64, Ordering::Release);
        Some(out)
    }
}

/// Write `data` into the ring starting at `pos`, wrapping at the end.
fn write_wrap(dst: &mut [u8], pos: usize, data: &[u8]) {
    let cap = dst.len();
    let first = (cap - pos).min(data.len());
    dst[pos..pos + first].copy_from_slice(&data[..first]);
    if first < data.len() {
        dst[..data.len() - first].copy_from_slice(&data[first..]);
    }
}

/// Read `out.len()` bytes from the ring starting at `pos`, wrapping at the end.
fn read_wrap(src: &[u8], pos: usize, out: &mut [u8]) {
    let cap = src.len();
    let n = out.len();
    let first = (cap - pos).min(n);
    out[..first].copy_from_slice(&src[pos..pos + first]);
    let rest = n - first;
    if rest > 0 {
        out[first..].copy_from_slice(&src[..rest]);
    }
}

fn read_u32_wrap(src: &[u8], pos: usize) -> u32 {
    let mut buf = [0u8; 4];
    read_wrap(src, pos, &mut buf);
    u32::from_le_bytes(buf)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    fn test_path(name: &str) -> String {
        format!("/tmp/lina_ipc_ring_{name}.bin")
    }

    fn fresh_ring(name: &str) -> ChamberRing {
        let path = test_path(name);
        let _ = std::fs::remove_file(&path);
        ChamberRing::create(&path, "test").unwrap()
    }

    #[test]
    fn layout_is_cache_line_separated() {
        assert_eq!(std::mem::align_of::<Chamber>(), 64);
        assert_eq!(std::mem::size_of::<Chamber>() % 64, 0);
        // head at offset 0 (cache line 0), tail at offset 64 (cache line 1)
        assert_eq!(std::mem::offset_of!(Chamber, head), 0);
        assert_eq!(std::mem::offset_of!(Chamber, tail), 64);
        assert_eq!(std::mem::offset_of!(Chamber, payload), 128);
    }

    #[test]
    fn push_pop_roundtrip() {
        let mut ring = fresh_ring("roundtrip");
        assert_eq!(ring.pop(), None);
        ring.push(b"hello").unwrap();
        ring.push(b"world").unwrap();
        assert_eq!(ring.pop().unwrap(), b"hello");
        assert_eq!(ring.pop().unwrap(), b"world");
        assert_eq!(ring.pop(), None);
        assert!(ring.is_empty());
    }

    #[test]
    fn wrap_around_and_binary_payloads() {
        let mut ring = fresh_ring("wrap");
        // Frame A (4 + 65530 bytes) leaves exactly 2 bytes of contiguous
        // space at the end of the ring.
        let big = vec![0xABu8; CHAMBER_PAYLOAD - RING_HEADER - 2];
        ring.push(&big).unwrap();
        assert!(ring.bytes_available() as usize == CHAMBER_PAYLOAD - 2);
        // Consume it so the head counter sits 2 bytes short of the boundary.
        assert_eq!(ring.pop().unwrap(), big);
        // Frame B (4 + 100 bytes) now straddles the end of the payload
        // region: 2 bytes of header at the tail, 2 wrapped to the start,
        // payload contiguous from offset 2.
        let small = vec![0x42u8; 100];
        ring.push(&small).unwrap();
        assert_eq!(ring.pop().unwrap(), small);
        assert!(ring.is_empty());
    }

    #[test]
    fn full_and_too_large() {
        let mut ring = fresh_ring("full");
        let big = vec![1u8; CHAMBER_PAYLOAD - RING_HEADER];
        ring.push(&big).unwrap();
        assert_eq!(ring.push(&[2u8; 10]), Err(RingError::Full));
        assert_eq!(ring.push(&[0u8; CHAMBER_PAYLOAD]), Err(RingError::TooLarge));
        ring.pop().unwrap();
        ring.push(&[3u8; 10]).unwrap(); // space freed
    }

    #[test]
    fn spsc_concurrent_across_handles() {
        // Two handles on the same file — the producer/consumer pattern that
        // Triton will use across processes (same shared-memory semantics).
        let path = test_path("spsc");
        let _ = std::fs::remove_file(&path);
        let mut prod = ChamberRing::create(&path, "prod").unwrap();
        let mut cons = ChamberRing::open(&path, "cons").unwrap();

        const TOTAL: u32 = 2000;

        let producer = thread::spawn(move || {
            for i in 0..TOTAL {
                let msg = format!("msg-{i}-{}", "x".repeat((i % 300) as usize));
                // Ring full — back off and retry (documented producer behavior).
                while let Err(RingError::Full) = prod.push(msg.as_bytes()) {
                    thread::sleep(Duration::from_micros(100));
                }
            }
        });

        let consumer = thread::spawn(move || {
            let mut seen = 0u32;
            while seen < TOTAL {
                match cons.pop() {
                    Some(bytes) => {
                        let s = String::from_utf8(bytes).unwrap();
                        assert!(s.starts_with(&format!("msg-{seen}-")));
                        seen += 1;
                    }
                    None => thread::sleep(Duration::from_micros(50)),
                }
            }
            seen
        });

        producer.join().unwrap();
        let seen = consumer.join().unwrap();
        assert_eq!(seen, TOTAL);
    }
}
