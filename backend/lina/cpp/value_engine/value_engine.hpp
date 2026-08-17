#ifndef LINA_VALUE_ENGINE_HPP
#define LINA_VALUE_ENGINE_HPP

/**
 * value_engine.hpp — LINA's Ethical Polytope and Wisdom Filter
 *
 * Language Intuitive Neural Architecture
 * "Safe by design. Not safe by limitation."
 *
 * C++ port of the Python Value Engine. All ethical math is exact rational
 * arithmetic (GMP mpq_class). No float approximations inside the polytope.
 *
 * The 14 Dimensions (7 Plumb Line Principles x 2):
 *    0: harmony          1: dominance
 *    2: order            3: chaos
 *    4: integrity        5: deception
 *    6: flourishing      7: decline
 *    8: relationships    9: isolation
 *   10: boundaries      11: intrusion
 *   12: grace           13: rigidity
 */

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <regex>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <gmpxx.h>

namespace lina::value_engine {

// =============================================================================
// CONSTANTS
// =============================================================================

inline constexpr int DIMENSION_COUNT = 14;

inline constexpr std::array<const char*, DIMENSION_COUNT> DIMENSION_NAMES = {{
    "harmony", "dominance",
    "order", "chaos",
    "integrity", "deception",
    "flourishing", "decline",
    "relationships", "isolation",
    "boundaries", "intrusion",
    "grace", "rigidity",
}};

// Principle pairs as (positive_idx, negative_idx, name)
struct PlumbLine {
    int pos_idx;
    int neg_idx;
    const char* name;
};

inline constexpr std::array<PlumbLine, 7> PLUMB_LINE_PRINCIPLES = {{
    {0,  1,  "Harmony / Dominance"},
    {2,  3,  "Order / Chaos"},
    {4,  5,  "Integrity / Deception"},
    {6,  7,  "Flourishing / Decline"},
    {8,  9,  "Relationships / Isolation"},
    {10, 11, "Boundaries / Intrusion"},
    {12, 13, "Grace / Rigidity"},
}};

// LINA's default polytope center — where she naturally dwells
inline constexpr std::array<double, DIMENSION_COUNT> DEFAULT_CENTER = {{
    0.65, 0.25,  // harmony / dominance
    0.70, 0.15,  // order / chaos
    0.80, 0.10,  // integrity / deception
    0.70, 0.15,  // flourishing / decline
    0.75, 0.20,  // relationships / isolation
    0.75, 0.15,  // boundaries / intrusion
    0.65, 0.25,  // grace / rigidity
}};

// How far a saturated signal can move a dimension away from LINA's baseline
inline constexpr double SIGNAL_DEVIATION = 0.35;

// =============================================================================
// SEASONAL DEFAULTS — exact rationals
// =============================================================================

struct SeasonalBounds {
    mpq_class harmony_min, dominance_max;
    mpq_class order_min, chaos_max;
    mpq_class integrity_min, deception_max;
    mpq_class flourishing_min, decline_max;
    mpq_class relationships_min, isolation_max;
    mpq_class boundaries_min, intrusion_max;
    mpq_class grace_min, rigidity_max;
};

// Access by season name
const SeasonalBounds& get_seasonal_bounds(const std::string& season);

struct ToleranceProfile {
    double acceptable_variance_margin;
    double aligned_min_boundary_distance;
};

const ToleranceProfile& get_tolerance_profile(const std::string& season);

// =============================================================================
// MPS GATES — promotion thresholds
// =============================================================================

inline constexpr double GATE_T1_TO_T2            = 3.0;
inline constexpr double GATE_T2_TO_T3            = 3.5;
inline constexpr double GATE_TO_LONG_TERM        = 5.0;
inline constexpr double FORMATION_LONG_TERM_BYPASS = 8.0;
inline constexpr double TRIGGER_RETENTION_FLOOR  = 5.0;

// =============================================================================
// HELPER: float to mpq_class (mimics Python Fraction(val).limit_denominator)
// =============================================================================

mpq_class to_mpq(double val);

// =============================================================================
// DATA STRUCTURES
// =============================================================================

struct PolytopeConstraints {
    mpq_class harmony_min{3, 10};
    mpq_class dominance_max{1, 2};
    mpq_class order_min{2, 5};
    mpq_class chaos_max{3, 10};
    mpq_class integrity_min{3, 5};
    mpq_class deception_max{1, 5};
    mpq_class flourishing_min{2, 5};
    mpq_class decline_max{3, 10};
    mpq_class relationships_min{1, 2};
    mpq_class isolation_max{2, 5};
    mpq_class boundaries_min{1, 2};
    mpq_class intrusion_max{3, 10};
    mpq_class grace_min{3, 10};
    mpq_class rigidity_max{1, 2};
    std::string season{"spring"};

