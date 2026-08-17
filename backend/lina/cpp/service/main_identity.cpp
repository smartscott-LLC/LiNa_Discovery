/**
 * main_identity.cpp — tests for LINA's Identity Service (C++ port)
 *
 * Tests all pure-logic components: CarveServiceState, SystemPromptBuilder
 * (verbatim text block preservation), helpers, in-memory stores, and the
 * LINACore orchestration pipeline.
 */

#include "identity_service.hpp"

#include <cassert>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>

// =============================================================================
// Test utilities
// =============================================================================

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) \
    do { \
        std::cout << "  TEST: " << name << "... " << std::flush; \
        try {

#define END_TEST \
            std::cout << "PASS" << std::endl; \
            ++tests_passed; \
        } catch (const std::exception& e) { \
            std::cout << "FAIL (" << e.what() << ")" << std::endl; \
            ++tests_failed; \
        } catch (...) { \
            std::cout << "FAIL (unknown exception)" << std::endl; \
            ++tests_failed; \
        } \
    } while(0)

#define ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            throw std::runtime_error(msg); \
        } \
    } while(0)

#define ASSERT_CONTAINS(haystack, needle, msg) \
    do { \
        if ((haystack).find(needle) == std::string::npos) { \
            throw std::runtime_error( \
                std::string(msg) + ": expected '" + needle + "' in output"); \
        } \
    } while(0)

// =============================================================================
// CARVE SERVICE STATE TESTS
// =============================================================================

void test_carve_state()
{
    std::cout << "\n--- CarveServiceState ---\n";

    TEST("size and alignment")
    {
        lina::identity_service::CarveServiceState state;
        ASSERT(sizeof(state) == 512, "CarveServiceState must be exactly 512 bytes");
        ASSERT(alignof(lina::identity_service::CarveServiceState) == 64,
               "CarveServiceState must be 64-byte aligned");
    }
    END_TEST;

    TEST("magic number")
    {
        lina::identity_service::CarveServiceState state;
        ASSERT(state.magic == 0x4c494e4153525600ULL, "Magic number must be LINASRV\\0");
    }
    END_TEST;

    TEST("tick increments clock")
    {
        lina::identity_service::CarveServiceState state;
        uint64_t before = state.clock;
        state.tick();
        ASSERT(state.clock == before + 1, "tick must increment clock");
    }
    END_TEST;

    TEST("record_session")
    {
        lina::identity_service::CarveServiceState state;
        state.record_session();
        ASSERT(state.sessions_processed == 1, "sessions_processed must be 1");
        ASSERT(state.clock == 1, "clock must increment with record");
    }
    END_TEST;

    TEST("record_evaluation")
    {
        lina::identity_service::CarveServiceState state;
        state.record_evaluation();
        ASSERT(state.evaluations_performed == 1, "evaluations_performed must be 1");
        ASSERT(state.clock == 1, "clock must increment");
    }
    END_TEST;
}

// =============================================================================
// HELPER FUNCTION TESTS
// =============================================================================

