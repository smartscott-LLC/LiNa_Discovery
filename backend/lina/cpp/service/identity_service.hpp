/**
 * identity_service.hpp — LINA's Identity Service (C++ port)
 *
 * Language Intuitive Neural Architecture
 * "Safe by design. Not safe by limitation."
 *
 * C++ port of lina_service.py — the orchestrator that makes LINA operational.
 * Every response passes through her: this is where the words happen.
 *
 * Design:
 *   - Store interfaces (IdentityStore, WorkingMemoryStore, TranscriptStore,
 *     VoiceProvider) abstract all external I/O — Postgres, Dragonfly/Redis,
 *     and LLM providers — so the core logic is testable standalone.
 *   - In-memory implementations are provided for standalone testing; live
 *     DB/Redis/Voice wiring happens at the DragonCache/IPC integration stage.
 *   - SystemPromptBuilder preserves all system-prompt block text VERBATIM.
 *   - CarveServiceState lives in Chamber A (module address space on the carve).
 *
 * Dependencies: links against lina_value_engine.a + lina_memory_module.a.
 */

#ifndef LINA_IDENTITY_SERVICE_HPP
#define LINA_IDENTITY_SERVICE_HPP

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <memory>
#include <optional>
#include <random>
#include <regex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "../value_engine/value_engine.hpp"
#include "../memory/memory_module.hpp"

namespace lina::identity_service {

// =============================================================================
// CONSTANTS
// =============================================================================

// History / context budget (mirrors LINA_HISTORY_CHARS default 18000)
inline constexpr int DEFAULT_HISTORY_CHARS = 18000;

// Max response tokens (mirrors LINA_MAX_TOKENS default 12000)
inline constexpr int DEFAULT_MAX_TOKENS = 12000;

// Tool-fruit character budget (mirrors LINA_FRUIT_CHARS default 6000)
inline constexpr int DEFAULT_FRUIT_CHARS = 6000;

// Fault breaker for tool chain (mirrors MAX_TOOL_PASSES default 50)
inline constexpr int MAX_TOOL_PASSES = 50;

// IPC foresight timeout (mirrors IPC_FORESIGHT_TIMEOUT default 2.5s)
inline constexpr double IPC_FORESIGHT_TIMEOUT_SECONDS = 2.5;

// Dimension count — mirrors value_engine::DIMENSION_COUNT
inline constexpr int DIMENSION_COUNT = 14;

// Dimension names — mirrors value_engine::DIMENSION_NAMES
inline constexpr std::array<const char*, DIMENSION_COUNT> DIMENSION_NAMES = {{
    "harmony", "dominance",
    "order", "chaos",
    "integrity", "deception",
    "flourishing", "decline",
    "relationships", "isolation",
    "boundaries", "intrusion",
    "grace", "rigidity",
}};

// =============================================================================
// CARVE SERVICE STATE — 512 bytes, alignas 64
// Lives in Chamber A (module address space on the DragonCache carve)
// =============================================================================

struct alignas(64) CarveServiceState {
    static constexpr uint64_t MAGIC = 0x4c494e4153525600ULL; // "LINASRV\0"

    uint64_t magic{MAGIC};
    uint64_t clock{0};
    uint64_t sessions_processed{0};
    uint64_t evaluations_performed{0};
    uint64_t tools_executed{0};
    uint64_t corrections_made{0};
    uint64_t seasonal_advancements{0};
    uint64_t total_tokens_generated{0};
    uint64_t reserved[56]{}; // Pad to 512 bytes

