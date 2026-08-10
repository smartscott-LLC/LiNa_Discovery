//! Triton — LINA's hardware substrate.
//!
//! The Triton-side consumer of the dual-chamber IPC bridge:
//!
//! ```text
//!   LINA (Python)  ──TX──▶  Chamber A  ──pop──▶  Triton
//!   LINA (Python)  ◀─RX──  Chamber B  ◀─push──  Triton (component foresight)
//! ```
//!
//! Loop:
//!   1. attach to the shared-memory files (`/dev/shm/lina_ipc_tx.bin`,
//!      `/dev/shm/lina_ipc_rx.bin` — re-attaching if LINA recreates them)
//!   2. poll Chamber A for outgoing requests
//!   3. process each request (sub-agent dispatch / web search — for now,
//!      log and echo)
//!   4. component foresight: broadcast the context to all PCIe spokes and
//!      collect acks BEFORE the delivery gate opens
//!   5. pre-populate Chamber B (RX) so LINA's evaluation happens instantly
//!
//! Run:
//!   cargo run --release -- --tx-path /dev/shm/lina_ipc_tx.bin \
//!       --rx-path /dev/shm/lina_ipc_rx.bin --poll-ms 10

mod spokes;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use ipc_core::buffer::ChamberRing;
use spokes::{SimulatedSpoke, SpokeRegistry};

const TX_FILENAME: &str = "lina_ipc_tx.bin";
const RX_FILENAME: &str = "lina_ipc_rx.bin";
const SHM_DIR: &str = "/dev/shm";

/// Triton stats — the substrate's vital signs.
#[derive(Default)]
struct Stats {
    messages_received: u64,
    tx_bytes_received: u64,
    rx_bytes_prepopulated: u64,
    broadcasts: u64,
    missed_acks: u64,
    reattaches: u64,
}

impl Stats {
    fn snapshot(&self) -> String {
        format!(
            "messages={} tx_bytes={} rx_prepop={} broadcasts={} missed_acks={} reattaches={}",
            self.messages_received,
            self.tx_bytes_received,
            self.rx_bytes_prepopulated,
            self.broadcasts,
            self.missed_acks,
            self.reattaches,
        )
    }
}

/// The two attached rings plus the inodes they were opened against, so we
/// can detect LINA recreating the files (create() unlinks + recreates).
struct Attached {
    tx: ChamberRing,
    rx: ChamberRing,
    tx_ino: u64,
    rx_ino: u64,
}

fn default_shm_dir() -> PathBuf {
    if Path::new(SHM_DIR).is_dir() {
        PathBuf::from(SHM_DIR)
    } else {
        std::env::temp_dir()
    }
}

fn current_ino(path: &Path) -> Option<u64> {
    use std::os::unix::fs::MetadataExt;
    std::fs::metadata(path).ok().map(|m| m.ino())
}

/// Open the shared-memory files if they exist. Returns None while LINA has
/// not created them yet (or while they are mid-recreation).
fn attach(tx_path: &Path, rx_path: &Path) -> Option<Attached> {
    let tx_ino = current_ino(tx_path)?;
    let rx_ino = current_ino(rx_path)?;
    let tx = ChamberRing::open(tx_path, "tx").ok()?;
    let rx = ChamberRing::open(rx_path, "rx").ok()?;
    Some(Attached {
        tx,
        rx,
        tx_ino,
        rx_ino,
    })
}

fn parse_args() -> (PathBuf, PathBuf, Duration, Duration) {
    let mut tx_path = default_shm_dir().join(TX_FILENAME);
    let mut rx_path = default_shm_dir().join(RX_FILENAME);
    let mut poll_ms: u64 = 10;
    let mut attach_ms: u64 = 200;

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--tx-path" => {
                if let Some(v) = args.next() {
                    tx_path = PathBuf::from(v);
                }
            }
            "--rx-path" => {
                if let Some(v) = args.next() {
                    rx_path = PathBuf::from(v);
                }
            }
            "--poll-ms" => {
                if let Some(v) = args.next() {
                    poll_ms = v.parse().unwrap_or(10);
                }
            }
            "--attach-ms" => {
                if let Some(v) = args.next() {
                    attach_ms = v.parse().unwrap_or(200);
                }
            }
            "--help" | "-h" => {
                println!(
                    "triton — LINA's hardware substrate (shared-memory consumer)\n\n\
                     USAGE:\n    triton [--tx-path PATH] [--rx-path PATH] [--poll-ms N] [--attach-ms N]\n\n\
                     Defaults mirror the ipc_bridge: /dev/shm (fallback: temp dir), 10ms poll."
                );
                std::process::exit(0);
            }
            other => eprintln!("[triton] ignoring unknown argument: {other}"),
        }
    }
    (
        tx_path,
        rx_path,
        Duration::from_millis(poll_ms),
        Duration::from_millis(attach_ms),
    )
}