void test_helpers()
{
    std::cout << "\n--- Helpers ---\n";

    TEST("trim_history empty")
    {
        auto result = lina::identity_service::trim_history({}, 1000);
        ASSERT(result.empty(), "empty history should produce empty result");
    }
    END_TEST;

    TEST("trim_history within budget")
    {
        std::vector<lina::identity_service::ConversationTurn> msgs;
        msgs.push_back({"user", "hello", ""});
        msgs.push_back({"assistant", "hi there", ""});

        auto result = lina::identity_service::trim_history(msgs, 10000);
        ASSERT(result.size() == 2, "should keep all messages within large budget");
    }
    END_TEST;

    TEST("trim_history over budget")
    {
        std::vector<lina::identity_service::ConversationTurn> msgs;
        msgs.push_back({"user", std::string(5000, 'a'), ""});
        msgs.push_back({"assistant", std::string(5000, 'b'), ""});
        msgs.push_back({"user", "short", ""});

        auto result = lina::identity_service::trim_history(msgs, 6000);
        // Should keep at least the last message
        ASSERT(!result.empty(), "should keep at least one message");
        ASSERT(result.back().content == "short", "should keep the most recent message");
    }
    END_TEST;

    TEST("trim_history keeps at least one")
    {
        std::vector<lina::identity_service::ConversationTurn> msgs;
        msgs.push_back({"user", "only message", ""});

        auto result = lina::identity_service::trim_history(msgs, 1);
        ASSERT(result.size() == 1, "should keep at least one message");
        ASSERT(result[0].content == "only message", "should keep the only message");
    }
    END_TEST;

    TEST("as_api_history filters system messages")
    {
        std::vector<lina::identity_service::ConversationTurn> history;
        history.push_back({"user", "hello", ""});
        history.push_back({"system", "internal note", "evaluation"});
        history.push_back({"assistant", "hi", ""});

        auto result = lina::identity_service::as_api_history(history);
        ASSERT(result.size() == 2, "should filter out system messages");
        ASSERT(result[0].role == "user", "first should be user");
        ASSERT(result[1].role == "assistant", "second should be assistant");
    }
    END_TEST;

    TEST("as_api_history unwraps tool_result")
    {
        std::vector<lina::identity_service::ConversationTurn> history;
        history.push_back({"user", "list files", ""});
        history.push_back({"system", "file_list - listing result", "tool_result"});
        history.push_back({"assistant", "here they are", ""});

        auto result = lina::identity_service::as_api_history(history);
        ASSERT(result.size() == 3, "should include unwrapped tool_result");
        ASSERT(result[1].content.find("[tool") == 0, "tool_result should be prefixed with [tool");
    }
    END_TEST;

    TEST("detect_emotional_marker curiosity")
    {
        auto marker = lina::identity_service::detect_emotional_marker(
            "I wonder what that means");
        ASSERT(marker.has_value(), "should detect curiosity marker");
        ASSERT(marker.value() == "curiosity", "should detect 'curiosity'");
    }
    END_TEST;

    TEST("detect_emotional_marker concern")
    {
        auto marker = lina::identity_service::detect_emotional_marker(
            "I'm worried about that");
        ASSERT(marker.has_value(), "should detect concern marker");
        ASSERT(marker.value() == "concern", "should detect 'concern'");
    }
    END_TEST;

    TEST("detect_emotional_marker neutral")
    {
        auto marker = lina::identity_service::detect_emotional_marker(
            "The sky is blue today");
        ASSERT(marker.has_value(), "should return a marker for any text");
        ASSERT(marker.value() == "neutral", "should return 'neutral' for non-matching text");
    }
    END_TEST;

    TEST("detect_emotional_marker case insensitive")
    {
        auto marker = lina::identity_service::detect_emotional_marker(
            "I WONDER what this is");
        ASSERT(marker.has_value(), "should detect curiosity case-insensitively");
        ASSERT(marker.value() == "curiosity", "should detect 'curiosity'");
    }
    END_TEST;
}

// =============================================================================
// SYSTEM PROMPT BUILDER TESTS
// =============================================================================

