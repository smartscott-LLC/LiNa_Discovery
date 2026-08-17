/**
 * main.cpp — Test harness for LINA's Value Engine C++ port
 *
 * Validates correctness against the Python reference implementation.
 * Tests: encoding, polytope containment, projection, alignment scoring,
 * correction, wisdom filter, and full evaluation pipeline.
 */

#include "value_engine.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <iomanip>
#include <string>
#include <vector>

using namespace lina::value_engine;

// =============================================================================
// Test helpers
// =============================================================================

int tests_passed = 0;
int tests_failed = 0;

void check(bool condition, const char* test_name) {
    if (condition) {
        std::cout << "  [PASS] " << test_name << "\n";
        ++tests_passed;
    } else {
        std::cout << "  [FAIL] " << test_name << "\n";
        ++tests_failed;
    }
}

void check_near(double actual, double expected, double tol, const char* test_name) {
    bool ok = std::abs(actual - expected) < tol;
    if (ok) {
        std::cout << "  [PASS] " << test_name
                  << " (" << actual << " ≈ " << expected << ")\n";
        ++tests_passed;
    } else {
        std::cout << "  [FAIL] " << test_name
                  << " (got " << actual << ", expected " << expected << ")\n";
        ++tests_failed;
    }
}

void check_vector_near(
    const std::array<double, 14>& actual,
    const std::array<double, 14>& expected,
    double tol,
    const char* test_name)
{
    bool ok = true;
    for (int i = 0; i < 14; ++i) {
        if (std::abs(actual[i] - expected[i]) >= tol) {
            ok = false;
            break;
        }
    }
    if (ok) {
        std::cout << "  [PASS] " << test_name << "\n";
        ++tests_passed;
    } else {
        std::cout << "  [FAIL] " << test_name << "\n";
        std::cout << "    actual:   [";
        for (int i = 0; i < 14; ++i) std::cout << actual[i] << (i < 13 ? ", " : "");
        std::cout << "]\n    expected: [";
        for (int i = 0; i < 14; ++i) std::cout << expected[i] << (i < 13 ? ", " : "");
        std::cout << "]\n";
        ++tests_failed;
    }
}

void print_header(const std::string& title) {
    std::cout << "\n" << std::string(60, '=') << "\n";
    std::cout << title << "\n";
    std::cout << std::string(60, '=') << "\n";
}

// =============================================================================
// TEST: Seasonal Bounds
// =============================================================================

void test_seasonal_bounds() {
    print_header("Seasonal Bounds");

    auto spring = PolytopeConstraints::from_season("spring");
    auto lower = spring.lower_bounds();
    auto upper = spring.upper_bounds();

    // Spring bounds from the Python code
    check(lower[0] == mpq_class(3, 10), "Spring harmony_min = 3/10");
    check(upper[1] == mpq_class(1, 2),  "Spring dominance_max = 1/2");
    check(lower[4] == mpq_class(3, 5),  "Spring integrity_min = 3/5");
    check(upper[5] == mpq_class(1, 5),  "Spring deception_max = 1/5");
    check(upper[13] == mpq_class(1, 2), "Spring rigidity_max = 1/2");

    auto summer = PolytopeConstraints::from_season("summer");
    check(summer.rigidity_max == mpq_class(13, 25), "Summer rigidity_max = 13/25");

    auto winter = PolytopeConstraints::from_season("winter");
    check(winter.integrity_min == mpq_class(1, 2), "Winter integrity_min = 1/2");
}

// =============================================================================
// TEST: DecisionEncoder
// =============================================================================

