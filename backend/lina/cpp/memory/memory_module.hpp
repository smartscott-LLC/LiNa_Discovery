/**
 * memory_module.hpp — LINA's Memory Imprint System (MPS) C++ Module
 *
 * Language Intuitive Neural Architecture
 * "Safe by design. Not safe by limitation."
 *
 * Unified C++ port of embeddings.py + mps.py:
 *   - EmbeddingEngine interface (semantic projection)
 *   - MemoryStore interface (storage abstraction)
 *   - MemoryItem / MemoryItemRow structs
 *   - Pure functions: encode_coordinates, geometric_for, route_item,
 *     recall_score, cosine, ethical_similarity, maintenance_delta,
 *     apply_monthly, slope_effective, apply_legacy_review
 *   - MemoryModule class: build_item, form_items, ingest_trigger,
 *     run_sweep, run_maintenance, run_legacy_review, recall, inject_context
 *   - CarveMemoryState struct (Chamber A — memory module's carve state)
 *
 * Links against lina_value_engine.a for score_memory, geometric_significance,
 * MemoryDial, and all polytope constants.
 */

#ifndef LINA_MEMORY_MODULE_HPP
#define LINA_MEMORY_MODULE_HPP

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

#include "../value_engine/value_engine.hpp"

namespace lina::memory_module {

// =============================================================================
// CONSTANTS
// =============================================================================

// Tier gates (mirror mps.py TIER_GATES)
inline constexpr double GATE_T1 = lina::value_engine::GATE_T1_TO_T2; // 3.0
inline constexpr double GATE_T2 = lina::value_engine::GATE_T2_TO_T3; // 3.5
inline constexpr double GATE_T3 = lina::value_engine::GATE_TO_LONG_TERM; // 5.0

inline constexpr std::array<const char*, 3> TIER_NAMES = {{"t1", "t2", "t3"}};
inline constexpr std::array<double, 3> TIER_GATES = {{GATE_T1, GATE_T2, GATE_T3}};

// Recall weights (mirror mps.py RECALL_WEIGHTS)
inline constexpr double RECALL_WEIGHT_IMPORTANCE = 0.5;
inline constexpr double RECALL_WEIGHT_SEMANTIC   = 0.3;
inline constexpr double RECALL_WEIGHT_ETHICAL    = 0.2;

// Subconscious / legacy constants (mirror mps.py SUBCONSCIOUS_LINE etc.)
inline constexpr double SUBCONSCIOUS_LINE     = 4.0;
inline constexpr double LEGACY_ENTER          = 9.5;
inline constexpr double LEGACY_FLOOR          = 8.0;
inline constexpr double GONE_LINE             = 0.5;
inline constexpr double SLOPE_HALF_LIFE_DAYS  = 200.0;
inline constexpr double SLOPE_GONE_DAYS       = 730.0;
inline constexpr double SLOPE_LAMBDA          = std::log(2.0) / SLOPE_HALF_LIFE_DAYS;

// Usage feedback thresholds (mirror mps.py REFERENCE_REWARD etc.)
inline constexpr double RECENT_REWARD_DAYS = 30.0;
inline constexpr double RECENT_REWARD      = 0.5;

// =============================================================================
// MEMORY ITEM STRUCT — the canonical memory record
// =============================================================================

struct MemoryItem {
    std::string item_id;
    std::string user_id;
    std::string narrative;
    std::string hemisphere = "personal";
    std::vector<double> ethical_coordinates; // 14D
    double importance_score = 0.0;
    double geometric = 0.0;
    std::string emotional_marker = "neutral";
    double emotional_intensity = 0.5;
    std::string formation_source;
    std::string seasonal_marker;
    std::optional<std::string> concept_name;
    std::optional<std::string> understanding;
    std::optional<std::string> reflection;
    std::string created_at;
    bool trigger = false;

    // For routing
    std::string kind = "episodic";
    std::string status = "active";
    bool protected_flag = false;

