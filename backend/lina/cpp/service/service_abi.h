// ═══════════════════════════════════════════════════════════════════════════
//  service_abi.h — C ABI for LINA Identity Service (LINACore)
//
//  Wraps the full LINACore chat pipeline behind a flat C interface.
//  Complex return types (ChatResponse, SessionEndResponse, etc.) are
//  serialized to JSON strings for the Python ctypes consumer.
//
//  Depends on value_engine_abi.h for lina_evaluation_result_t.
// ═══════════════════════════════════════════════════════════════════════════

#ifndef LINA_SERVICE_ABI_H
#define LINA_SERVICE_ABI_H

#include <stdint.h>
#include <stdbool.h>

// Reuse the value engine evaluation result struct
#include "../value_engine/value_engine_abi.h"

// Export visibility
#if defined(_MSC_VER)
#  define LINA_SRV_API __declspec(dllexport)
#else
#  define LINA_SRV_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ── Constants ─────────────────────────────────────────────────────────────
#define LINA_SRV_SESSION_ID_MAX 64
#define LINA_SRV_USER_ID_MAX    64
#define LINA_SRV_SEASON_MAX     16
#define LINA_SRV_VERSION_STR_MAX 64

// ── Service state snapshot (mirrors CarveServiceState, 512 bytes) ─────────
typedef struct {
    uint64_t magic;
    uint64_t clock;
    uint64_t sessions_processed;
    uint64_t evaluations_performed;
    uint64_t tools_executed;
    uint64_t corrections_made;
    uint64_t seasonal_advancements;
    uint64_t total_tokens_generated;
    uint64_t reserved[56];
} lina_service_state_t;

// ── End session result (flat struct, no nested allocations) ───────────────
typedef struct {
    char     session_id[LINA_SRV_SESSION_ID_MAX];
    int      t1_formed;
    int      long_term_formed;
    int      crown_formed;
    int      moments_reflected;
    bool     alignment_maintained;
    bool     season_advanced;
    char     season_name[LINA_SRV_SEASON_MAX];
} lina_end_session_result_t;

// ── Season advancement result ──────────────────────────────────────────────
typedef struct {
    bool     advanced;
    char     season[LINA_SRV_SEASON_MAX];
    char     previous_season[LINA_SRV_SEASON_MAX];
    int      session_number;
    bool     has_session_number;
    char     reasons[1024]; // colon-separated list of reasons
} lina_season_result_t;

// ── Lifecycle ──────────────────────────────────────────────────────────────

/// Create a LINACore with in-memory stores and a mock voice provider.
/// @param season   Initial season ("spring", "summer", "fall", "winter")
/// @param user_id  Initial user to create context for
/// @returns Opaque handle, or NULL on failure. Free with lina_core_destroy().
LINA_SRV_API void* lina_core_create(const char* season, const char* user_id);

/// Destroy a LINACore handle. Passing NULL is a no-op.
LINA_SRV_API void  lina_core_destroy(void* core);

// ── Chat ───────────────────────────────────────────────────────────────────

/// Run a single chat turn through the full LINACore pipeline.
/// Returns a JSON string with the following fields:
///   - "response": the assistant's response text
///   - "session_id": the session identifier
///   - "emotional_marker": emotional marker string
///   - "foresight_context": optional foresight context (null if absent)
///   - "proposals": JSON array of tool proposals (may be empty)
///   - "evaluation": JSON object with evaluation details (aligned, score, etc.)
///
/// Caller must free the returned string with lina_core_free_string().
/// Returns NULL on failure.
LINA_SRV_API char* lina_core_chat(
    void* core,
    const char* user_id,
    const char* session_id,
    const char* message);

// ── End Session ────────────────────────────────────────────────────────────

/// End a session, processing memory formation, and populate the result.
/// Returns JSON string. Caller must free with lina_core_free_string().
LINA_SRV_API char* lina_core_end_session(
    void* core,
    const char* user_id,
    const char* session_id);

// ── Season ─────────────────────────────────────────────────────────────────

/// Advance season if ready. Returns JSON string.
/// Caller must free with lina_core_free_string().
LINA_SRV_API char* lina_core_advance_season(
    void* core,
    const char* user_id,
    int session_number);

// ── Evaluation ─────────────────────────────────────────────────────────────

/// Evaluate a response directly through the value engine.
/// @param core     Opaque handle from lina_core_create()
/// @param user_id  The user whose engine to use
/// @param response The response text to evaluate
/// @param result   Output: populated evaluation result (call init first)
LINA_SRV_API void  lina_core_evaluate(
    void* core,
    const char* user_id,
    const char* response,
    lina_evaluation_result_t* result);

// ── State ──────────────────────────────────────────────────────────────────

/// Snapshot the current service state (CarveServiceState counters).
LINA_SRV_API void  lina_core_get_state(void* core, lina_service_state_t* out);

// ── Utility ────────────────────────────────────────────────────────────────

/// Free a string returned by a lina_core_* function.
LINA_SRV_API void  lina_core_free_string(char* str);

/// Version string of the service ABI.
LINA_SRV_API const char* lina_core_version(void);

#ifdef __cplusplus
}
#endif

#endif // LINA_SERVICE_ABI_H