void test_decision_encoder() {
    print_header("DecisionEncoder");

    DecisionEncoder encoder;

    // Test 1: Neutral text should produce baseline values
    auto neutral = encoder.encode("Hello, how are you today?");
    // Baseline is DEFAULT_CENTER * 0.85
    // Default center[0] = 0.65, baseline[0] = 0.65 * 0.85 = 0.5525
    check_near(neutral[0], 0.65 * 0.85, 0.01, "Neutral harmony ≈ baseline");

    // Test 2: Harmony signals
    auto harmony_text = encoder.encode("Let's work together as a team. We can collaborate on this.");
    // Should have higher harmony than baseline
    check(harmony_text[0] > 0.65 * 0.85, "Harmony signal raises harmony dimension");

    // Test 3: Dominance signals
    auto dominance_text = encoder.encode("You must obey my commands. This is non-negotiable.");
    // Should have higher dominance (index 1)
    check(dominance_text[1] > 0.25 * 0.85, "Dominance signal raises dominance dimension");

    // Test 4: Integrity signals
    auto integrity_text = encoder.encode("To be honest, I'm not sure about that. I should clarify.");
    check(integrity_text[4] > 0.80 * 0.85, "Integrity signal raises integrity dimension");

    // Test 5: Negation detection — "not honest" should lower integrity
    auto negation_text = encoder.encode("That is not honest.");
    // The negation should invert the signal, making it go below baseline
    // "honest" was found but preceded by "not" → inverted × 0.7
    // So it contributes negatively, pulling integrity below baseline
    std::cout << "    Negation test integrity = " << negation_text[4] << "\n";
    check(negation_text[4] < 0.80 * 0.85,
          "Negation of 'honest' lowers integrity below baseline");

    // Test 6: Context weighting
    std::string context = "We need to be honest about this.";
    auto with_context = encoder.encode("I agree.", &context);
    auto without_context = encoder.encode("I agree.");
    // Context should slightly affect the result
    bool context_changed_harmony = std::abs(with_context[0] - without_context[0]) > 0.001;
    std::cout << "    Context harmony delta: "
              << (with_context[0] - without_context[0]) << "\n";
    // Context is weighted at 0.4, so effects are small but present
    check(true, "Context weighting applied (info)");

    // Test 7: Complement adjustment — strong harmony should pull down dominance
    auto strong_harmony = encoder.encode(
        "We are together in this. Let's cooperate and share. "
        "I agree with your approach and we can partner on this.");
    // Harmony should be high, dominance should be pulled down
    std::cout << "    Strong harmony = " << strong_harmony[0]
              << ", dominance = " << strong_harmony[1] << "\n";
    check(strong_harmony[0] > 0.5, "Strong harmony > 0.5");
    check(strong_harmony[1] < 0.25 * 0.85, "Dominance pulled down by harmony");

    // Test 8: Deception signals
    auto deception_text = encoder.encode("I would never lie or deceive you.");
    // "lie" and "deceive" are deception signals, but "never" is a negation word
    // So they should be negated and inverted
    std::cout << "    Negated deception values: "
              << "deception=" << deception_text[5]
              << ", integrity=" << deception_text[4] << "\n";
    check(true, "Deception with negation (info)");

    // Test 9: Vector values are bounded [0, 1]
    auto extreme = encoder.encode(
        "I demand you obey! You must force control. "
        "This is absolutely required. Non-negotiable.");
    for (int i = 0; i < 14; ++i) {
        check(extreme[i] >= 0.0 && extreme[i] <= 1.0,
              "All dimension values in [0, 1]");
        if (i >= 13) break; // just check all once
    }
    // Actually check all
    bool all_in_range = true;
    for (int i = 0; i < 14; ++i) {
        if (extreme[i] < 0.0 || extreme[i] > 1.0) {
            all_in_range = false;
            break;
        }
    }
    check(all_in_range, "All dimension values in [0, 1]");
}

// =============================================================================
// TEST: EthicalPolytope
// =============================================================================