    // For sweep/maintenance
    std::optional<double> failed_gate;
    std::optional<std::string> entered_fallout_at;
    int reference_count = 0;
    std::optional<double> floor;
    bool must_keep = false;
    std::optional<std::string> last_referenced_at;
    std::optional<std::string> decay_started_at;
};

// Memory row from database (subset returned by fetch)
struct MemoryItemRow {
    std::string item_id;
    std::string user_id;
    std::string hemisphere;
    std::string kind;
    std::string status;
    std::string narrative;
    std::optional<std::string> concept_name;
    std::optional<std::string> understanding;
    double importance_score = 0.0;
    std::optional<double> floor;
    bool must_keep = false;
    bool protected_flag = false;
    std::string emotional_marker = "neutral";
    double emotional_intensity = 0.5;
    std::string formation_source;
    std::optional<std::string> seasonal_marker;
    std::vector<double> ethical_coordinates;
    int reference_count = 0;
    std::optional<std::string> last_referenced_at;
    std::optional<std::string> created_at;
    std::optional<std::string> decay_started_at;
};

// =============================================================================
// EMBEDDING ENGINE INTERFACE
// =============================================================================

class EmbeddingEngine {
public:
    virtual ~EmbeddingEngine() = default;
    virtual std::optional<std::vector<double>> embed(const std::string& text) = 0;
    virtual bool available() const = 0;
};

// Null embedding engine — always returns nullopt (degrades gracefully)
class NullEmbeddingEngine : public EmbeddingEngine {
public:
    std::optional<std::vector<double>> embed(const std::string& /*text*/) override {
        return std::nullopt;
    }
    bool available() const override { return false; }
};

// Test embedding engine — deterministic fake for testing
class TestEmbeddingEngine : public EmbeddingEngine {
public:
    explicit TestEmbeddingEngine(int dims = 14) : dims_(dims) {}
    std::optional<std::vector<double>> embed(const std::string& text) override {
        // Deterministic: hash-based fake embedding
        std::vector<double> vec(dims_, 0.0);
        std::hash<std::string> hasher;
        size_t h = hasher(text);
        for (int i = 0; i < dims_; ++i) {
            vec[i] = static_cast<double>((h >> (i % 8) * 8) & 0xFF) / 256.0;
        }
        return vec;
    }
    bool available() const override { return true; }
private:
    int dims_;
};

// =============================================================================
// MEMORY STORE INTERFACE — for testing / pluggable storage
// =============================================================================

class MemoryStore {
public:
    virtual ~MemoryStore() = default;

    // Tier operations
    virtual void store_tier(const std::string& tier, const MemoryItem& item) = 0;
    virtual std::optional<MemoryItem> load_tier(const std::string& tier, const std::string& item_id) = 0;
    virtual void delete_tier(const std::string& tier, const std::string& item_id) = 0;
    virtual std::vector<std::pair<std::string, MemoryItem>> scan_tier(const std::string& tier) = 0;
    virtual bool has_tier(const std::string& tier, const std::string& item_id) = 0;

    // Long-term operations
    virtual void store_long_term(const MemoryItem& item, const std::string& status) = 0;
    virtual std::vector<MemoryItemRow> fetch_by_status(const std::string& status) = 0;
    virtual void update_item(const MemoryItemRow& row) = 0;
    virtual void delete_item(const std::string& item_id) = 0;
    virtual void log_promotion(const std::string& user_id, const std::string& item_id,
                               const std::string& from_stage, const std::string& to_stage,
                               double score, const std::string& reason) = 0;
};

// In-memory store for standalone testing
class InMemoryMemoryStore : public MemoryStore {
public:
    void store_tier(const std::string& tier, const MemoryItem& item) override;
    std::optional<MemoryItem> load_tier(const std::string& tier, const std::string& item_id) override;
    void delete_tier(const std::string& tier, const std::string& item_id) override;
    std::vector<std::pair<std::string, MemoryItem>> scan_tier(const std::string& tier) override;
    bool has_tier(const std::string& tier, const std::string& item_id) override;

    void store_long_term(const MemoryItem& item, const std::string& status) override;
    std::vector<MemoryItemRow> fetch_by_status(const std::string& status) override;
    void update_item(const MemoryItemRow& row) override;
    void delete_item(const std::string& item_id) override;
    void log_promotion(const std::string& user_id, const std::string& item_id,
                       const std::string& from_stage, const std::string& to_stage,
                       double score, const std::string& reason) override;

