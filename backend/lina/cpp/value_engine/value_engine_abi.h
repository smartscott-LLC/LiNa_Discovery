// ═══════════════════════════════════════════════════════════════════════════
//  value_engine_abi.h — C ABI for LINA Value Engine
//
//  Flat C structs, no stdlib crossings, fixed-size string buffers.
//  Designed to be loaded via ctypes, dlopen, or linked directly.
//  Thread-safe for distinct engine handles.
//
//  This ABI exposes ONLY the polytope evaluation — the core ethical geometry.
//  Memory scoring and season advancement are in the memory/service ABIs.
// ═══════════════════════════════════════════════════════════════════════════

#ifndef LINA_VALUE_ENGINE_ABI_H
#define LINA_VALUE_ENGINE_ABI_H

#include <stdint.h>
#include <stdbool.h>

// Export visibility for shared library builds
#if defined(_MSC_VER)
#  define LINA_API __declspec(dllexport)
#else
#  define LINA_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ── Constants ─────────────────────────────────────────────────────────────
#define LINA_DIMENSION_COUNT 14
#define LINA_SEASON_MAX 16
#define LINA_ZONE_MAX 24
#define LINA_MAX_VIOLATIONS 3
#define LINA_VIOLATION_NAME_MAX 32
#define LINA_VIOLATION_TYPE_MAX 16

// ── Evaluation result — flat struct, no pointers, ABI-safe ────────────────
typedef struct {
    bool     is_aligned;
    double   alignment_score;
    double   decision_vector[LINA_DIMENSION_COUNT];

    int      violation_count;
    int      violation_dimensions[LINA_MAX_VIOLATIONS];
    char     violation_names[LINA_MAX_VIOLATIONS][LINA_VIOLATION_NAME_MAX];
    double   violation_values[LINA_MAX_VIOLATIONS];
    double   violation_bounds[LINA_MAX_VIOLATIONS];
    char     violation_types[LINA_MAX_VIOLATIONS][LINA_VIOLATION_TYPE_MAX];
    double   violation_severities[LINA_MAX_VIOLATIONS];

    bool     was_corrected;
    double   correction_vector[LINA_DIMENSION_COUNT];
    double   correction_magnitude;

    bool     wisdom_filter_applied;
    bool     overconfidence_detected;
    bool     humility_added;
    bool     validation_suggested;

    char     zone[LINA_ZONE_MAX];
    double   boundary_distance;
    double   variance_margin_used;

    char     season[LINA_SEASON_MAX];
} lina_evaluation_result_t;

// ── Polytope constraints — 14 dimension bounds ───────────────────────────
typedef struct {
    double harmony_min;
    double dominance_max;
    double order_min;
    double chaos_max;
    double integrity_min;
    double deception_max;
    double flourishing_min;
    double decline_max;
    double relationships_min;
    double isolation_max;
    double boundaries_min;
    double intrusion_max;
    double grace_min;
    double rigidity_max;
    char   season[LINA_SEASON_MAX];
} lina_constraints_t;

// ── Lifecycle ────────────────────────────────────────────────────────────

/// Create a value engine for the given season.
/// Season must be one of: "spring", "summer", "fall", "winter".
/// Returns opaque handle, or NULL on failure. Free with lina_engine_destroy().
LINA_API void* lina_engine_create(const char* season);

/// Destroy a value engine handle. Passing NULL is a no-op.
LINA_API void  lina_engine_destroy(void* engine);

// ── Evaluation ──────────────────────────────────────────────────────────

/// Evaluate a response text against the polytope.
/// @param engine   Opaque handle from lina_engine_create()
/// @param response The response text to evaluate (null-terminated UTF-8)
/// @param result   Output: populated evaluation result (call init first)
LINA_API void  lina_evaluate(void* engine, const char* response,
                    lina_evaluation_result_t* result);

/// Encode a response into a 14-dimension decision vector.
LINA_API void  lina_encode(void* engine, const char* response,
                  double vector[LINA_DIMENSION_COUNT]);

/// Get current polytope constraints.
LINA_API void  lina_get_constraints(void* engine, lina_constraints_t* out);

/// Get the current season string.
LINA_API void  lina_get_season(void* engine, char* out, int max_len);

// ── Utility ──────────────────────────────────────────────────────────────

/// Version string of the value engine ABI.
LINA_API const char* lina_version(void);

/// Zero-initialize an evaluation result.
LINA_API void  lina_evaluation_result_init(lina_evaluation_result_t* result);

#ifdef __cplusplus
}
#endif

#endif // LINA_VALUE_ENGINE_ABI_H