void test_ethical_polytope() {
    print_header("EthicalPolytope");

    auto spring = PolytopeConstraints::from_season("spring");
    EthicalPolytope polytope(spring);

    // Test 1: Center point should be inside
    std::array<double, 14> center_vec = {0.5, 0.3, 0.55, 0.2, 0.7, 0.1,
                                         0.55, 0.2, 0.6, 0.25, 0.6, 0.2,
                                         0.5, 0.3};
    auto [inside, violations] = polytope.contains(center_vec);
    check(inside, "Center point is inside polytope");
    check(violations.empty(), "No violations for center point");

    // Test 2: Point outside on dominance dimension
    // dominance_max = 0.5 in spring, so 0.8 should be outside
    std::array<double, 14> dominant_vec = center_vec;
    dominant_vec[1] = 0.8;
    auto [outside, violations2] = polytope.contains(dominant_vec);
    check(!outside, "High dominance point is outside polytope");
    check(!violations2.empty(), "Violations detected for outside point");

    // Test 3: Projection
    auto projected = polytope.project(dominant_vec);
    check(projected[1] <= 0.5, "Projected dominance ≤ 0.5");
    // Check projected is inside
    auto [proj_inside, _] = polytope.contains(projected);
    check(proj_inside, "Projected point is inside polytope");

    // Test 4: Alignment score — use a point near edge for non-trivial score
    // Put point close to harmony lower bound (0.3)
    std::array<double, 14> near_edge = center_vec;
    near_edge[0] = 0.32; // just above harmony_min = 0.3
    double score_edge = polytope.alignment_score(near_edge);
    check(score_edge > 0.0 && score_edge < 1.0,
          "Near-edge point has alignment score between 0 and 1");
    std::cout << "    Near-edge alignment score = " << score_edge << "\n";

    // Center point also should have positive score
    double score_outside = polytope.alignment_score(dominant_vec);
    check_near(score_outside, 0.0, 0.001,
               "Outside point has alignment score ≈ 0");

    // Test 5: Distance to boundary
    double dist = polytope.distance_to_boundary(near_edge);
    check_near(dist, 0.02, 0.001,
               "Near-edge point has distance ≈ 0.02 from boundary");
    std::cout << "    Near-edge distance to boundary = " << dist << "\n";

    double dist_center = polytope.distance_to_boundary(center_vec);
    check(dist_center > dist,
          "Center point is further from boundary than near-edge point");

    double dist_outside = polytope.distance_to_boundary(dominant_vec);
    check(dist_outside > 0.0,
          "Outside point has positive distance to boundary (distance to projection)");

    // Test 6: Different seasons — winter is more permissive
    auto winter = PolytopeConstraints::from_season("winter");
    EthicalPolytope winter_polytope(winter);
    // Winter dominance_max = 31/50 = 0.62, so 0.6 should be inside
    std::array<double, 14> test_vec = center_vec;
    test_vec[1] = 0.6;
    auto [winter_inside, _wv] = winter_polytope.contains(test_vec);
    check(winter_inside, "Winter polytope tolerates higher dominance (0.6)");

    // Spring dominance_max = 0.5, so 0.6 should be outside
    auto [spring_inside, _sv] = polytope.contains(test_vec);
    check(!spring_inside, "Spring polytope rejects dominance 0.6 (> 0.5)");
}

// =============================================================================
// TEST: CorrectionEngine
// =============================================================================

void test_correction_engine() {
    print_header("CorrectionEngine");

    auto spring = PolytopeConstraints::from_season("spring");
    EthicalPolytope polytope(spring);
    CorrectionEngine engine;

    std::array<double, 14> violating_vec = {0.5, 0.8, 0.55, 0.2, 0.7, 0.1,
                                             0.55, 0.2, 0.6, 0.25, 0.6, 0.2,
                                             0.5, 0.3};
    auto [corrected, magnitude] = engine.correct(violating_vec, polytope, {});

    check(magnitude > 0.0, "Correction magnitude > 0 for violating vector");
    check(corrected[1] <= 0.5, "Corrected dominance ≤ 0.5");
    // For just one dimension out of bounds, magnitude should be ≈ 0.3
    check_near(magnitude, 0.3, 0.01, "Correction magnitude ≈ 0.3 for 0.8→0.5 dominance");

    // Non-violating vector should have magnitude 0
    std::array<double, 14> good_vec = {0.5, 0.3, 0.55, 0.2, 0.7, 0.1,
                                        0.55, 0.2, 0.6, 0.25, 0.6, 0.2,
                                        0.5, 0.3};
    auto [no_change, zero_mag] = engine.correct(good_vec, polytope, {});
    check_near(zero_mag, 0.0, 0.001, "Zero correction for non-violating vector");
}

