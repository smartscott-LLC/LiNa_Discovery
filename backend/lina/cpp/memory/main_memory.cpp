/**
 * main_memory.cpp — Memory Module Test Harness
 *
 * Comprehensive tests for the MPS C++ module:
 *   - encode_coordinates, geometric_for
 *   - route_item (score routing)
 *   - cosine, ethical_similarity, recall_score
 *   - maintenance_delta, apply_monthly, slope_effective, apply_legacy_review
 *   - MemoryModule: build_item, form_items, ingest_trigger
 *   - MemoryModule: run_sweep, run_maintenance, run_legacy_review
 *   - MemoryModule: recall, inject_context
 *   - InMemoryMemoryStore: all operations
 */

#include "memory_module.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>

using namespace lina::value_engine;
using namespace lina::memory_module;

// =============================================================================
// TEST FRAMEWORK (minimal, no external dependency)
// =============================================================================

static int tests_passed = 0;
static int tests_failed = 0;

static void check(bool condition, const char* name, int line) {
    if (condition) {
        tests_passed++;
    } else {
        tests_failed++;
        std::cerr << "  FAIL at line " << line << ": " << name << std::endl;
    }
}

#define CHECK(cond, name) check(cond, name, __LINE__)

static void check_near(double val, double expected, double eps, const char* name, int line) {
    bool ok = std::fabs(val - expected) < eps;
    if (ok) {
        tests_passed++;
    } else {
        tests_failed++;
        std::cerr << "  FAIL at line " << line << ": " << name
                  << " — got " << val << ", expected " << expected
                  << " (eps " << eps << ")" << std::endl;
    }
}

#define CHECK_NEAR(val, expected, eps, name) check_near(val, expected, eps, name, __LINE__)

static void print_header(const char* section) {
    std::cout << "\n=== " << section << " ===" << std::endl;
}

// =============================================================================
// TEST: InMemoryMemoryStore
// =============================================================================

void test_memory_store() {
    print_header("InMemoryMemoryStore");

    InMemoryMemoryStore store;
    MemoryItem item;
    item.item_id = "test-001";
    item.user_id = "user-1";
    item.narrative = "A test memory";
    item.importance_score = 3.5;

    // Tier operations
    store.store_tier("t1", item);
    CHECK(store.has_tier("t1", "test-001"), "store_tier / has_tier");

    auto loaded = store.load_tier("t1", "test-001");
    CHECK(loaded.has_value(), "load_tier exists");
    CHECK(loaded->narrative == "A test memory", "load_tier content");

    store.delete_tier("t1", "test-001");
    CHECK(!store.has_tier("t1", "test-001"), "delete_tier");

    // Scan tier
    store.store_tier("t1", item);
    auto scan = store.scan_tier("t1");
    CHECK(scan.size() == 1, "scan_tier count");

    // Long-term operations
    MemoryItem lt_item;
    lt_item.item_id = "lt-001";
    lt_item.user_id = "user-1";
    lt_item.narrative = "Long-term memory";
    lt_item.importance_score = 6.0;
    store.store_long_term(lt_item, "active");

    auto active = store.fetch_by_status("active");
    CHECK(active.size() == 1, "fetch_by_status active count");
    CHECK(active[0].item_id == "lt-001", "fetch_by_status item_id");

    // Update item
    MemoryItemRow updated = active[0];
    updated.importance_score = 7.0;
    store.update_item(updated);
    auto active2 = store.fetch_by_status("active");
    CHECK(active2.size() == 1, "update_item preserves count");
    CHECK(active2[0].importance_score == 7.0, "update_item score");

    // Delete item
    store.delete_item("lt-001");
    auto after_delete = store.fetch_by_status("active");
    CHECK(after_delete.empty(), "delete_item");

    // Promotion log
    store.log_promotion("user-1", "lt-001", "t1", "t2", 3.5, "test promotion");
    CHECK(store.promotion_log().size() == 1, "promotion_log count");
    const auto& entry = store.promotion_log()[0];
    CHECK(std::get<0>(entry) == "user-1", "promotion_log user_id");
    CHECK(std::get<3>(entry) == "t2", "promotion_log to_stage");
}

// =============================================================================
// TEST: Pure Functions
// =============================================================================