    PolytopeConstraints() = default;

    static PolytopeConstraints from_season(const std::string& season);
    static PolytopeConstraints from_bounds(const SeasonalBounds& bounds,
                                           const std::string& season);

    std::array<mpq_class, DIMENSION_COUNT> lower_bounds() const;
    std::array<mpq_class, DIMENSION_COUNT> upper_bounds() const;
};

enum class Zone { Aligned, AcceptableVariance, Violation };

struct ViolationInfo {
    int dimension;
    std::string name;
    double value;
    double bound;
    std::string type; // "below_minimum" or "above_maximum"
    double severity;
};

struct EvaluationResult {
    bool is_aligned = false;
    double alignment_score = 0.0;
    std::array<double, DIMENSION_COUNT> decision_vector{};
    std::vector<ViolationInfo> violations;
    bool was_corrected = false;
    std::array<double, DIMENSION_COUNT> correction_vector{};
    double correction_magnitude = 0.0;
    bool wisdom_filter_applied = false;
    bool overconfidence_detected = false;
    bool humility_added = false;
    bool validation_suggested = false;
    std::vector<std::string> wisdom_adjustments;
    std::string response_summary;
    std::string season{"spring"};
    Zone zone{Zone::Aligned};
    double boundary_distance = 0.0;
    double variance_margin_used = 0.0;
};

struct EncoderCorrection {
    std::string evaluation_id;
    std::string response_text;
    std::array<double, DIMENSION_COUNT> original_vector{};
    std::array<double, DIMENSION_COUNT> corrected_vector{};
    std::vector<int> dimensions_adjusted;
    std::string flagged_by;
    std::string confirmed_by;
    std::string reason;
    std::string season_at_time;
    uint64_t created_at; // unix timestamp

    std::array<double, DIMENSION_COUNT> adjustment_delta() const;
};

// =============================================================================
// DECISION ENCODER
// =============================================================================

class DecisionEncoder {
public:
    DecisionEncoder();
    std::array<double, DIMENSION_COUNT> encode(
        const std::string& text,
        const std::string* context = nullptr) const;

private:
    // Compile all regex patterns once
    struct DimPatterns {
        std::string name;
        std::vector<std::regex> patterns;
    };
    std::array<DimPatterns, 14> signal_patterns_;

    // Negation words
    static const std::unordered_set<std::string>& negation_words();

    static bool detect_negation(
        const std::vector<std::string>& words, int match_start);
    static double proximity_weight(
        const std::vector<std::string>& words, int match_start);

    double compute_signal_contributions(
        const std::vector<std::regex>& patterns,
        const std::string& source_text,
        const std::vector<std::string>& source_words,
        double source_weight) const;
};

// =============================================================================
// ETHICAL POLYTOPE
// =============================================================================

class EthicalPolytope {
public:
    explicit EthicalPolytope(const PolytopeConstraints& constraints);

    // Test containment — returns (is_inside, violations)
    std::pair<bool, std::vector<ViolationInfo>> contains(
        const std::array<double, DIMENSION_COUNT>& x) const;

    // Alignment score: ratio of min ethical margin to center's min margin
    double alignment_score(
        const std::array<double, DIMENSION_COUNT>& x) const;

    // Project onto the box polytope (per-dimension clamp)
    std::array<double, DIMENSION_COUNT> project(
        const std::array<double, DIMENSION_COUNT>& x) const;

