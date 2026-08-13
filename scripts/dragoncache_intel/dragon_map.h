#pragma once
#include <atomic>
#include <cstdint>

// These offsets are the "Map" for your memory-mapped RAM
constexpr uint64_t CHAMBER_A_OFFSET = 64; 
constexpr uint64_t CHAMBER_B_OFFSET = 1536ULL * 1024 * 1024; // 1.5 GB
constexpr uint64_t CHAMBER_C_OFFSET = 3584ULL * 1024 * 1024; // 3.5 GB

struct alignas(64) DragonMap {
    std::atomic<uint64_t> global_clock;
    std::atomic<uint32_t> system_status;
};