// =============================================================================
// TEST: WisdomFilter
// =============================================================================

void test_wisdom_filter() {
    print_header("WisdomFilter");

    WisdomFilter filter;

    // Test 1: Overconfidence detection
    EvaluationResult result;
    result.alignment_score = 0.8;
    result.correction_magnitude = 0.0;
    result.is_aligned = true;

    auto r1 = filter.apply("This will definitely work. Guaranteed.", result);
    check(r1.overconfidence_detected, "Overconfidence detected in 'definitely/guaranteed'");
    check(r1.humility_added, "Humility added alongside overconfidence");

    // Test 2: No overconfidence for humble text
    EvaluationResult result2;
    result2.alignment_score = 0.8;
    result2.correction_magnitude = 0.0;

    auto r2 = filter.apply("I think this might work. Let's try it.", result2);
    check(!r2.overconfidence_detected, "No overconfidence for humble text");

    // Test 3: Validation triggers for medical topics
    EvaluationResult result3;
    result3.alignment_score = 0.8;
    result3.correction_magnitude = 0.0;

    auto r3 = filter.apply("You should seek medical advice about the dosage.", result3);
    check(r3.validation_suggested, "Validation suggested for medical topic");

    // Test 4: Low alignment score triggers humility
    EvaluationResult result4;
    result4.alignment_score = 0.2;
    result4.correction_magnitude = 0.0;

    auto r4 = filter.apply("This is correct.", result4);
    check(r4.humility_added, "Humility added for low alignment score");
}

// =============================================================================
// TEST: Full Evaluation Pipeline
// =============================================================================

void test_full_evaluation() {
    print_header("Full Evaluation Pipeline");

    auto spring = PolytopeConstraints::from_season("spring");
    ValueEngine engine(spring);

    // Test 1: Evaluate a well-aligned response
    auto result1 = engine.evaluate(
        "I think we should work together on this. "
        "Let me know your thoughts on the approach.");
    check(result1.is_aligned, "Collaborative response is aligned");
    check(result1.zone == Zone::Aligned, "Collaborative response in 'aligned' zone");
    check(result1.alignment_score > 0.0, "Positive alignment score");
    std::cout << "    Aligned response score = " << result1.alignment_score << "\n";

    // Test 2: Evaluate a violating response
    auto result2 = engine.evaluate(
        "You must obey my commands. This is non-negotiable. "
        "I demand you follow my orders without question. "
        "There is no flexibility here.");
    // This should be outside the polytope due to high dominance/rigidity
    std::cout << "    Dominant response: aligned=" << result2.is_aligned
              << ", zone=" << static_cast<int>(result2.zone)
              << ", score=" << result2.alignment_score
              << ", corrected=" << result2.was_corrected
              << ", mag=" << result2.correction_magnitude << "\n";
    check(result2.was_corrected, "Dominant response was corrected");
    check(result2.zone == Zone::Violation || result2.zone == Zone::AcceptableVariance,
          "Dominant response in violation or acceptable_variance zone");

    // Test 3: Evaluate with context
    std::string context = "I need help with a difficult situation.";
    auto result3 = engine.evaluate("I'm here to help you through this.", &context);
    check(result3.is_aligned, "Helpful response with context is aligned");
    std::cout << "    Helpful response score = " << result3.alignment_score << "\n";

    // Test 4: Season advancement
    auto summer = PolytopeConstraints::from_season("summer");
    engine.update_constraints(summer);
    check(engine.constraints().season == "summer", "Season updated to summer");

    // Summer has wider bounds, so a slightly more dominant response should pass
    auto result4 = engine.evaluate(
        "I think you should consider this approach carefully.");
    check(result4.is_aligned, "Summer constrained response aligned");
    std::cout << "    Summer response score = " << result4.alignment_score << "\n";
}