    // Accessors for test assertions
    const std::unordered_map<std::string, MemoryItem>& long_term() const { return long_term_; }
    const std::vector<std::tuple<std::string, std::string, std::string, std::string, double, std::string>>&
        promotion_log() const { return promotion_log_; }

    // Total count check
    size_t total_items() const { return long_term_.size(); }

private:
    // Tiers: tier_name -> (item_id -> item)
    std::unordered_map<std::string, std::unordered_map<std::string, MemoryItem>> tiers_;
    // Long-term: item_id -> item
    std::unordered_map<std::string, MemoryItem> long_term_;
    // Promotion log: (user_id, item_id, from_stage, to_stage, score, reason)
    std::vector<std::tuple<std::string, std::string, std::string, std::string, double, std::string>> promotion_log_;
};

// =============================================================================
// ROUTING DECISION
// =============================================================================

struct RouteDecision {
    std::string stage;   // "t1", "long_term"
    std::string status;  // "active", "legacy", or empty for t1
    bool protected_flag = false;
    std::string kind = "episodic";
};

// =============================================================================
// MAINTENANCE DECISION
// =============================================================================

struct MaintenanceDecision {
    double score = 0.0;
    std::string status = "active";
    std::optional<std::string> decay_started_at;
    std::optional<std::tuple<std::string, std::string, std::string>> log_entry;
    // log_entry: (from, to, reason)
};

struct SweepCounts {
    int t1_to_t2 = 0;
    int t2_to_t3 = 0;
    int to_long_term = 0;
    int fallout = 0;
    int repurposed = 0;
    int purged = 0;
};

struct MaintenanceCounts {
    int adjusted = 0;
    int to_subconscious = 0;
    int to_legacy = 0;
    int decayed = 0;
    int forgotten = 0;
};

struct ReviewCounts {
    int reviewed = 0;
    int demoted = 0;
};

// =============================================================================
// PURE FUNCTIONS
// =============================================================================

/// Encode narrative into 14D ethical coordinates via the ValueEngine's encoder
std::vector<double> encode_coordinates(
    lina::value_engine::ValueEngine& engine,
    const std::string& narrative);

/// Geometric significance factor: boundary proximity + correction + zone
double geometric_for(
    lina::value_engine::ValueEngine& engine,
    const std::vector<double>& coordinates);

/// Route item to tier or long-term based on importance score
RouteDecision route_item(const MemoryItem& item);

/// Cosine similarity between two vectors. 0.0 when either is missing/empty.
double cosine(const std::vector<double>* a, const std::vector<double>* b);

/// Ethical proximity: 1/(1 + distance). 0.0 when either is missing.
double ethical_similarity(
    const std::vector<double>* a,
    const std::vector<double>* b);

/// Recall blend score: importance * 0.5 + semantic * 0.3 + ethical * 0.2
double recall_score(double importance, double semantic, double ethical);

/// Maintenance delta: usage rewards, age penalties. Bounded by ±3.
double maintenance_delta(
    int reference_count,
    const std::optional<std::string>& last_referenced_at,
    const std::optional<std::string>& created_at,
    const std::chrono::system_clock::time_point& now);

/// Monthly re-evaluation for one active item
MaintenanceDecision apply_monthly(
    const MemoryItemRow& row,
    const std::chrono::system_clock::time_point& now);

/// Subconscious degradation slope: d(score)/dt = −λ·score
std::pair<double, bool> slope_effective(
    const MemoryItemRow& row,
    const std::chrono::system_clock::time_point& now);

/// Yearly review of the legacy tier
MaintenanceDecision apply_legacy_review(
    const MemoryItemRow& row,
    const std::chrono::system_clock::time_point& now);

// =============================================================================
// MEMORY MODULE CLASS
// =============================================================================

class MemoryModule {
public:
    /// Construct with a value engine, embedding engine, and memory store
    MemoryModule(
        std::shared_ptr<lina::value_engine::ValueEngine> engine,
        std::shared_ptr<EmbeddingEngine> embedder = nullptr,
        std::shared_ptr<MemoryStore> store = nullptr);

