#include <sycl/sycl.hpp>
#include <iostream>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <thread>
#include <chrono>
#include "dragon_map.h" // The Contract

using namespace sycl;

constexpr uint64_t TOTAL_POOL_SIZE = 4ULL * 1024 * 1024 * 1024; // 4 GB

int main() {
    // Target the native Intel hardware environment
    queue q{default_selector_v};
    device dev = q.get_device();
    std::cout << "[Intel oneAPI Engine] Platform: " << dev.get_info<info::device::name>() << "\n";

    // Initialize physical memory block
    int shm_fd = shm_open("/intel_dragon_cache", O_CREAT | O_RDWR, 0666);
    ftruncate(shm_fd, TOTAL_POOL_SIZE);

    // Map memory
    void* base_ptr = mmap(nullptr, TOTAL_POOL_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    if (base_ptr == MAP_FAILED) {
        std::cerr << "[-] Mapping Fault.\n";
        return -1;
    }

    // Overlay structure
    DragonMap* header = reinterpret_cast<DragonMap*>(base_ptr);
    header->global_clock.store(0, std::memory_order_relaxed);
    header->system_status.store(1, std::memory_order_relaxed);

    std::cout << "[+] DragonCache active. Memory locked.\n";

    // Persistent Loop with Parent-Death Monitoring
    while (true) {
        // If parent process ID is 1, our parent Rust process has exited
        if (getppid() == 1) {
            munmap(base_ptr, TOTAL_POOL_SIZE);
            close(shm_fd);
            shm_unlink("/intel_dragon_cache");
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    return 0;
}