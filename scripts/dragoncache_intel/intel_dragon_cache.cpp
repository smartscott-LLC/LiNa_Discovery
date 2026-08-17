#include <sycl/sycl.hpp>
#include <iostream>
#include <fstream>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <thread>
#include <chrono>
#include <cerrno>
#include "dragon_map.h"

using namespace sycl;

// ── Model disk paths ──────────────────────────────────────────────────────
constexpr const char* MODEL_QWEN_PATH   = "/home/server/models/lina-local/Qwen2-VL-2B-Instruct-Q6_K.gguf";
constexpr const char* MODEL_MMPROJ_PATH = "/home/server/models/lina-local/mmproj-Qwen2-VL-2B-Instruct-f16.gguf";
constexpr const char* MODEL_NOMIC_PATH  = "/home/server/models/lina-local/nomic-embed-text-v1.5.Q8_0.gguf";
constexpr const char* POOL_FILE         = "/mnt/huge/lina_pool";
constexpr const char* HUGETLBFS_MOUNT   = "/mnt/huge";
constexpr const char* ADDRESS_MAP_FILE  = "/home/server/LiNa_Discovery/.dragoncache_map";

// ── Helper: copy a file onto the carve at pool_base + offset ──────────────
static bool place_on_carve(int pool_fd, void* pool_base, uint64_t offset,
                           const char* src_path, const char* label) {
    int src_fd = open(src_path, O_RDONLY);
    if (src_fd < 0) {
        std::cerr << "[-] " << label << " — cannot open " << src_path << "\n";
        return false;
    }
    struct stat st;
    fstat(src_fd, &st);
    uint64_t file_size = st.st_size;

    uint64_t pages = (file_size + PAGE_2M - 1) / PAGE_2M;
    uint64_t placed_size = pages * PAGE_2M;

    char* dst = static_cast<char*>(pool_base) + offset;
    for (uint64_t o = 0; o < placed_size; o += PAGE_2M) {
        dst[o] = 0;
    }

    constexpr size_t CHUNK = 2ULL * 1024 * 1024;
    char* buf = new char[CHUNK];
    uint64_t written = 0;
    while (written < file_size) {
        size_t to_read = std::min(CHUNK, file_size - written);
        ssize_t n = read(src_fd, buf, to_read);
        if (n <= 0) break;
        std::memcpy(dst + written, buf, n);
        written += n;
    }
    delete[] buf;
    close(src_fd);

    msync(dst, placed_size, MS_SYNC);
    std::cout << "[+] " << label << " placed at offset "
              << (offset / 1024 / 1024) << " MiB ("
              << placed_size / 1e6 << " MB, " << pages << " pages)\n";
    return true;
}

// ── Helper: zero-init a slot on the carve and msync ────────────────────────
static void init_slot(void* pool_base, uint64_t abs_offset, uint64_t size,
                       const char* label) {
    char* slot = static_cast<char*>(pool_base) + abs_offset;
    std::memset(slot, 0, size);
    msync(slot, size, MS_SYNC);
    std::cout << "[+] " << label << " slot zeroed at offset "
              << (abs_offset / 1024) << " KiB (" << size << " bytes)\n";
}