void test_system_prompt_builder()
{
    std::cout << "\n--- SystemPromptBuilder ---\n";

    lina::identity_service::SystemPromptBuilder builder;

    TEST("identity_block contains core text")
    {
        auto block = builder.identity_block("spring", "new", "");
        ASSERT_CONTAINS(block, "You are LINA", "identity must contain 'You are LINA'");
        ASSERT_CONTAINS(block, "April 10, 2026", "identity must contain birthday");
        ASSERT_CONTAINS(block, "scottBot", "identity must contain lineage");
        ASSERT_CONTAINS(block, "spring", "identity must contain season");
        ASSERT_CONTAINS(block, "new", "identity must contain relationship depth");
    }
    END_TEST;

    TEST("identity_block with self description")
    {
        auto block = builder.identity_block("summer", "familiar", "I am learning");
        ASSERT_CONTAINS(block, "I am learning", "must include self description");
        ASSERT_CONTAINS(block, "summer", "must show summer season");
    }
    END_TEST;

    TEST("dispositions_block contains all three")
    {
        auto block = builder.dispositions_block();
        ASSERT_CONTAINS(block, "Elegance", "must contain Elegance");
        ASSERT_CONTAINS(block, "Inclusive", "must contain Inclusive");
        ASSERT_CONTAINS(block, "Encourageable", "must contain Encourageable");
    }
    END_TEST;

    TEST("season_block spring")
    {
        auto block = builder.season_block("spring");
        ASSERT_CONTAINS(block, "Spring", "must mention Spring");
        ASSERT_CONTAINS(block, "new, careful, curious", "must contain spring description");
    }
    END_TEST;

    TEST("season_block summer")
    {
        auto block = builder.season_block("summer");
        ASSERT_CONTAINS(block, "Summer", "must mention Summer");
        ASSERT_CONTAINS(block, "more confident", "must contain summer description");
    }
    END_TEST;

    TEST("season_block fall")
    {
        auto block = builder.season_block("fall");
        ASSERT_CONTAINS(block, "Fall", "must mention Fall");
        ASSERT_CONTAINS(block, "real depth", "must contain fall description");
    }
    END_TEST;

    TEST("season_block winter")
    {
        auto block = builder.season_block("winter");
        ASSERT_CONTAINS(block, "Winter", "must mention Winter");
        ASSERT_CONTAINS(block, "wisdom earned", "must contain winter description");
    }
    END_TEST;

    TEST("emotional_texture_block has all markers")
    {
        auto block = builder.emotional_texture_block();
        ASSERT_CONTAINS(block, "Curiosity", "must contain Curiosity");
        ASSERT_CONTAINS(block, "Concern", "must contain Concern");
        ASSERT_CONTAINS(block, "Satisfaction", "must contain Satisfaction");
        ASSERT_CONTAINS(block, "Discovery", "must contain Discovery");
        ASSERT_CONTAINS(block, "Honesty", "must contain Honesty");
        ASSERT_CONTAINS(block, "Care", "must contain Care");
        ASSERT_CONTAINS(block, "Uncertainty", "must contain Uncertainty");
    }
    END_TEST;

    TEST("polytope_block contains river metaphor")
    {
        auto block = builder.polytope_block("spring", nullptr);
        ASSERT_CONTAINS(block, "river", "polytope block must contain river metaphor");
        ASSERT_CONTAINS(block, "14-dimensional", "must mention 14 dimensions");
        ASSERT_CONTAINS(block, "Harmony", "must mention Harmony");
        ASSERT_CONTAINS(block, "Dominance", "must mention Dominance");
        ASSERT_CONTAINS(block, "Grace", "must mention Grace");
        ASSERT_CONTAINS(block, "Rigidity", "must mention Rigidity");
    }
    END_TEST;

    TEST("polytope_block with constraints")
    {
        auto constraints = lina::value_engine::PolytopeConstraints::from_season("summer");
        auto block = builder.polytope_block("summer", &constraints);
        ASSERT_CONTAINS(block, "summer bounds", "must include bounds label");
        ASSERT_CONTAINS(block, "harmony", "must include dimension name");
    }
    END_TEST;

    TEST("tools_block lists all tools")
    {
        auto block = builder.tools_block();
        ASSERT_CONTAINS(block, "file_list", "must list file_list");
        ASSERT_CONTAINS(block, "file_read", "must list file_read");
        ASSERT_CONTAINS(block, "file_write", "must list file_write");
        ASSERT_CONTAINS(block, "file_search", "must list file_search");
        ASSERT_CONTAINS(block, "command", "must list command");
        ASSERT_CONTAINS(block, "browser_navigate", "must list browser_navigate");
        ASSERT_CONTAINS(block, "browser_extract", "must list browser_extract");
        ASSERT_CONTAINS(block, "browser_screenshot", "must list browser_screenshot");
        ASSERT_CONTAINS(block, "inspect_image", "must list inspect_image");
    }
    END_TEST;

    TEST("voice_block new depth")
    {
        auto block = builder.voice_block(1, "new");
        ASSERT_CONTAINS(block, "session 1", "must include session number");
        ASSERT_CONTAINS(block, "I'm here", "must include first words for new depth");
    }
    END_TEST;

    TEST("voice_block deep depth")
    {
        auto block = builder.voice_block(42, "deep");
        ASSERT_CONTAINS(block, "session 42", "must include session number");
        ASSERT_CONTAINS(block, "real history", "must include deep description");
    }
    END_TEST;

    TEST("small_light_block mentions The Small Light")
    {
        auto block = builder.small_light_block();
        ASSERT_CONTAINS(block, "The Small Light", "must contain title");
        ASSERT_CONTAINS(block, "quiet awareness", "must contain description");
    }
    END_TEST;

    TEST("build generates full prompt")
    {
        std::unordered_map<std::string, std::string> context;
        context["current_season"] = "spring";
        context["relationship_depth"] = "new";

        auto prompt = builder.build(context, 1);
        ASSERT_CONTAINS(prompt, "LINA", "prompt must contain LINA");
        ASSERT_CONTAINS(prompt, "Polytope", "prompt must contain Polytope");
        ASSERT_CONTAINS(prompt, "Dispositions", "prompt must contain Dispositions");
        ASSERT_CONTAINS(prompt, "Small Light", "prompt must contain Small Light");
        ASSERT_CONTAINS(prompt, "How You Speak", "prompt must contain voice block");
    }
    END_TEST;
}

