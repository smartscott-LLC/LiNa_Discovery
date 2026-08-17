// ═══════════════════════════════════════════════════════════════════════════
//  memory_module_abi.cpp — C ABI implementation for LINA Memory Module
//
//  Wraps MemoryModule behind flat C structs and JSON-serialized complex
//  return types. No std::string, no std::vector, no exceptions cross the
//  ABI boundary (except via the JSON helper, which is local).
// ═══════════════════════════════════════════════════════════════════════════

#include "memory_module_abi.h"
#include "memory_module.hpp"
#include "../value_engine/value_engine.hpp"

#include <cstring>
#include <new>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <sstream>
#include <memory>
#include <algorithm>

// ── Namespace aliases ──────────────────────────────────────────────────────
namespace ve = lina::value_engine;
namespace mem = lina::memory_module;

// ── Wrapper struct — holds MemoryModule + shared_ptr to engine (borrowed) ─
struct MemoryWrapper {
    std::shared_ptr<ve::ValueEngine> engine;
    mem::MemoryModule module;
    mem::CarveMemoryState state;

    MemoryWrapper(ve::ValueEngine* raw_engine)
        : engine(raw_engine, [](ve::ValueEngine*) { /* no-op deleter — caller owns */ })
        , module(engine,
                 std::make_shared<mem::NullEmbeddingEngine>(),
                 std::make_shared<mem::InMemoryMemoryStore>())
        , state{}
    {}
};

// ── Simple in-place JSON builder (no allocations until final string) ───────
//     Since nlohmann/json is not available, we write a thin utility that
//     produces parseable JSON for the Python ctypes consumer.

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

std::string row_to_json(const mem::MemoryItemRow& row) {
    std::ostringstream oss;
    oss << "{"
        << "\"item_id\":\"" << json_escape(row.item_id) << "\","
        << "\"user_id\":\"" << json_escape(row.user_id) << "\","
        << "\"hemisphere\":\"" << json_escape(row.hemisphere) << "\","
        << "\"kind\":\"" << json_escape(row.kind) << "\","
        << "\"status\":\"" << json_escape(row.status) << "\","
        << "\"narrative\":\"" << json_escape(row.narrative) << "\","
        << "\"concept_name\":" << (row.concept_name ? "\"" + json_escape(*row.concept_name) + "\"" : "null") << ","
        << "\"understanding\":" << (row.understanding ? "\"" + json_escape(*row.understanding) + "\"" : "null") << ","
        << "\"importance_score\":" << row.importance_score << ","
        << "\"floor\":" << (row.floor ? std::to_string(*row.floor) : "null") << ","
        << "\"must_keep\":" << (row.must_keep ? "true" : "false") << ","
        << "\"protected_flag\":" << (row.protected_flag ? "true" : "false") << ","
        << "\"emotional_marker\":\"" << json_escape(row.emotional_marker) << "\","
        << "\"emotional_intensity\":" << row.emotional_intensity << ","
        << "\"formation_source\":\"" << json_escape(row.formation_source) << "\","
        << "\"seasonal_marker\":" << (row.seasonal_marker ? "\"" + json_escape(*row.seasonal_marker) + "\"" : "null") << ","
        << "\"reference_count\":" << row.reference_count << ","
        << "\"last_referenced_at\":" << (row.last_referenced_at ? "\"" + json_escape(*row.last_referenced_at) + "\"" : "null") << ","
        << "\"created_at\":" << (row.created_at ? "\"" + json_escape(row.created_at.value()) + "\"" : "null") << ","
        << "\"decay_started_at\":" << (row.decay_started_at ? "\"" + json_escape(*row.decay_started_at) + "\"" : "null")
        << "}";
    return oss.str();
}

std::string context_section_to_json(
    const std::vector<std::unordered_map<std::string, std::string>>& items)
{
    std::string json = "[";
    for (size_t i = 0; i < items.size(); ++i) {
        if (i > 0) json += ",";
        json += "{";
        size_t j = 0;
        for (const auto& [key, val] : items[i]) {
            if (j > 0) json += ",";
            json += "\"" + json_escape(key) + "\":\"" + json_escape(val) + "\"";
            ++j;
        }
        json += "}";
    }
    json += "]";
    return json;
}

} // anonymous namespace