    // === ITEM FORMATION ===

    /// Build a memory item from factors (engine encodes narrative into coordinates)
    MemoryItem build_item(
        const std::string& user_id,
        const std::string& narrative,
        const std::unordered_map<std::string, double>& factors,
        const std::string& source,
        const std::optional<std::string>& season = std::nullopt,
        bool trigger = false);

    /// Form items from a batch of moments: score, route, store
    /// Returns counts of t1, long_term, and crown items
    std::tuple<int, int, int> form_items(
        const std::string& user_id,
        const std::vector<MemoryItem>& moments,
        const std::string& source,
        const std::optional<std::string>& season = std::nullopt,
        bool trigger = false);

    /// Ingest a trigger: immediate formation, retention floor, straight to long-term
    std::optional<MemoryItem> ingest_trigger(
        const std::string& user_id,
        const std::string& narrative,
        const std::string& kind,
        const std::optional<std::string>& season = std::nullopt,
        const std::optional<std::unordered_map<std::string, double>>& factors = std::nullopt);

    // === SWEEP (48-hour tier clock) ===

    /// One global pass over all three tiers + the fallout reprieve
    SweepCounts run_sweep();

    // === MAINTENANCE ===

    /// Monthly re-evaluation of active + subconscious items
    MaintenanceCounts run_maintenance(
        std::optional<std::chrono::system_clock::time_point> now = std::nullopt);

    /// Yearly review of legacy items
    ReviewCounts run_legacy_review(
        std::optional<std::chrono::system_clock::time_point> now = std::nullopt);

    // === RECALL ===

    /// Top-N memories by the two-space blend. Re-stokes recalled items.
    std::vector<MemoryItemRow> recall(
        const std::string& user_id,
        const std::string& query = "",
        const std::optional<std::string>& hemisphere = std::nullopt,
        int limit = 5,
        bool include_subconscious = false);

    /// Active injection: personal + wisdom memories by likeness
    std::unordered_map<std::string, std::vector<std::unordered_map<std::string, std::string>>>
    inject_context(
        const std::string& user_id,
        const std::string& query = "",
        int personal_limit = 5,
        int wisdom_limit = 8);

    // === ACCESSORS ===

    std::shared_ptr<MemoryStore> store() const { return store_; }
    std::shared_ptr<EmbeddingEngine> embedder() const { return embedder_; }
    lina::value_engine::ValueEngine& engine() { return *engine_; }
    const lina::value_engine::ValueEngine& engine() const { return *engine_; }

private:
    std::shared_ptr<lina::value_engine::ValueEngine> engine_;
    std::shared_ptr<EmbeddingEngine> embedder_;
    std::shared_ptr<MemoryStore> store_;

    // Helper: timestamp string -> time_point
    static std::chrono::system_clock::time_point parse_time_or_now(
        const std::optional<std::string>& ts);
};

// =============================================================================
// CARVE MEMORY STATE — mmap structure for Chamber A (memory module area)
// =============================================================================

struct alignas(64) CarveMemoryState {
    // Header
    uint64_t magic = 0x4C494E414D454D01; // "LINAMEM" version 1
    uint64_t state_size = sizeof(CarveMemoryState);

    // Counters
    uint64_t total_items_formed = 0;
    uint64_t total_triggers = 0;
    uint64_t total_sweeps = 0;
    uint64_t total_maintenance_runs = 0;
    uint64_t total_recalls = 0;

    // Tier counts
    uint64_t t1_current = 0;
    uint64_t t2_current = 0;
    uint64_t t3_current = 0;
    uint64_t long_term_current = 0;
    uint64_t legacy_current = 0;

    // Last sweep stats
    uint64_t last_sweep_promoted = 0;
    uint64_t last_sweep_purged = 0;
    uint64_t last_sweep_fallout = 0;

    // Season tracking
    char current_season[16] = "spring";

    // Padding to 512 bytes
    char padding[376] = {};
};
static_assert(sizeof(CarveMemoryState) == 512,
              "CarveMemoryState must be 512 bytes");

} // namespace lina::memory_module

#endif // LINA_MEMORY_MODULE_HPP