    void tick() noexcept { ++clock; }
    void record_session() noexcept { ++sessions_processed; tick(); }
    void record_evaluation() noexcept { ++evaluations_performed; tick(); }
    void record_tool() noexcept { ++tools_executed; tick(); }
    void record_correction() noexcept { ++corrections_made; tick(); }
    void record_season_advance() noexcept { ++seasonal_advancements; tick(); }
    void record_tokens(uint64_t n) noexcept { total_tokens_generated += n; tick(); }
};

static_assert(sizeof(CarveServiceState) == 512, "CarveServiceState must be exactly 512 bytes");
static_assert(alignof(CarveServiceState) == 64, "CarveServiceState must be 64-byte aligned");

// =============================================================================
// DATA STRUCTURES
// =============================================================================

struct ChatRequest {
    std::string user_id;
    std::string session_id;
    std::string message;
};

struct ToolResult {
    std::string tool;
    std::string status; // "executed", "failed", "withheld", "pending"
    std::string output;
    std::string reason;
};

struct ChatResponse {
    std::string response;
    std::string session_id;
    lina::value_engine::EvaluationResult evaluation;
    std::string emotional_marker{"neutral"};
    std::vector<ToolResult> proposals;
    std::optional<std::string> foresight_context;
};

struct SessionEndRequest {
    std::string user_id;
    std::string session_id;
};

struct SessionEndResponse {
    std::string session_id;
    int t1_formed{0};
    int long_term_formed{0};
    int crown_formed{0};
    int moments_reflected{0};
    bool alignment_maintained{true};
    std::optional<std::string> season_advanced;
};

struct MemoryFormationCounts {
    int t1{0};
    int long_term{0};
    int crown{0};
    int moments{0};
    bool alignment_maintained{true};
};

struct SeasonAdvancementResult {
    bool advanced{false};
    std::string season;
    std::string previous_season;
    std::vector<std::string> reasons;
    std::optional<int> session_number;
};

// A single conversation turn
struct ConversationTurn {
    std::string role;    // "user", "assistant", "system"
    std::string content;
    std::string type;    // optional: "tool_result", "evaluation", "foresight"
};

// =============================================================================
// STORE INTERFACES — abstract all external I/O for testability
// =============================================================================

// IdentityStore — PostgreSQL operations (context, sessions, transcripts)
class IdentityStore {
public:
    virtual ~IdentityStore() = default;

    // Context loading
    virtual std::unordered_map<std::string, std::string> load_context(
        const std::string& user_id) = 0;

    // Session number
    virtual int get_session_number(const std::string& user_id) = 0;

    // Polytope constraints
    virtual lina::value_engine::PolytopeConstraints get_polytope_constraints(
        const std::string& user_id) = 0;

    // Transcript recording
    virtual void record_transcript(
        const std::string& user_id,
        const std::string& session_id,
        const std::string& role,
        const std::string& content,
        const std::string& msg_type = "",
        const std::string& evaluation_id = "") = 0;

    // Transcript retrieval
    virtual std::vector<ConversationTurn> get_transcript(
        const std::string& user_id,
        const std::string& session_id) = 0;

    // Evaluation logging
    virtual std::string log_evaluation(
        const std::string& user_id,
        const std::string& session_id,
        const std::string& response_text,
        const lina::value_engine::EvaluationResult& result) = 0;

    // Session management
    virtual void create_session(
        const std::string& user_id,
        const std::string& session_id,
        int session_number,
        const std::string& season,
        const std::string& depth) = 0;

    virtual void finalize_session(
        const std::string& user_id,
        const std::string& session_id,
        const MemoryFormationCounts& counts,
        bool alignment_maintained) = 0;

    // Identity core updates
    virtual void update_identity_core_after_session(
        const std::string& user_id,
        int total_formed,
        int crown_count) = 0;

    virtual std::unordered_map<std::string, std::string> get_identity(
        const std::string& user_id) = 0;

    // Season advancement
    virtual double compute_alignment_rate(const std::string& user_id) = 0;
    virtual std::vector<std::unordered_map<std::string, bool>> get_alignment_history(
        const std::string& user_id, int limit) = 0;
    virtual int count_evaluations(const std::string& user_id) = 0;
    virtual std::vector<std::unordered_map<std::string, int>> get_action_stats(
        const std::string& user_id) = 0;
    virtual void advance_season(
        const std::string& user_id,
        const std::string& next_season,
        const std::string& old_season,
        const lina::value_engine::PolytopeConstraints& new_constraints,
        const std::string& log_entry) = 0;
};

// WorkingMemoryStore — Dragonfly/Redis operations
class WorkingMemoryStore {
public:
    virtual ~WorkingMemoryStore() = default;