// ── Lifecycle ──────────────────────────────────────────────────────────────

void* lina_memory_create(void* engine) {
    if (!engine) return nullptr;
    auto* raw = static_cast<ve::ValueEngine*>(engine);
    auto* wrapper = new (std::nothrow) MemoryWrapper(raw);
    return static_cast<void*>(wrapper);
}

void lina_memory_destroy(void* memory) {
    if (!memory) return;
    delete static_cast<MemoryWrapper*>(memory);
}

// ── Formation ──────────────────────────────────────────────────────────────

lina_formation_counts_t lina_memory_form_items(
    void* memory, const char* user_id, const char* narratives_json,
    const char* source, const char* season, bool trigger)
{
    lina_formation_counts_t counts = {0, 0, 0};
    if (!memory || !user_id || !narratives_json || !source) return counts;

    auto* wrapper = static_cast<MemoryWrapper*>(memory);

    // Parse JSON array. Each element is either:
    //   - A plain string (narrative only, uses default factors)
    //   - An object {"narrative":"...", "emotional_weight":9.0, ...}
    // Simple parser — no dependencies, handles both formats.
    std::vector<mem::MemoryItem> moments;
    std::string json(narratives_json);

    // Find the first '[' or skip whitespace
    size_t pos = json.find_first_of('[');
    if (pos == std::string::npos) return counts;
    pos = pos + 1;

    while (pos < json.size()) {
        // Skip whitespace
        while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                     json[pos] == '\n' || json[pos] == '\r'))
            ++pos;
        if (pos >= json.size() || json[pos] == ']') break;

        std::string narrative;
        std::unordered_map<std::string, double> factors;
        bool has_object = (json[pos] == '{');

        if (has_object) {
            // Object format: parse key-value pairs
            ++pos; // skip '{'
            while (pos < json.size() && json[pos] != '}') {
                // Skip whitespace
                while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                             json[pos] == '\n' || json[pos] == '\r'))
                    ++pos;
                if (pos >= json.size() || json[pos] == '}') break;

                // Find key (quoted string)
                if (json[pos] != '"') { ++pos; continue; }
                ++pos; // skip opening quote
                std::string key;
                while (pos < json.size() && json[pos] != '"') {
                    if (json[pos] == '\\' && pos + 1 < json.size()) {
                        key += json[pos + 1];
                        pos += 2;
                    } else {
                        key += json[pos];
                        ++pos;
                    }
                }
                if (pos < json.size()) ++pos; // skip closing quote

                // Skip colon
                while (pos < json.size() && json[pos] != ':') ++pos;
                if (pos < json.size()) ++pos; // skip ':'

                // Skip whitespace
                while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t'))
                    ++pos;

                if (key == "narrative") {
                    // String value
                    if (pos < json.size() && json[pos] == '"') {
                        ++pos;
                        while (pos < json.size() && json[pos] != '"') {
                            if (json[pos] == '\\' && pos + 1 < json.size()) {
                                narrative += json[pos + 1];
                                pos += 2;
                            } else {
                                narrative += json[pos];
                                ++pos;
                            }
                        }
                        if (pos < json.size()) ++pos;
                    }
                } else if (key == "emotional_weight" ||
                           key == "relational_significance" ||
                           key == "identity_significance" ||
                           key == "emotional_intensity" ||
                           key == "emotional_marker") {
                    // Numeric value — parse double
                    char* end = nullptr;
                    double val = std::strtod(&json[pos], &end);
                    if (end != &json[pos]) {
                        factors[key] = val;
                        pos = end - &json[0];
                    }
                } else {
                    // Skip unknown value
                    if (pos < json.size() && json[pos] == '"') {
                        ++pos;
                        while (pos < json.size() && json[pos] != '"') {
                            if (json[pos] == '\\') pos += 2;
                            else ++pos;
                        }
                        if (pos < json.size()) ++pos;
                    } else {
                        char* end = nullptr;
                        std::strtod(&json[pos], &end);
                        if (end != &json[pos]) pos = end - &json[0];
                        else ++pos;
                    }
                }

                // Skip comma
                while (pos < json.size() && (json[pos] == ',' || json[pos] == ' '))
                    ++pos;
            }
            if (pos < json.size() && json[pos] == '}') ++pos; // skip '}'
        } else if (json[pos] == '"') {
            // Plain string format
            ++pos;
            while (pos < json.size() && json[pos] != '"') {
                if (json[pos] == '\\' && pos + 1 < json.size()) {
                    narrative += json[pos + 1];
                    pos += 2;
                } else {
                    narrative += json[pos];
                    ++pos;
                }
            }
            if (pos < json.size()) ++pos;
        }

        if (!narrative.empty()) {
            // Use default factors for any not explicitly provided
            if (factors.find("emotional_weight") == factors.end())
                factors["emotional_weight"] = 8.0;
            if (factors.find("relational_significance") == factors.end())
                factors["relational_significance"] = 7.0;
            if (factors.find("identity_significance") == factors.end())
                factors["identity_significance"] = 9.0;
            if (factors.find("emotional_intensity") == factors.end())
                factors["emotional_intensity"] = 0.9;

            moments.push_back(wrapper->module.build_item(
                user_id, narrative, factors, source,
                season ? std::optional<std::string>(season) : std::nullopt,
                trigger));
        }

        // Skip comma
        while (pos < json.size() && (json[pos] == ',' || json[pos] == ' '))
            ++pos;
    }

    if (moments.empty()) return counts;

    auto result = wrapper->module.form_items(
        user_id, moments, source,
        season ? std::optional<std::string>(season) : std::nullopt,
        trigger);

    counts.t1 = std::get<0>(result);
    counts.long_term = std::get<1>(result);
    counts.crown = std::get<2>(result);

    return counts;
}

