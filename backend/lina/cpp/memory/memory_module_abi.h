// ═══════════════════════════════════════════════════════════════════════════
//  memory_module_abi.h — C ABI for LINA Memory Module
//
//  Flat C structs with fixed-size buffers. Designed for ctypes / dlopen.
//  Wraps MemoryModule, SweepCounts, MaintenanceCounts, ReviewCounts.
//
//  Complex return types (recall, inject_context) are serialized to JSON
//  strings for simplicity. Future versions can add richer structures.
// ═══════════════════════════════════════════════════════════════════════════

#ifndef LINA_MEMORY_MODULE_ABI_H
#define LINA_MEMORY_MODULE_ABI_H

#include <stdint.h>
#include <stdbool.h>

// Export visibility
#if defined(_MSC_VER)
#  define LINA_MEM_API __declspec(dllexport)
#else
#  define LINA_MEM_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ── Sweep directory ───────────────────────────────────────────────────────
typedef struct {
    int t1_to_t2;
    int t2_to_t3;
    int to_long_term;
    int fallout;
    int repurposed;
    int purged;
} lina_sweep_counts_t;

// ── Maintenance counts ─────────────────────────────────────────────────────
typedef struct {
    int adjusted;
    int to_subconscious;
    int to_legacy;
    int decayed;
    int forgotten;
} lina_maintenance_counts_t;

// ── Legacy review counts ───────────────────────────────────────────────────
typedef struct {
    int reviewed;
    int demoted;
} lina_review_counts_t;

// ── Formation counts ───────────────────────────────────────────────────────
typedef struct {
    int t1;
    int long_term;
    int crown;
} lina_formation_counts_t;

// ── Carve memory state snapshot (mirrors CarveMemoryState) ────────────────
typedef struct {
    uint64_t magic;
    uint64_t state_size;
    uint64_t total_items_formed;
    uint64_t total_triggers;
    uint64_t total_sweeps;
    uint64_t total_maintenance_runs;
    uint64_t total_recalls;
    uint64_t t1_current;
    uint64_t t2_current;
    uint64_t t3_current;
    uint64_t long_term_current;
    uint64_t legacy_current;
    uint64_t last_sweep_promoted;
    uint64_t last_sweep_purged;
    uint64_t last_sweep_fallout;
    char     current_season[16];
} lina_memory_state_t;

// ── Lifecycle ──────────────────────────────────────────────────────────────

/// Create a memory module.
/// @param engine  Opaque handle from lina_engine_create() — the memory module
///                borrows a shared_ptr reference to keep the engine alive.
/// @returns Opaque handle, or NULL on failure. Free with lina_memory_destroy().
LINA_MEM_API void* lina_memory_create(void* engine);

/// Destroy a memory module handle. Passing NULL is a no-op.
LINA_MEM_API void  lina_memory_destroy(void* memory);

// ── Formation ──────────────────────────────────────────────────────────────

/// Form items from a JSON array of narrative strings.
/// @param memory    Opaque handle from lina_memory_create()
/// @param user_id   The user these items belong to
/// @param narratives_json  JSON array of strings, e.g. '["mem1","mem2"]'
/// @param source    Formation source tag
/// @param season    Optional season override (nullptr for defer to engine)
/// @param trigger   If true, items bypass tier routing and go to long-term
/// @returns Populated lina_formation_counts_t
LINA_MEM_API lina_formation_counts_t lina_memory_form_items(
    void* memory,
    const char* user_id,
    const char* narratives_json,
    const char* source,
    const char* season,
    bool trigger);

/// Ingest a single trigger narrative.
/// @returns A JSON string describing the ingested item, or empty string
///          on failure. Caller must free with lina_memory_free_string().
LINA_MEM_API char* lina_memory_ingest_trigger(
    void* memory,
    const char* user_id,
    const char* narrative,
    const char* kind,
    const char* season);

// ── Sweep & Maintenance ────────────────────────────────────────────────────

/// Run the 48-hour tier promotion sweep.
LINA_MEM_API lina_sweep_counts_t lina_memory_run_sweep(void* memory);

/// Run monthly maintenance re-evaluation.
LINA_MEM_API lina_maintenance_counts_t lina_memory_run_maintenance(void* memory);

/// Run yearly legacy review.
LINA_MEM_API lina_review_counts_t lina_memory_run_legacy_review(void* memory);

// ── Recall & Context ───────────────────────────────────────────────────────

/// Recall top-N memories for a user. Returns JSON array of MemoryItemRow.
/// Recall automatically re-stokes returned items (increments reference_count,
/// updates last_referenced_at) so Lina's act of looking reinforces the memory.
/// Caller must free with lina_memory_free_string().
LINA_MEM_API char* lina_memory_recall(
    void* memory,
    const char* user_id,
    const char* query,
    const char* hemisphere,
    int limit,
    bool include_subconscious);

/// Inject context for a user query. Returns JSON object with "personal" and
/// "wisdom" arrays. Caller must free with lina_memory_free_string().
LINA_MEM_API char* lina_memory_inject_context(
    void* memory,
    const char* user_id,
    const char* query,
    int personal_limit,
    int wisdom_limit);

/// Update a memory item after Lina has reviewed it.
/// @param memory    Opaque handle from lina_memory_create()
/// @param item_id   The item to update
/// @param update_json  JSON object with fields to update, e.g.:
///        {"importance_score": 8.5, "understanding": "new insight",
///         "concept_name": "key-idea", "floor": 5.0, "protected_flag": true}
///        Only provided fields are changed. reference_count is auto-incremented
///        and last_referenced_at is set to now.
/// @returns true if the item was found and updated
LINA_MEM_API bool lina_memory_update_item(
    void* memory,
    const char* item_id,
    const char* update_json);

// ── State ──────────────────────────────────────────────────────────────────

/// Snapshot the current carve state into the provided struct.
LINA_MEM_API void lina_memory_get_state(void* memory, lina_memory_state_t* out);

/// Reset the carve state counters to zero (does NOT clear stored items).
LINA_MEM_API void lina_memory_reset_state(void* memory);

// ── Utility ────────────────────────────────────────────────────────────────

/// Free a string returned by a lina_memory_* function.
LINA_MEM_API void lina_memory_free_string(char* str);

/// Version string.
LINA_MEM_API const char* lina_memory_version(void);

#ifdef __cplusplus
}
#endif

#endif // LINA_MEMORY_MODULE_ABI_H