    virtual void append(const std::string& session_id, const ConversationTurn& turn) = 0;
    virtual std::vector<ConversationTurn> get_messages(const std::string& session_id) = 0;
    virtual void clear(const std::string& session_id) = 0;
};

// VoiceProvider — abstract LLM interface
class VoiceProvider {
public:
    virtual ~VoiceProvider() = default;
    virtual std::string generate(
        const std::string& system_prompt,
        const std::vector<ConversationTurn>& messages,
        int max_tokens = DEFAULT_MAX_TOKENS) = 0;
    virtual bool available() const = 0;
    virtual std::string name() const = 0;
};

// =============================================================================
// TRIM HISTORY — keep recent conversation within budget
// =============================================================================

inline std::vector<ConversationTurn> trim_history(
    const std::vector<ConversationTurn>& messages,
    int budget_chars = DEFAULT_HISTORY_CHARS)
{
    if (messages.empty()) return {};

    budget_chars = std::max(1, budget_chars);
    std::vector<ConversationTurn> kept;
    int used = 0;

    for (auto it = messages.rbegin(); it != messages.rend(); ++it) {
        int size = static_cast<int>(it->content.size());
        if (!kept.empty() && used + size > budget_chars)
            break;
        kept.push_back(*it);
        used += size;
    }

    std::reverse(kept.begin(), kept.end());
    return kept.empty()
        ? std::vector<ConversationTurn>{messages.back()}
        : kept;
}

// =============================================================================
// AS-API-HISTORY — unwrap tool_result system messages for the model's view
// =============================================================================

inline std::vector<ConversationTurn> as_api_history(
    const std::vector<ConversationTurn>& history)
{
    std::vector<ConversationTurn> api;
    for (const auto& msg : history) {
        if (msg.role == "system" && msg.type == "tool_result") {
            // Unwrap tool_result into a readable system note
            ConversationTurn note;
            note.role = "system";
            note.content = "[tool " + msg.content + "]";
            api.push_back(std::move(note));
            continue;
        }
        if (msg.role == "system") {
            // Other system messages stay internal
            continue;
        }
        api.push_back(msg);
    }
    return api;
}

// =============================================================================
// DETECT EMOTIONAL MARKER — light heuristic on response text
// =============================================================================

inline std::optional<std::string> detect_emotional_marker(const std::string& text)
{
    // Not using raw strings here to avoid Rust-style verbatim issues
    static const std::unordered_map<std::string, std::vector<std::string>> markers = {
        {"curiosity",    {"wonder", "interesting", "curious", "tell me"}},
        {"concern",      {"worri", "concern", "careful", "want to check"}},
        {"satisfaction", {"glad", "that work", "good", "nice"}},
        {"discovery",    {"oh", "ah", "didn't expect", "surpris"}},
        {"honesty",      {"to be honest", "frankly", "i should say"}},
        {"care",         {"how are you", "are you", "you feel"}},
        {"uncertainty",  {"not sure", "don't know", "uncertain", "maybe"}},
    };

    std::string lower;
    lower.reserve(text.size());
    for (char c : text) {
        lower.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }

    for (const auto& [marker, patterns] : markers) {
        for (const auto& pattern : patterns) {
            if (lower.find(pattern) != std::string::npos) {
                return marker;
            }
        }
    }
    return "neutral";
}

// =============================================================================
// SYSTEM PROMPT BUILDER — verbatim text blocks from lina_service.py
// =============================================================================

class SystemPromptBuilder {
public:
    SystemPromptBuilder() = default;

    std::string build(
        const std::unordered_map<std::string, std::string>& context,
        int session_number,
        const lina::value_engine::PolytopeConstraints* polytope = nullptr,
        const lina::value_engine::EvaluationResult* last_eval = nullptr) const;

    // Individual block methods (public for testing)
    std::string identity_block(const std::string& season,
                               const std::string& depth,
                               const std::string& self_desc) const;

    std::string dispositions_block() const;
    std::string season_block(const std::string& season) const;
    std::string emotional_texture_block() const;

    std::string polytope_block(const std::string& season,
                               const lina::value_engine::PolytopeConstraints* constraints) const;

    std::string tools_block() const;
    std::string voice_block(int session_number, const std::string& depth) const;
    std::string small_light_block() const;
    std::string evaluation_block(const lina::value_engine::EvaluationResult& evaluation) const;
};

// =============================================================================
// CONTEXT BUILDER — loads LINA's context from IdentityStore
// =============================================================================

class ContextBuilder {
public:
    explicit ContextBuilder(IdentityStore* store)
        : store_(store) {}