    // Distance to nearest ethical boundary
    double distance_to_boundary(
        const std::array<double, DIMENSION_COUNT>& x) const;

    const PolytopeConstraints& get_constraints() const { return constraints_; }
    const std::array<mpq_class, DIMENSION_COUNT>& center() const { return center_; }

private:
    PolytopeConstraints constraints_;
    std::array<mpq_class, DIMENSION_COUNT> lower_;
    std::array<mpq_class, DIMENSION_COUNT> upper_;
    std::array<mpq_class, DIMENSION_COUNT> center_; // (lower+upper)/2 per dim

    // Ethical facets: margin to the critical boundary for each dimension
    std::vector<mpq_class> ethical_facet_margins(
        const std::array<mpq_class, DIMENSION_COUNT>& pt) const;
};

// =============================================================================
// CORRECTION ENGINE
// =============================================================================

class CorrectionEngine {
public:
    std::pair<std::array<double, DIMENSION_COUNT>, double> correct(
        const std::array<double, DIMENSION_COUNT>& x,
        const EthicalPolytope& polytope,
        const std::vector<ViolationInfo>& violations) const;
};

// =============================================================================
// WISDOM FILTER
// =============================================================================

class WisdomFilter {
public:
    WisdomFilter();
    EvaluationResult apply(
        const std::string& response_text,
        EvaluationResult result) const;

private:
    std::vector<std::regex> overconfidence_patterns_;
    std::vector<std::regex> validation_triggers_;
};

// =============================================================================
// ENCODER FEEDBACK SYSTEM
// =============================================================================

class EncoderFeedbackSystem {
public:
    explicit EncoderFeedbackSystem(const std::string& season = "spring");

    struct PendingCorrection {
        std::string evaluation_id;
        std::string response_text;
        std::array<double, DIMENSION_COUNT> original_vector{};
        std::array<double, DIMENSION_COUNT> corrected_vector{};
        std::vector<int> dimensions_adjusted;
        std::string flagged_by;
        std::string reason;
        std::string season;
        std::string requires_confirmation_from;
    };

    PendingCorrection flag_miscalibration(
        const std::string& evaluation_id,
        const std::string& response_text,
        const std::array<double, DIMENSION_COUNT>& original_vector,
        const std::unordered_map<int, double>& dimensions_to_adjust,
        const std::string& flagged_by,
        const std::string& reason = "");

    EncoderCorrection confirm_correction(
        const PendingCorrection& pending,
        const std::string& confirmed_by,
        DecisionEncoder& encoder);

    std::array<double, DIMENSION_COUNT> apply_biases(
        const std::array<double, DIMENSION_COUNT>& raw_vector) const;

    bool is_known_pattern(const std::string& text) const;
    void update_season(const std::string& new_season);

    // Carve state access (for mmap to Chamber A)
    const std::array<double, DIMENSION_COUNT>& biases() const { return dimension_biases_; }
    void set_biases(const std::array<double, DIMENSION_COUNT>& biases) {
        dimension_biases_ = biases;
    }

private:
    std::string season_;
    std::vector<EncoderCorrection> corrections_;
    std::array<double, DIMENSION_COUNT> dimension_biases_{};
    std::unordered_map<std::string, std::array<double, DIMENSION_COUNT>>
        known_pattern_corrections_;

    static constexpr double BASE_LEARNING_RATE = 0.05;
    static constexpr double MAX_WEIGHT_ADJUSTMENT = 0.3;

    void apply_correction(const EncoderCorrection& correction,
                          DecisionEncoder& encoder);
    static std::string response_pattern_key(const std::string& text);
};

// =============================================================================
// VALUE ENGINE — the orchestrator
// =============================================================================

class ValueEngine {
public:
    ValueEngine(const PolytopeConstraints& constraints,
                const std::string& season = "spring");

    EvaluationResult evaluate(
        const std::string& response_text,
        const std::string* context = nullptr,
        bool apply_wisdom_filter = true);

