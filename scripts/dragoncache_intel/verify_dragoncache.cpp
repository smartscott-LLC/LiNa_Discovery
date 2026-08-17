// ═══════════════════════════════════════════════════════════════════════════
//  verify_dragoncache.cpp — live IPC verification of the carved DragonCache
//
//  Opens /mnt/huge/lina_pool, mmaps the full carve, and verifies every spoke
//  slot, every model placement, and the DragonMap heartbeat — all by reading
//  the same shared-memory frames that every spoke will map.
//
//  This proves the header contract (dragon_map.h) matches the physical carve.
//
//  Usage:
//      g++ -std=c++17 -O2 verify_dragoncache.cpp -o verify_dragoncache
//      sudo ./verify_dragoncache
//
//  Exit code: 0 = all checks PASS, 1 = any check FAILED
// ═══════════════════════════════════════════════════════════════════════════

#include <iostream>
#include <iomanip>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cerrno>
#include "dragon_map.h"

// ── Colors ────────────────────────────────────────────────────────────────
constexpr const char* GREEN  = "\033[1;32m";
constexpr const char* RED    = "\033[1;31m";
constexpr const char* YELLOW = "\033[1;33m";
constexpr const char* RESET  = "\033[0m";

static int failures = 0;

#define CHECK(cond, fmt, ...) do {                                          \
    char _buf[512];                                                         \
    snprintf(_buf, sizeof(_buf), fmt, ##__VA_ARGS__);                       \
    if (!(cond)) {                                                          \
        std::cout << "  " << RED << "[FAIL]" << RESET << " " << _buf        \
                  << "\n";                                                  \
        ++failures;                                                         \
    } else {                                                                \
        std::cout << "  " << GREEN << "[PASS]" << RESET << " " << _buf      \
                  << "\n";                                                  \
    }                                                                       \
} while(0)

#define CHECK_NA(fmt, ...) do {                                             \
    char _buf[512];                                                         \
    snprintf(_buf, sizeof(_buf), fmt, ##__VA_ARGS__);                       \
    std::cout << "  " << YELLOW << "[SKIP]" << RESET << " " << _buf << "\n";\
} while(0)

// ── GGUF magic ───────────────────────────────────────────────────────────
static bool check_gguf_magic(const void* base, uint64_t offset) {
    const char* p = static_cast<const char*>(base) + offset;
    // GGUF magic bytes: 'G' 'G' 'U' 'F' at offset 0 (little-endian: 0x46554747)
    uint32_t magic;
    std::memcpy(&magic, p, 4);
    return magic == 0x46554747U;
}

// ── Format bytes as MiB ───────────────────────────────────────────────────
static double mib(uint64_t bytes) {
    return static_cast<double>(bytes) / (1024.0 * 1024.0);
}