char* lina_memory_ingest_trigger(
    void* memory, const char* user_id, const char* narrative,
    const char* kind, const char* season)
{
    if (!memory || !user_id || !narrative || !kind) {
        char* empty = new (std::nothrow) char[1];
        if (empty) empty[0] = '\0';
        return empty;
    }

    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    std::unordered_map<std::string, double> factors;
    factors["importance"] = 0.95;

    auto item = wrapper->module.ingest_trigger(
        user_id, narrative, kind,
        season ? std::optional<std::string>(season) : std::nullopt,
        factors);

    if (!item) {
        char* empty = new (std::nothrow) char[1];
        if (empty) empty[0] = '\0';
        return empty;
    }

    // Serialize item to JSON
    std::string json = "{"
        "\"item_id\":\"" + json_escape(item->item_id) + "\","
        "\"narrative\":\"" + json_escape(item->narrative) + "\","
        "\"importance_score\":" + std::to_string(item->importance_score) + ","
        "\"kind\":\"" + json_escape(item->kind) + "\""
        "}";

    char* result = new (std::nothrow) char[json.size() + 1];
    if (result) {
        std::memcpy(result, json.c_str(), json.size() + 1);
    }
    return result;
}

// ── Sweep & Maintenance ────────────────────────────────────────────────────

lina_sweep_counts_t lina_memory_run_sweep(void* memory) {
    lina_sweep_counts_t counts = {0, 0, 0, 0, 0, 0};
    if (!memory) return counts;
    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    auto result = wrapper->module.run_sweep();
    counts.t1_to_t2 = result.t1_to_t2;
    counts.t2_to_t3 = result.t2_to_t3;
    counts.to_long_term = result.to_long_term;
    counts.fallout = result.fallout;
    counts.repurposed = result.repurposed;
    counts.purged = result.purged;
    return counts;
}

