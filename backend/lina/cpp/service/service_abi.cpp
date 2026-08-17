// ═══════════════════════════════════════════════════════════════════════════
//  service_abi.cpp — C ABI implementation for LINA Identity Service
//
//  Wraps LINACore (with InMemory stores + InMemoryVoiceProvider) behind
//  flat C functions. Complex return types (ChatResponse, etc.) are
//  serialized to JSON strings for the Python ctypes consumer.
// ═══════════════════════════════════════════════════════════════════════════

#include "service_abi.h"
#include "identity_service.hpp"

#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cctype>
#include <new>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
#include <ctime>
#include <iomanip>
#include <algorithm>

// ── Namespace alias ────────────────────────────────────────────────────────
namespace id = lina::identity_service;
namespace ve = lina::value_engine;

// ── JSON escape (duplicated from memory_module_abi.cpp for self-containment) ─
namespace {

std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 2);
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

// ── NoVoiceProvider — returns hard error when no real voice is available ───
//  This is the failsafe. When no real voice provider is wired (local llama.cpp
//  or siliconflow), the user gets a clear ``_LINA has no voice right now.``
//  rather than a canned response. Hard fail > silent fake.

class NoVoiceProvider : public id::VoiceProvider {
public:
    std::string generate(
        const std::string& system_prompt,
        const std::vector<id::ConversationTurn>& messages,
        int max_tokens) override
    {
        (void)system_prompt;
        (void)messages;
        (void)max_tokens;
        return "_LINA has no voice right now.";
    }

    bool available() const override { return false; }
    std::string name() const override { return "none"; }
};

// ── Wrapper struct ─────────────────────────────────────────────────────────
//  Owns all stores + voice provider + LINACore + CarveServiceState.
//  This is what the opaque void* handle points to.

struct CoreWrapper {
    id::InMemoryIdentityStore db;
    id::InMemoryWorkingMemoryStore cache;
    NoVoiceProvider voice;
    id::LINACore core;
    id::CarveServiceState state;

    CoreWrapper(const std::string& season, const std::string& user_id)
        : voice()
        , core(&db, &cache, &voice)
        , state{}
    {
        // Set up initial context for the user
        std::string s = season.empty() ? "spring" : season;
        std::unordered_map<std::string, std::string> ctx;
        ctx["current_season"] = s;
        db.set_context(user_id, ctx);
        db.set_season(user_id, s);
    }
};

// ── JSON serialization helpers ─────────────────────────────────────────────
//  These mirror the patterns in memory_module_abi.cpp.

std::string evaluation_result_to_json(const ve::EvaluationResult& eval) {
    std::ostringstream oss;
    oss << "{"
        << "\"is_aligned\":" << (eval.is_aligned ? "true" : "false") << ","
        << "\"alignment_score\":" << eval.alignment_score << ","
        << "\"zone\":\"";

    // Determine zone string
    switch (eval.zone) {
        case ve::Zone::Aligned:           oss << "aligned"; break;
        case ve::Zone::AcceptableVariance: oss << "acceptable_variance"; break;
        case ve::Zone::Violation:          oss << "violation"; break;
        default:                           oss << "aligned"; break;
    }

    oss << "\","
        << "\"was_corrected\":" << (eval.was_corrected ? "true" : "false") << ","
        << "\"correction_magnitude\":" << eval.correction_magnitude << ","
        << "\"wisdom_filter_applied\":" << (eval.wisdom_filter_applied ? "true" : "false") << ","
        << "\"overconfidence_detected\":" << (eval.overconfidence_detected ? "true" : "false") << ","
        << "\"humility_added\":" << (eval.humility_added ? "true" : "false") << ","
        << "\"validation_suggested\":" << (eval.validation_suggested ? "true" : "false");

    // Violations
    if (eval.violations.empty()) {
        oss << ",\"violations\":[]";
    } else {
        oss << ",\"violations\":[";
        for (size_t i = 0; i < eval.violations.size(); ++i) {
            if (i > 0) oss << ",";
            const auto& v = eval.violations[i];
            oss << "{\"name\":\"" << json_escape(v.name) << "\","
                << "\"value\":" << v.value << ","
                << "\"bound\":" << v.bound << ","
                << "\"type\":\"" << json_escape(v.type) << "\","
                << "\"severity\":" << v.severity
                << "}";
        }
        oss << "]";
    }

    // Wisdom adjustments
    if (eval.wisdom_adjustments.empty()) {
        oss << ",\"wisdom_adjustments\":[]";
    } else {
        oss << ",\"wisdom_adjustments\":[";
        for (size_t i = 0; i < eval.wisdom_adjustments.size(); ++i) {
            if (i > 0) oss << ",";
            oss << "\"" << json_escape(eval.wisdom_adjustments[i]) << "\"";
        }
        oss << "]";
    }

    oss << "}";
    return oss.str();
}

std::string tool_result_to_json(const id::ToolResult& tr) {
    std::ostringstream oss;
    oss << "{"
        << "\"tool\":\"" << json_escape(tr.tool) << "\","
        << "\"status\":\"" << json_escape(tr.status) << "\","
        << "\"output\":\"" << json_escape(tr.output) << "\","
        << "\"reason\":\"" << json_escape(tr.reason) << "\""
        << "}";
    return oss.str();
}