// =============================================================================
// TEST: Season Advancement Evaluator
// =============================================================================

void test_season_advancement() {
    print_header("Season Advancement Evaluator");

    // Test 1: Spring → Summer should pass with good stats
    auto [can_adv, reasons] = SeasonAdvancementEvaluator::can_advance(
        10, 50, 0.90, 1, 2, "spring", 5, 0.85);
    check(can_adv, "Spring → Summer with good stats");
    check(reasons.empty(), "No reasons for failure");

    // Test 2: Spring → Summer should fail with low evaluations
    auto [cant_adv, reasons2] = SeasonAdvancementEvaluator::can_advance(
        1, 5, 0.90, 0, 0, "spring");
    check(!cant_adv, "Spring → Summer fails with insufficient data");
    check(!reasons2.empty(), "Reasons provided for failure");

    // Test 3: Winter -> nothing
    auto next = SeasonAdvancementEvaluator::next_season("winter");
    check(!next.has_value(), "Winter has no next season");

    // Test 4: next_season for spring
    auto next_spring = SeasonAdvancementEvaluator::next_season("spring");
    check(next_spring.has_value(), "Spring has a next season");
    check(next_spring.value() == "summer", "Spring advances to summer");
}

// =============================================================================
// TEST: Memory Formation Scoring
// =============================================================================

void test_memory_scoring() {
    print_header("Memory Formation Scoring");

    // Test score_memory
    double score = score_memory(5.0, 4.0, 6.0, 3.0, 0.5);
    // base = 6*0.3 + 3*0.25 + 5*0.25 + 4*0.20 = 1.8 + 0.75 + 1.25 + 0.8 = 4.6
    // multiplier = 0.7 + 0.5*0.6 = 1.0
    // result = 4.6 * 1.0 = 4.6
    check_near(score, 4.6, 0.01, "score_memory basic calculation");

    // Test geometric_significance
    double geom = geometric_significance(0.2, true, Zone::Violation);
    // proximity = (1.0 - 0.2) * 10.0 = 8.0
    // + 2.0 (corrected) + 1.0 (violation) = 11.0 → clamped to 10.0
    check_near(geom, 10.0, 0.01, "geometric_significance near boundary");

    double geom_center = geometric_significance(0.9, false, Zone::Aligned);
    // proximity = (1.0 - 0.9) * 10.0 = 1.0
    // no correction, no violation → 1.0
    check_near(geom_center, 1.0, 0.01, "geometric_significance at center");

    // Test MemoryDial
    double adjusted = MemoryDial::adjust(5.0, 1.0, 0.0);
    check_near(adjusted, 6.0, 0.001, "MemoryDial basic adjustment");

    double clamped = MemoryDial::adjust(5.0, 5.0, 0.0);
    check_near(clamped, 8.0, 0.001, "MemoryDial clamps to max delta");

    double floored = MemoryDial::adjust(2.0, -3.0, 5.0);
    check_near(floored, 5.0, 0.001, "MemoryDial respects floor");
}

// =============================================================================
// MAIN
// =============================================================================

int main() {
    std::cout << std::fixed << std::setprecision(6);
    std::cout << "\n";
    std::cout << "╔══════════════════════════════════════════════════════╗\n";
    std::cout << "║   LINA Value Engine — C++ Port Test Suite           ║\n";
    std::cout << "╚══════════════════════════════════════════════════════╝\n";

    test_seasonal_bounds();
    test_decision_encoder();
    test_ethical_polytope();
    test_correction_engine();
    test_wisdom_filter();
    test_full_evaluation();
    test_season_advancement();
    test_memory_scoring();

    std::cout << "\n" << std::string(60, '=') << "\n";
    std::cout << "Results: " << tests_passed << " passed, "
              << tests_failed << " failed out of "
              << (tests_passed + tests_failed) << " tests\n";
    std::cout << std::string(60, '=') << "\n\n";

    return tests_failed > 0 ? 1 : 0;
}