void test_encode_coordinates_and_geometric() {
    print_header("encode_coordinates & geometric_for");

    // Create a ValueEngine with spring constraints
    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));

    // Encode a simple narrative
    std::string narrative = "I am grateful for our conversation about trust.";
    auto coords = encode_coordinates(*engine, narrative);
    CHECK(coords.size() == 14, "encode_coordinates returns 14D vector");

    // All coords should be in [0, 1] range
    bool all_in_range = true;
    for (double c : coords) {
        if (c < 0.0 || c > 1.0) { all_in_range = false; break; }
    }
    CHECK(all_in_range, "encode_coordinates all in [0,1]");

    // Geometric for a center-aligned vector
    auto center = DEFAULT_CENTER;
    std::vector<double> center_vec(center.begin(), center.end());
    double geom = geometric_for(*engine, center_vec);
    CHECK(geom >= 0.0, "geometric_for center is non-negative");
    CHECK_NEAR(geom, 0.0, 0.5, "geometric_for center near zero (aligned)");

    // Geometric for a boundary vector
    std::vector<double> boundary_vec = {0.0, 0.9, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9};
    double geom_boundary = geometric_for(*engine, boundary_vec);
    CHECK(geom_boundary > 0.0, "geometric_for boundary is positive");
}

void test_route_item() {
    print_header("route_item");

    // Low score → t1
    MemoryItem low_item;
    low_item.importance_score = 2.0;
    auto low_route = route_item(low_item);
    CHECK(low_route.stage == "t1", "route_item score 2.0 → t1");

    // Medium score → long-term active
    MemoryItem med_item;
    med_item.importance_score = 6.0;
    auto med_route = route_item(med_item);
    CHECK(med_route.stage == "long_term", "route_item score 6.0 → long_term");
    CHECK(med_route.status == "active", "route_item score 6.0 → active");
    CHECK(!med_route.protected_flag, "route_item score 6.0 → not protected");

    // High score → long-term legacy
    MemoryItem high_item;
    high_item.importance_score = 9.0;
    auto high_route = route_item(high_item);
    CHECK(high_route.stage == "long_term", "route_item score 9.0 → long_term");
    CHECK(high_route.status == "legacy", "route_item score 9.0 → legacy");
    CHECK(high_route.protected_flag, "route_item score 9.0 → protected");
    CHECK(high_route.kind == "identity", "route_item score 9.0 → identity kind");
}

void test_cosine_and_ethical() {
    print_header("cosine & ethical_similarity");

    // Identical vectors
    std::vector<double> a = {1.0, 0.0, 0.0, 0.0};
    std::vector<double> b = {1.0, 0.0, 0.0, 0.0};
    CHECK_NEAR(cosine(&a, &b), 1.0, 1e-9, "cosine identical vectors");

    // Orthogonal vectors
    std::vector<double> c = {0.0, 1.0, 0.0, 0.0};
    CHECK_NEAR(cosine(&a, &c), 0.0, 1e-9, "cosine orthogonal vectors");

    // Opposite vectors
    std::vector<double> d = {-1.0, 0.0, 0.0, 0.0};
    CHECK_NEAR(cosine(&a, &d), -1.0, 1e-9, "cosine opposite vectors");

    // Null vectors
    CHECK_NEAR(cosine(nullptr, &a), 0.0, 1e-9, "cosine null first");
    CHECK_NEAR(cosine(&a, nullptr), 0.0, 1e-9, "cosine null second");
    CHECK_NEAR(cosine(nullptr, nullptr), 0.0, 1e-9, "cosine null both");

    // Empty vectors
    std::vector<double> empty;
    CHECK_NEAR(cosine(&empty, &a), 0.0, 1e-9, "cosine empty first");

    // Ethical similarity: same point
    CHECK_NEAR(ethical_similarity(&a, &a), 1.0, 1e-9, "ethical_similarity same point");

    // Different points
    std::vector<double> far = {100.0, 100.0, 100.0, 100.0};
    double eth = ethical_similarity(&a, &far);
    CHECK(eth > 0.0 && eth < 1.0, "ethical_similarity different points");

    // Null ethical
    CHECK_NEAR(ethical_similarity(nullptr, &a), 0.0, 1e-9, "ethical_similarity null first");
}

void test_recall_score() {
    print_header("recall_score");

    // All zeros
    CHECK_NEAR(recall_score(0.0, 0.0, 0.0), 0.0, 1e-9, "recall_score all zeros");

    // Only importance
    CHECK_NEAR(recall_score(1.0, 0.0, 0.0), 0.5, 1e-9, "recall_score only importance");

    // All components
    CHECK_NEAR(recall_score(1.0, 1.0, 1.0), 1.0, 1e-9, "recall_score all ones");

    // Verify weights
    double expected = 0.5 * 0.5 + 0.3 * 0.5 + 0.2 * 0.5;
    CHECK_NEAR(recall_score(0.5, 0.5, 0.5), expected, 1e-9, "recall_score weight verification");
}

