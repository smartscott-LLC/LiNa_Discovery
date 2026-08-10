"""ipc_bridge — LINA/Triton dual-chamber zero-copy IPC bridge.

Chamber A (TX): outgoing requests  Python → Rust → network
Chamber B (RX): incoming context   network → Rust → Python

The chambers are fixed-size, 64-byte aligned memory-mapped files with
lock-free SPSC ring buffers (atomic head/tail counters). The payload is
exposed to Python zero-copy via the buffer protocol:

    bridge = ipc_bridge.IPCBridge()
    mv = memoryview(bridge.tx_view())      # direct window into shared memory

Frames on the ring are `[u32 little-endian length][payload]`.
"""

from ._ipc_bridge import IPCBridge, ChamberView

__all__ = ["IPCBridge", "ChamberView"]
__version__ = "0.1.0"