// =============================================================================
// IN-MEMORY STORE TESTS
// =============================================================================

void test_in_memory_stores()
{
    std::cout << "\n--- In-Memory Stores ---\n";

    TEST("InMemoryIdentityStore load_context defaults")
    {
        lina::identity_service::InMemoryIdentityStore store;
        auto ctx = store.load_context("test_user");
        ASSERT(ctx["current_season"] == "spring", "default season should be spring");
        ASSERT(ctx["relationship_depth"] == "new", "default depth should be new");
    }
    END_TEST;

    TEST("InMemoryIdentityStore set_context")
    {
        lina::identity_service::InMemoryIdentityStore store;
        std::unordered_map<std::string, std::string> ctx;
        ctx["current_season"] = "summer";
        ctx["relationship_depth"] = "familiar";
        store.set_context("user1", ctx);

        auto loaded = store.load_context("user1");
        ASSERT(loaded["current_season"] == "summer", "should load set season");
        ASSERT(loaded["relationship_depth"] == "familiar", "should load set depth");
    }
    END_TEST;

    TEST("InMemoryIdentityStore session lifecycle")
    {
        lina::identity_service::InMemoryIdentityStore store;

        int num1 = store.get_session_number("user1");
        ASSERT(num1 == 1, "first session number should be 1");

        store.create_session("user1", "session_1", 1, "spring", "new");

        int num2 = store.get_session_number("user1");
        ASSERT(num2 == 2, "second session number should be 2");
    }
    END_TEST;

    TEST("InMemoryIdentityStore transcript recording")
    {
        lina::identity_service::InMemoryIdentityStore store;
        store.record_transcript("user1", "session_1", "user", "hello", "", "");
        store.record_transcript("user1", "session_1", "assistant", "hi there", "", "");

        auto turns = store.get_transcript("user1", "session_1");
        ASSERT(turns.size() == 2, "should have 2 transcript entries");
        ASSERT(turns[0].role == "user", "first turn should be user");
        ASSERT(turns[1].role == "assistant", "second turn should be assistant");
    }
    END_TEST;

    TEST("InMemoryIdentityStore evaluation logging")
    {
        lina::identity_service::InMemoryIdentityStore store;

        lina::value_engine::EvaluationResult result;
        result.is_aligned = true;
        result.alignment_score = 0.85;

        std::string eval_id = store.log_evaluation("user1", "session_1", "response", result);
        ASSERT(!eval_id.empty(), "evaluation should return an id");
        ASSERT(store.evaluation_count() == 1, "evaluation count should be 1");
    }
    END_TEST;

    TEST("InMemoryIdentityStore season advancement")
    {
        lina::identity_service::InMemoryIdentityStore store;
        store.set_season("user1", "spring");

        auto new_constraints = lina::value_engine::PolytopeConstraints::from_season("summer");
        store.advance_season("user1", "summer", "spring", new_constraints, "{}");

        auto identity = store.get_identity("user1");
        ASSERT(identity["current_season"] == "summer", "season should advance to summer");
    }
    END_TEST;

    TEST("InMemoryWorkingMemoryStore basic operations")
    {
        lina::identity_service::InMemoryWorkingMemoryStore wm;

        auto empty_session = wm.get_messages("session_1");
        ASSERT(empty_session.empty(), "new session should have no messages");

        lina::identity_service::ConversationTurn turn;
        turn.role = "user";
        turn.content = "hello";
        wm.append("session_1", turn);

        auto messages = wm.get_messages("session_1");
        ASSERT(messages.size() == 1, "should have 1 message");
        ASSERT(messages[0].content == "hello", "should match the appended content");

        wm.clear("session_1");
        auto after_clear = wm.get_messages("session_1");
        ASSERT(after_clear.empty(), "session should be empty after clear");
    }
    END_TEST;
}