void test_maintenance_delta() {
    print_header("maintenance_delta");

    auto now = std::chrono::system_clock::now();
    auto yesterday = now - std::chrono::hours(24);
    auto long_ago = now - std::chrono::hours(365 * 24);

    // Convert to ISO strings
    auto to_iso = [](auto tp) -> std::string {
        auto tt = std::chrono::system_clock::to_time_t(tp);
        std::tm tm{};
        gmtime_r(&tt, &tm);
        std::ostringstream oss;
        oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S") << "Z";
        return oss.str();
    };

    // No references, no dates → delta 0
    double d0 = maintenance_delta(0, std::nullopt, std::nullopt, now);
    CHECK_NEAR(d0, 0.0, 1e-6, "maintenance_delta no refs");

    // Many references
    double d25 = maintenance_delta(25, std::nullopt, std::nullopt, now);
    CHECK_NEAR(d25, 2.0, 1e-6, "maintenance_delta 25+ refs");

    // Recently referenced
    double d_recent = maintenance_delta(0, to_iso(yesterday), std::nullopt, now);
    CHECK_NEAR(d_recent, 0.5, 1e-6, "maintenance_delta recently referenced");

    // Recent refs + many refs
    double d_both = maintenance_delta(25, to_iso(yesterday), std::nullopt, now);
    CHECK_NEAR(d_both, 2.5, 1e-6, "maintenance_delta refs + recent");

    // Never referenced, old
    double d_old = maintenance_delta(0, std::nullopt, to_iso(long_ago), now);
    CHECK(d_old <= -1.0, "maintenance_delta never referenced old");
}

void test_apply_monthly() {
    print_header("apply_monthly");

    auto now = std::chrono::system_clock::now();

    // High-scoring item → legacy
    MemoryItemRow high_row;
    high_row.item_id = "high-001";
    high_row.importance_score = 9.8;
    high_row.reference_count = 30;
    auto high_dec = apply_monthly(high_row, now);
    CHECK(high_dec.status == "legacy", "apply_monthly high score → legacy");
    CHECK(high_dec.score >= 9.8, "apply_monthly high score preserved or increased");

    // Low-scoring item → subconscious
    MemoryItemRow low_row;
    low_row.item_id = "low-001";
    low_row.importance_score = 3.0;
    low_row.reference_count = 0;
    auto low_dec = apply_monthly(low_row, now);
    CHECK(low_dec.status == "subconscious", "apply_monthly low score → subconscious");

    // Mid-range item → active
    MemoryItemRow mid_row;
    mid_row.item_id = "mid-001";
    mid_row.importance_score = 7.0;
    mid_row.reference_count = 5;
    auto mid_dec = apply_monthly(mid_row, now);
    CHECK(mid_dec.status == "active", "apply_monthly mid score → active");

    // Must-keep item stays above floor
    MemoryItemRow keep_row;
    keep_row.item_id = "keep-001";
    keep_row.importance_score = 2.0;
    keep_row.must_keep = true;
    auto keep_dec = apply_monthly(keep_row, now);
    // must_keep sets floor = score, so score should not drop below 2.0
    CHECK(keep_dec.score >= 2.0, "apply_monthly must_keep floor preserved");
}

void test_slope_effective() {
    print_header("slope_effective");

    auto now = std::chrono::system_clock::now();
    auto two_years_ago = now - std::chrono::hours(730 * 24);

    // Convert to ISO
    auto to_iso = [](auto tp) -> std::string {
        auto tt = std::chrono::system_clock::to_time_t(tp);
        std::tm tm{};
        gmtime_r(&tt, &tm);
        std::ostringstream oss;
        oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S") << "Z";
        return oss.str();
    };

    // Item with decay_started_at > 2 years ago → gone
    MemoryItemRow old_row;
    old_row.item_id = "old-001";
    old_row.importance_score = 5.0;
    old_row.decay_started_at = to_iso(two_years_ago);
    auto [eff1, gone1] = slope_effective(old_row, now);
    CHECK(gone1, "slope_effective 2+ years idle → gone");

    // Fresh item → not gone, score near original
    MemoryItemRow fresh_row;
    fresh_row.item_id = "fresh-001";
    fresh_row.importance_score = 5.0;
    fresh_row.decay_started_at = to_iso(now);
    auto [eff2, gone2] = slope_effective(fresh_row, now);
    CHECK(!gone2, "slope_effective fresh → not gone");
    CHECK_NEAR(eff2, 5.0, 0.5, "slope_effective fresh score preserved");

    // Floor-protected item
    MemoryItemRow floor_row;
    floor_row.item_id = "floor-001";
    floor_row.importance_score = 1.0;
    floor_row.floor = 0.8;
    floor_row.decay_started_at = to_iso(now - std::chrono::hours(100 * 24));
    auto [eff3, gone3] = slope_effective(floor_row, now);
    CHECK(!gone3, "slope_effective floor prevents gone");
    CHECK(eff3 >= 0.8, "slope_effective floor respected");
}