int main() {
    // ── 1. Detect Intel hardware via SYCL ────────────────────────────────
    queue q{default_selector_v};
    device dev = q.get_device();
    std::cout << "[Intel oneAPI Engine] Platform: " << dev.get_info<info::device::name>() << "\n";

    // ── 2. Verify hugetlbfs mount ────────────────────────────────────────
    struct stat mount_stat;
    if (stat(HUGETLBFS_MOUNT, &mount_stat) != 0 || !S_ISDIR(mount_stat.st_mode)) {
        std::cerr << "[-] hugetlbfs mount point " << HUGETLBFS_MOUNT
                  << " not found — mount -t hugetlbfs -o pagesize=2M none "
                  << HUGETLBFS_MOUNT << "\n";
        return -1;
    }
    std::cout << "[+] hugetlbfs at " << HUGETLBFS_MOUNT << "\n";

    // ── 3. Create / truncate the pool file ───────────────────────────────
    int pool_fd = open(POOL_FILE, O_CREAT | O_RDWR, 0600);
    if (pool_fd < 0) {
        std::cerr << "[-] cannot open " << POOL_FILE << ": " << strerror(errno) << "\n";
        return -1;
    }
    ftruncate(pool_fd, TOTAL_POOL_SIZE);

    // ── 4. Map the entire pool ───────────────────────────────────────────
    void* base_ptr = mmap(nullptr, TOTAL_POOL_SIZE, PROT_READ | PROT_WRITE,
                          MAP_SHARED, pool_fd, 0);
    if (base_ptr == MAP_FAILED) {
        std::cerr << "[-] mmap " << TOTAL_POOL_SIZE / 1e9
                  << " GiB: " << strerror(errno) << "\n";
        close(pool_fd);
        return -1;
    }
    std::cout << "[+] Pool: " << (TOTAL_POOL_SIZE / 1024 / 1024)
              << " MiB (" << TOTAL_POOL_SIZE / 1e9 << " GiB) at " << POOL_FILE << "\n";

    // ── 5. Write the DragonMap header ────────────────────────────────────
    DragonMap* header = static_cast<DragonMap*>(base_ptr);
    header->global_clock.store(0, std::memory_order_relaxed);
    header->system_status.store(STATUS_BOOTING, std::memory_order_relaxed);
    header->spoke_health.store(0, std::memory_order_relaxed);
    msync(base_ptr, sizeof(DragonMap), MS_SYNC);
    std::cout << "[+] DragonMap: clock=0 status=booting spokes=0\n";

    // ── 6. Touch all huge pages to wire them resident ────────────────────
    volatile char* touch = static_cast<char*>(base_ptr);
    for (uint64_t off = 0; off < TOTAL_POOL_SIZE; off += PAGE_2M) {
        touch[off] = 0;
    }
    std::cout << "[+] All " << (TOTAL_POOL_SIZE / PAGE_2M) << " pages resident\n";

    // ── 7. Initialize module state slots (Chamber A) ────────────────────
    std::cout << "\n── Initializing module state slots (Chamber A at "
              << (MODULE_OFFSET / 1024 / 1024) << " MiB) ──\n";

    // 7a. Service state slot (CarveServiceState, 512 bytes)
    init_slot(base_ptr, ADDR_SERVICE_STATE, 512,
              "ServiceState");

    // 7b. Value engine state slot (CarveModuleState, 512 bytes)
    init_slot(base_ptr, ADDR_VALUE_STATE, 512,
              "ValueEngine");

    // 7c. Memory module state slot (CarveMemoryState, 512 bytes)
    init_slot(base_ptr, ADDR_MEMORY_STATE, 512,
              "MemoryModule");

    // 7d. TX ring region (zero the first page as sentinel)
    init_slot(base_ptr, ADDR_TX_RING, PAGE_2M,
              "TX-Ring (first 2 MiB)");

    // 7e. RX ring region (zero the first page as sentinel)
    init_slot(base_ptr, ADDR_RX_RING, PAGE_2M,
              "RX-Ring (first 2 MiB)");

    // ── 8. Place models on the carve (Chamber B) ─────────────────────────
    std::cout << "\n── Placing models (Chamber B at "
              << (MODEL_OFFSET / 1024 / 1024) << " MiB) ──\n";
    place_on_carve(pool_fd, base_ptr, MODEL_OFFSET + MODEL_QWEN_OFFSET,
                   MODEL_QWEN_PATH, "Qwen2-VL-2B");
    place_on_carve(pool_fd, base_ptr, MODEL_OFFSET + MODEL_MMPROJ_OFFSET,
                   MODEL_MMPROJ_PATH, "mmproj");
    place_on_carve(pool_fd, base_ptr, MODEL_OFFSET + MODEL_NOMIC_OFFSET,
                   MODEL_NOMIC_PATH, "nomic-embed-text");

    // ── 9. Mark header as live ───────────────────────────────────────────
    header->system_status.store(STATUS_LIVE, std::memory_order_release);
    header->global_clock.fetch_add(1, std::memory_order_acq_rel);
    msync(base_ptr, sizeof(DragonMap), MS_SYNC);
    std::cout << "[+] DragonMap: clock=" << header->global_clock.load()
              << " status=live\n";

    // ── 10. Output the address map ───────────────────────────────────────
    auto mb = [](uint64_t b) { return b / 1024 / 1024; };
    auto kb = [](uint64_t b) { return b / 1024; };

    std::cout << "\n── DragonCache Address Map ("
              << mb(TOTAL_POOL_SIZE) << " MiB total) ──\n";
    std::cout << "  Header:      " << mb(HEADER_OFFSET) << " MiB  (" << mb(HEADER_SIZE) << " MiB)\n";
    std::cout << "    DragonMap: " << mb(HEADER_OFFSET) << " MiB  (64 B)\n";
    std::cout << "  Chamber A:   " << mb(MODULE_OFFSET) << " MiB  (" << mb(MODULE_SIZE) << " MiB)  Module Offset\n";
    std::cout << "    Slots:     " << kb(MODULE_SLOT_REGION_OFFSET) << " KiB  (" << kb(MODULE_SLOT_REGION_SIZE) << " KiB)\n";
    std::cout << "      Service: " << kb(SLOT_SERVICE_STATE) << " B  (512 B)  CarveServiceState\n";
    std::cout << "      Value:   " << kb(SLOT_VALUE_STATE) << " B  (512 B)  CarveModuleState\n";
    std::cout << "      Memory:  " << kb(SLOT_MEMORY_STATE) << " B  (512 B)  CarveMemoryState\n";
    std::cout << "    TX-Ring:   " << mb(TX_RING_OFFSET) << " MiB  (" << mb(TX_RING_SIZE) << " MiB)\n";
    std::cout << "    RX-Ring:   " << mb(RX_RING_OFFSET) << " MiB  (" << mb(RX_RING_SIZE) << " MiB)\n";
    std::cout << "    WorkArea:  " << mb(WORK_AREA_OFFSET) << " MiB  (" << mb(WORK_AREA_SIZE) << " MiB)\n";
    std::cout << "  Chamber B:   " << mb(MODEL_OFFSET) << " MiB  (" << mb(MODEL_SIZE) << " MiB)  Model Offset\n";
    std::cout << "    Qwen:      " << mb(MODEL_OFFSET + MODEL_QWEN_OFFSET) << " MiB  (" << (MODEL_QWEN_PAGES * 2) << " MiB)\n";
    std::cout << "    mmproj:    " << mb(MODEL_OFFSET + MODEL_MMPROJ_OFFSET) << " MiB  (" << (MODEL_MMPROJ_PAGES * 2) << " MiB)\n";
    std::cout << "    nomic:     " << mb(MODEL_OFFSET + MODEL_NOMIC_OFFSET) << " MiB  (" << (MODEL_NOMIC_PAGES * 2) << " MiB)\n";
    std::cout << "  Chamber C:   " << mb(MEMORY_OFFSET) << " MiB  (" << mb(MEMORY_SIZE) << " MiB)  Memory Offset\n";

    // ── 11. Write to file for .env sourcing ──────────────────────────────
    std::ofstream mf(ADDRESS_MAP_FILE);
    mf << "# DragonCache Address Map\n";
    mf << "# Generated by intel_dragon_cache.cpp on carve\n";
    mf << "# Total pool: " << mb(TOTAL_POOL_SIZE) << " MiB (" << (TOTAL_POOL_SIZE / PAGE_2M) << " huge pages)\n";
    mf << "\n";
    mf << "DRAGONCACHE_POOL_SIZE=" << TOTAL_POOL_SIZE << "\n";
    mf << "DRAGONCACHE_POOL_FILE=" << POOL_FILE << "\n";
    mf << "\n";
    mf << "# Header region (0 - 128 MiB)\n";
    mf << "DRAGONCACHE_HEADER_OFFSET=" << HEADER_OFFSET << "\n";
    mf << "DRAGONCACHE_HEADER_SIZE=" << HEADER_SIZE << "\n";
    mf << "\n";
    mf << "# Chamber A — Module Offset (128 MiB - 1152 MiB)\n";
    mf << "DRAGONCACHE_MODULE_OFFSET=" << MODULE_OFFSET << "\n";
    mf << "DRAGONCACHE_MODULE_SIZE=" << MODULE_SIZE << "\n";
    mf << "DRAGONCACHE_MODULE_SLOT_REGION_OFFSET=" << (MODULE_OFFSET + MODULE_SLOT_REGION_OFFSET) << "\n";
    mf << "DRAGONCACHE_MODULE_SLOT_REGION_SIZE=" << MODULE_SLOT_REGION_SIZE << "\n";
    mf << "DRAGONCACHE_SLOT_SERVICE_STATE=" << ADDR_SERVICE_STATE << "\n";
    mf << "DRAGONCACHE_SLOT_VALUE_STATE=" << ADDR_VALUE_STATE << "\n";
    mf << "DRAGONCACHE_SLOT_MEMORY_STATE=" << ADDR_MEMORY_STATE << "\n";
    mf << "DRAGONCACHE_TX_RING_OFFSET=" << ADDR_TX_RING << "\n";
    mf << "DRAGONCACHE_TX_RING_SIZE=" << TX_RING_SIZE << "\n";
    mf << "DRAGONCACHE_RX_RING_OFFSET=" << ADDR_RX_RING << "\n";
    mf << "DRAGONCACHE_RX_RING_SIZE=" << RX_RING_SIZE << "\n";
    mf << "DRAGONCACHE_WORK_AREA_OFFSET=" << (MODULE_OFFSET + WORK_AREA_OFFSET) << "\n";
    mf << "DRAGONCACHE_WORK_AREA_SIZE=" << WORK_AREA_SIZE << "\n";
    mf << "\n";
    mf << "# Chamber B — Model Offset (1152 MiB - 3840 MiB)\n";
    mf << "DRAGONCACHE_MODEL_OFFSET=" << MODEL_OFFSET << "\n";
    mf << "DRAGONCACHE_MODEL_SIZE=" << MODEL_SIZE << "\n";
    mf << "DRAGONCACHE_MODEL_QWEN_OFFSET=" << (MODEL_OFFSET + MODEL_QWEN_OFFSET) << "\n";
    mf << "DRAGONCACHE_MODEL_QWEN_PAGES=" << MODEL_QWEN_PAGES << "\n";
    mf << "DRAGONCACHE_MODEL_MMPROJ_OFFSET=" << (MODEL_OFFSET + MODEL_MMPROJ_OFFSET) << "\n";
    mf << "DRAGONCACHE_MODEL_MMPROJ_PAGES=" << MODEL_MMPROJ_PAGES << "\n";
    mf << "DRAGONCACHE_MODEL_NOMIC_OFFSET=" << (MODEL_OFFSET + MODEL_NOMIC_OFFSET) << "\n";
    mf << "DRAGONCACHE_MODEL_NOMIC_PAGES=" << MODEL_NOMIC_PAGES << "\n";
    mf << "\n";
    mf << "# Chamber C — Memory Offset (3840 MiB - 5888 MiB)\n";
    mf << "DRAGONCACHE_MEMORY_OFFSET=" << MEMORY_OFFSET << "\n";
    mf << "DRAGONCACHE_MEMORY_SIZE=" << MEMORY_SIZE << "\n";
    mf << "\n";
    mf << "# Spoke health bitmask values (for use in scripts)\n";
    mf << "SPOKE_IDENTITY_SERVICE=1\n";
    mf << "SPOKE_VALUE_ENGINE=2\n";
    mf << "SPOKE_MEMORY_MODULE=4\n";
    mf << "SPOKE_CORTEX=8\n";
    mf << "SPOKE_VOICE=16\n";
    mf << "SPOKE_TX_RING=32\n";
    mf << "SPOKE_RX_RING=64\n";
    mf.close();
    std::cout << "\n[+] Address map written to " << ADDRESS_MAP_FILE << "\n";

    // ── 12. mlock ────────────────────────────────────────────────────────
    if (mlock(base_ptr, TOTAL_POOL_SIZE) == 0)
        std::cout << "[+] Pool pinned — never swapped\n";
    else
        std::cout << "[!] mlock: " << strerror(errno) << " (expected if not root)\n";

    std::cout << "\n[+] DragonCache active — "
              << (TOTAL_POOL_SIZE / 1024 / 1024) << " MiB live\n"
              << "    Header:   " << mb(HEADER_OFFSET) << " - " << mb(HEADER_SIZE + HEADER_OFFSET) << " MiB\n"
              << "    Chamber A: " << mb(MODULE_OFFSET) << " - " << mb(MODULE_OFFSET + MODULE_SIZE) << " MiB\n"
              << "    Chamber B: " << mb(MODEL_OFFSET) << " - " << mb(MODEL_OFFSET + MODEL_SIZE) << " MiB\n"
              << "    Chamber C: " << mb(MEMORY_OFFSET) << " - " << mb(MEMORY_OFFSET + MEMORY_SIZE) << " MiB\n";

    // ── 13. Keep-alive loop (exit when parent dies) ──────────────────────
    while (true) {
        if (getppid() == 1) {
            header->system_status.store(STATUS_OFFLINE, std::memory_order_release);
            header->spoke_health.store(0, std::memory_order_release);
            msync(base_ptr, sizeof(DragonMap), MS_SYNC);
            munmap(base_ptr, TOTAL_POOL_SIZE);
            close(pool_fd);
            std::cout << "[+] DragonCache released.\n";
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    return 0;
}