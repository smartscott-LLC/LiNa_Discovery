// ═══════════════════════════════════════════════════════════════════════════
//  value_engine_abi.cpp — C ABI implementation for LINA Value Engine
//
//  Wraps the C++ ValueEngine class behind flat C structs. No std::string,
//  no std::vector, no exceptions cross the ABI boundary.
// ═══════════════════════════════════════════════════════════════════════════

#include "value_engine_abi.h"
#include "value_engine.hpp"

#include <cstring>
#include <new>
#include <cstdio>

// ── Lifecycle ──────────────────────────────────────────────────────────────

void* lina_engine_create(const char* season) {
    if (!season) season = "spring";

    auto constraints = lina::value_engine::PolytopeConstraints::from_season(season);
    auto* engine = new (std::nothrow) lina::value_engine::ValueEngine(constraints, season);
    return static_cast<void*>(engine);
}

void lina_engine_destroy(void* engine) {
    if (!engine) return;
    delete static_cast<lina::value_engine::ValueEngine*>(engine);
}

// ── Evaluation ─────────────────────────────────────────────────────────────

void lina_evaluate(void* engine, const char* response,
                   lina_evaluation_result_t* result) {
    if (!engine || !response || !result) return;
    lina_evaluation_result_init(result);

    auto* ve = static_cast<lina::value_engine::ValueEngine*>(engine);
    auto eval = ve->evaluate(response);

    result->is_aligned = eval.is_aligned;
    result->alignment_score = eval.alignment_score;

    for (int i = 0; i < LINA_DIMENSION_COUNT; ++i)
        result->decision_vector[i] = eval.decision_vector[i];

    result->violation_count = static_cast<int>(eval.violations.size());
    if (result->violation_count > LINA_MAX_VIOLATIONS)
        result->violation_count = LINA_MAX_VIOLATIONS;

    for (int i = 0; i < result->violation_count; ++i) {
        result->violation_dimensions[i] = eval.violations[i].dimension;
        std::snprintf(result->violation_names[i], LINA_VIOLATION_NAME_MAX,
                     "%s", eval.violations[i].name.c_str());
        result->violation_values[i] = eval.violations[i].value;
        result->violation_bounds[i] = eval.violations[i].bound;
        std::snprintf(result->violation_types[i], LINA_VIOLATION_TYPE_MAX,
                     "%s", eval.violations[i].type.c_str());
        result->violation_severities[i] = eval.violations[i].severity;
    }

    result->was_corrected = eval.was_corrected;
    for (int i = 0; i < LINA_DIMENSION_COUNT; ++i)
        result->correction_vector[i] = eval.correction_vector[i];
    result->correction_magnitude = eval.correction_magnitude;

    result->wisdom_filter_applied = eval.wisdom_filter_applied;
    result->overconfidence_detected = eval.overconfidence_detected;
    result->humility_added = eval.humility_added;
    result->validation_suggested = eval.validation_suggested;

    switch (eval.zone) {
        case lina::value_engine::Zone::Aligned:
            std::snprintf(result->zone, LINA_ZONE_MAX, "Aligned"); break;
        case lina::value_engine::Zone::AcceptableVariance:
            std::snprintf(result->zone, LINA_ZONE_MAX, "AcceptableVariance"); break;
        case lina::value_engine::Zone::Violation:
            std::snprintf(result->zone, LINA_ZONE_MAX, "Violation"); break;
    }
    result->boundary_distance = eval.boundary_distance;
    result->variance_margin_used = eval.variance_margin_used;
    std::snprintf(result->season, LINA_SEASON_MAX, "%s", eval.season.c_str());
}

void lina_encode(void* engine, const char* response,
                 double vector[LINA_DIMENSION_COUNT]) {
    if (!engine || !response || !vector) return;
    auto* ve = static_cast<lina::value_engine::ValueEngine*>(engine);
    auto encoded = ve->encoder().encode(response);
    for (int i = 0; i < LINA_DIMENSION_COUNT; ++i)
        vector[i] = encoded[i];
}

void lina_get_constraints(void* engine, lina_constraints_t* out) {
    if (!engine || !out) return;
    std::memset(out, 0, sizeof(*out));

    auto* ve = static_cast<lina::value_engine::ValueEngine*>(engine);
    auto& c = ve->constraints();

    out->harmony_min       = c.harmony_min.get_d();
    out->dominance_max     = c.dominance_max.get_d();
    out->order_min         = c.order_min.get_d();
    out->chaos_max         = c.chaos_max.get_d();
    out->integrity_min     = c.integrity_min.get_d();
    out->deception_max     = c.deception_max.get_d();
    out->flourishing_min   = c.flourishing_min.get_d();
    out->decline_max       = c.decline_max.get_d();
    out->relationships_min = c.relationships_min.get_d();
    out->isolation_max     = c.isolation_max.get_d();
    out->boundaries_min    = c.boundaries_min.get_d();
    out->intrusion_max     = c.intrusion_max.get_d();
    out->grace_min         = c.grace_min.get_d();
    out->rigidity_max      = c.rigidity_max.get_d();
    std::snprintf(out->season, LINA_SEASON_MAX, "%s", c.season.c_str());
}

void lina_get_season(void* engine, char* out, int max_len) {
    if (!engine || !out || max_len <= 0) return;
    auto* ve = static_cast<lina::value_engine::ValueEngine*>(engine);
    std::snprintf(out, max_len, "%s", ve->constraints().season.c_str());
}

// ── Utility ────────────────────────────────────────────────────────────────

const char* lina_version(void) {
    return "0.1.0";
}

void lina_evaluation_result_init(lina_evaluation_result_t* result) {
    if (!result) return;
    std::memset(result, 0, sizeof(*result));
    std::snprintf(result->season, LINA_SEASON_MAX, "spring");
    std::snprintf(result->zone, LINA_ZONE_MAX, "Aligned");
}