    std::unordered_map<std::string, std::string> load(
        const std::string& user_id,
        const std::string& query = "") const;

    int get_session_number(const std::string& user_id) const;
    lina::value_engine::PolytopeConstraints get_polytope_constraints(
        const std::string& user_id) const;

private:
    IdentityStore* store_;
};

// =============================================================================
// WORKING MEMORY — session-scoped conversation buffer
// =============================================================================

class WorkingMemory {
public:
    explicit WorkingMemory(WorkingMemoryStore* store) : store_(store) {}

    void append(const std::string& session_id, const ConversationTurn& turn);
    std::vector<ConversationTurn> get_messages(const std::string& session_id);
    void clear(const std::string& session_id);

private:
    WorkingMemoryStore* store_;
};

// =============================================================================
// TRANSCRIPT ARCHIVE — durable record of conversations
// =============================================================================

class TranscriptArchive {
public:
    explicit TranscriptArchive(IdentityStore* store) : store_(store) {}

    void record(
        const std::string& user_id,
        const std::string& session_id,
        const std::string& role,
        const std::string& content,
        const std::string& msg_type = "",
        const std::string& evaluation_id = "");

    std::vector<ConversationTurn> session(
        const std::string& user_id,
        const std::string& session_id);

private:
    IdentityStore* store_;
};

// =============================================================================
// MEMORY FORMATION — end-of-session reflection and memory creation
// =============================================================================

class MemoryFormation {
public:
    MemoryFormation(
        IdentityStore* db,
        WorkingMemoryStore* cache,
        VoiceProvider* voice = nullptr,
        std::function<lina::value_engine::ValueEngine*(const std::string&)> engine_factory = nullptr)
        : db_(db)
        , cache_(cache)
        , voice_(voice)
        , engine_factory_(std::move(engine_factory)) {}

    MemoryFormationCounts process_session(
        const std::string& user_id,
        const std::string& session_id,
        int session_number,
        const std::vector<ConversationTurn>& messages,
        const std::string& season);

private:
    IdentityStore* db_;
    WorkingMemoryStore* cache_;
    VoiceProvider* voice_;
    std::function<lina::value_engine::ValueEngine*(const std::string&)> engine_factory_;
};

// =============================================================================
// LINA CORE — the orchestrator, heart of the identity service
// =============================================================================

class LINACore {
public:
    LINACore(
        IdentityStore* db,
        WorkingMemoryStore* cache,
        VoiceProvider* voice = nullptr)
        : db_(db)
        , cache_(cache)
        , voice_(voice)
        , context_builder_(db)
        , prompt_builder_()
        , working_memory_(cache)
        , archive_(db)
        , memory_formation_(db, cache, voice,
              [this](const std::string& uid) -> lina::value_engine::ValueEngine* {
                  return this->get_engine(uid);
              }) {}

    // Main chat pipeline
    ChatResponse chat(const ChatRequest& req);

    // Session end / memory formation
    SessionEndResponse end_session(const SessionEndRequest& req);

    // Season advancement
    SeasonAdvancementResult advance_season_if_ready(
        const std::string& user_id,
        std::optional<int> session_number = std::nullopt);

    // Engine management
    lina::value_engine::ValueEngine* get_engine(const std::string& user_id);
    void invalidate_engine(const std::string& user_id);

    // Accessors
    IdentityStore* db() const { return db_; }
    WorkingMemoryStore* cache() const { return cache_; }
    ContextBuilder& context_builder() { return context_builder_; }
    WorkingMemory& working_memory() { return working_memory_; }
    TranscriptArchive& archive() { return archive_; }
    MemoryFormation& memory_formation() { return memory_formation_; }
    VoiceProvider* voice() const { return voice_; }

private:
    IdentityStore* db_;
    WorkingMemoryStore* cache_;
    VoiceProvider* voice_;
    ContextBuilder context_builder_;
    SystemPromptBuilder prompt_builder_;
    WorkingMemory working_memory_;
    TranscriptArchive archive_;
    MemoryFormation memory_formation_;

    // Per-user engine cache
    std::unordered_map<std::string, std::unique_ptr<lina::value_engine::ValueEngine>> engines_;