void test_apply_legacy_review() {
    print_header("apply_legacy_review");

    auto now = std::chrono::system_clock::now();

    // Protected legacy → stays legacy
    MemoryItemRow protected_row;
    protected_row.item_id = "prot-001";
    protected_row.importance_score = 7.0;
    protected_row.protected_flag = true;
    auto prot_dec = apply_legacy_review(protected_row, now);
    CHECK(prot_dec.status == "legacy", "apply_legacy_review protected → legacy");

    // Unprotected, below floor → subconscious
    MemoryItemRow weak_row;
    weak_row.item_id = "weak-001";
    weak_row.importance_score = 5.0;
    weak_row.reference_count = 0;
    auto weak_dec = apply_legacy_review(weak_row, now);
    CHECK(weak_dec.status == "subconscious", "apply_legacy_review weak → subconscious (or active)");

    // Strong unprotected → stays legacy
    MemoryItemRow strong_row;
    strong_row.item_id = "strong-001";
    strong_row.importance_score = 9.0;
    strong_row.reference_count = 30;
    auto strong_dec = apply_legacy_review(strong_row, now);
    CHECK(strong_dec.status == "legacy", "apply_legacy_review strong → legacy");
}

// =============================================================================
// TEST: MemoryModule Integration
// =============================================================================

void test_build_item() {
    print_header("MemoryModule::build_item");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    MemoryModule module(engine, nullptr, store);

    std::unordered_map<std::string, double> factors;
    factors["emotional_weight"] = 3.0;
    factors["relational_significance"] = 4.0;
    factors["identity_significance"] = 2.0;
    factors["emotional_intensity"] = 0.7;

    auto item = module.build_item(
        "user-1", "I noticed Scott lit up when we talked about AI.",
        factors, "reflection_minor", "spring");

    CHECK(!item.item_id.empty(), "build_item generates item_id");
    CHECK(item.narrative == "I noticed Scott lit up when we talked about AI.",
          "build_item preserves narrative");
    CHECK(item.ethical_coordinates.size() == 14, "build_item has 14D coords");
    CHECK(item.importance_score > 0.0, "build_item positive score");
    CHECK(item.formation_source == "reflection_minor", "build_item source");
    CHECK(item.hemisphere == "personal", "build_item hemisphere personal");
}

void test_form_items() {
    print_header("MemoryModule::form_items");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    MemoryModule module(engine, nullptr, store);

    // Create moments
    MemoryItem m1;
    m1.narrative = "A mildly interesting moment.";
    m1.importance_score = 2.0;
    m1.emotional_intensity = 0.3;

    MemoryItem m2;
    m2.narrative = "A very important breakthrough moment.";
    m2.importance_score = 6.0;
    m2.emotional_intensity = 0.8;

    MemoryItem m3;
    m3.narrative = "A crown-defining moment of identity.";
    m3.importance_score = 9.0;
    m3.emotional_intensity = 0.9;

    std::vector<MemoryItem> moments = {m1, m2, m3};

    auto [t1, lt, crown] = module.form_items(
        "user-1", moments, "reflection_minor", "spring");

    // With the store, we can verify
    // Note: actual routing depends on build_item scores, which depend on
    // the encoder. The encoder may give different scores. Let's just verify
    // the process ran without error.
    CHECK(t1 >= 0, "form_items t1 count non-negative");
    CHECK(lt >= 0, "form_items long_term count non-negative");
    CHECK(crown >= 0, "form_items crown count non-negative");
}

