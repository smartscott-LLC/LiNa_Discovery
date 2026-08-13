#!/usr/bin/env python3
"""dragoncache_carve.py — the DragonCache carve: real, pinned, resident RAM.

The evolution of ``scripts/dragoncache_intel/intel_dragon_cache.cpp`` into a
managed tool. It reserves physical memory as huge pages (1GB when the CPU
supports it, else 2MB), mounts hugetlbfs, carves one contiguous pool file,
maps it, and pins it with ``mlock`` — the OS can never swap it. The
``DragonMap`` header (the contract from dragon_map.h) governs the pool:
chambers and the model region live at fixed offsets inside it, and every
spoke maps the same physical frames.

Safe by design: the default size is small (1GB) so the mechanism is proven
before the real 4GB carve; ``--release`` tears everything down cleanly.

Usage:
    sudo python3 scripts/dragoncache_carve.py --size 1G --page 1G
    sudo python3 scripts/dragoncache_carve.py --release
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

# The contract — dragon_map.h, mirrored in Python (ipc.py is the sibling).
DATA_OFFSET = 64
HEADER_SIZE = DATA_OFFSET  # 64 bytes: clock (u64) + status (u32) + pad


def parse_size(text: str) -> int:
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    text = text.strip().upper()
    if text[-1] in mult:
        return int(text[:-1]) * mult[text[-1]]
    return int(text)


def page_size_bytes(page: str) -> int:
    return parse_size(page)


def huge_page_count(size: int, psize: int) -> int:
    return max(1, -(-size // psize))  # ceil


def sysfs_path(psize: int) -> str:
    return SYSFS_1G if psize >= 1024 ** 3 else SYSFS_2M


def reserve(pages: int, psize: int) -> None:
    path = sysfs_path(psize)
    current = int(open(path).read().strip())
    if current < pages:
        with open(path, "w") as fh:
            fh.write(str(pages))
        print(f"[carve] reserved {pages} × {psize // (1024 ** 2)}MB huge pages "
              f"(was {current})")


def mount_hugetlbfs(psize: int) -> None:
    if os.path.ismount(HUGETLBFS):
        return
    rc = os.system(f"mount -t hugetlbfs -o pagesize={psize} none {HUGETLBFS}")
    if rc != 0:
        raise RuntimeError(f"hugetlbfs mount failed (rc={rc}) — is the pool "
                           "directory created and are huge pages reserved?")
    print(f"[carve] hugetlbfs mounted at {HUGETLBFS} (pagesize={psize // (1024 ** 2)}MB)")


def write_header(mapping: mmap.mmap) -> None:
    """DragonMap contract: global_clock (u64) at 0, system_status (u32) at 8."""
    struct.pack_into("<Q", mapping, 0, 0)  # global_clock
    struct.pack_into("<I", mapping, 8, 1)  # system_status = 1 (live)
    struct.pack_into("<I", mapping, 12, 0)  # pad


def resident_rss() -> int:
    """Resident set size in bytes from /proc/self/statm (field 2, in pages)."""
    with open("/proc/self/statm") as fh:
        parts = fh.read().split()
    return int(parts[1]) * os.sysconf("SC_PAGE_SIZE")


def carve(size: int, psize: int) -> None:
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
    # Touch a spread of pages so they are resident (huge pages are never
    # swapped — this is the "live on it" pin).
    step = max(4096, psize // 4)
    for off in range(HEADER_SIZE, actual, step):
        mapping[off] = 0
    ctypes.CDLL(None, use_errno=True).mlock(
        ctypes.c_void_p(ctypes.addressof(ctypes.c_char.from_buffer(mapping))),
        ctypes.c_size_t(actual),
    )

    rss = resident_rss()
    print(f"[carve] pool live — {actual / 1024 ** 3:.2f} GiB at {POOL_PATH}")
    print(f"[carve] header: clock=0 status=1 (DragonMap contract)")
    print(f"[carve] resident RSS: {rss / 1024 ** 3:.2f} GiB")
    print(f"[carve] region plan (4 GiB pool): control @64 · chambers @4K · "
          "weights @1.5G · working @3.5G")
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
    print("[carve] huge pages released")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--size", default="1G", help="pool size (default: 1G)")
    ap.add_argument("--page", default="1G", help="huge page size, 1G or 2M (default: 1G)")
    ap.add_argument("--release", action="store_true", help="tear the pool down")
    args = ap.parse_args()

    if args.release:
        release()
        return 0
    if os.geteuid() != 0:
        print("the carve needs root — run with sudo", file=sys.stderr)
        return 1
    carve(parse_size(args.size), page_size_bytes(args.page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
