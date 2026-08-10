"""End-to-end test of the ipc_bridge Python extension (built with maturin)."""
import os
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/ipc/python")

import ipc_bridge

results = []

def check(name, fn):
    try:
        fn()
        results.append((name, "OK"))
    except Exception as e:
        results.append((name, f"FAIL: {type(e).__name__}: {e}"))
        import traceback; traceback.print_exc()

def test_import():
    assert ipc_bridge.__version__ == "0.1.0"
    assert hasattr(ipc_bridge, "IPCBridge")
    assert hasattr(ipc_bridge, "ChamberView")

def test_bridge_creation():
    b = ipc_bridge.IPCBridge()
    assert b.available() is True, "bridge should be available"
    assert os.path.exists(b.tx_path()), f"tx file missing: {b.tx_path()}"
    assert os.path.exists(b.rx_path()), f"rx file missing: {b.rx_path()}"
    assert b.capacity() == 65536

def test_push_pop_roundtrip():
    b = ipc_bridge.IPCBridge()
    b.reset()
    b.push_tx(b"hello from python")
    b.push_tx(b"\x00\x01\x02\xff binary payload")
    assert b.pop_tx() == b"hello from python"
    assert b.pop_tx() == b"\x00\x01\x02\xff binary payload"
    assert b.pop_tx() is None
    assert b.pop_rx() is None

def test_rx_loopback():
    b = ipc_bridge.IPCBridge()
    b.reset()
    b.push_rx(b"context pre-populated")
    assert b.pop_rx() == b"context pre-populated"

def test_zero_copy_memoryview():
    b = ipc_bridge.IPCBridge()
    b.reset()
    view = memoryview(b.tx_view())
    assert view.nbytes == 65536
    assert view.format == "B"
    assert view.readonly == 0  # TX writable

    # Push a message and confirm it appears in the memoryview region at the
    # head position (frame: [u32 LE length][payload]).
    b.push_tx(b"zero-copy")
    st = b.status()
    head, tail = st["tx_head"], st["tx_tail"]
    assert head - tail == 4 + len(b"zero-copy")
    # header
    length = int.from_bytes(view[0:4], "little")
    assert length == len(b"zero-copy")
    assert bytes(view[4:4 + length]) == b"zero-copy"

    # Writing into the memoryview is visible through shared memory.
    view[100] = 0xAA
    assert bytes(view[100:101]) == b"\xaa"
    # The frame at ring positions 0..13 is untouched and still consumable.
    assert b.pop_tx() == b"zero-copy"

    # RX view is read-only
    rv = memoryview(b.rx_view())
    assert rv.readonly == 1

def test_status_after_ops():
    b = ipc_bridge.IPCBridge()
    b.reset()
    b.push_tx(b"a" * 1000)
    st = b.status()
    assert st["available"] is True
    assert st["tx_available_bytes"] == 1004
    b.pop_tx()
    st2 = b.status()
    assert st2["tx_available_bytes"] == 0

def test_large_message_and_full():
    b = ipc_bridge.IPCBridge()
    b.reset()
    big = os.urandom(65536 - 4)  # max frame
    b.push_tx(big)
    assert b.pop_tx() == big
    # exceeding capacity raises
    try:
        b.push_tx(os.urandom(65536))
        raise AssertionError("oversized message must be rejected")
    except RuntimeError:
        pass
    results.append(("large message + full", "OK"))

def test_view_lifetime():
    # memoryview keeps the bridge alive after we drop our reference
    view = None
    b = ipc_bridge.IPCBridge()
    view = memoryview(b.tx_view())
    del b
    assert view.nbytes == 65536  # still valid — strong ref held

if __name__ == "__main__":
    check("import", test_import)
    check("bridge creation", test_bridge_creation)
    check("push/pop roundtrip", test_push_pop_roundtrip)
    check("rx loopback", test_rx_loopback)
    check("zero-copy memoryview", test_zero_copy_memoryview)
    check("status after ops", test_status_after_ops)
    check("large message + full", test_large_message_and_full)
    check("view lifetime", test_view_lifetime)

    print("=" * 60)
    ok = True
    for name, status in results:
        print(f"[{status}] {name}")
        if status != "OK":
            ok = False
    print("=" * 60)
    print("ALL IPC BRIDGE TESTS PASS" if ok else "FAILURES PRESENT")
