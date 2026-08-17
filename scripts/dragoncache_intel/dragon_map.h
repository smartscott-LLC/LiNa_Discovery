#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>

// ═══════════════════════════════════════════════════════════════════════════
//  dragon_map.h — The Unified Address Map Contract for LINA's DragonCache
//  Carve. Every spoke includes this header. Every spoke mmaps the same
//  physical frames at /mnt/huge/lina_pool. Offsets carve the pool into
//  four regions. The DragonMap at offset 0 is the heartbeat — one atomic
//  cache line that makes every spoke state-aware.
//
//  The DragonCache is not a pipeline. It is a hub-and-spoke architecture
//  where every spoke reads the same header and knows the state of every
//  other spoke. There is no "last in the chain" — every spoke is aware.
// ═══════════════════════════════════════════════════════════════════════════

// ── Page size ──────────────────────────────────────────────────────────────
constexpr uint64_t PAGE_2M = 2ULL * 1024 * 1024;

// ── Pool layout ────────────────────────────────────────────────────────────
//   Region        Offset     Size       Contents
//   ──────        ──────     ────       ────────
//   Header        0          128 MiB    DragonMap heartbeat + spare
//   Chamber A    128 MiB    1024 MiB    Module states, TX/RX ring, work areas
//   Chamber B   1152 MiB    2688 MiB    Placed weights (Qwen, mmproj, nomic)
//   Chamber C   3840 MiB    2048 MiB    Dragonfly short-term memory space
//   ──────        ──────     ────       ────────
//   Total       5888 MiB = 5.75 GiB = 2944 × 2M huge pages
// ═══════════════════════════════════════════════════════════════════════════

// ── Header region ──────────────────────────────────────────────────────────
constexpr uint64_t HEADER_OFFSET  = 0ULL;
constexpr uint64_t HEADER_SIZE    = 128ULL * 1024 * 1024;        // 128 MiB ≈ 0.1 GiB

// ── Chamber A — Module Offset (spoke live state + TX/RX ring) ──────────────
constexpr uint64_t MODULE_OFFSET  = HEADER_OFFSET + HEADER_SIZE; // 128 MiB
constexpr uint64_t MODULE_SIZE    = 1ULL * 1024 * 1024 * 1024;   // 1 GiB

//   Chamber A sub-layout (offsets relative to MODULE_OFFSET):
//   ─────────────────────────────────────────────────────────────────
//   Range          Size     Contents
//   0x000000000    512 KiB  Module state slots (spoke state blocks)
//   0x000080000    256 MiB  TX ring (SPSC, variable-length frames)
//   0x100080000    256 MiB  RX ring (SPSC, variable-length frames)
//   0x200080000    ~512 MiB Spoke work areas (reserved for future)
//   ─────────────────────────────────────────────────────────────────

//   Module state slots (each 512 bytes, 64B cache-line aligned):
constexpr uint64_t MODULE_SLOT_REGION_OFFSET = 0ULL;
constexpr uint64_t MODULE_SLOT_REGION_SIZE    = 512ULL * 1024;       // 512 KiB

constexpr uint64_t SLOT_DRAGONMAP      = 0ULL;       // offset 0x000000 → DragonMap itself
constexpr uint64_t SLOT_SERVICE_STATE  = 0x000100;   // offset 0x000100 → CarveServiceState (512B)
constexpr uint64_t SLOT_VALUE_STATE    = 0x000300;   // offset 0x000300 → CarveModuleState (512B)
constexpr uint64_t SLOT_MEMORY_STATE   = 0x000500;   // offset 0x000500 → CarveMemoryState (512B)
// ... more slots available at 0x000700, 0x000900, 0x000B00, etc. (each 512B)

//   TX ring (offsets relative to MODULE_OFFSET):
constexpr uint64_t TX_RING_OFFSET = MODULE_SLOT_REGION_SIZE;         // 512 KiB
constexpr uint64_t TX_RING_SIZE   = 256ULL * 1024 * 1024;           // 256 MiB