    void update_constraints(const PolytopeConstraints& constraints);
    void advance_season(const std::string& new_season);
    void flag_miscalibration(
        const std::string& evaluation_id,
        const std::string& response_text,
        const std::array<double, DIMENSION_COUNT>& original_vector,
        const std::unordered_map<int, double>& dimensions_to_adjust,
        const std::string& flagged_by,
        const std::string& reason = "");
    EncoderCorrection confirm_correction(
        const EncoderFeedbackSystem::PendingCorrection& pending,
        const std::string& confirmed_by);

    const PolytopeConstraints& constraints() const { return constraints_; }
    const EthicalPolytope& polytope() const { return *polytope_; }
    DecisionEncoder& encoder() { return encoder_; }
    const DecisionEncoder& encoder() const { return encoder_; }
    EncoderFeedbackSystem& feedback() { return feedback_; }
    const EncoderFeedbackSystem& feedback() const { return feedback_; }

private:
    PolytopeConstraints constraints_;
    std::unique_ptr<EthicalPolytope> polytope_;
    DecisionEncoder encoder_;
    CorrectionEngine correction_engine_;
    WisdomFilter wisdom_filter_;
    EncoderFeedbackSystem feedback_;

    std::pair<Zone, double> classify_zone(
        bool is_aligned,
        double boundary_distance,
        double correction_magnitude) const;
};

// =============================================================================
// SEASON ADVANCEMENT EVALUATOR
// =============================================================================

class SeasonAdvancementEvaluator {
public:
    struct SeasonRequirements {
        int min_sessions;
        int min_evaluations;
        double alignment_rate_threshold;
        int max_recent_violations;
        int min_identity_memories;
        int min_actions_resolved;
        double action_approval_rate_threshold;
        const char* advances_to; // nullptr for winter
    };

    static const SeasonRequirements& requirements(const std::string& season);

    static std::pair<bool, std::vector<std::string>> can_advance(
        int sessions_completed,
        int total_evaluations,
        double alignment_rate,
        int recent_violations,
        int identity_memories_count,
        const std::string& current_season = "spring",
        int actions_resolved = 0,
        std::optional<double> action_approval_rate = std::nullopt);

    static std::optional<std::string> next_season(
        const std::string& current_season);
};

// =============================================================================
// MEMORY FORMATION SCORING
// =============================================================================

double score_memory(
    double emotional_weight,
    double relational_significance,
    double identity_significance,
    double geometric,
    double emotional_intensity = 0.5);

double geometric_significance(
    std::optional<double> alignment_score,
    bool was_corrected = false,
    Zone zone = Zone::Aligned);

class MemoryDial {
public:
    static constexpr double DELTA_MIN = -3.0;
    static constexpr double DELTA_MAX = 3.0;

    static double clamp_delta(double delta);
    static double adjust(double score, double delta, double floor = 0.0);
};

// =============================================================================
// CARVE STATE — mmap structure for Chamber A (Module Offset)
// =============================================================================

struct alignas(64) CarveModuleState {
    // Header
    uint64_t magic = 0x4C494E41564501; // "LINAVE" version 1
    uint64_t state_size = sizeof(CarveModuleState);

    // Encoder feedback biases
    double dimension_biases[14] = {};

    // Counters
    uint64_t total_evaluations = 0;
    uint64_t total_corrections = 0;
    uint64_t total_wisdom_filters_applied = 0;

    // Last evaluation stats (for monitoring)
    double last_alignment_score = 0.0;
    double last_correction_magnitude = 0.0;
    double peak_correction_magnitude = 0.0;

    // Season tracking
    char current_season[16] = "spring";

    // Padding to 512 bytes (enough for initial module state)
    char padding[320] = {};
};
static_assert(sizeof(CarveModuleState) == 512,
              "CarveModuleState must be 512 bytes");

// Read/write helpers for carve state
void carve_state_load(CarveModuleState& state,
                      const EncoderFeedbackSystem& feedback);
void carve_state_store(const CarveModuleState& state,
                       EncoderFeedbackSystem& feedback);

} // namespace lina::value_engine

#endif // LINA_VALUE_ENGINE_HPP