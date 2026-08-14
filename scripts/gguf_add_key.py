#!/usr/bin/env python3
"""gguf_add_key.py — add a UINT32 metadata key to a GGUF by inserting it into
the header (streaming copy; tensor-data offsets are relative and untouched).

Conversion tools sometimes emit metadata under the wrong key name (the cstr
Qwen3-TTS conversion wrote ``qwen3tts.talker.max_pos`` where llama.cpp demands
``qwen3tts.context_length``). This inserts the corrected key without
rewriting tensors — fast and memory-light.

Usage:
    python gguf_add_key.py <src.gguf> <dst.gguf> <key> <uint32-value>
"""
from __future__ import annotations

import struct
import sys

UINT32 = 4  # GGUFValueType.UINT32


def main() -> None:
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)
    src, dst, key, value = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])

    with open(src, "rb") as f:
        head = f.read(24)
        if head[:4] != b"GGUF":
            raise SystemExit(f"{src} is not a GGUF file")
        kv_count = struct.unpack("<Q", head[16:24])[0]

        entry = (
            struct.pack("<Q", len(key)) + key.encode()
            + struct.pack("<I", UINT32) + struct.pack("<I", value)
        )
        with open(dst, "wb") as g:
            g.write(head[:16])
            g.write(struct.pack("<Q", kv_count + 1))
            g.write(entry)
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                g.write(chunk)

    print(f"inserted {key}={value} -> {dst} ({kv_count + 1} kv entries)")


if __name__ == "__main__":
    main()
