"""Dual-chamber shared-memory IPC — LINA's chair at the table.

The chambers are memory-mapped files (``/dev/shm`` by default). Python maps
them with the stdlib ``mmap`` module; Triton maps the same files with
memmap3. Same physical frames, zero bindings — no PyO3, no maturin, no
phone line. Both sides look at the same table.

The on-disk layout mirrors memmap3's ``MmapStruct<Chamber>`` exactly (the
Rust side is the definition of truth; this module is its faithful mirror):

    offset 0     magic: 8 bytes   "MMAP0001" (memmap3's validation header)
    offset 8     56 pad bytes     data aligned to the struct's 64-byte align
    offset 64    head: u64 LE     producer write position (monotonic)
    offset 72    56 pad bytes     head alone on its cache line
    offset 128   tail: u64 LE     consumer read position (monotonic)
    offset 136   56 pad bytes     tail alone on its cache line
    offset 192   payload[65536]   wrap-around ring, framed by a u32 LE
                                 length prefix per message

    total file size: 64 + 65664 = 65728

SPSC discipline (the governance, §1 of LINA_DISCIPLINE):
  - one producer pushes (writes the frame, advances head)
  - one consumer pops (reads the frame, advances tail)
  - aligned 64-bit word accesses are atomic at the hardware level; the
    monotonic counters plus the wrap-around ring give the protocol its
    correctness — no locks, no kernel round-trips.
"""

from __future__ import annotations

import mmap
import os
import struct
import tempfile
from typing import Any

#: Raw payload capacity of one chamber — 64 KiB.
CHAMBER_PAYLOAD = 65536
#: Framing header — a little-endian u32 message length.
RING_HEADER = 4
#: memmap3's magic header (validated on open — a foreign file is refused).
MAGIC = b"MMAP0001"
#: The Chamber struct starts after the magic, aligned to its 64-byte align.
DATA_OFFSET = 64
HEAD_SIZE = 8
HEAD_PAD = 56
TAIL_OFFSET = DATA_OFFSET + HEAD_SIZE + HEAD_PAD          # 128
TAIL_SIZE = 8
TAIL_PAD = 56
PAYLOAD_OFFSET = TAIL_OFFSET + TAIL_SIZE + TAIL_PAD       # 192
#: Total file size: magic/data offset (64) + struct (65664).
CHAMBER_FILE_SIZE = DATA_OFFSET + (PAYLOAD_OFFSET - DATA_OFFSET) + CHAMBER_PAYLOAD  # 65728

_DEFAULT_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()


class ChamberError(Exception):
    """The chamber could not be mapped — the bridge is not available."""