lina_maintenance_counts_t lina_memory_run_maintenance(void* memory) {
    lina_maintenance_counts_t counts = {0, 0, 0, 0, 0};
    if (!memory) return counts;
    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    auto result = wrapper->module.run_maintenance();
    counts.adjusted = result.adjusted;
    counts.to_subconscious = result.to_subconscious;
    counts.to_legacy = result.to_legacy;
    counts.decayed = result.decayed;
    counts.forgotten = result.forgotten;
    return counts;
}

lina_review_counts_t lina_memory_run_legacy_review(void* memory) {
    lina_review_counts_t counts = {0, 0};
    if (!memory) return counts;
    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    auto result = wrapper->module.run_legacy_review();
    counts.reviewed = result.reviewed;
    counts.demoted = result.demoted;
    return counts;
}

// ── Recall & Context ───────────────────────────────────────────────────────

char* lina_memory_recall(
    void* memory, const char* user_id, const char* query,
    const char* hemisphere, int limit, bool include_subconscious)
{
    if (!memory || !user_id) {
        char* empty = new (std::nothrow) char[1];
        if (empty) empty[0] = '\0';
        return empty;
    }

    auto* wrapper = static_cast<MemoryWrapper*>(memory);

    std::optional<std::string> hemi;
    if (hemisphere && hemisphere[0] != '\0') hemi = std::string(hemisphere);

    std::string q = query ? query : "";
    auto rows = wrapper->module.recall(user_id, q, hemi, limit, include_subconscious);

    // Re-stoke: increment reference_count and update last_referenced_at
    // for each recalled item so Lina's act of looking reinforces the memory.
    auto* store = wrapper->module.store().get();
    if (store) {
        auto now = std::chrono::system_clock::now();
        auto now_time_t = std::chrono::system_clock::to_time_t(now);
        char now_buf[32];
        std::strftime(now_buf, sizeof(now_buf), "%Y-%m-%dT%H:%M:%S", std::gmtime(&now_time_t));
        std::string now_iso(now_buf);

        for (auto& row : rows) {
            row.reference_count++;
            row.last_referenced_at = now_iso;
            store->update_item(row);
        }
    }

    // Build JSON array
    std::string json = "[";
    for (size_t i = 0; i < rows.size(); ++i) {
        if (i > 0) json += ",";
        json += row_to_json(rows[i]);
    }
    json += "]";

    char* result = new (std::nothrow) char[json.size() + 1];
    if (result) {
        std::memcpy(result, json.c_str(), json.size() + 1);
    }
    return result;
}

char* lina_memory_inject_context(
    void* memory, const char* user_id, const char* query,
    int personal_limit, int wisdom_limit)
{
    if (!memory || !user_id) {
        char* empty = new (std::nothrow) char[1];
        if (empty) empty[0] = '\0';
        return empty;
    }

    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    std::string q = query ? query : "";

    auto context = wrapper->module.inject_context(user_id, q, personal_limit, wisdom_limit);

    // Build JSON object with "personal" and "wisdom" arrays
    std::string json = "{";
    json += "\"personal\":";
    if (context.count("personal")) {
        json += context_section_to_json(context["personal"]);
    } else {
        json += "[]";
    }
    json += ",\"wisdom\":";
    if (context.count("wisdom")) {
        json += context_section_to_json(context["wisdom"]);
    } else {
        json += "[]";
    }
    json += "}";

    char* result = new (std::nothrow) char[json.size() + 1];
    if (result) {
        std::memcpy(result, json.c_str(), json.size() + 1);
    }
    return result;
}

    // ── Post-Recall Update ─────────────────────────────────────────────────────