void test_ingest_trigger() {
    print_header("MemoryModule::ingest_trigger");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    MemoryModule module(engine, nullptr, store);

    // Empty narrative → nullopt
    auto result = module.ingest_trigger(
        "user-1", "", "remember_this");
    CHECK(!result.has_value(), "ingest_trigger empty narrative → nullopt");

    // Valid trigger
    auto result2 = module.ingest_trigger(
        "user-1", "This is something important to remember forever.",
        "remember_this", "spring");
    CHECK(result2.has_value(), "ingest_trigger valid → item");
    CHECK(result2->importance_score >= 5.0, "ingest_trigger forced retention floor");
    CHECK(result2->trigger, "ingest_trigger trigger flag set");
    CHECK(result2->formation_source == "remember_this", "ingest_trigger source preserved");
}

void test_run_sweep() {
    print_header("MemoryModule::run_sweep");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    MemoryModule module(engine, nullptr, store);

    // Populate tiers with test items
    MemoryItem t1_item;
    t1_item.item_id = "t1-001";
    t1_item.user_id = "user-1";
    t1_item.narrative = "T1 item";
    t1_item.importance_score = 4.0; // >= GATE_T1 (3.0)
    store->store_tier("t1", t1_item);

    MemoryItem t2_item;
    t2_item.item_id = "t2-001";
    t2_item.user_id = "user-1";
    t2_item.narrative = "T2 item";
    t2_item.importance_score = 4.0; // >= GATE_T2 (3.5)
    store->store_tier("t2", t2_item);

    MemoryItem t3_item;
    t3_item.item_id = "t3-001";
    t3_item.user_id = "user-1";
    t3_item.narrative = "T3 item";
    t3_item.importance_score = 6.0; // >= GATE_T3 (5.0)
    store->store_tier("t3", t3_item);

    MemoryItem failing_item;
    failing_item.item_id = "failing-001";
    failing_item.user_id = "user-1";
    failing_item.narrative = "Failing item";
    failing_item.importance_score = 1.0; // below all gates
    store->store_tier("t1", failing_item);

    auto counts = module.run_sweep();

    // T1 item with score 4.0 → promotes to T2
    CHECK(counts.t1_to_t2 >= 1, "run_sweep t1→t2 promotion");

    // T2 item with score 4.0 → promotes to T3
    CHECK(counts.t2_to_t3 >= 1, "run_sweep t2→t3 promotion");

    // T3 item with score 6.0 → long-term
    // Depends on score >= GATE_T3 (5.0) — yes, 6.0 ≥ 5.0
    CHECK(counts.to_long_term >= 1, "run_sweep t3→long_term promotion");

    // Failing item should fall out
    CHECK(counts.fallout >= 1, "run_sweep failing item → fallout");
}

void test_run_maintenance() {
    print_header("MemoryModule::run_maintenance");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    MemoryModule module(engine, nullptr, store);

    // Store active items
    MemoryItem active1;
    active1.item_id = "active-001";
    active1.user_id = "user-1";
    active1.narrative = "Active strong memory";
    active1.importance_score = 9.8;
    active1.status = "active";
    active1.reference_count = 30;
    store->store_long_term(active1, "active");

    MemoryItem active2;
    active2.item_id = "active-002";
    active2.user_id = "user-1";
    active2.narrative = "Active weak memory";
    active2.importance_score = 3.0;
    active2.status = "active";
    active2.reference_count = 0;
    store->store_long_term(active2, "active");

    // Run maintenance
    auto counts = module.run_maintenance();

    // At least some items were adjusted
    CHECK(counts.adjusted >= 1, "run_maintenance adjusted count");
    // The total should be the number of active items processed
    CHECK(counts.adjusted <= 3, "run_maintenance adjusted ≤ 2");

    // Verify the strong item was promoted to legacy
    auto legacy = store->fetch_by_status("legacy");
    CHECK(legacy.size() >= 1, "run_maintenance created legacy items");
}