//   RX ring (offsets relative to MODULE_OFFSET):
constexpr uint64_t RX_RING_OFFSET = TX_RING_OFFSET + TX_RING_SIZE;  // 256 MiB + 512 KiB
constexpr uint64_t RX_RING_SIZE   = 256ULL * 1024 * 1024;           // 256 MiB

//   Spoke work areas (remaining space in Chamber A, ~512 MiB):
constexpr uint64_t WORK_AREA_OFFSET = RX_RING_OFFSET + RX_RING_SIZE;
constexpr uint64_t WORK_AREA_SIZE   = MODULE_SIZE - WORK_AREA_OFFSET;

// ── Chamber B — Model Offset (placed weights) ──────────────────────────────
constexpr uint64_t MODEL_OFFSET  = MODULE_OFFSET + MODULE_SIZE; // 1152 MiB
constexpr uint64_t MODEL_SIZE    = 2688ULL * 1024 * 1024;       // 2688 MiB = 2.625 GiB

//   Model sub-offsets (relative to MODEL_OFFSET):
constexpr uint64_t MODEL_QWEN_OFFSET   = 0ULL;
constexpr uint64_t MODEL_QWEN_PAGES    = 607;                    // 1,214 MiB
constexpr uint64_t MODEL_MMPROJ_OFFSET = MODEL_QWEN_PAGES * PAGE_2M;  // 1,214 MiB
constexpr uint64_t MODEL_MMPROJ_PAGES  = 635;                    // 1,270 MiB
constexpr uint64_t MODEL_NOMIC_OFFSET  = MODEL_MMPROJ_OFFSET + MODEL_MMPROJ_PAGES * PAGE_2M;
constexpr uint64_t MODEL_NOMIC_PAGES   = 70;                     // 140 MiB

// ── Chamber C — Memory Offset (dragonfly short-term memory space) ──────────
constexpr uint64_t MEMORY_OFFSET = MODEL_OFFSET + MODEL_SIZE; // 3840 MiB
constexpr uint64_t MEMORY_SIZE   = 2ULL * 1024 * 1024 * 1024; // 2 GiB

// ── Total carve ────────────────────────────────────────────────────────────
constexpr uint64_t TOTAL_POOL_SIZE = 5888ULL * 1024 * 1024;  // 5888 MiB = 5.75 GiB

// ── Spoke health bits ──────────────────────────────────────────────────────
// Each spoke sets its bit in DragonMap.spoke_health when it comes online
// and clears it when it goes offline. The DragonCache monitors these bits.
constexpr uint32_t SPOKE_IDENTITY_SERVICE = 1U << 0;
constexpr uint32_t SPOKE_VALUE_ENGINE     = 1U << 1;
constexpr uint32_t SPOKE_MEMORY_MODULE    = 1U << 2;
constexpr uint32_t SPOKE_CORTEX           = 1U << 3;
constexpr uint32_t SPOKE_VOICE            = 1U << 4;
constexpr uint32_t SPOKE_TX_RING          = 1U << 5;
constexpr uint32_t SPOKE_RX_RING          = 1U << 6;
constexpr uint32_t SPOKE_ALL              = 0x000000FFU;

// ── System status codes ─────────────────────────────────────────────────────
constexpr uint32_t STATUS_OFFLINE  = 0;
constexpr uint32_t STATUS_LIVE     = 1;
constexpr uint32_t STATUS_DEGRADED = 2;
constexpr uint32_t STATUS_BOOTING  = 3;

// ═══════════════════════════════════════════════════════════════════════════
//  DragonMap — The unified heartbeat header (one cache line, 64 bytes)
//
//  Every spoke mmaps this at offset 0 of the pool file. All fields are
//  std::atomic for lock-free reads/writes. The struct is 64-byte aligned
//  so it fits on a single cache line and is never split across lines.
//
//  Because every spoke sees the same DragonMap, every spoke is state-aware:
//  - global_clock ticks on every transition → any spoke can detect staleness
//  - system_status and spoke_health tell every spoke who is alive
//  - No servers, no HTTP, no polling — just one atomic read per turn
// ═══════════════════════════════════════════════════════════════════════════
struct alignas(64) DragonMap {
    // +0:  global monotonic clock — ticked on every spoke transition
    std::atomic<uint64_t> global_clock;