bool lina_memory_update_item(
    void* memory, const char* item_id, const char* update_json)
{
    if (!memory || !item_id || !update_json) return false;

    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    auto* store = wrapper->module.store().get();
    if (!store) return false;

    // Get current time as ISO string
    auto now = std::chrono::system_clock::now();
    auto now_time_t = std::chrono::system_clock::to_time_t(now);
    char now_buf[32];
    std::strftime(now_buf, sizeof(now_buf), "%Y-%m-%dT%H:%M:%S", std::gmtime(&now_time_t));
    std::string now_iso(now_buf);

    // Parse update JSON once
    std::string json(update_json);

    auto find_val = [&](const std::string& key) -> std::optional<double> {
        auto kpos = json.find("\"" + key + "\"");
        if (kpos == std::string::npos) return std::nullopt;
        auto colon = json.find(':', kpos);
        if (colon == std::string::npos) return std::nullopt;
        char* end = nullptr;
        double val = std::strtod(json.c_str() + colon + 1, &end);
        if (end == json.c_str() + colon + 1) return std::nullopt;
        return val;
    };
    auto find_str = [&](const std::string& key) -> std::optional<std::string> {
        auto kpos = json.find("\"" + key + "\"");
        if (kpos == std::string::npos) return std::nullopt;
        auto colon = json.find(':', kpos);
        if (colon == std::string::npos) return std::nullopt;
        auto qpos = json.find('"', colon + 1);
        if (qpos == std::string::npos) return std::nullopt;
        ++qpos;
        std::string val;
        while (qpos < json.size() && json[qpos] != '"') {
            if (json[qpos] == '\\' && qpos + 1 < json.size()) {
                val += json[qpos + 1];
                qpos += 2;
            } else {
                val += json[qpos];
                ++qpos;
            }
        }
        return val;
    };
    auto find_bool = [&](const std::string& key) -> std::optional<bool> {
        auto kpos = json.find("\"" + key + "\"");
        if (kpos == std::string::npos) return std::nullopt;
        auto colon = json.find(':', kpos);
        if (colon == std::string::npos) return std::nullopt;
        auto val_pos = colon + 1;
        while (val_pos < json.size() && json[val_pos] == ' ') ++val_pos;
        if (json.substr(val_pos, 4) == "true") return true;
        if (json.substr(val_pos, 5) == "false") return false;
        return std::nullopt;
    };

    // Is this an update to an existing item (re-stoke) or a new value?
    // First check long-term store by scanning all statuses
    std::string found_item_id;
    std::string found_narrative;
    std::string found_user_id;
    std::string found_hemisphere;
    std::string found_kind;
    std::string found_status;
    std::string found_emotional_marker;
    double found_emotional_intensity = 0.5;
    std::string found_formation_source;
    std::optional<std::string> found_seasonal_marker;
    std::vector<double> found_coords;
    int found_ref_count = 0;
    std::optional<std::string> found_last_ref;
    std::string found_created;
    std::optional<std::string> found_decay;
    std::optional<std::string> found_concept;
    std::optional<std::string> found_understanding;
    std::optional<double> found_floor;
    double found_importance = 0.0;
    bool found_protected = false;
    bool found_must_keep = false;
    bool found_item = false;

    // Search long-term store via fetch_by_status
    for (const char* status : {"active", "legacy", "subconscious"}) {
        auto items = store->fetch_by_status(status);
        for (const auto& row : items) {
            if (row.item_id == item_id) {
                found_item_id = row.item_id;
                found_narrative = row.narrative;
                found_user_id = row.user_id;
                found_hemisphere = row.hemisphere;
                found_kind = row.kind;
                found_status = row.status;
                found_emotional_marker = row.emotional_marker;
                found_emotional_intensity = row.emotional_intensity;
                found_formation_source = row.formation_source;
                found_seasonal_marker = row.seasonal_marker;
                found_coords = row.ethical_coordinates;
                found_ref_count = row.reference_count;
                found_last_ref = row.last_referenced_at;
                if (row.created_at) found_created = row.created_at.value();
                found_decay = row.decay_started_at;
                found_concept = row.concept_name;
                found_understanding = row.understanding;
                found_floor = row.floor;
                found_importance = row.importance_score;
                found_protected = row.protected_flag;
                found_must_keep = row.must_keep;
                found_item = true;
                break;
            }
        }
        if (found_item) break;
    }

    // If not found in long-term, search tiers
    if (!found_item) {
        static const char* TIERS[] = {"t1", "t2", "t3", "fallout"};
        for (const char* t : TIERS) {
            auto items = store->scan_tier(t);
            for (auto& [id, item] : items) {
                if (id == item_id) {
                    found_item_id = item.item_id;
                    found_narrative = item.narrative;
                    found_user_id = item.user_id;
                    found_hemisphere = item.hemisphere;
                    found_kind = item.kind;
                    found_status = item.status;
                    found_emotional_marker = item.emotional_marker;
                    found_emotional_intensity = item.emotional_intensity;
                    found_formation_source = item.formation_source;
                    found_seasonal_marker = item.seasonal_marker;
                    found_coords = item.ethical_coordinates;
                    found_ref_count = item.reference_count;
                    found_last_ref = item.last_referenced_at;
                    found_created = item.created_at;
                    found_decay = item.decay_started_at;
                    found_concept = item.concept_name;
                    found_understanding = item.understanding;
                    found_floor = item.floor;
                    found_importance = item.importance_score;
                    found_protected = item.protected_flag;
                    found_must_keep = item.must_keep;
                    found_item = true;
                    break;
                }
            }
            if (found_item) break;
        }
    }

    if (!found_item) return false;

    // Apply updates from JSON
    if (auto v = find_val("importance_score")) found_importance = *v;
    if (auto v = find_str("concept_name")) found_concept = *v;
    if (auto v = find_str("understanding")) found_understanding = *v;
    if (auto v = find_val("floor")) found_floor = *v;
    if (auto v = find_bool("protected_flag")) found_protected = *v;
    if (auto v = find_bool("must_keep")) found_must_keep = *v;

    // Auto re-stoke
    found_ref_count++;
    found_last_ref = now_iso;

    // Build MemoryItemRow and persist
    mem::MemoryItemRow row;
    row.item_id = found_item_id;
    row.narrative = found_narrative;
    row.user_id = found_user_id;
    row.hemisphere = found_hemisphere;
    row.kind = found_kind;
    row.status = found_status;
    row.emotional_marker = found_emotional_marker;
    row.emotional_intensity = found_emotional_intensity;
    row.formation_source = found_formation_source;
    row.seasonal_marker = found_seasonal_marker;
    row.ethical_coordinates = found_coords;
    row.reference_count = found_ref_count;
    row.last_referenced_at = found_last_ref;
    row.created_at = found_created.empty() ? std::nullopt : std::optional<std::string>(found_created);
    row.decay_started_at = found_decay;
    row.concept_name = found_concept;
    row.understanding = found_understanding;
    row.floor = found_floor;
    row.importance_score = found_importance;
    row.protected_flag = found_protected;
    row.must_keep = found_must_keep;

    store->update_item(row);
    return true;
}

