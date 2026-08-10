//! Component foresight — the pre-broadcast layer.
//!
//! Before the delivery gate opens, Triton broadcasts the context to every
//! connected PCIe spoke. Each spoke acknowledges receipt; when the gate
//! opens, every downstream node already holds a verified copy. This is how
//! latency is killed before it accumulates.

use std::time::Duration;

/// A downstream hardware spoke that receives pre-broadcast context.
pub trait Spoke {
    /// Stable identifier for observability and ack tracking.
    fn id(&self) -> &str;

    /// Deliver `data` to the spoke. Returns `true` when the spoke
    /// acknowledges receipt (verified copy held).
    fn deliver(&mut self, data: &[u8]) -> bool;
}

/// Result of a broadcast — which spokes acked and which missed.
#[derive(Debug, Default, Clone)]
pub struct BroadcastReport {
    pub acked: Vec<String>,
    pub missed: Vec<String>,
}

impl BroadcastReport {
    pub fn total(&self) -> usize {
        self.acked.len() + self.missed.len()
    }
}

/// Registry of connected spokes. Broadcasts fan out to every spoke before
/// the delivery gate opens.
#[derive(Default)]
pub struct SpokeRegistry {
    spokes: Vec<Box<dyn Spoke + Send>>,
}

impl SpokeRegistry {
    pub fn new() -> Self {
        SpokeRegistry::default()
    }

    pub fn register(&mut self, spoke: Box<dyn Spoke + Send>) {
        self.spokes.push(spoke);
    }

    pub fn len(&self) -> usize {
        self.spokes.len()
    }

    /// Fan out `data` to all spokes, collecting acks. Never blocks on a
    /// spoke beyond its own delivery timeout.
    pub fn broadcast(&mut self, data: &[u8]) -> BroadcastReport {
        let mut report = BroadcastReport::default();
        for spoke in &mut self.spokes {
            if spoke.deliver(data) {
                report.acked.push(spoke.id().to_string());
            } else {
                report.missed.push(spoke.id().to_string());
            }
        }
        report
    }
}

/// A simulated spoke for development and testing: acknowledges after a
/// short latency, can be told to fail so the missed-ack path is exercised.
pub struct SimulatedSpoke {
    id: String,
    delivered: u64,
    fail_next: bool,
}

impl SimulatedSpoke {
    pub fn new(id: &str) -> Self {
        SimulatedSpoke {
            id: id.to_string(),
            delivered: 0,
            fail_next: false,
        }
    }

    /// Arm a single failed delivery (for testing the missed-ack path).
    #[allow(dead_code)] // test helper — unused by the production loop
    pub fn arm_failure(&mut self) {
        self.fail_next = true;
    }

    #[allow(dead_code)] // test helper
    pub fn delivered(&self) -> u64 {
        self.delivered
    }
}

impl Spoke for SimulatedSpoke {
    fn id(&self) -> &str {
        &self.id
    }

    fn deliver(&mut self, data: &[u8]) -> bool {
        // Simulated spoke latency — a real spoke would DMA the copy.
        std::thread::sleep(Duration::from_micros(50));
        if self.fail_next {
            self.fail_next = false;
            return false;
        }
        self.delivered += 1;
        let _ = data; // a real spoke would copy into its own buffer
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn broadcast_acks_all_spokes() {
        let mut registry = SpokeRegistry::new();
        registry.register(Box::new(SimulatedSpoke::new("spoke-0")));
        registry.register(Box::new(SimulatedSpoke::new("spoke-1")));
        registry.register(Box::new(SimulatedSpoke::new("spoke-2")));

        let report = registry.broadcast(b"foresight context");
        assert_eq!(report.acked.len(), 3);
        assert_eq!(report.missed.len(), 0);
        assert_eq!(report.total(), 3);
    }

    #[test]
    fn broadcast_tracks_missed_acks() {
        let mut registry = SpokeRegistry::new();
        let mut spoke = SimulatedSpoke::new("spoke-0");
        spoke.arm_failure();
        registry.register(Box::new(spoke));
        registry.register(Box::new(SimulatedSpoke::new("spoke-1")));

        let report = registry.broadcast(b"x");
        assert_eq!(report.acked, vec!["spoke-1".to_string()]);
        assert_eq!(report.missed, vec!["spoke-0".to_string()]);

        // Next broadcast succeeds again — failure was one-shot.
        let report2 = registry.broadcast(b"y");
        assert_eq!(report2.acked.len(), 2);
        assert_eq!(report2.missed.len(), 0);
    }

    #[test]
    fn empty_registry_broadcasts_cleanly() {
        let mut registry = SpokeRegistry::new();
        let report = registry.broadcast(b"z");
        assert_eq!(report.total(), 0);
    }
}
