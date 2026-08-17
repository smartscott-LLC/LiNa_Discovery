#!/usr/bin/env python3
"""dragoncache_carve.py — the DragonCache carve: real, pinned, resident RAM.

The managed Python version of the Intel oneAPI carve tool. Reserves huge pages,
mounts hugetlbfs, creates the pool file, maps it, places models at their
offsets, and pins with mlock.

Layout (5.75 GiB = 5888 MiB = 2944 × 2M pages):

   0 MiB   –  128 MiB    Header region          (0.125 GiB)  DragonMap + spare
  128 MiB  – 1152 MiB    Chamber A — Module     (1.0 GiB)    Module slots + TX/RX ring
 1152 MiB  – 3840 MiB    Chamber B — Models     (2.625 GiB)  Qwen, mmproj, nomic
 3840 MiB  – 5888 MiB    Chamber C — Memory     (2.0 GiB)    dragonfly

Usage:
    sudo python3 scripts/dragoncache_carve.py                    # carve 5.75G
    sudo python3 scripts/dragoncache_carve.py --release          # tear down
    sudo python3 scripts/dragoncache_carve.py --status           # check state
"""
from __future__ import annotations

import argparse
import ctypes
import mmap
import os
import struct
import sys

POOL_PATH = "/mnt/huge/lina_pool"
HUGETLBFS = "/mnt/huge"
SYSFS_1G = "/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages"
SYSFS_2M = "/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
ADDRESS_MAP_FILE = "/home/server/LiNa_Discovery/.dragoncache_map"

# ── The contract — MUST match dragon_map.h exactly ────────────────────────
PAGE_2M = 2 * 1024 * 1024

# Header
HEADER_SIZE = 128 * 1024 * 1024      # 128 MiB

# Chamber A — Module Offset
MODULE_OFFSET = HEADER_SIZE           # 128 MiB
MODULE_SIZE = 1 * 1024 * 1024 * 1024  # 1 GiB

#   Chamber A sub-layout (offsets relative to MODULE_OFFSET):
#   0x000000000    512 KiB  Module state slots (spoke state blocks)
#   0x000080000    256 MiB  TX ring
#   0x100080000    256 MiB  RX ring
#   0x200080000    ~512 MiB Spoke work areas
MODULE_SLOT_REGION_SIZE = 512 * 1024       # 512 KiB

SLOT_SERVICE_STATE = 0x000100   # CarveServiceState (512B)
SLOT_VALUE_STATE   = 0x000300   # CarveModuleState (512B)
SLOT_MEMORY_STATE  = 0x000500   # CarveMemoryState (512B)

TX_RING_OFFSET = MODULE_SLOT_REGION_SIZE         # 512 KiB
TX_RING_SIZE = 256 * 1024 * 1024                # 256 MiB
RX_RING_OFFSET = TX_RING_OFFSET + TX_RING_SIZE   # 256 MiB + 512 KiB
RX_RING_SIZE = 256 * 1024 * 1024                # 256 MiB
WORK_AREA_OFFSET = RX_RING_OFFSET + RX_RING_SIZE
WORK_AREA_SIZE = MODULE_SIZE - WORK_AREA_OFFSET

# Chamber B — Model Offset
MODEL_OFFSET = MODULE_OFFSET + MODULE_SIZE   # 1152 MiB
MODEL_SIZE = 2688 * 1024 * 1024               # 2688 MiB = 2.625 GiB

# Model sub-offsets (relative to MODEL_OFFSET)
MODEL_QWEN_OFFSET = 0
MODEL_QWEN_PAGES = 607
MODEL_MMPROJ_OFFSET = MODEL_QWEN_PAGES * PAGE_2M
MODEL_MMPROJ_PAGES = 635
MODEL_NOMIC_OFFSET = MODEL_MMPROJ_OFFSET + MODEL_MMPROJ_PAGES * PAGE_2M
MODEL_NOMIC_PAGES = 70

# Chamber C — Memory Offset
MEMORY_OFFSET = MODEL_OFFSET + MODEL_SIZE   # 3840 MiB
MEMORY_SIZE = 2 * 1024 * 1024 * 1024        # 2 GiB