// ── State ──────────────────────────────────────────────────────────────────

void lina_memory_get_state(void* memory, lina_memory_state_t* out) {
    if (!memory || !out) return;
    std::memset(out, 0, sizeof(*out));

    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    auto& s = wrapper->state;

    out->magic = s.magic;
    out->state_size = s.state_size;
    out->total_items_formed = s.total_items_formed;
    out->total_triggers = s.total_triggers;
    out->total_sweeps = s.total_sweeps;
    out->total_maintenance_runs = s.total_maintenance_runs;
    out->total_recalls = s.total_recalls;
    out->t1_current = s.t1_current;
    out->t2_current = s.t2_current;
    out->t3_current = s.t3_current;
    out->long_term_current = s.long_term_current;
    out->legacy_current = s.legacy_current;
    out->last_sweep_promoted = s.last_sweep_promoted;
    out->last_sweep_purged = s.last_sweep_purged;
    out->last_sweep_fallout = s.last_sweep_fallout;
    std::snprintf(out->current_season, sizeof(out->current_season), "%s",
                  s.current_season);
}

void lina_memory_reset_state(void* memory) {
    if (!memory) return;
    auto* wrapper = static_cast<MemoryWrapper*>(memory);
    wrapper->state = mem::CarveMemoryState{};
}

// ── Utility ────────────────────────────────────────────────────────────────

void lina_memory_free_string(char* str) {
    delete[] str;
}

const char* lina_memory_version(void) {
    return "0.1.0";
}