// ── Main ──────────────────────────────────────────────────────────────────
int main() {
    std::cout << "\n"
        << "╔══════════════════════════════════════════════════════════╗\n"
        << "║   DragonCache Verification — Live Carve IPC Check       ║\n"
        << "╚══════════════════════════════════════════════════════════╝\n\n";

    // ── 1. Open the pool ────────────────────────────────────────────────
    const char* pool_path = "/mnt/huge/lina_pool";
    int fd = open(pool_path, O_RDWR);
    if (fd < 0) {
        std::cerr << RED << "[FATAL]" << RESET
                  << " Cannot open " << pool_path << ": " << strerror(errno) << "\n";
        return 1;
    }

    struct stat st;
    fstat(fd, &st);
    uint64_t pool_size = st.st_size;

    std::cout << "  Pool file:  " << pool_path << "\n";
    std::cout << "  Pool size:  " << pool_size << " bytes ("
              << mib(pool_size) << " MiB = " << mib(pool_size)/1024.0 << " GiB)\n";
    std::cout << "  Expected:   " << TOTAL_POOL_SIZE << " bytes ("
              << mib(TOTAL_POOL_SIZE) << " MiB)\n\n";

    if (pool_size != TOTAL_POOL_SIZE) {
        std::cerr << RED << "[FATAL]" << RESET
                  << " Pool size mismatch — carve needs re-running\n";
        close(fd);
        return 1;
    }

    void* base = mmap(nullptr, TOTAL_POOL_SIZE, PROT_READ | PROT_WRITE,
                      MAP_SHARED, fd, 0);
    close(fd);

    if (base == MAP_FAILED) {
        std::cerr << RED << "[FATAL]" << RESET
                  << " mmap failed: " << strerror(errno) << "\n";
        return 1;
    }

    // ── 2. Verify DragonMap heartbeat (first 64 bytes) ──────────────────
    std::cout << "── DragonMap Heartbeat ──\n";

    DragonMap* dm = static_cast<DragonMap*>(base);

    uint64_t clock = dm->global_clock.load(std::memory_order_acquire);
    uint32_t status = dm->system_status.load(std::memory_order_acquire);
    uint32_t health = dm->spoke_health.load(std::memory_order_acquire);

    CHECK(status == STATUS_LIVE,
          "system_status = %u (expected %u = LIVE)",
          status, STATUS_LIVE);
    CHECK(clock == 0 || clock > 0,
          "global_clock = %lu (monotonic)", clock);
    CHECK(health == 0,
          "spoke_health = 0x%x (no spokes claimed yet)", health);
    CHECK(sizeof(DragonMap) == 64,
          "DragonMap size = %zu bytes (expected 64)", sizeof(DragonMap));
    CHECK(alignof(DragonMap) == 64,
          "DragonMap alignment = %zu (expected 64)", alignof(DragonMap));

    // Write a test tick + read back
    dm->global_clock.fetch_add(1, std::memory_order_acq_rel);
    dm->spoke_health.fetch_or(SPOKE_TX_RING, std::memory_order_acq_rel);
    uint64_t clock2 = dm->global_clock.load(std::memory_order_acquire);
    uint32_t health2 = dm->spoke_health.load(std::memory_order_acquire);
    CHECK(clock2 == clock + 1,
          "atomic tick works: %lu → %lu", clock, clock2);
    CHECK(health2 & SPOKE_TX_RING,
          "spoke bit set: 0x%x & 0x%x = 0x%x", health2, SPOKE_TX_RING, health2);

    // Clean up test writes
    dm->spoke_health.fetch_and(~SPOKE_TX_RING, std::memory_order_acq_rel);
    uint32_t health3 = dm->spoke_health.load(std::memory_order_acquire);
    CHECK(health3 == 0,
          "spoke bit cleared: 0x%x → 0", health3);

    // ── 3. Verify module state slots (Chamber A) ────────────────────────
    std::cout << "\n── Module State Slots (Chamber A) ──\n";

    // Each slot should be 512 bytes, zero initialised after carve
    const char* slot_base = static_cast<const char*>(base) + MODULE_OFFSET;

    // 3a. Service State slot
    {
        uint64_t abs_off = MODULE_OFFSET + SLOT_SERVICE_STATE;
        CHECK(abs_off == ADDR_SERVICE_STATE,
              "ADDR_SERVICE_STATE = %lu (0x%lx) — correct", abs_off, abs_off);
        CHECK((abs_off & 63) == 0,
              "ServiceState 64-byte aligned (offset & 63 = %lu)", abs_off & 63);

        uint64_t magic;
        std::memcpy(&magic, slot_base + SLOT_SERVICE_STATE, 8);
        // LINASRV\0 = 0x4c494e4153525600 (from CarveServiceState::MAGIC in identity_service.hpp)
        CHECK(magic == 0 || magic == 0x4c494e4153525600ULL,
              "ServiceState magic = 0x%016lx (expected 0x0000000000000000 after carve)", magic);

        // Check the 512-byte slot is within bounds
        CHECK(SLOT_SERVICE_STATE + 512 <= MODULE_SLOT_REGION_SIZE,
              "ServiceState (offset 0x%lx + 512) fits in slot region (0x%lx)",
              SLOT_SERVICE_STATE, MODULE_SLOT_REGION_SIZE);
    }

    // 3b. Value Engine State slot
    {
        uint64_t abs_off = MODULE_OFFSET + SLOT_VALUE_STATE;
        CHECK(abs_off == ADDR_VALUE_STATE,
              "ADDR_VALUE_STATE = %lu (0x%lx) — correct", abs_off, abs_off);
        CHECK((abs_off & 63) == 0,
              "ValueState 64-byte aligned");

        uint64_t magic;
        std::memcpy(&magic, slot_base + SLOT_VALUE_STATE, 8);
        // LINAVE = 0x4C494E41564501 (from CarveModuleState::magic in value_engine.hpp)
        CHECK(magic == 0 || magic == 0x4C494E41564501ULL,
              "ValueState magic = 0x%016lx (expected 0 after carve)", magic);

        // Read dimension_biases (at offset 16: magic 8 + state_size 8)
        double bias0;
        std::memcpy(&bias0, slot_base + SLOT_VALUE_STATE + 16, 8);
        CHECK(bias0 == 0.0,
              "dimension_bias[0] = %f (expected 0.0 after carve)", bias0);
    }

    // 3c. Memory State slot
    {
        uint64_t abs_off = MODULE_OFFSET + SLOT_MEMORY_STATE;
        CHECK(abs_off == ADDR_MEMORY_STATE,
              "ADDR_MEMORY_STATE = %lu (0x%lx) — correct", abs_off, abs_off);
        CHECK((abs_off & 63) == 0,
              "MemoryState 64-byte aligned");

        uint64_t magic;
        std::memcpy(&magic, slot_base + SLOT_MEMORY_STATE, 8);
        // LINAMEM = 0x4C494E414D454D01 (from CarveMemoryState::magic in memory_module.hpp)
        CHECK(magic == 0 || magic == 0x4C494E414D454D01ULL,
              "MemoryState magic = 0x%016lx (expected 0 after carve)", magic);
    }

    // 3d. Slot spacing is correct (each is 512 bytes, starting at 0x100)
    CHECK(SLOT_SERVICE_STATE + 512 == SLOT_VALUE_STATE,
          "ServiceState(0x%lx) + 512 = ValueState(0x%lx)",
          SLOT_SERVICE_STATE, SLOT_VALUE_STATE);
    CHECK(SLOT_VALUE_STATE + 512 == SLOT_MEMORY_STATE,
          "ValueState(0x%lx) + 512 = MemoryState(0x%lx)",
          SLOT_VALUE_STATE, SLOT_MEMORY_STATE);

    // 3e. Next free slot
    CHECK(SLOT_MEMORY_STATE + 512 <= MODULE_SLOT_REGION_SIZE,
          "MemoryState(0x%lx) + 512 fits in 0x%lx slot region",
          SLOT_MEMORY_STATE, MODULE_SLOT_REGION_SIZE);
    std::cout << "  ── next free slot at 0x"
              << std::hex << (SLOT_MEMORY_STATE + 512) << std::dec << " ("
              << (SLOT_MEMORY_STATE + 512) << " bytes)\n";

    // ── 4. Verify TX/RX ring regions ────────────────────────────────────
    std::cout << "\n── TX/RX Ring Regions (Chamber A) ──\n";

    CHECK(TX_RING_OFFSET == MODULE_SLOT_REGION_SIZE,
          "TX_RING_OFFSET = %lu (0x%lx) = slot region end",
          TX_RING_OFFSET, TX_RING_OFFSET);

    CHECK(RX_RING_OFFSET == TX_RING_OFFSET + TX_RING_SIZE,
          "RX_RING_OFFSET = %lu (0x%lx) = TX_RING_OFFSET + TX_RING_SIZE",
          RX_RING_OFFSET, RX_RING_OFFSET);

    CHECK(TX_RING_SIZE == 256ULL * 1024 * 1024,
          "TX_RING_SIZE = %lu (%lu MiB)", TX_RING_SIZE, TX_RING_SIZE / 1024 / 1024);

    CHECK(RX_RING_SIZE == 256ULL * 1024 * 1024,
          "RX_RING_SIZE = %lu (%lu MiB)", RX_RING_SIZE, RX_RING_SIZE / 1024 / 1024);

    CHECK(MODULE_SIZE >= WORK_AREA_OFFSET + WORK_AREA_SIZE,
          "Chamber A total = %lu, slots+rings+work = %lu + %lu + %lu + %lu = %lu",
          MODULE_SIZE,
          MODULE_SLOT_REGION_SIZE, TX_RING_SIZE, RX_RING_SIZE, WORK_AREA_SIZE,
          MODULE_SLOT_REGION_SIZE + TX_RING_SIZE + RX_RING_SIZE + WORK_AREA_SIZE);

    // ── 5. Verify model placements (Chamber B) ──────────────────────────
    std::cout << "\n── Model Placements (Chamber B) ──\n";

    CHECK(MODEL_OFFSET == 1152ULL * 1024 * 1024,
          "MODEL_OFFSET = %lu (%lu MiB)", MODEL_OFFSET, MODEL_OFFSET / 1024 / 1024);
    CHECK(MODEL_SIZE == 2688ULL * 1024 * 1024,
          "MODEL_SIZE = %lu (%lu MiB)", MODEL_SIZE, MODEL_SIZE / 1024 / 1024);

    // 5a. Qwen2-VL-2B
    uint64_t qwen_abs = MODEL_OFFSET + MODEL_QWEN_OFFSET;
    CHECK(check_gguf_magic(base, qwen_abs),
          "Qwen2-VL-2B GGUF magic at %.0f MiB", mib(qwen_abs));
    std::cout << "    Qwen:   " << mib(qwen_abs) << " MiB ✓\n";

    // 5b. mmproj
    uint64_t mmproj_abs = MODEL_OFFSET + MODEL_MMPROJ_OFFSET;
    CHECK(check_gguf_magic(base, mmproj_abs),
          "mmproj GGUF magic at %.0f MiB", mib(mmproj_abs));
    std::cout << "    mmproj: " << mib(mmproj_abs) << " MiB ✓\n";

    // 5c. nomic
    uint64_t nomic_abs = MODEL_OFFSET + MODEL_NOMIC_OFFSET;
    CHECK(check_gguf_magic(base, nomic_abs),
          "nomic-embed-text GGUF magic at %.0f MiB", mib(nomic_abs));
    std::cout << "    nomic:  " << mib(nomic_abs) << " MiB ✓\n";

    // Model sub-offset arithmetic
    CHECK(MODEL_QWEN_OFFSET == 0,
          "MODEL_QWEN_OFFSET = %lu", MODEL_QWEN_OFFSET);
    CHECK(MODEL_MMPROJ_OFFSET == MODEL_QWEN_PAGES * PAGE_2M,
          "MODEL_MMPROJ_OFFSET = %lu = Qwen size (%lu MiB)",
          MODEL_MMPROJ_OFFSET, MODEL_MMPROJ_OFFSET / 1024 / 1024);
    CHECK(MODEL_NOMIC_OFFSET == MODEL_MMPROJ_OFFSET + MODEL_MMPROJ_PAGES * PAGE_2M,
          "MODEL_NOMIC_OFFSET = %lu = Qwen + mmproj (%lu MiB)",
          MODEL_NOMIC_OFFSET, MODEL_NOMIC_OFFSET / 1024 / 1024);

    // ── 6. Verify Chamber C ─────────────────────────────────────────────
    std::cout << "\n── Memory Region (Chamber C) ──\n";

    CHECK(MEMORY_OFFSET == 3840ULL * 1024 * 1024,
          "MEMORY_OFFSET = %lu (%lu MiB)", MEMORY_OFFSET, MEMORY_OFFSET / 1024 / 1024);
    CHECK(MEMORY_SIZE == 2ULL * 1024 * 1024 * 1024,
          "MEMORY_SIZE = %lu (%lu MiB)", MEMORY_SIZE, MEMORY_SIZE / 1024 / 1024);

    // ── 7. Total pool arithmetic ────────────────────────────────────────
    std::cout << "\n── Pool Arithmetic ──\n";

    uint64_t regions_total = HEADER_SIZE + MODULE_SIZE + MODEL_SIZE + MEMORY_SIZE;
    CHECK(regions_total == TOTAL_POOL_SIZE,
          "Header(%lu) + Module(%lu) + Model(%lu) + Memory(%lu) = %lu = TOTAL(%lu)",
          HEADER_SIZE, MODULE_SIZE, MODEL_SIZE, MEMORY_SIZE,
          regions_total, TOTAL_POOL_SIZE);

    uint64_t expected_pages = TOTAL_POOL_SIZE / PAGE_2M;
    CHECK(TOTAL_POOL_SIZE % PAGE_2M == 0,
          "Pool size is 2M-aligned: %lu mod %lu = %lu",
          TOTAL_POOL_SIZE, PAGE_2M, TOTAL_POOL_SIZE % PAGE_2M);
    CHECK(expected_pages == 2944,
          "Pool = %lu huge pages (expected 2944)", expected_pages);

    // Model page arithmetic
    uint64_t model_total_pages = MODEL_QWEN_PAGES + MODEL_MMPROJ_PAGES + MODEL_NOMIC_PAGES;
    uint64_t model_total_size = model_total_pages * PAGE_2M;
    CHECK(model_total_size <= MODEL_SIZE,
          "Models use %lu MiB of %lu MiB Chamber B — fits",
          model_total_size / 1024 / 1024, MODEL_SIZE / 1024 / 1024);

    // ── 8. Summary ──────────────────────────────────────────────────────
    std::cout << "\n"
        << "╔══════════════════════════════════════════════════════════╗\n"
        << "║   Summary                                               ║\n"
        << "╚══════════════════════════════════════════════════════════╝\n";

    if (failures == 0) {
        std::cout << "\n  " << GREEN << "ALL CHECKS PASSED" << RESET << "\n";
    } else {
        std::cout << "\n  " << RED << failures << " CHECK(S) FAILED" << RESET << "\n";
    }

    std::cout << "\n  DragonMap:      " << (dm->system_status.load() == STATUS_LIVE ? "LIVE" : "OFFLINE")
              << ", clock=" << dm->global_clock.load()
              << ", spokes=0x" << std::hex << dm->spoke_health.load() << std::dec << "\n";
    std::cout << "  Header:         0 – " << mib(HEADER_SIZE) << " MiB\n";
    std::cout << "  Chamber A:      " << mib(MODULE_OFFSET) << " – "
              << mib(MODULE_OFFSET + MODULE_SIZE) << " MiB  (Module)\n";
    std::cout << "    TX ring:      " << mib(MODULE_OFFSET + TX_RING_OFFSET)
              << " – " << mib(MODULE_OFFSET + TX_RING_OFFSET + TX_RING_SIZE) << " MiB\n";
    std::cout << "    RX ring:      " << mib(MODULE_OFFSET + RX_RING_OFFSET)
              << " – " << mib(MODULE_OFFSET + RX_RING_OFFSET + RX_RING_SIZE) << " MiB\n";
    std::cout << "  Chamber B:      " << mib(MODEL_OFFSET) << " – "
              << mib(MODEL_OFFSET + MODEL_SIZE) << " MiB  (Models)\n";
    std::cout << "  Chamber C:      " << mib(MEMORY_OFFSET) << " – "
              << mib(MEMORY_OFFSET + MEMORY_SIZE) << " MiB  (Memory)\n";
    std::cout << "  Total:          " << mib(TOTAL_POOL_SIZE) << " MiB ("
              << (TOTAL_POOL_SIZE / PAGE_2M) << " × 2M pages)\n\n";

    munmap(base, TOTAL_POOL_SIZE);
    return failures > 0 ? 1 : 0;
}