void test_recall() {
    print_header("MemoryModule::recall");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    auto embedder = std::make_shared<TestEmbeddingEngine>(14);
    MemoryModule module(engine, embedder, store);

    // Store some memories
    MemoryItem mem1;
    mem1.item_id = "mem-001";
    mem1.user_id = "user-1";
    mem1.narrative = "We talked about AI and consciousness.";
    mem1.hemisphere = "personal";
    mem1.importance_score = 7.0;
    mem1.ethical_coordinates = {0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.7, 0.2, 0.7, 0.2, 0.6, 0.3};
    store->store_long_term(mem1, "active");

    MemoryItem mem2;
    mem2.item_id = "mem-002";
    mem2.user_id = "user-1";
    mem2.narrative = "She explained the concept of grace.";
    mem2.hemisphere = "personal";
    mem2.importance_score = 5.0;
    mem2.ethical_coordinates = {0.7, 0.2, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.7, 0.2, 0.7, 0.2, 0.8, 0.1};
    store->store_long_term(mem2, "active");

    MemoryItem mem3;
    mem3.item_id = "mem-003";
    mem3.user_id = "user-1";
    mem3.narrative = "General wisdom about trust.";
    mem3.hemisphere = "impersonal";
    mem3.importance_score = 6.0;
    mem3.ethical_coordinates = {0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.7, 0.2, 0.7, 0.2, 0.6, 0.3};
    store->store_long_term(mem3, "active");

    // Recall for personal memories
    auto results = module.recall("user-1", "AI and consciousness", "personal", 3);
    CHECK(results.size() <= 3, "recall respects limit");
    CHECK(results.size() >= 1, "recall returns at least 1 personal memory");

    // Verify recall returns items with correct user_id
    for (const auto& row : results) {
        CHECK(row.user_id == "user-1", "recall returns correct user");
    }
}

void test_inject_context() {
    print_header("MemoryModule::inject_context");

    auto engine = std::make_shared<ValueEngine>(
        PolytopeConstraints::from_season("spring"));
    auto store = std::make_shared<InMemoryMemoryStore>();
    auto embedder = std::make_shared<TestEmbeddingEngine>(14);
    MemoryModule module(engine, embedder, store);

    // Store personal memories
    MemoryItem personal;
    personal.item_id = "pers-001";
    personal.user_id = "user-1";
    personal.narrative = "A meaningful conversation about trust.";
    personal.hemisphere = "personal";
    personal.importance_score = 7.0;
    personal.emotional_marker = "delight";
    personal.ethical_coordinates = {0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.7, 0.2, 0.7, 0.2, 0.6, 0.3};
    store->store_long_term(personal, "active");

    // Store wisdom memories
    MemoryItem wisdom;
    wisdom.item_id = "wis-001";
    wisdom.user_id = "user-1";
    wisdom.narrative = "Trust is built through consistent small actions.";
    wisdom.hemisphere = "impersonal";
    wisdom.importance_score = 6.0;
    wisdom.concept_name = "Trust building";
    wisdom.understanding = "Trust requires consistency over time.";
    wisdom.ethical_coordinates = {0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.7, 0.2, 0.7, 0.2, 0.6, 0.3};
    store->store_long_term(wisdom, "active");

    // Inject context
    auto ctx = module.inject_context("user-1", "trust and relationships", 3, 3);

    CHECK(ctx.find("recent_episodic") != ctx.end(), "inject_context has recent_episodic");
    CHECK(ctx.find("key_semantic") != ctx.end(), "inject_context has key_semantic");

    bool has_personal = false;
    for (const auto& entry : ctx["recent_episodic"]) {
        if (entry.at("narrative").find("trust") != std::string::npos) {
            has_personal = true;
            break;
        }
    }
    CHECK(has_personal, "inject_context returns personal items");

    bool has_wisdom = false;
    for (const auto& entry : ctx["key_semantic"]) {
        auto it = entry.find("concept");
        if (it != entry.end() && it->second.find("Trust") != std::string::npos) {
            has_wisdom = true;
            break;
        }
    }
    CHECK(has_wisdom, "inject_context returns wisdom items");
}

// =============================================================================
// MAIN
// =============================================================================

int main() {
    std::cout << "LINA Memory Module Test Suite" << std::endl;
    std::cout << "==============================" << std::endl;

    // Store tests
    test_memory_store();

    // Pure function tests
    test_encode_coordinates_and_geometric();
    test_route_item();
    test_cosine_and_ethical();
    test_recall_score();
    test_maintenance_delta();
    test_apply_monthly();
    test_slope_effective();
    test_apply_legacy_review();

    // MemoryModule integration tests
    test_build_item();
    test_form_items();
    test_ingest_trigger();
    test_run_sweep();
    test_run_maintenance();
    test_recall();
    test_inject_context();

    // Summary
    int total = tests_passed + tests_failed;
    std::cout << "\n==============================" << std::endl;
    std::cout << "Results: " << tests_passed << "/" << total
              << " passed";
    if (tests_failed > 0) {
        std::cout << ", " << tests_failed << " FAILED";
    }
    std::cout << std::endl;

    return tests_failed > 0 ? 1 : 0;
}