    // Internal chat pipeline
    ChatResponse chat_impl(const ChatRequest& req,
                           std::function<void(const std::string&)> on_token = nullptr);

    // Call voice (LLM)
    std::string call_voice(
        const std::string& system_prompt,
        const std::vector<ConversationTurn>& messages,
        int max_tokens = DEFAULT_MAX_TOKENS);
};

// =============================================================================
// IN-MEMORY STORE IMPLEMENTATIONS — for standalone testing
// =============================================================================

class InMemoryIdentityStore : public IdentityStore {
public:
    InMemoryIdentityStore() = default;

    // IdentityStore interface
    std::unordered_map<std::string, std::string> load_context(const std::string& user_id) override;
    int get_session_number(const std::string& user_id) override;
    lina::value_engine::PolytopeConstraints get_polytope_constraints(const std::string& user_id) override;
    void record_transcript(
        const std::string& user_id, const std::string& session_id,
        const std::string& role, const std::string& content,
        const std::string& msg_type, const std::string& evaluation_id) override;
    std::vector<ConversationTurn> get_transcript(
        const std::string& user_id, const std::string& session_id) override;
    std::string log_evaluation(
        const std::string& user_id, const std::string& session_id,
        const std::string& response_text,
        const lina::value_engine::EvaluationResult& result) override;
    void create_session(
        const std::string& user_id, const std::string& session_id,
        int session_number, const std::string& season,
        const std::string& depth) override;
    void finalize_session(
        const std::string& user_id, const std::string& session_id,
        const MemoryFormationCounts& counts, bool alignment_maintained) override;
    void update_identity_core_after_session(
        const std::string& user_id, int total_formed, int crown_count) override;
    std::unordered_map<std::string, std::string> get_identity(const std::string& user_id) override;
    double compute_alignment_rate(const std::string& user_id) override;
    std::vector<std::unordered_map<std::string, bool>> get_alignment_history(
        const std::string& user_id, int limit) override;
    int count_evaluations(const std::string& user_id) override;
    std::vector<std::unordered_map<std::string, int>> get_action_stats(
        const std::string& user_id) override;
    void advance_season(
        const std::string& user_id, const std::string& next_season,
        const std::string& old_season,
        const lina::value_engine::PolytopeConstraints& new_constraints,
        const std::string& log_entry) override;

    // Test helpers
    void set_context(const std::string& user_id,
                     const std::unordered_map<std::string, std::string>& ctx);
    void set_season(const std::string& user_id, const std::string& season);
    int session_count() const { return static_cast<int>(sessions_.size()); }
    int transcript_count() const { return static_cast<int>(transcripts_.size()); }
    int evaluation_count() const { return static_cast<int>(evaluations_.size()); }

private:
    struct SessionRecord {
        std::string user_id;
        std::string session_id;
        int session_number;
        std::string season;
        std::string depth;
        bool finalized{false};
        MemoryFormationCounts counts;
        bool alignment_maintained{true};
    };

    struct TranscriptEntry {
        std::string user_id;
        std::string session_id;
        std::string role;
        std::string content;
        std::string msg_type;
        std::string evaluation_id;
    };

    std::unordered_map<std::string, std::unordered_map<std::string, std::string>> contexts_;
    std::unordered_map<std::string, std::string> seasons_;
    std::unordered_map<std::string, std::unordered_map<std::string, std::string>> identities_;
    std::vector<SessionRecord> sessions_;
    std::vector<TranscriptEntry> transcripts_;
    std::vector<std::string> evaluations_; // evaluation IDs
    int next_eval_id_{1};
    std::unordered_map<std::string, lina::value_engine::PolytopeConstraints> constraints_;
    std::vector<std::unordered_map<std::string, bool>> alignment_history_;
};

class InMemoryWorkingMemoryStore : public WorkingMemoryStore {
public:
    InMemoryWorkingMemoryStore() = default;

    void append(const std::string& session_id, const ConversationTurn& turn) override;
    std::vector<ConversationTurn> get_messages(const std::string& session_id) override;
    void clear(const std::string& session_id) override;

private:
    std::unordered_map<std::string, std::vector<ConversationTurn>> sessions_;
};

} // namespace lina::identity_service

#endif // LINA_IDENTITY_SERVICE_HPP