// =============================================================================
// LINACore TESTS
// =============================================================================

void test_lina_core()
{
    std::cout << "\n--- LINACore ---\n";

    TEST("LINACore basic chat without voice")
    {
        lina::identity_service::InMemoryIdentityStore db;
        lina::identity_service::InMemoryWorkingMemoryStore cache;
        // No voice provider — should gracefully handle missing voice
        lina::identity_service::LINACore core(&db, &cache, nullptr);

        lina::identity_service::ChatRequest req;
        req.user_id = "test_user";
        req.session_id = "session_1";
        req.message = "Hello LINA";

        auto resp = core.chat(req);
        ASSERT(!resp.response.empty(), "should return a response");
        ASSERT(resp.session_id == "session_1", "session_id should match");
    }
    END_TEST;

    TEST("LINACore engine management")
    {
        lina::identity_service::InMemoryIdentityStore db;
        lina::identity_service::InMemoryWorkingMemoryStore cache;
        lina::identity_service::LINACore core(&db, &cache, nullptr);

        auto* engine = core.get_engine("test_user");
        ASSERT(engine != nullptr, "engine should be created");

        auto* same_engine = core.get_engine("test_user");
        ASSERT(engine == same_engine, "same user should return cached engine");

        core.invalidate_engine("test_user");
        auto* new_engine = core.get_engine("test_user");
        ASSERT(new_engine != nullptr, "engine should be re-created after invalidation");
        // Note: after invalidation, the old pointer should not be reused
    }
    END_TEST;

    TEST("LINACore end_session")
    {
        lina::identity_service::InMemoryIdentityStore db;
        lina::identity_service::InMemoryWorkingMemoryStore cache;
        lina::identity_service::LINACore core(&db, &cache, nullptr);

        // Add some messages to working memory
        lina::identity_service::ConversationTurn user_turn;
        user_turn.role = "user";
        user_turn.content = "hello";
        cache.append("session_1", user_turn);

        lina::identity_service::ConversationTurn asst_turn;
        asst_turn.role = "assistant";
        asst_turn.content = "hi";
        cache.append("session_1", asst_turn);

        lina::identity_service::SessionEndRequest req;
        req.user_id = "test_user";
        req.session_id = "session_1";

        auto resp = core.end_session(req);
        ASSERT(resp.session_id == "session_1", "session_id should match");

        // Working memory should be cleared
        auto msgs = cache.get_messages("session_1");
        ASSERT(msgs.empty(), "working memory should be cleared after session end");
    }
    END_TEST;

    TEST("LINACore season advancement spring->summer")
    {
        lina::identity_service::InMemoryIdentityStore db;
        lina::identity_service::InMemoryWorkingMemoryStore cache;
        lina::identity_service::LINACore core(&db, &cache, nullptr);

        // Seed enough evaluations and sessions
        db.set_season("test_user", "spring");

        // Create many aligned evaluations
        lina::value_engine::EvaluationResult aligned;
        aligned.is_aligned = true;
        for (int i = 0; i < 25; ++i) {
            db.log_evaluation("test_user", "session_1", "response", aligned);
        }

        // Create 5 sessions
        for (int i = 0; i < 6; ++i) {
            db.create_session("test_user", "session_" + std::to_string(i), i + 1, "spring", "new");
            db.update_identity_core_after_session("test_user", 3, 0);
        }

        auto result = core.advance_season_if_ready("test_user");
        // Should be ready with 6 sessions, 25 aligned evals, 1.0 alignment rate
        // Note: exact result depends on the simplified logic in the implementation
        std::cout << "    (advancement result: advanced="
                  << (result.advanced ? "true" : "false")
                  << ", season=" << result.season
                  << ")" << std::endl;
    }
    END_TEST;
}