std::string chat_response_to_json(const id::ChatResponse& resp) {
    std::ostringstream oss;
    oss << "{"
        << "\"response\":\"" << json_escape(resp.response) << "\","
        << "\"session_id\":\"" << json_escape(resp.session_id) << "\","
        << "\"emotional_marker\":\"" << json_escape(resp.emotional_marker) << "\","
        << "\"evaluation\":" << evaluation_result_to_json(resp.evaluation) << ",";

    // Proposals
    if (resp.proposals.empty()) {
        oss << "\"proposals\":[]";
    } else {
        oss << "\"proposals\":[";
        for (size_t i = 0; i < resp.proposals.size(); ++i) {
            if (i > 0) oss << ",";
            oss << tool_result_to_json(resp.proposals[i]);
        }
        oss << "]";
    }

    // Foresight context
    if (resp.foresight_context.has_value()) {
        oss << ",\"foresight_context\":\"" << json_escape(resp.foresight_context.value()) << "\"";
    } else {
        oss << ",\"foresight_context\":null";
    }

    oss << "}";
    return oss.str();
}

std::string end_session_result_to_json(const id::SessionEndResponse& resp) {
    std::ostringstream oss;
    oss << "{"
        << "\"session_id\":\"" << json_escape(resp.session_id) << "\","
        << "\"t1_formed\":" << resp.t1_formed << ","
        << "\"long_term_formed\":" << resp.long_term_formed << ","
        << "\"crown_formed\":" << resp.crown_formed << ","
        << "\"moments_reflected\":" << resp.moments_reflected << ","
        << "\"alignment_maintained\":" << (resp.alignment_maintained ? "true" : "false");

    if (resp.season_advanced.has_value()) {
        oss << ",\"season_advanced\":\"" << json_escape(resp.season_advanced.value()) << "\"";
    } else {
        oss << ",\"season_advanced\":null";
    }

    oss << "}";
    return oss.str();
}

std::string season_result_to_json(const id::SeasonAdvancementResult& result) {
    std::ostringstream oss;
    oss << "{"
        << "\"advanced\":" << (result.advanced ? "true" : "false") << ","
        << "\"season\":\"" << json_escape(result.season) << "\","
        << "\"previous_season\":\"" << json_escape(result.previous_season) << "\",";

    if (result.session_number.has_value()) {
        oss << "\"session_number\":" << result.session_number.value() << ",";
    } else {
        oss << "\"session_number\":null,";
    }

    // Reasons as JSON array
    if (result.reasons.empty()) {
        oss << "\"reasons\":[]";
    } else {
        oss << "\"reasons\":[";
        for (size_t i = 0; i < result.reasons.size(); ++i) {
            if (i > 0) oss << ",";
            oss << "\"" << json_escape(result.reasons[i]) << "\"";
        }
        oss << "]";
    }

    oss << "}";
    return oss.str();
}

void copy_state_to_c(const id::CarveServiceState& src, lina_service_state_t* dst) {
    if (!dst) return;
    std::memset(dst, 0, sizeof(*dst));
    dst->magic = src.magic;
    dst->clock = src.clock;
    dst->sessions_processed = src.sessions_processed;
    dst->evaluations_performed = src.evaluations_performed;
    dst->tools_executed = src.tools_executed;
    dst->corrections_made = src.corrections_made;
    dst->seasonal_advancements = src.seasonal_advancements;
    dst->total_tokens_generated = src.total_tokens_generated;
}

} // anonymous namespace

// =============================================================================
// ABI IMPLEMENTATIONS
// =============================================================================

LINA_SRV_API void* lina_core_create(const char* season, const char* user_id) {
    if (!season || !user_id) return nullptr;

    try {
        auto* wrapper = new CoreWrapper(
            std::string(season),
            std::string(user_id));
        return static_cast<void*>(wrapper);
    } catch (const std::exception&) {
        return nullptr;
    }
}

LINA_SRV_API void lina_core_destroy(void* core) {
    if (!core) return;
    delete static_cast<CoreWrapper*>(core);
}

LINA_SRV_API char* lina_core_chat(
    void* core,
    const char* user_id,
    const char* session_id,
    const char* message)
{
    if (!core || !user_id || !session_id || !message) return nullptr;

    try {
        auto* wrapper = static_cast<CoreWrapper*>(core);

        id::ChatRequest req;
        req.user_id = user_id;
        req.session_id = session_id;
        req.message = message;

        auto response = wrapper->core.chat(req);
        std::string json = chat_response_to_json(response);

        char* result = static_cast<char*>(std::malloc(json.size() + 1));
        if (!result) return nullptr;
        std::memcpy(result, json.c_str(), json.size() + 1);
        return result;
    } catch (const std::exception&) {
        return nullptr;
    }
}