fn main() {
    let (tx_path, rx_path, poll, attach_delay) = parse_args();

    let running = Arc::new(AtomicBool::new(true));
    let stop = running.clone();
    ctrlc::set_handler(move || {
        stop.store(false, Ordering::SeqCst);
    })
    .expect("[triton] failed to install SIGINT handler");

    // Component foresight spokes — in production these are real PCIe lanes;
    // here they are simulated so the broadcast/ack path is exercised.
    let mut registry = SpokeRegistry::new();
    registry.register(Box::new(SimulatedSpoke::new("spoke-pcie-0")));
    registry.register(Box::new(SimulatedSpoke::new("spoke-pcie-1")));

    let mut stats = Stats::default();
    let mut attached: Option<Attached> = None;
    let mut last_stats = Instant::now();
    let mut attach_logged = false;

    println!("[triton] substrate online — awaiting shared memory at {tx_path:?} / {rx_path:?}");
    println!("[triton] spokes registered: {}", registry.len());

    while running.load(Ordering::SeqCst) {
        // ---- attach / re-attach ----
        if attached.is_none() {
            match attach(&tx_path, &rx_path) {
                Some(a) => {
                    if attach_logged || stats.reattaches == 0 {
                        println!("[triton] attached to shared memory");
                    }
                    stats.reattaches += 1;
                    attached = Some(a);
                }
                None => {
                    if !attach_logged {
                        println!("[triton] waiting for LINA to create shared memory...");
                        attach_logged = true;
                    }
                    std::thread::sleep(attach_delay);
                    continue;
                }
            }
        }

        let a = attached.as_mut().expect("attached state");

        // ---- detect LINA recreating the files (create() unlinks) ----
        if current_ino(&tx_path) != Some(a.tx_ino) || current_ino(&rx_path) != Some(a.rx_ino) {
            println!("[triton] shared memory recreated by LINA — re-attaching");
            attached = None;
            stats.reattaches += 1;
            attach_logged = false;
            continue;
        }

        // ---- consume Chamber A (TX): outgoing requests ----
        match a.tx.pop() {
            Some(msg) => {
                stats.messages_received += 1;
                stats.tx_bytes_received += msg.len() as u64;
                println!(
                    "[triton] received {} bytes: {}",
                    msg.len(),
                    String::from_utf8_lossy(&msg)
                );

                // Process: sub-agent dispatch / web search. For now: echo.
                let context = process(&msg);
                println!(
                    "[triton] processed — foresight context: {} bytes",
                    context.len()
                );

                // ---- component foresight: broadcast BEFORE the delivery gate ----
                let report = registry.broadcast(&context);
                stats.broadcasts += 1;
                stats.missed_acks += report.missed.len() as u64;
                println!(
                    "[triton] pre-broadcast to {} spokes (acked={}, missed={})",
                    report.total(),
                    report.acked.len(),
                    report.missed.len()
                );
                if !report.missed.is_empty() {
                    println!("[triton]   missed acks: {}", report.missed.join(", "));
                }

                // ---- the delivery gate: pre-populate Chamber B (RX) ----
                match a.rx.push(&context) {
                    Ok(()) => {
                        stats.rx_bytes_prepopulated += context.len() as u64;
                        println!(
                            "[triton] delivery gate opened — RX pre-populated ({} bytes)",
                            context.len()
                        );
                    }
                    Err(e) => {
                        eprintln!("[triton] RX push failed: {e} (LINA will time out and continue)")
                    }
                }
            }
            None => std::thread::sleep(poll),
        }

        // ---- periodic vital signs ----
        if last_stats.elapsed() >= Duration::from_secs(10) {
            println!("[triton] stats — {}", stats.snapshot());
            last_stats = Instant::now();
        }
    }

    println!("\n[triton] shutdown — final stats: {}", stats.snapshot());
}

/// Process one request from Chamber A.
///
/// In production this dispatches to sub-agents / web search / the compute
/// fabric. The protocol is raw bytes — no serialization — so the response
/// here is the echo of the request, returned as the foresight context.
fn process(request: &[u8]) -> Vec<u8> {
    request.to_vec()
}