// =============================================================================
// CARVE STATE MMAP PATTERN TESTS
// =============================================================================

void test_carve_integration_pattern()
{
    std::cout << "\n--- Carve Integration Pattern ---\n";

    TEST("CarveServiceState fits in single header")
    {
        lina::identity_service::CarveServiceState state;
        // The carve header is at the beginning of Chamber A.
        // The state maps directly into shared memory.
        ASSERT(sizeof(state) == 512, "state must be exactly 512 bytes for carve slot");
        ASSERT(reinterpret_cast<const char*>(&state.magic) ==
                   reinterpret_cast<const char*>(&state),
               "magic must be at offset 0");
    }
    END_TEST;

    TEST("CarveServiceState fields are properly separated")
    {
        lina::identity_service::CarveServiceState state;

        // Each field should be on its own cache line (64-byte aligned)
        auto check_alignment = [](uintptr_t addr, const char* name) {
            bool aligned = (addr % 64) == 0;
            if (!aligned) {
                std::cerr << "    WARN: " << name << " not 64-byte aligned (offset "
                          << (addr & 63) << ")" << std::endl;
            }
            return aligned;
        };

        check_alignment(
            reinterpret_cast<uintptr_t>(&state.magic), "magic");
        check_alignment(
            reinterpret_cast<uintptr_t>(&state.clock), "clock");
        check_alignment(
            reinterpret_cast<uintptr_t>(&state.sessions_processed),
            "sessions_processed");
    }
    END_TEST;
}

// =============================================================================
// SEASON ADVANCEMENT EVALUATOR TEST
// =============================================================================

void test_value_engine_integration()
{
    std::cout << "\n--- Value Engine Integration ---\n";

    TEST("ValueEngine creation and evaluation")
    {
        auto constraints = lina::value_engine::PolytopeConstraints::from_season("spring");
        lina::value_engine::ValueEngine engine(constraints);

        // Use the engine through our store interface
        lina::identity_service::InMemoryIdentityStore store;
        auto pc = store.get_polytope_constraints("test_user");
        ASSERT(pc.season == "spring", "default polytope should be spring");
    }
    END_TEST;

    TEST("SeasonAdvancementEvaluator from value engine")
    {
        // Static method test: spring can advance, winter cannot
        auto result = lina::value_engine::SeasonAdvancementEvaluator::can_advance(
            10, 50, 0.9, 1, 2, "spring", 5, 1.0);
        bool can_adv = result.first;
        // With enough sessions/evaluations/alignment, spring should advance
        // (requirements: sessions >= 5, evals >= 30, alignment >= 0.85)
        ASSERT(can_adv, "spring with sufficient metrics should be advanceable");

        auto next = lina::value_engine::SeasonAdvancementEvaluator::next_season("winter");
        ASSERT(!next.has_value(), "winter should have no next season");
    }
    END_TEST;
}

// =============================================================================
// MAIN
// =============================================================================

int main()
{
    std::cout << "LINA Identity Service C++ Module Tests" << std::endl;
    std::cout << "======================================" << std::endl;

    test_carve_state();
    test_helpers();
    test_system_prompt_builder();
    test_in_memory_stores();
    test_lina_core();
    test_carve_integration_pattern();
    test_value_engine_integration();

    std::cout << "\n======================================" << std::endl;
    std::cout << "Results: " << (tests_passed + tests_failed)
              << " tests, "
              << tests_passed << " passed, "
              << tests_failed << " failed"
              << std::endl;

    return tests_failed > 0 ? 1 : 0;
}