class _Chamber:
    """One memory-mapped chamber: a lock-free SPSC ring over shared memory."""

    def __init__(self, path: str, name: str) -> None:
        self.path = path
        self.name = name
        self._mm: mmap.mmap | None = None
        self._open()

    def _open(self) -> None:
        try:
            if not os.path.exists(self.path):
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
                os.ftruncate(fd, CHAMBER_FILE_SIZE)
                os.write(fd, MAGIC)  # memmap3's magic — Triton validates it on open
                os.close(fd)
            fd = os.open(self.path, os.O_RDWR)
            try:
                file_len = os.fstat(fd).st_size
                if file_len != CHAMBER_FILE_SIZE:
                    raise ChamberError(
                        f"{self.name} chamber has wrong size {file_len} "
                        f"(expected {CHAMBER_FILE_SIZE}) — refusing a foreign file"
                    )
                head = os.read(fd, len(MAGIC))
                if head != MAGIC:
                    raise ChamberError(
                        f"{self.name} chamber has no memmap3 magic — refusing a foreign file"
                    )
                self._mm = mmap.mmap(fd, CHAMBER_FILE_SIZE, mmap.MAP_SHARED)
            finally:
                os.close(fd)
        except ChamberError:
            raise
        except Exception as exc:  # allocation failure — fail loudly, never silently
            raise ChamberError(f"{self.name} chamber map failed: {exc}") from exc

    # ── counters ──────────────────────────────────────────────────────────────
    def head(self) -> int:
        assert self._mm is not None
        return struct.unpack_from("<Q", self._mm, DATA_OFFSET)[0]

    def tail(self) -> int:
        assert self._mm is not None
        return struct.unpack_from("<Q", self._mm, TAIL_OFFSET)[0]

    def bytes_available(self) -> int:
        return self.head() - self.tail()

    def is_empty(self) -> bool:
        return self.head() == self.tail()

    def is_full(self) -> bool:
        return self.bytes_available() >= CHAMBER_PAYLOAD

    def reset(self) -> None:
        assert self._mm is not None
        struct.pack_into("<Q", self._mm, DATA_OFFSET, 0)
        struct.pack_into("<Q", self._mm, TAIL_OFFSET, 0)

    # ── SPSC ring operations ──────────────────────────────────────────────────
    def push(self, data: bytes) -> None:
        """Push one framed message (producer side)."""
        assert self._mm is not None
        length = len(data)
        if length > CHAMBER_PAYLOAD - RING_HEADER:
            raise ChamberError("message larger than ring capacity")
        head = self.head()
        used = head - self.tail()
        if used + RING_HEADER + length > CHAMBER_PAYLOAD:
            raise ChamberError("ring buffer full")
        self._write_wrap(head % CHAMBER_PAYLOAD, struct.pack("<I", length))
        self._write_wrap((head + RING_HEADER) % CHAMBER_PAYLOAD, data)
        # Publish: advance head after the payload is visible.
        struct.pack_into("<Q", self._mm, DATA_OFFSET, head + RING_HEADER + length)

    def pop(self) -> bytes | None:
        """Pop one framed message (consumer side). None when empty."""
        assert self._mm is not None
        head = self.head()
        tail = self.tail()
        if head == tail:
            return None
        pos = tail % CHAMBER_PAYLOAD
        length = struct.unpack("<I", self._read_wrap(pos, 4))[0]
        if length == 0 or length > CHAMBER_PAYLOAD - RING_HEADER:
            return None  # corrupt frame — refuse to advance (framing preserved)
        if head - tail < RING_HEADER + length:
            return None  # frame not fully committed yet
        out = self._read_wrap((pos + RING_HEADER) % CHAMBER_PAYLOAD, length)
        # Publish: advance tail after the frame is consumed.
        struct.pack_into("<Q", self._mm, TAIL_OFFSET, tail + RING_HEADER + length)
        return out

    def _write_wrap(self, pos: int, data: bytes) -> None:
        assert self._mm is not None
        first = min(CHAMBER_PAYLOAD - pos, len(data))
        self._mm[PAYLOAD_OFFSET + pos: PAYLOAD_OFFSET + pos + first] = data[:first]
        if first < len(data):
            rest = len(data) - first
            self._mm[PAYLOAD_OFFSET: PAYLOAD_OFFSET + rest] = data[first:]

    def _read_wrap(self, pos: int, length: int) -> bytes:
        assert self._mm is not None
        first = min(CHAMBER_PAYLOAD - pos, length)
        out = bytes(self._mm[PAYLOAD_OFFSET + pos: PAYLOAD_OFFSET + pos + first])
        if first < length:
            out += bytes(self._mm[PAYLOAD_OFFSET: PAYLOAD_OFFSET + length - first])
        return out

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None


class IPCBridge:
    """The dual-chamber bridge — LINA's seat at the shared-memory table.

    Allocation is eager and loud: if a chamber cannot be mapped, the
    bridge raises — the system is either built right or it is not running
    (LINA_DISCIPLINE §4.3 — no cover-your-ass degradation).
    """

    def __init__(self, tx_path: str | None = None, rx_path: str | None = None) -> None:
        self._tx_path = tx_path or os.getenv("IPC_TX_PATH") or os.path.join(_DEFAULT_DIR, "lina_ipc_tx.bin")
        self._rx_path = rx_path or os.getenv("IPC_RX_PATH") or os.path.join(_DEFAULT_DIR, "lina_ipc_rx.bin")
        self.tx = _Chamber(self._tx_path, "tx")
        self.rx = _Chamber(self._rx_path, "rx")

    def available(self) -> bool:
        return True  # construction raised if either chamber could not be mapped

    def capacity(self) -> int:
        return CHAMBER_PAYLOAD

    def tx_path(self) -> str:
        return self._tx_path

    def rx_path(self) -> str:
        return self._rx_path

    def push_tx(self, data: bytes) -> None:
        self.tx.push(data)

    def pop_tx(self) -> bytes | None:
        return self.tx.pop()

    def push_rx(self, data: bytes) -> None:
        self.rx.push(data)

    def pop_rx(self) -> bytes | None:
        return self.rx.pop()

    def reset(self) -> None:
        self.tx.reset()
        self.rx.reset()

    def close(self) -> None:
        self.tx.close()
        self.rx.close()

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available(),
            "capacity": CHAMBER_PAYLOAD,
            "tx_path": self._tx_path,
            "rx_path": self._rx_path,
            "tx_head": self.tx.head(),
            "tx_tail": self.tx.tail(),
            "tx_available_bytes": self.tx.bytes_available(),
            "rx_head": self.rx.head(),
            "rx_tail": self.rx.tail(),
            "rx_available_bytes": self.rx.bytes_available(),
        }