LINA_SRV_API char* lina_core_end_session(
    void* core,
    const char* user_id,
    const char* session_id)
{
    if (!core || !user_id || !session_id) return nullptr;

    try {
        auto* wrapper = static_cast<CoreWrapper*>(core);

        id::SessionEndRequest req;
        req.user_id = user_id;
        req.session_id = session_id;

        auto response = wrapper->core.end_session(req);
        std::string json = end_session_result_to_json(response);

        char* result = static_cast<char*>(std::malloc(json.size() + 1));
        if (!result) return nullptr;
        std::memcpy(result, json.c_str(), json.size() + 1);
        return result;
    } catch (const std::exception&) {
        return nullptr;
    }
}

LINA_SRV_API char* lina_core_advance_season(
    void* core,
    const char* user_id,
    int session_number)
{
    if (!core || !user_id) return nullptr;

    try {
        auto* wrapper = static_cast<CoreWrapper*>(core);

        auto result = wrapper->core.advance_season_if_ready(
            user_id,
            session_number >= 0
                ? std::optional<int>(session_number)
                : std::nullopt);

        std::string json = season_result_to_json(result);

        char* out = static_cast<char*>(std::malloc(json.size() + 1));
        if (!out) return nullptr;
        std::memcpy(out, json.c_str(), json.size() + 1);
        return out;
    } catch (const std::exception&) {
        return nullptr;
    }
}

LINA_SRV_API void lina_core_evaluate(
    void* core,
    const char* user_id,
    const char* response,
    lina_evaluation_result_t* result)
{
    if (!core || !user_id || !response || !result) return;

    try {
        auto* wrapper = static_cast<CoreWrapper*>(core);
        auto* engine = wrapper->core.get_engine(user_id);

        if (!engine) {
            lina_evaluation_result_init(result);
            return;
        }

        std::string user_id_str(user_id);
        auto eval = engine->evaluate(std::string(response), &user_id_str);

        // Map C++ EvaluationResult to C lina_evaluation_result_t
        result->is_aligned = eval.is_aligned;
        result->alignment_score = eval.alignment_score;

        // Decision vector
        for (int i = 0; i < LINA_DIMENSION_COUNT && i < 14; ++i) {
            result->decision_vector[i] = eval.decision_vector[i];
        }

        // Violations (up to LINA_MAX_VIOLATIONS=3)
        result->violation_count = std::min(
            static_cast<int>(eval.violations.size()),
            LINA_MAX_VIOLATIONS);
        for (int i = 0; i < result->violation_count; ++i) {
            result->violation_dimensions[i] = eval.violations[i].dimension;
            std::strncpy(result->violation_names[i],
                eval.violations[i].name.c_str(),
                LINA_VIOLATION_NAME_MAX - 1);
            result->violation_names[i][LINA_VIOLATION_NAME_MAX - 1] = '\0';
            result->violation_values[i] = eval.violations[i].value;
            result->violation_bounds[i] = eval.violations[i].bound;
            std::strncpy(result->violation_types[i],
                eval.violations[i].type.c_str(),
                LINA_VIOLATION_TYPE_MAX - 1);
            result->violation_types[i][LINA_VIOLATION_TYPE_MAX - 1] = '\0';
            result->violation_severities[i] = eval.violations[i].severity;
        }

        // Correction
        result->was_corrected = eval.was_corrected;
        result->correction_magnitude = eval.correction_magnitude;
        for (int i = 0; i < LINA_DIMENSION_COUNT && i < 14; ++i) {
            result->correction_vector[i] = eval.correction_vector[i];
        }

        // Wisdom
        result->wisdom_filter_applied = eval.wisdom_filter_applied;
        result->overconfidence_detected = eval.overconfidence_detected;
        result->humility_added = eval.humility_added;
        result->validation_suggested = eval.validation_suggested;

        // Zone
        switch (eval.zone) {
            case ve::Zone::Aligned:
                std::strncpy(result->zone, "aligned", LINA_ZONE_MAX - 1);
                break;
            case ve::Zone::AcceptableVariance:
                std::strncpy(result->zone, "acceptable_variance", LINA_ZONE_MAX - 1);
                break;
            case ve::Zone::Violation:
                std::strncpy(result->zone, "violation", LINA_ZONE_MAX - 1);
                break;
            default:
                std::strncpy(result->zone, "aligned", LINA_ZONE_MAX - 1);
                break;
        }
        result->zone[LINA_ZONE_MAX - 1] = '\0';
        result->boundary_distance = eval.boundary_distance;
        result->variance_margin_used = eval.variance_margin_used;

        // Season
        std::strncpy(result->season, eval.season.c_str(), LINA_SEASON_MAX - 1);
        result->season[LINA_SEASON_MAX - 1] = '\0';

    } catch (const std::exception&) {
        lina_evaluation_result_init(result);
    }
}

LINA_SRV_API void lina_core_get_state(void* core, lina_service_state_t* out) {
    if (!core || !out) return;

    auto* wrapper = static_cast<CoreWrapper*>(core);
    copy_state_to_c(wrapper->state, out);
}

LINA_SRV_API void lina_core_free_string(char* str) {
    std::free(str);
}

LINA_SRV_API const char* lina_core_version(void) {
    return "lina-service-abi v1.0.0 -- LINACore C ABI";
}