# Total
TOTAL_POOL_SIZE = 5888 * 1024 * 1024         # 5888 MiB = 5.75 GiB

# Model disk paths
MODEL_QWEN_PATH = "/home/server/models/lina-local/Qwen2-VL-2B-Instruct-Q6_K.gguf"
MODEL_MMPROJ_PATH = "/home/server/models/lina-local/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"
MODEL_NOMIC_PATH = "/home/server/models/lina-local/nomic-embed-text-v1.5.Q8_0.gguf"

# Spoke health bitmask values (must match dragon_map.h)
SPOKE_IDENTITY_SERVICE = 1
SPOKE_VALUE_ENGINE     = 2
SPOKE_MEMORY_MODULE    = 4
SPOKE_CORTEX           = 8
SPOKE_VOICE            = 16
SPOKE_TX_RING          = 32
SPOKE_RX_RING          = 64


def parse_size(text: str) -> int:
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    text = text.strip().upper()
    if text and text[-1] in mult:
        return int(float(text[:-1]) * mult[text[-1]])
    return int(text)


def page_size_bytes(page: str) -> int:
    return parse_size(page)


def huge_page_count(size: int, psize: int) -> int:
    return max(1, -(-size // psize))


def sysfs_path(psize: int) -> str:
    return SYSFS_1G if psize >= 1024 ** 3 else SYSFS_2M


def reserve(pages: int, psize: int) -> None:
    HEADROOM = 96
    path = sysfs_path(psize)
    current = int(open(path).read().strip())
    target = pages + HEADROOM
    if current < target:
        with open(path, "w") as fh:
            fh.write(str(target))
        print(f"[carve] reserved {target} × {psize // (1024 ** 2)}MB huge pages "
              f"(was {current}, headroom {HEADROOM})")
    else:
        print(f"[carve] huge pages already reserved: {current} × {psize // (1024 ** 2)}MB")


def mount_hugetlbfs(psize: int) -> None:
    if os.path.ismount(HUGETLBFS):
        return
    rc = os.system(f"mount -t hugetlbfs -o pagesize={psize} none {HUGETLBFS}")
    if rc != 0:
        raise RuntimeError(f"hugetlbfs mount failed (rc={rc})")


def write_header(mapping: mmap.mmap) -> None:
    """DragonMap: global_clock (u64) at 0, system_status (u32) at 8,
    spoke_health (u32) at 12, pad to 64 bytes."""
    struct.pack_into("<Q", mapping, 0, 0)       # global_clock = 0
    struct.pack_into("<I", mapping, 8, 3)       # system_status = STATUS_BOOTING
    struct.pack_into("<I", mapping, 12, 0)      # spoke_health = 0
    # Remaining 48 bytes of the 64B DragonMap are padding (already zero from mmap)


def init_slot(mapping: mmap.mmap, abs_offset: int, size: int, label: str) -> None:
    """Zero-init a slot on the carve and flush."""
    mapping[abs_offset:abs_offset + size] = b'\x00' * size
    mapping.flush()
    print(f"[carve] {label} slot zeroed at offset {abs_offset // 1024} KiB ({size} bytes)")


def write_address_map() -> None:
    with open(ADDRESS_MAP_FILE, "w") as f:
        f.write("# DragonCache Address Map\n")
        f.write("# Generated by dragoncache_carve.py\n")
        f.write(f"# Total pool: {TOTAL_POOL_SIZE // 1024 // 1024} MiB "
                f"({TOTAL_POOL_SIZE // PAGE_2M} huge pages)\n")
        f.write("\n")
        f.write(f"DRAGONCACHE_POOL_SIZE={TOTAL_POOL_SIZE}\n")
        f.write(f"DRAGONCACHE_POOL_FILE={POOL_PATH}\n")
        f.write("\n")
        f.write("# Header region (0 - 128 MiB)\n")
        f.write("DRAGONCACHE_HEADER_OFFSET=0\n")
        f.write(f"DRAGONCACHE_HEADER_SIZE={HEADER_SIZE}\n")
        f.write("\n")
        f.write("# Chamber A — Module Offset (128 MiB - 1152 MiB)\n")
        f.write(f"DRAGONCACHE_MODULE_OFFSET={MODULE_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODULE_SIZE={MODULE_SIZE}\n")
        f.write(f"DRAGONCACHE_MODULE_SLOT_REGION_OFFSET={MODULE_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODULE_SLOT_REGION_SIZE={MODULE_SLOT_REGION_SIZE}\n")
        f.write(f"DRAGONCACHE_SLOT_SERVICE_STATE={MODULE_OFFSET + SLOT_SERVICE_STATE}\n")
        f.write(f"DRAGONCACHE_SLOT_VALUE_STATE={MODULE_OFFSET + SLOT_VALUE_STATE}\n")
        f.write(f"DRAGONCACHE_SLOT_MEMORY_STATE={MODULE_OFFSET + SLOT_MEMORY_STATE}\n")
        f.write(f"DRAGONCACHE_TX_RING_OFFSET={MODULE_OFFSET + TX_RING_OFFSET}\n")
        f.write(f"DRAGONCACHE_TX_RING_SIZE={TX_RING_SIZE}\n")
        f.write(f"DRAGONCACHE_RX_RING_OFFSET={MODULE_OFFSET + RX_RING_OFFSET}\n")
        f.write(f"DRAGONCACHE_RX_RING_SIZE={RX_RING_SIZE}\n")
        f.write(f"DRAGONCACHE_WORK_AREA_OFFSET={MODULE_OFFSET + WORK_AREA_OFFSET}\n")
        f.write(f"DRAGONCACHE_WORK_AREA_SIZE={WORK_AREA_SIZE}\n")
        f.write("\n")
        f.write("# Chamber B — Model Offset (1152 MiB - 3840 MiB)\n")
        f.write(f"DRAGONCACHE_MODEL_OFFSET={MODEL_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODEL_SIZE={MODEL_SIZE}\n")
        f.write(f"DRAGONCACHE_MODEL_QWEN_OFFSET={MODEL_OFFSET + MODEL_QWEN_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODEL_QWEN_PAGES={MODEL_QWEN_PAGES}\n")
        f.write(f"DRAGONCACHE_MODEL_MMPROJ_OFFSET={MODEL_OFFSET + MODEL_MMPROJ_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODEL_MMPROJ_PAGES={MODEL_MMPROJ_PAGES}\n")
        f.write(f"DRAGONCACHE_MODEL_NOMIC_OFFSET={MODEL_OFFSET + MODEL_NOMIC_OFFSET}\n")
        f.write(f"DRAGONCACHE_MODEL_NOMIC_PAGES={MODEL_NOMIC_PAGES}\n")
        f.write("\n")
        f.write("# Chamber C — Memory Offset (3840 MiB - 5888 MiB)\n")
        f.write(f"DRAGONCACHE_MEMORY_OFFSET={MEMORY_OFFSET}\n")
        f.write(f"DRAGONCACHE_MEMORY_SIZE={MEMORY_SIZE}\n")
        f.write("\n")
        f.write("# Spoke health bitmask values\n")
        f.write(f"SPOKE_IDENTITY_SERVICE={SPOKE_IDENTITY_SERVICE}\n")
        f.write(f"SPOKE_VALUE_ENGINE={SPOKE_VALUE_ENGINE}\n")
        f.write(f"SPOKE_MEMORY_MODULE={SPOKE_MEMORY_MODULE}\n")
        f.write(f"SPOKE_CORTEX={SPOKE_CORTEX}\n")
        f.write(f"SPOKE_VOICE={SPOKE_VOICE}\n")
        f.write(f"SPOKE_TX_RING={SPOKE_TX_RING}\n")
        f.write(f"SPOKE_RX_RING={SPOKE_RX_RING}\n")
    print(f"[carve] address map @ {ADDRESS_MAP_FILE}")


def print_address_map() -> None:
    mb = lambda b: b // 1024 // 1024
    kb = lambda b: b // 1024
    print(f"\n── DragonCache Address Map ({mb(TOTAL_POOL_SIZE)} MiB total) ──")
    print(f"  Header:      {mb(0)} MiB  ({mb(HEADER_SIZE)} MiB)")
    print(f"  Chamber A:   {mb(MODULE_OFFSET)} MiB  ({mb(MODULE_SIZE)} MiB)  Module Offset")
    print(f"    Slots:     {kb(0)} KiB  ({kb(MODULE_SLOT_REGION_SIZE)} KiB)")
    print(f"      Service: {kb(SLOT_SERVICE_STATE)} B  (512 B)  CarveServiceState")
    print(f"      Value:   {kb(SLOT_VALUE_STATE)} B  (512 B)  CarveModuleState")
    print(f"      Memory:  {kb(SLOT_MEMORY_STATE)} B  (512 B)  CarveMemoryState")
    print(f"    TX-Ring:   {mb(TX_RING_OFFSET)} MiB  ({mb(TX_RING_SIZE)} MiB)")
    print(f"    RX-Ring:   {mb(RX_RING_OFFSET)} MiB  ({mb(RX_RING_SIZE)} MiB)")
    print(f"    WorkArea:  {mb(WORK_AREA_OFFSET)} MiB  ({mb(WORK_AREA_SIZE)} MiB)")
    print(f"  Chamber B:   {mb(MODEL_OFFSET)} MiB  ({mb(MODEL_SIZE)} MiB)  Model Offset")
    print(f"    Qwen:      {mb(MODEL_OFFSET + MODEL_QWEN_OFFSET)} MiB  ({MODEL_QWEN_PAGES * 2} MiB)")
    print(f"    mmproj:    {mb(MODEL_OFFSET + MODEL_MMPROJ_OFFSET)} MiB  ({MODEL_MMPROJ_PAGES * 2} MiB)")
    print(f"    nomic:     {mb(MODEL_OFFSET + MODEL_NOMIC_OFFSET)} MiB  ({MODEL_NOMIC_PAGES * 2} MiB)")
    print(f"  Chamber C:   {mb(MEMORY_OFFSET)} MiB  ({mb(MEMORY_SIZE)} MiB)  Memory Offset")


def resident_rss() -> int:
    with open("/proc/self/statm") as fh:
        parts = fh.read().split()
    return int(parts[1]) * os.sysconf("SC_PAGE_SIZE")


def place_model(mapping: mmap.mmap, src_path: str, offset: int,
                pages: int, label: str) -> bool:
    if not os.path.isfile(src_path):
        print(f"[carve] {label} not found: {src_path}")
        return False
    size = os.path.getsize(src_path)
    placed = pages * PAGE_2M

    # Quick idempotency check: first 4 bytes match?
    if offset + 4 <= len(mapping):
        existing = struct.unpack_from("<I", mapping, offset)[0]
        with open(src_path, "rb") as f:
            expected = struct.unpack_from("<I", f.read(4))[0]
        if existing == expected:
            print(f"[carve] {label} already on carve at {offset // 1024 // 1024} MiB")
            return True

    CHUNK = PAGE_2M
    with open(src_path, "rb") as fin:
        written = 0
        while written < size:
            block = fin.read(CHUNK)
            if not block:
                break
            mapping[offset + written:offset + written + len(block)] = block
            written += len(block)
    mapping.flush()
    print(f"[carve] {label} placed at {offset // 1024 // 1024} MiB "
          f"({placed // 1024 // 1024} MiB, {pages} pages)")
    return True


def carve(size: int, psize: int, place_models: bool = True) -> None:
    pages = huge_page_count(size, psize)
    actual = pages * psize
    reserve(pages, psize)
    mount_hugetlbfs(psize)

    if os.path.exists(POOL_PATH):
        os.unlink(POOL_PATH)
    fd = os.open(POOL_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    os.ftruncate(fd, actual)
    mapping = mmap.mmap(fd, actual, mmap.MAP_SHARED)
    os.close(fd)

    write_header(mapping)

    # Touch all pages to wire them
    step = max(4096, psize // 4)
    for off in range(HEADER_SIZE, actual, step):
        mapping[off] = 0

    # Initialize module state slots (Chamber A)
    print("\n── Initializing module state slots (Chamber A) ──")
    init_slot(mapping, MODULE_OFFSET + SLOT_SERVICE_STATE, 512, "ServiceState")
    init_slot(mapping, MODULE_OFFSET + SLOT_VALUE_STATE, 512, "ValueEngine")
    init_slot(mapping, MODULE_OFFSET + SLOT_MEMORY_STATE, 512, "MemoryModule")
    init_slot(mapping, MODULE_OFFSET + TX_RING_OFFSET, PAGE_2M, "TX-Ring (first 2 MiB)")
    init_slot(mapping, MODULE_OFFSET + RX_RING_OFFSET, PAGE_2M, "RX-Ring (first 2 MiB)")

    # Mark header as live
    struct.pack_into("<I", mapping, 8, 1)  # system_status = STATUS_LIVE

    # Pin with mlock
    ctypes.CDLL(None, use_errno=True).mlock(
        ctypes.c_void_p(ctypes.addressof(ctypes.c_char.from_buffer(mapping))),
        ctypes.c_size_t(actual),
    )

    rss = resident_rss()
    print(f"[carve] pool live — {actual / 1024 ** 3:.2f} GiB at {POOL_PATH}")
    print(f"[carve] header: clock=0 status=live")
    print(f"[carve] resident RSS: {rss / 1024 ** 3:.2f} GiB")

    # Place models
    if place_models:
        print("\n── Placing models (Chamber B) ──")
        place_model(mapping, MODEL_QWEN_PATH, MODEL_OFFSET + MODEL_QWEN_OFFSET,
                    MODEL_QWEN_PAGES, "Qwen2-VL-2B")
        place_model(mapping, MODEL_MMPROJ_PATH, MODEL_OFFSET + MODEL_MMPROJ_OFFSET,
                    MODEL_MMPROJ_PAGES, "mmproj")
        place_model(mapping, MODEL_NOMIC_PATH, MODEL_OFFSET + MODEL_NOMIC_OFFSET,
                    MODEL_NOMIC_PAGES, "nomic-embed-text")

    write_address_map()
    print_address_map()
    mapping.flush()


def release() -> None:
    for path in (POOL_PATH,):
        if os.path.exists(path):
            os.unlink(path)
            print(f"[carve] released {path}")
    if os.path.ismount(HUGETLBFS):
        os.system(f"umount {HUGETLBFS}")
        print(f"[carve] unmounted {HUGETLBFS}")
    for sp in (SYSFS_1G, SYSFS_2M):
        if os.path.exists(sp):
            with open(sp, "w") as fh:
                fh.write("0")
    if os.path.exists(ADDRESS_MAP_FILE):
        os.unlink(ADDRESS_MAP_FILE)
    print("[carve] huge pages released")


def status() -> int:
    print("── DragonCache Status ──")
    if os.path.exists(POOL_PATH):
        sz = os.path.getsize(POOL_PATH)
        print(f"  Pool:     {POOL_PATH} ({sz / 1e9:.2f} GiB)")
    else:
        print(f"  Pool:     {POOL_PATH} — NOT PRESENT")
    print(f"  hugetlbfs: {'mounted' if os.path.ismount(HUGETLBFS) else 'NOT MOUNTED'}")
    total = 0
    free = 0
    for line in open("/proc/meminfo"):
        if "HugePages_Total" in line:
            total = int(line.split()[1])
        if "HugePages_Free" in line:
            free = int(line.split()[1])
    print(f"  Huge pages: {total} × 2M = {total * 2 / 1024:.1f} GiB total, "
          f"{total - free} used, {free} free")
    for label, path in [("Qwen", MODEL_QWEN_PATH),
                        ("mmproj", MODEL_MMPROJ_PATH),
                        ("nomic", MODEL_NOMIC_PATH)]:
        ok = "✓" if os.path.exists(path) else "✗ MISSING"
        print(f"  {label:6s}  {ok}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--size", default="5.75G",
                    help="pool size (default: 5.75G)")
    ap.add_argument("--page", default="2M",
                    help="huge page size (default: 2M)")
    ap.add_argument("--release", action="store_true", help="tear down")
    ap.add_argument("--status", action="store_true", help="check state")
    ap.add_argument("--no-models", action="store_true",
                    help="skip placing models")
    args = ap.parse_args()

    if args.status:
        return status()
    if args.release:
        release()
        return 0
    if os.geteuid() != 0:
        print("the carve needs root — run with sudo", file=sys.stderr)
        return 1
    carve(parse_size(args.size), page_size_bytes(args.page),
          place_models=not args.no_models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())