    // +8:  system status — STATUS_OFFLINE | STATUS_BOOTING | STATUS_LIVE |
    //      STATUS_DEGRADED
    std::atomic<uint32_t> system_status;

    // +12: spoke health bitmask — each spoke sets its bit when ready
    std::atomic<uint32_t> spoke_health;

    // +16: reserved — fill to 64 bytes
    uint64_t _pad[5];

    DragonMap()
        : global_clock(0)
        , system_status(STATUS_OFFLINE)
        , spoke_health(0)
        , _pad{0, 0, 0, 0, 0} {}
};
static_assert(sizeof(DragonMap) == 64,
              "DragonMap must be exactly 64 bytes (one cache line)");
static_assert(alignof(DragonMap) == 64,
              "DragonMap must be 64-byte aligned");

// ═══════════════════════════════════════════════════════════════════════════
//  Convenience: absolute carve address for each spoke's state slot
//  Usage:  mmap() the pool file at one of these offsets
//  Example: int fd = open("/mnt/huge/lina_pool", O_RDWR);
//           void* svc = mmap(nullptr, 512, PROT_READ|PROT_WRITE,
//                            MAP_SHARED, fd, ADDR_SERVICE_STATE);
// ═══════════════════════════════════════════════════════════════════════════
constexpr uint64_t ADDR_SERVICE_STATE = MODULE_OFFSET + SLOT_SERVICE_STATE;
constexpr uint64_t ADDR_VALUE_STATE   = MODULE_OFFSET + SLOT_VALUE_STATE;
constexpr uint64_t ADDR_MEMORY_STATE  = MODULE_OFFSET + SLOT_MEMORY_STATE;
constexpr uint64_t ADDR_TX_RING       = MODULE_OFFSET + TX_RING_OFFSET;
constexpr uint64_t ADDR_RX_RING       = MODULE_OFFSET + RX_RING_OFFSET;

// ═══════════════════════════════════════════════════════════════════════════
//  Inline helpers — atomic read/write on the DragonMap at a given base
// ═══════════════════════════════════════════════════════════════════════════

/// Tick the global clock and set system status to live.
inline void dragonmap_set_live(void* base) noexcept {
    auto* dm = static_cast<DragonMap*>(base);
    dm->system_status.store(STATUS_LIVE, std::memory_order_release);
    dm->global_clock.fetch_add(1, std::memory_order_acq_rel);
}

/// Register a spoke as ready (sets its bit and ticks the clock).
inline void dragonmap_spoke_ready(void* base, uint32_t spoke_bit) noexcept {
    auto* dm = static_cast<DragonMap*>(base);
    dm->spoke_health.fetch_or(spoke_bit, std::memory_order_acq_rel);
    dm->global_clock.fetch_add(1, std::memory_order_acq_rel);
}

/// Unregister a spoke (clears its bit and ticks the clock).
inline void dragonmap_spoke_offline(void* base, uint32_t spoke_bit) noexcept {
    auto* dm = static_cast<DragonMap*>(base);
    dm->spoke_health.fetch_and(~spoke_bit, std::memory_order_acq_rel);
    dm->global_clock.fetch_add(1, std::memory_order_acq_rel);
}

/// Read the current clock (monotonic, never decreases).
inline uint64_t dragonmap_clock(void* base) noexcept {
    return static_cast<DragonMap*>(base)->global_clock.load(std::memory_order_acquire);
}

/// Read the spoke health bitmask (which spokes are live).
inline uint32_t dragonmap_spokes(void* base) noexcept {
    return static_cast<DragonMap*>(base)->spoke_health.load(std::memory_order_acquire);
}

/// Read the system status.
inline uint32_t dragonmap_status(void* base) noexcept {
    return static_cast<DragonMap*>(base)->system_status.load(std::memory_order_acquire);
}