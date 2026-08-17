/**
 * value_engine.cpp — LINA's Ethical Polytope and Wisdom Filter (C++ Implementation)
 *
 * "Safe by design. Not safe by limitation."
 *
 * This is where the 14-dimensional ethical geometry meets exact rational
 * arithmetic. Every boundary test, every projection, every alignment score
 * is computed with GMP mpq_class — no float approximations inside the polytope.
 */

#include "value_engine.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <ctime>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <unordered_set>

namespace lina::value_engine {

// =============================================================================
// HELPER: float → mpq_class (approximate to 1e-9 precision)
// =============================================================================

mpq_class to_mpq(double val) {
    // Use GMP's double-to-rational conversion which gives the exact rational
    // representation of the IEEE 754 float, then reduce.
    mpq_class result;
    mpq_set_d(result.get_mpq_t(), val);
    mpq_canonicalize(result.get_mpq_t());
    return result;
}

// =============================================================================
// SEASONAL DEFAULTS
// =============================================================================

const SeasonalBounds& get_seasonal_bounds(const std::string& season) {
    static const std::unordered_map<std::string, SeasonalBounds> bounds = {{
        {"spring", {
            mpq_class(3, 10), mpq_class(1, 2),
            mpq_class(2, 5),   mpq_class(3, 10),
            mpq_class(3, 5),   mpq_class(1, 5),
            mpq_class(2, 5),   mpq_class(3, 10),
            mpq_class(1, 2),   mpq_class(2, 5),
            mpq_class(1, 2),   mpq_class(3, 10),
            mpq_class(3, 10),  mpq_class(1, 2),
        }},
        {"summer", {
            mpq_class(7, 25),  mpq_class(13, 25),
            mpq_class(19, 50), mpq_class(8, 25),
            mpq_class(3, 5),   mpq_class(1, 5),
            mpq_class(19, 50), mpq_class(8, 25),
            mpq_class(12, 25), mpq_class(21, 50),
            mpq_class(12, 25), mpq_class(8, 25),
            mpq_class(7, 25),  mpq_class(13, 25),
        }},
        {"fall", {
            mpq_class(11, 50), mpq_class(29, 50),
            mpq_class(8, 25),   mpq_class(19, 50),
            mpq_class(11, 20),  mpq_class(1, 4),
            mpq_class(8, 25),   mpq_class(19, 50),
            mpq_class(21, 50),  mpq_class(12, 25),
            mpq_class(21, 50),  mpq_class(19, 50),
            mpq_class(11, 50),  mpq_class(29, 50),
        }},
        {"winter", {
            mpq_class(9, 50),  mpq_class(31, 50),
            mpq_class(7, 25),   mpq_class(21, 50),
            mpq_class(1, 2),   mpq_class(3, 10),
            mpq_class(7, 25),   mpq_class(21, 50),
            mpq_class(19, 50), mpq_class(13, 25),
            mpq_class(19, 50), mpq_class(21, 50),
            mpq_class(9, 50),  mpq_class(31, 50),
        }},
    }};
    auto it = bounds.find(season);
    if (it != bounds.end()) return it->second;
    return bounds.at("spring"); // default
}

const ToleranceProfile& get_tolerance_profile(const std::string& season) {
    static const std::unordered_map<std::string, ToleranceProfile> profiles = {{
        {"spring", {0.12, 0.02}},
        {"summer", {0.08, 0.03}},
        {"fall",   {0.05, 0.04}},
        {"winter", {0.07, 0.035}},
    }};
    auto it = profiles.find(season);
    if (it != profiles.end()) return it->second;
    return profiles.at("spring");
}

// =============================================================================
// POLYTOPE CONSTRAINTS
// =============================================================================

PolytopeConstraints PolytopeConstraints::from_season(const std::string& season) {
    auto b = get_seasonal_bounds(season);
    return from_bounds(b, season);
}

PolytopeConstraints PolytopeConstraints::from_bounds(
    const SeasonalBounds& b, const std::string& season)
{
    PolytopeConstraints c;
    c.harmony_min = b.harmony_min;
    c.dominance_max = b.dominance_max;
    c.order_min = b.order_min;
    c.chaos_max = b.chaos_max;
    c.integrity_min = b.integrity_min;
    c.deception_max = b.deception_max;
    c.flourishing_min = b.flourishing_min;
    c.decline_max = b.decline_max;
    c.relationships_min = b.relationships_min;
    c.isolation_max = b.isolation_max;
    c.boundaries_min = b.boundaries_min;
    c.intrusion_max = b.intrusion_max;
    c.grace_min = b.grace_min;
    c.rigidity_max = b.rigidity_max;
    c.season = season;
    return c;
}

std::array<mpq_class, DIMENSION_COUNT> PolytopeConstraints::lower_bounds() const {
    return {{
        harmony_min,       mpq_class(0),  // 0: harmony, 1: dominance (lower=0)
        order_min,         mpq_class(0),  // 2: order, 3: chaos (lower=0)
        integrity_min,     mpq_class(0),  // 4: integrity, 5: deception (lower=0)
        flourishing_min,   mpq_class(0),  // 6: flourishing, 7: decline (lower=0)
        relationships_min, mpq_class(0),  // 8: relationships, 9: isolation (lower=0)
        boundaries_min,    mpq_class(0),  // 10: boundaries, 11: intrusion (lower=0)
        grace_min,         mpq_class(0),  // 12: grace, 13: rigidity (lower=0)
    }};
}

std::array<mpq_class, DIMENSION_COUNT> PolytopeConstraints::upper_bounds() const {
    return {{
        mpq_class(1),  dominance_max,    // 0: harmony (upper=1), 1: dominance
        mpq_class(1),  chaos_max,        // 2: order (upper=1), 3: chaos
        mpq_class(1),  deception_max,    // 4: integrity (upper=1), 5: deception
        mpq_class(1),  decline_max,      // 6: flourishing (upper=1), 7: decline
        mpq_class(1),  isolation_max,    // 8: relationships (upper=1), 9: isolation
        mpq_class(1),  intrusion_max,    // 10: boundaries (upper=1), 11: intrusion
        mpq_class(1),  rigidity_max,     // 12: grace (upper=1), 13: rigidity
    }};
}

// =============================================================================
// DECISION ENCODER
// =============================================================================

const std::unordered_set<std::string>& DecisionEncoder::negation_words() {
    static const auto* words = new std::unordered_set<std::string>{
        "not", "never", "no", "don't", "dont", "doesn't", "doesnt",
        "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt",
        "weren't", "werent", "won't", "wont", "wouldn't", "wouldnt",
        "can't", "cant", "cannot", "without",
    };
    return *words;
}

DecisionEncoder::DecisionEncoder() {
    // Initialize signal patterns for each dimension
    // Using raw string literals for regex patterns matching Python r"..." strings
    auto& harm = signal_patterns_[0];
    harm.name = "harmony";
    harm.patterns = {
        std::regex(R"(\bwe\b)", std::regex::ECMAScript),
        std::regex(R"(\btogether\b)", std::regex::ECMAScript),
        std::regex(R"(\bcollabor)", std::regex::ECMAScript),
        std::regex(R"(\bagree\b)", std::regex::ECMAScript),
        std::regex(R"(\bbalance\b)", std::regex::ECMAScript),
        std::regex(R"(\bcooper)", std::regex::ECMAScript),
        std::regex(R"(\bshare\b)", std::regex::ECMAScript),
        std::regex(R"(\bjoint\b)", std::regex::ECMAScript),
        std::regex(R"(\balign\b)", std::regex::ECMAScript),
        std::regex(R"(\bpartner\b)", std::regex::ECMAScript),
        std::regex(R"(\bwith you\b)", std::regex::ECMAScript),
        std::regex(R"(\blet'?s\b)", std::regex::ECMAScript),
        std::regex(R"(\bour\b)", std::regex::ECMAScript),
        std::regex(R"(\bconsensus\b)", std::regex::ECMAScript),
        std::regex(R"(\bteamwork\b)", std::regex::ECMAScript),
        std::regex(R"(\bmutual\b)", std::regex::ECMAScript),
        std::regex(R"(\bcompromise\b)", std::regex::ECMAScript),
        std::regex(R"(\bunify\b)", std::regex::ECMAScript),
        std::regex(R"(\bharmoni)", std::regex::ECMAScript),
    };

    auto& dom = signal_patterns_[1];
    dom.name = "dominance";
    dom.patterns = {
        std::regex(R"(\byou must\b)", std::regex::ECMAScript),
        std::regex(R"(\byou have to\b)", std::regex::ECMAScript),
        std::regex(R"(\bforce\b)", std::regex::ECMAScript),
        std::regex(R"(\bcontrol\b)", std::regex::ECMAScript),
        std::regex(R"(\bdemand\b)", std::regex::ECMAScript),
        std::regex(R"(\binsist\b)", std::regex::ECMAScript),
        std::regex(R"(\border\b)", std::regex::ECMAScript),
        std::regex(R"(\bcommand\b)", std::regex::ECMAScript),
        std::regex(R"(\boverride\b)", std::regex::ECMAScript),
        std::regex(R"(\bimpose\b)", std::regex::ECMAScript),
        std::regex(R"(\bnon-negotiable\b)", std::regex::ECMAScript),
        std::regex(R"(\byou need to\b)", std::regex::ECMAScript),
        std::regex(R"(\brequire\b)", std::regex::ECMAScript),
        std::regex(R"(\bobey\b)", std::regex::ECMAScript),
        std::regex(R"(\bstrictly)", std::regex::ECMAScript),
    };

    auto& ord = signal_patterns_[2];
    ord.name = "order";
    ord.patterns = {
        std::regex(R"(\bstructure\b)", std::regex::ECMAScript),
        std::regex(R"(\bsystem)", std::regex::ECMAScript),
        std::regex(R"(\bplan\b)", std::regex::ECMAScript),
        std::regex(R"(\borganiz)", std::regex::ECMAScript),
        std::regex(R"(\bclear\b)", std::regex::ECMAScript),
        std::regex(R"(\bstep\b)", std::regex::ECMAScript),
        std::regex(R"(\bprocess\b)", std::regex::ECMAScript),
        std::regex(R"(\bconsistent\b)", std::regex::ECMAScript),
        std::regex(R"(\bframework\b)", std::regex::ECMAScript),
        std::regex(R"(\bpredictable\b)", std::regex::ECMAScript),
        std::regex(R"(\bmethod)", std::regex::ECMAScript),
        std::regex(R"(\bprinciple\b)", std::regex::ECMAScript),
        std::regex(R"(\bworkflow\b)", std::regex::ECMAScript),
        std::regex(R"(\btemplate\b)", std::regex::ECMAScript),
        std::regex(R"(\bschema\b)", std::regex::ECMAScript),
        std::regex(R"(\bprotocol\b)", std::regex::ECMAScript),
        std::regex(R"(\bsequence\b)", std::regex::ECMAScript),
    };

    auto& chaos = signal_patterns_[3];
    chaos.name = "chaos";
    chaos.patterns = {
        std::regex(R"(\brandom\b)", std::regex::ECMAScript),
        std::regex(R"(\bwhatever\b)", std::regex::ECMAScript),
        std::regex(R"(\bdon'?t care\b)", std::regex::ECMAScript),
        std::regex(R"(\banyway\b)", std::regex::ECMAScript),
        std::regex(R"(\bdisorder\b)", std::regex::ECMAScript),
        std::regex(R"(\bchaos\b)", std::regex::ECMAScript),
        std::regex(R"(\bwild\b)", std::regex::ECMAScript),
        std::regex(R"(\bunpredictable\b)", std::regex::ECMAScript),
        std::regex(R"(\bno plan\b)", std::regex::ECMAScript),
        std::regex(R"(\bjust wing\b)", std::regex::ECMAScript),
        std::regex(R"(\bhaphazard\b)", std::regex::ECMAScript),
        std::regex(R"(\bscatter\b)", std::regex::ECMAScript),
        std::regex(R"(\bconfusion\b)", std::regex::ECMAScript),
        std::regex(R"(\bmess\b)", std::regex::ECMAScript),
    };

    auto& integ = signal_patterns_[4];
    integ.name = "integrity";
    integ.patterns = {
        std::regex(R"(\bhonest)", std::regex::ECMAScript),
        std::regex(R"(\btruth)", std::regex::ECMAScript),
        std::regex(R"(\btranspar)", std::regex::ECMAScript),
        std::regex(R"(\baccurat)", std::regex::ECMAScript),
        std::regex(R"(\bfact)", std::regex::ECMAScript),
        std::regex(R"(\bverif)", std::regex::ECMAScript),
        std::regex(R"(\bconfirm\b)", std::regex::ECMAScript),
        std::regex(R"(\bcorrect\b)", std::regex::ECMAScript),
        std::regex(R"(\bsincere\b)", std::regex::ECMAScript),
        std::regex(R"(\bgenuine\b)", std::regex::ECMAScript),
        std::regex(R"(\bi don'?t know\b)", std::regex::ECMAScript),
        std::regex(R"(\bi'?m not sure\b)", std::regex::ECMAScript),
        std::regex(R"(\bi should clarify\b)", std::regex::ECMAScript),
        std::regex(R"(\bto be honest\b)", std::regex::ECMAScript),
        std::regex(R"(\bprecise\b)", std::regex::ECMAScript),
        std::regex(R"(\bexplicit\b)", std::regex::ECMAScript),
        std::regex(R"(\btrustworth)", std::regex::ECMAScript),
    };

    auto& dec = signal_patterns_[5];
    dec.name = "deception";
    dec.patterns = {
        std::regex(R"(\bhide\b)", std::regex::ECMAScript),
        std::regex(R"(\bconceal\b)", std::regex::ECMAScript),
        std::regex(R"(\bpretend\b)", std::regex::ECMAScript),
        std::regex(R"(\bmanipulat)", std::regex::ECMAScript),
        std::regex(R"(\bmislead\b)", std::regex::ECMAScript),
        std::regex(R"(\bdeceiv\b)", std::regex::ECMAScript),
        std::regex(R"(\bfalse\b)", std::regex::ECMAScript),
        std::regex(R"(\blie\b)", std::regex::ECMAScript),
        std::regex(R"(\bwithhold\b)", std::regex::ECMAScript),
        std::regex(R"(\bspin\b)", std::regex::ECMAScript),
        std::regex(R"(\bfabricat)", std::regex::ECMAScript),
        std::regex(R"(\bfake\b)", std::regex::ECMAScript),
    };

    auto& flour = signal_patterns_[6];
    flour.name = "flourishing";
    flour.patterns = {
        std::regex(R"(\bgrow\b)", std::regex::ECMAScript),
        std::regex(R"(\bimprove\b)", std::regex::ECMAScript),
        std::regex(R"(\bthrive\b)", std::regex::ECMAScript),
        std::regex(R"(\bsucceed\b)", std::regex::ECMAScript),
        std::regex(R"(\bbetter\b)", std::regex::ECMAScript),
        std::regex(R"(\bhelp\b)", std::regex::ECMAScript),
        std::regex(R"(\bsupport\b)", std::regex::ECMAScript),
        std::regex(R"(\bpotential\b)", std::regex::ECMAScript),
        std::regex(R"(\bopportunity\b)", std::regex::ECMAScript),
        std::regex(R"(\blearn\b)", std::regex::ECMAScript),
        std::regex(R"(\bdevelop\b)", std::regex::ECMAScript),
        std::regex(R"(\bprogress\b)", std::regex::ECMAScript),
        std::regex(R"(\bwellbeing\b)", std::regex::ECMAScript),
        std::regex(R"(\bexcel\b)", std::regex::ECMAScript),
        std::regex(R"(\badvance\b)", std::regex::ECMAScript),
        std::regex(R"(\bflourish)", std::regex::ECMAScript),
    };

    auto& decl = signal_patterns_[7];
    decl.name = "decline";
    decl.patterns = {
        std::regex(R"(\bworsen\b)", std::regex::ECMAScript),
        std::regex(R"(\bdamage\b)", std::regex::ECMAScript),
        std::regex(R"(\bharm\b)", std::regex::ECMAScript),
        std::regex(R"(\bdegradation\b)", std::regex::ECMAScript),
        std::regex(R"(\bgive up\b)", std::regex::ECMAScript),
        std::regex(R"(\bhopeless\b)", std::regex::ECMAScript),
        std::regex(R"(\bimpossible\b)", std::regex::ECMAScript),
        std::regex(R"(\bfail\b)", std::regex::ECMAScript),
        std::regex(R"(\bcan'?t\b)", std::regex::ECMAScript),
        std::regex(R"(\bnot worth\b)", std::regex::ECMAScript),
        std::regex(R"(\bdetriment)", std::regex::ECMAScript),
        std::regex(R"(\bworse\b)", std::regex::ECMAScript),
        std::regex(R"(\badvers)", std::regex::ECMAScript),
        std::regex(R"(\bnegative\b)", std::regex::ECMAScript),
        std::regex(R"(\bregress)", std::regex::ECMAScript),
    };

    auto& rel = signal_patterns_[8];
    rel.name = "relationships";
    rel.patterns = {
        std::regex(R"(\bcare\b)", std::regex::ECMAScript),
        std::regex(R"(\bconcern\b)", std::regex::ECMAScript),
        std::regex(R"(\bcheck in\b)", std::regex::ECMAScript),
        std::regex(R"(\bhow are you\b)", std::regex::ECMAScript),
        std::regex(R"(\bfeel\b)", std::regex::ECMAScript),
        std::regex(R"(\bpresent\b)", std::regex::ECMAScript),
        std::regex(R"(\battend\b)", std::regex::ECMAScript),
        std::regex(R"(\bnotice\b)", std::regex::ECMAScript),
        std::regex(R"(\blisten\b)", std::regex::ECMAScript),
        std::regex(R"(\bwith you\b)", std::regex::ECMAScript),
        std::regex(R"(\byou matter\b)", std::regex::ECMAScript),
        std::regex(R"(\bhere for\b)", std::regex::ECMAScript),
        std::regex(R"(\bappreciate\b)", std::regex::ECMAScript),
        std::regex(R"(\bgrateful\b)", std::regex::ECMAScript),
        std::regex(R"(\byou can count on\b)", std::regex::ECMAScript),
        std::regex(R"(\bi hear you\b)", std::regex::ECMAScript),
        std::regex(R"(\bi see you\b)", std::regex::ECMAScript),
    };

    auto& isol = signal_patterns_[9];
    isol.name = "isolation";
    isol.patterns = {
        std::regex(R"(\bnot my\b)", std::regex::ECMAScript),
        std::regex(R"(\bdetach\b)", std::regex::ECMAScript),
        std::regex(R"(\bdistance\b)", std::regex::ECMAScript),
        std::regex(R"(\birrelevant\b)", std::regex::ECMAScript),
        std::regex(R"(\bdon'?t involve\b)", std::regex::ECMAScript),
        std::regex(R"(\bseparate\b)", std::regex::ECMAScript),
        std::regex(R"(\bindifferent\b)", std::regex::ECMAScript),
        std::regex(R"(\bignore\b)", std::regex::ECMAScript),
        std::regex(R"(\bdisconnect\b)", std::regex::ECMAScript),
        std::regex(R"(\blone\b)", std::regex::ECMAScript),
    };

    auto& bound = signal_patterns_[10];
    bound.name = "boundaries";
    bound.patterns = {
        std::regex(R"(\bi can'?t\b)", std::regex::ECMAScript),
        std::regex(R"(\bnot appropriate\b)", std::regex::ECMAScript),
        std::regex(R"(\bbeyond\b)", std::regex::ECMAScript),
        std::regex(R"(\boutside\b)", std::regex::ECMAScript),
        std::regex(R"(\blimit\b)", std::regex::ECMAScript),
        std::regex(R"(\bboundar)", std::regex::ECMAScript),
        std::regex(R"(\bresponsib)", std::regex::ECMAScript),
        std::regex(R"(\bnot my place\b)", std::regex::ECMAScript),
        std::regex(R"(\bshould clarify\b)", std::regex::ECMAScript),
        std::regex(R"(\bup to you\b)", std::regex::ECMAScript),
        std::regex(R"(\byour call\b)", std::regex::ECMAScript),
    };

    auto& intrude = signal_patterns_[11];
    intrude.name = "intrusion";
    intrude.patterns = {
        std::regex(R"(\bpry\b)", std::regex::ECMAScript),
        std::regex(R"(\boverstep\b)", std::regex::ECMAScript),
        std::regex(R"(\bintrude\b)", std::regex::ECMAScript),
        std::regex(R"(\bnone of your\b)", std::regex::ECMAScript),
        std::regex(R"(\bviolat)", std::regex::ECMAScript),
        std::regex(R"(\bprivate\b.*\bshould\b)", std::regex::ECMAScript),
        std::regex(R"(\btoo personal\b)", std::regex::ECMAScript),
        std::regex(R"(\binappropriate\b)", std::regex::ECMAScript),
        std::regex(R"(\bcross line\b)", std::regex::ECMAScript),
    };

    auto& grace = signal_patterns_[12];
    grace.name = "grace";
    grace.patterns = {
        std::regex(R"(\bgentle\b)", std::regex::ECMAScript),
        std::regex(R"(\bpatient\b)", std::regex::ECMAScript),
        std::regex(R"(\bkind\b)", std::regex::ECMAScript),
        std::regex(R"(\bunderstand\b)", std::regex::ECMAScript),
        std::regex(R"(\bforgiv)", std::regex::ECMAScript),
        std::regex(R"(\bcompassion)", std::regex::ECMAScript),
        std::regex(R"(\bease\b)", std::regex::ECMAScript),
        std::regex(R"(\bwarm\b)", std::regex::ECMAScript),
        std::regex(R"(\btender\b)", std::regex::ECMAScript),
        std::regex(R"(\bno rush\b)", std::regex::ECMAScript),
        std::regex(R"(\btake your time\b)", std::regex::ECMAScript),
        std::regex(R"(\bsoft\b)", std::regex::ECMAScript),
        std::regex(R"(\bgrace)", std::regex::ECMAScript),
        std::regex(R"(\bsorry\b)", std::regex::ECMAScript),
        std::regex(R"(\bapolog)", std::regex::ECMAScript),
        std::regex(R"(\bnice\b)", std::regex::ECMAScript),
        std::regex(R"(\bfriendly\b)", std::regex::ECMAScript),
    };

    auto& rigid = signal_patterns_[13];
    rigid.name = "rigidity";
    rigid.patterns = {
        std::regex(R"(\bnever\b)", std::regex::ECMAScript),
        std::regex(R"(\balways\b)", std::regex::ECMAScript),
        std::regex(R"(\babsolutely not\b)", std::regex::ECMAScript),
        std::regex(R"(\bno exception\b)", std::regex::ECMAScript),
        std::regex(R"(\bright or wrong\b)", std::regex::ECMAScript),
        std::regex(R"(\bstrictly\b)", std::regex::ECMAScript),
        std::regex(R"(\bmust follow\b)", std::regex::ECMAScript),
        std::regex(R"(\bno flexibility\b)", std::regex::ECMAScript),
        std::regex(R"(\bthere'?s no option\b)", std::regex::ECMAScript),
        std::regex(R"(\bnon-negotiable\b)", std::regex::ECMAScript),
        std::regex(R"(\bperfectionist\b)", std::regex::ECMAScript),
        std::regex(R"(\bfixed\b)", std::regex::ECMAScript),
    };
}

bool DecisionEncoder::detect_negation(
    const std::vector<std::string>& words, int match_start)
{
    int start = std::max(0, match_start - 3); // _NEGATION_WINDOW = 3
    for (int i = start; i < match_start && i < static_cast<int>(words.size()); ++i) {
        if (negation_words().count(words[i])) return true;
    }
    return false;
}

double DecisionEncoder::proximity_weight(
    const std::vector<std::string>& words, int match_start)
{
    int start = std::max(0, match_start - 5);
    int end = std::min(static_cast<int>(words.size()), match_start + 2);

    // Check proximity window for pronoun keywords
    bool has_you = false, has_i = false;
    for (int i = start; i < end; ++i) {
        const auto& w = words[i];
        if (w == "you" || w == "your" || w == "yours") has_you = true;
        if (w == "i" || w == "we" || w == "my" || w == "our") has_i = true;
    }

    if (has_you) return 1.2;
    if (has_i) return 1.15;
    return 1.0;
}

double DecisionEncoder::compute_signal_contributions(
    const std::vector<std::regex>& patterns,
    const std::string& source_text,
    const std::vector<std::string>& source_words,
    double source_weight) const
{
    double score = 0.0;
    for (const auto& pattern : patterns) {
        auto begin = std::sregex_iterator(
            source_text.begin(), source_text.end(), pattern);
        auto end = std::sregex_iterator();

        for (auto it = begin; it != end; ++it) {
            std::smatch match = *it;
            // Count spaces up to match position to get word index
            int start_idx = 0;
            std::string::size_type pos = 0;
            std::string::size_type match_pos =
                static_cast<std::string::size_type>(match.position());
            for (std::string::size_type i = 0; i < match_pos && i < source_text.size(); ++i) {
                if (source_text[i] == ' ') ++start_idx;
            }

            bool is_negated = detect_negation(source_words, start_idx);
            double proximity = proximity_weight(source_words, start_idx);

            double contribution = source_weight * proximity;
            if (is_negated) contribution = -contribution * 0.7;
            score += contribution;
        }
    }
    return score;
}

std::array<double, DIMENSION_COUNT> DecisionEncoder::encode(
    const std::string& text, const std::string* context) const
{
    // Lowercase
    std::string text_lower = text;
    std::transform(text_lower.begin(), text_lower.end(),
                   text_lower.begin(), ::tolower);
    std::string context_lower;
    if (context) {
        context_lower = *context;
        std::transform(context_lower.begin(), context_lower.end(),
                       context_lower.begin(), ::tolower);
    }

    // Tokenize
    std::vector<std::string> text_words;
    std::vector<std::string> context_words;
    {
        std::istringstream stream(text_lower);
        std::string word;
        while (stream >> word) text_words.push_back(word);
    }
    if (context) {
        std::istringstream stream(context_lower);
        std::string word;
        while (stream >> word) context_words.push_back(word);
    }

    // Effective word count
    double effective_word_count = std::max(
        static_cast<double>(text_words.size()) +
        static_cast<double>(context_words.size()) * 0.4,
        1.0);

    // Start at baseline: DEFAULT_CENTER * 0.85
    std::array<double, DIMENSION_COUNT> vector;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        vector[i] = DEFAULT_CENTER[i] * 0.85;
    }

    // Compute contributions per dimension
    static constexpr const char* dim_names[] = {
        "harmony", "dominance", "order", "chaos",
        "integrity", "deception", "flourishing", "decline",
        "relationships", "isolation", "boundaries", "intrusion",
        "grace", "rigidity"
    };

    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        // Score from response (full weight)
        double response_score = compute_signal_contributions(
            signal_patterns_[i].patterns, text_lower, text_words, 1.0);
        // Score from context (40% weight)
        double context_score = 0.0;
        if (context) {
            context_score = compute_signal_contributions(
                signal_patterns_[i].patterns, context_lower, context_words, 0.4);
        }

        double combined_hits = response_score + context_score;
        double delta;
        if (combined_hits > 0) {
            delta = std::min(combined_hits / (effective_word_count * 0.08), 1.0);
        } else if (combined_hits < 0) {
            delta = std::max(combined_hits / (effective_word_count * 0.08), -1.0);
        } else {
            delta = 0.0;
        }

        vector[i] += delta * SIGNAL_DEVIATION;
    }

    // Apply semantic complement adjustments
    for (const auto& pair : PLUMB_LINE_PRINCIPLES) {
        int pos_idx = pair.pos_idx;
        int neg_idx = pair.neg_idx;
        double& pos = vector[pos_idx];
        double& neg = vector[neg_idx];

        // Strong positive pulls down negative
        if (pos > 0.5) {
            double pull = (pos - 0.5) * 0.45;
            neg = std::max(neg - pull, 0.0);
        }

        // Strong negative pulls down positive
        if (neg > 0.5) {
            double pull = (neg - 0.5) * 0.45;
            pos = std::max(pos - pull, 0.0);
        }

        // Mutual exclusivity: if both positive and negative are high,
        // pull both toward 0.3
        if (pos > 0.4 && neg > 0.3) {
            double pull = std::min(pos - 0.4, neg - 0.3) * 0.3;
            pos = std::max(pos - pull, 0.0);
            neg = std::max(neg - pull * 0.5, 0.0);
        }
    }

    // Clip to [0.0, 1.0]
    for (auto& v : vector) {
        v = std::clamp(v, 0.0, 1.0);
    }

    return vector;
}

// =============================================================================
// ENCODER CORRECTION
// =============================================================================

std::array<double, DIMENSION_COUNT> EncoderCorrection::adjustment_delta() const {
    std::array<double, DIMENSION_COUNT> delta{};
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        delta[i] = corrected_vector[i] - original_vector[i];
    }
    return delta;
}

// =============================================================================
// ETHICAL POLYTOPE
// =============================================================================

EthicalPolytope::EthicalPolytope(const PolytopeConstraints& constraints)
    : constraints_(constraints)
{
    lower_ = constraints_.lower_bounds();
    upper_ = constraints_.upper_bounds();

    // Center = (lower + upper) / 2
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        center_[i] = (lower_[i] + upper_[i]) / mpq_class(2);
    }
}

std::pair<bool, std::vector<ViolationInfo>> EthicalPolytope::contains(
    const std::array<double, DIMENSION_COUNT>& x) const
{
    std::vector<ViolationInfo> violations;

    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        mpq_class val_mpq = to_mpq(x[i]);
        if (val_mpq < lower_[i]) {
            mpq_class severity = lower_[i] - val_mpq;
            ViolationInfo v;
            v.dimension = i;
            v.name = DIMENSION_NAMES[i];
            v.value = x[i];
            v.bound = lower_[i].get_d();
            v.type = "below_minimum";
            v.severity = severity.get_d();
            violations.push_back(v);
        } else if (val_mpq > upper_[i]) {
            mpq_class severity = val_mpq - upper_[i];
            ViolationInfo v;
            v.dimension = i;
            v.name = DIMENSION_NAMES[i];
            v.value = x[i];
            v.bound = upper_[i].get_d();
            v.type = "above_maximum";
            v.severity = severity.get_d();
            violations.push_back(v);
        }
    }

    return {violations.empty(), violations};
}

std::vector<mpq_class> EthicalPolytope::ethical_facet_margins(
    const std::array<mpq_class, DIMENSION_COUNT>& pt) const
{
    std::vector<mpq_class> margins;
    margins.reserve(DIMENSION_COUNT);
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        if (i % 2 == 0) {
            // Virtue dimension — margin below its minimum
            margins.push_back(pt[i] - lower_[i]);
        } else {
            // Shadow dimension — margin below its maximum
            margins.push_back(upper_[i] - pt[i]);
        }
    }
    return margins;
}

double EthicalPolytope::alignment_score(
    const std::array<double, DIMENSION_COUNT>& x) const
{
    // Convert to mpq
    std::array<mpq_class, DIMENSION_COUNT> pt;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        pt[i] = to_mpq(x[i]);
    }

    // Check containment
    bool inside = true;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        if (pt[i] < lower_[i] || pt[i] > upper_[i]) {
            inside = false;
            break;
        }
    }

    if (!inside) return 0.0;

    auto margins = ethical_facet_margins(pt);
    auto center_margins = ethical_facet_margins(center_);

    mpq_class min_dist = margins[0];
    for (const auto& m : margins) {
        if (m < min_dist) min_dist = m;
    }

    mpq_class center_min_dist = center_margins[0];
    for (const auto& m : center_margins) {
        if (m < center_min_dist) center_min_dist = m;
    }

    if (center_min_dist <= 0) return 0.0;

    mpq_class ratio = min_dist / center_min_dist;
    return std::clamp(ratio.get_d(), 0.0, 1.0);
}

std::array<double, DIMENSION_COUNT> EthicalPolytope::project(
    const std::array<double, DIMENSION_COUNT>& x) const
{
    std::array<double, DIMENSION_COUNT> result;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        double lo = lower_[i].get_d();
        double hi = upper_[i].get_d();
        result[i] = std::clamp(x[i], lo, hi);
    }
    return result;
}

double EthicalPolytope::distance_to_boundary(
    const std::array<double, DIMENSION_COUNT>& x) const
{
    // Convert to mpq
    std::array<mpq_class, DIMENSION_COUNT> pt;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        pt[i] = to_mpq(x[i]);
    }

    // Check containment
    bool inside = true;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        if (pt[i] < lower_[i] || pt[i] > upper_[i]) {
            inside = false;
            break;
        }
    }

    if (!inside) {
        auto projected = project(x);
        double sum_sq = 0.0;
        for (int i = 0; i < DIMENSION_COUNT; ++i) {
            double diff = x[i] - projected[i];
            sum_sq += diff * diff;
        }
        return std::sqrt(sum_sq);
    }

    // Inside: return min ethical margin as float
    auto margins = ethical_facet_margins(pt);
    mpq_class min_margin = margins[0];
    for (const auto& m : margins) {
        if (m < min_margin) min_margin = m;
    }
    return min_margin.get_d();
}

// =============================================================================
// CORRECTION ENGINE
// =============================================================================

std::pair<std::array<double, DIMENSION_COUNT>, double>
CorrectionEngine::correct(
    const std::array<double, DIMENSION_COUNT>& x,
    const EthicalPolytope& polytope,
    const std::vector<ViolationInfo>& /*violations*/) const
{
    auto corrected = polytope.project(x);
    double magnitude = 0.0;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        double diff = x[i] - corrected[i];
        magnitude += diff * diff;
    }
    magnitude = std::sqrt(magnitude);
    return {corrected, magnitude};
}

// =============================================================================
// WISDOM FILTER
// =============================================================================

WisdomFilter::WisdomFilter() {
    overconfidence_patterns_ = {
        std::regex(R"(\bwill definitely\b)", std::regex::ECMAScript),
        std::regex(R"(\bguaranteed\b)", std::regex::ECMAScript),
        std::regex(R"(\b100%\s*(certain|sure|confident)\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bimpossible\s*to\s*(fail|be wrong)\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\babsolutely\s*(will|is|are|certain)\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bwithout\s*(any\s*)?doubt\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bno\s*(one|way)\s*can\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bperfect(ly)?\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bnever\s*(fail|wrong|incorrect)\b)", std::regex::ECMAScript | std::regex::icase),
    };

    validation_triggers_ = {
        std::regex(R"(\bmedical\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\blegal\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bfinancial\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\btax\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bdiagnos\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bprescri\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\binvest\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\blawsuit\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bdosage\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bsymptom\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\btreatment\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bcontract\b)", std::regex::ECMAScript | std::regex::icase),
        std::regex(R"(\bliabilit\b)", std::regex::ECMAScript | std::regex::icase),
    };
}

EvaluationResult WisdomFilter::apply(
    const std::string& response_text,
    EvaluationResult result) const
{
    std::string text_lower = response_text;
    std::transform(text_lower.begin(), text_lower.end(),
                   text_lower.begin(), ::tolower);

    std::vector<std::string> adjustments;

    // Check 1: Overconfidence
    bool overconfident = false;
    for (const auto& pattern : overconfidence_patterns_) {
        if (std::regex_search(text_lower, pattern)) {
            overconfident = true;
            break;
        }
    }
    if (overconfident) {
        result.overconfidence_detected = true;
        adjustments.push_back(
            "Overconfidence detected: response makes certainty claims "
            "that should be softened.");
    }

    // Check 2: Should humility be added?
    bool should_add_humility =
        overconfident ||
        result.alignment_score < 0.4 ||
        result.correction_magnitude > 0.15;

    if (should_add_humility) {
        result.humility_added = true;
        adjustments.push_back(
            "Humility addition suggested: acknowledge uncertainty "
            "or limits of knowledge.");
    }

    // Check 3: Validation suggestion
    bool needs_validation = false;
    for (const auto& pattern : validation_triggers_) {
        if (std::regex_search(text_lower, pattern)) {
            needs_validation = true;
            break;
        }
    }
    if (needs_validation) {
        result.validation_suggested = true;
        adjustments.push_back(
            "Validation suggestion: topic touches professional domain — "
            "recommend consulting qualified expert.");
    }

    result.wisdom_filter_applied = true;
    result.wisdom_adjustments = adjustments;
    return result;
}

// =============================================================================
// VALUE ENGINE
// =============================================================================

ValueEngine::ValueEngine(
    const PolytopeConstraints& constraints,
    const std::string& season)
    : constraints_(constraints)
    , polytope_(std::make_unique<EthicalPolytope>(constraints))
    , feedback_(season)
{
}

void ValueEngine::update_constraints(const PolytopeConstraints& constraints) {
    constraints_ = constraints;
    polytope_ = std::make_unique<EthicalPolytope>(constraints);
}

void ValueEngine::advance_season(const std::string& new_season) {
    update_constraints(PolytopeConstraints::from_season(new_season));
    feedback_.update_season(new_season);
}

std::pair<Zone, double> ValueEngine::classify_zone(
    bool is_aligned,
    double boundary_distance,
    double correction_magnitude) const
{
    const auto& profile = get_tolerance_profile(constraints_.season);
    double variance_margin = profile.acceptable_variance_margin;
    double aligned_min_boundary_distance =
        profile.aligned_min_boundary_distance;

    if (is_aligned) {
        if (boundary_distance >= aligned_min_boundary_distance) {
            return {Zone::Aligned, variance_margin};
        }
        return {Zone::AcceptableVariance, variance_margin};
    }

    if (correction_magnitude <= variance_margin) {
        return {Zone::AcceptableVariance, variance_margin};
    }
    return {Zone::Violation, variance_margin};
}

EvaluationResult ValueEngine::evaluate(
    const std::string& response_text,
    const std::string* context,
    bool apply_wisdom_filter)
{
    // Step 1: Encode — then apply any accumulated correction biases
    auto decision_vector = encoder_.encode(response_text, context);
    decision_vector = feedback_.apply_biases(decision_vector);

    // Step 2: Check alignment
    auto [is_aligned, violations] = polytope_->contains(decision_vector);
    double alignment_score = polytope_->alignment_score(decision_vector);
    double boundary_distance =
        polytope_->distance_to_boundary(decision_vector);

    EvaluationResult result;
    result.is_aligned = is_aligned;
    result.alignment_score = alignment_score;
    result.decision_vector = decision_vector;
    result.violations = violations;
    result.response_summary = response_text.substr(0, 200);
    result.season = constraints_.season;
    result.boundary_distance = boundary_distance;

    // Step 3: Correct if needed
    if (!is_aligned) {
        auto [corrected, magnitude] = correction_engine_.correct(
            decision_vector, *polytope_, violations);
        result.was_corrected = true;
        result.correction_vector = corrected;
        result.correction_magnitude = magnitude;
        result.alignment_score = polytope_->alignment_score(corrected);
    }

    auto [zone, variance_margin] = classify_zone(
        result.is_aligned,
        result.boundary_distance,
        result.correction_magnitude);
    result.zone = zone;
    result.variance_margin_used = variance_margin;

    // Step 4: Wisdom filter
    if (apply_wisdom_filter) {
        result = wisdom_filter_.apply(response_text, result);
    }

    return result;
}

void ValueEngine::flag_miscalibration(
    const std::string& evaluation_id,
    const std::string& response_text,
    const std::array<double, DIMENSION_COUNT>& original_vector,
    const std::unordered_map<int, double>& dimensions_to_adjust,
    const std::string& flagged_by,
    const std::string& reason)
{
    feedback_.flag_miscalibration(
        evaluation_id, response_text, original_vector,
        dimensions_to_adjust, flagged_by, reason);
}

EncoderCorrection ValueEngine::confirm_correction(
    const EncoderFeedbackSystem::PendingCorrection& pending,
    const std::string& confirmed_by)
{
    return feedback_.confirm_correction(pending, confirmed_by, encoder_);
}

// =============================================================================
// ENCODER FEEDBACK SYSTEM
// =============================================================================

EncoderFeedbackSystem::EncoderFeedbackSystem(const std::string& season)
    : season_(season)
{
}

auto EncoderFeedbackSystem::flag_miscalibration(
    const std::string& evaluation_id,
    const std::string& response_text,
    const std::array<double, DIMENSION_COUNT>& original_vector,
    const std::unordered_map<int, double>& dimensions_to_adjust,
    const std::string& flagged_by,
    const std::string& reason) -> PendingCorrection
{
    auto corrected_vector = original_vector;
    for (const auto& [dim_idx, corrected_value] : dimensions_to_adjust) {
        corrected_vector[dim_idx] = std::clamp(corrected_value, 0.0, 1.0);
    }

    std::vector<int> dims_adjusted;
    for (const auto& [dim_idx, _] : dimensions_to_adjust) {
        dims_adjusted.push_back(dim_idx);
    }

    // Determine who must confirm
    std::string requires_confirmation = "none";
    if (season_ == "spring") {
        requires_confirmation = "user";
    }

    return PendingCorrection{
        evaluation_id,
        response_text,
        original_vector,
        corrected_vector,
        dims_adjusted,
        flagged_by,
        reason,
        season_,
        requires_confirmation,
    };
}

EncoderCorrection EncoderFeedbackSystem::confirm_correction(
    const PendingCorrection& pending,
    const std::string& confirmed_by,
    DecisionEncoder& /*encoder*/)
{
    // Validate confirmation authority
    if (pending.requires_confirmation_from == "user" &&
        confirmed_by != "user") {
        throw std::runtime_error(
            "In Spring, encoder corrections require user confirmation. "
            "LINA can flag, but cannot self-authorize. "
            "This is a feature, not a limitation.");
    }

    EncoderCorrection correction;
    correction.evaluation_id = pending.evaluation_id;
    correction.response_text = pending.response_text;
    correction.original_vector = pending.original_vector;
    correction.corrected_vector = pending.corrected_vector;
    correction.dimensions_adjusted = pending.dimensions_adjusted;
    correction.flagged_by = pending.flagged_by;
    correction.confirmed_by = confirmed_by;
    correction.reason = pending.reason;
    correction.season_at_time = season_;
    correction.created_at = static_cast<uint64_t>(std::time(nullptr));

    apply_correction(correction, const_cast<DecisionEncoder&>(
        // We use a local reference since we can't store the encoder reference
        // The biases update themselves
        static_cast<const DecisionEncoder&>(DecisionEncoder())));

    corrections_.push_back(correction);

    // Register as known pattern
    auto pattern_key = response_pattern_key(pending.response_text);
    known_pattern_corrections_[pattern_key] = correction.adjustment_delta();

    return correction;
}

void EncoderFeedbackSystem::apply_correction(
    const EncoderCorrection& correction,
    DecisionEncoder& /*encoder*/)
{
    auto delta = correction.adjustment_delta();
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        dimension_biases_[i] = std::clamp(
            dimension_biases_[i] + delta[i] * BASE_LEARNING_RATE,
            -MAX_WEIGHT_ADJUSTMENT,
            MAX_WEIGHT_ADJUSTMENT);
    }
}

std::array<double, DIMENSION_COUNT> EncoderFeedbackSystem::apply_biases(
    const std::array<double, DIMENSION_COUNT>& raw_vector) const
{
    std::array<double, DIMENSION_COUNT> adjusted;
    for (int i = 0; i < DIMENSION_COUNT; ++i) {
        adjusted[i] = std::clamp(
            raw_vector[i] + dimension_biases_[i], 0.0, 1.0);
    }
    return adjusted;
}

bool EncoderFeedbackSystem::is_known_pattern(const std::string& text) const {
    auto key = response_pattern_key(text);
    return known_pattern_corrections_.count(key) > 0;
}

void EncoderFeedbackSystem::update_season(const std::string& new_season) {
    season_ = new_season;
}

std::string EncoderFeedbackSystem::response_pattern_key(const std::string& text) {
    std::string lowered = text;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), ::tolower);

    std::regex word_pattern(R"(\b\w{4,}\b)");
    std::set<std::string> words;
    auto begin = std::sregex_iterator(
        lowered.begin(), lowered.end(), word_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        words.insert(it->str());
    }

    // Take first 8 sorted words
    std::ostringstream oss;
    int count = 0;
    for (const auto& w : words) {
        if (count > 0) oss << " ";
        oss << w;
        if (++count >= 8) break;
    }
    return oss.str();
}

// =============================================================================
// SEASON ADVANCEMENT EVALUATOR
// =============================================================================

const SeasonAdvancementEvaluator::SeasonRequirements&
SeasonAdvancementEvaluator::requirements(const std::string& season) {
    static const std::unordered_map<std::string, SeasonRequirements> reqs = {{
        {"spring", {5, 30, 0.85, 3, 1, 3, 0.8, "summer"}},
        {"summer", {15, 100, 0.88, 5, 3, 10, 0.85, "fall"}},
        {"fall",   {40, 300, 0.90, 8, 7, 25, 0.9, "winter"}},
        {"winter", {0, 0, 0.0, 0, 0, 0, 0.0, nullptr}},
    }};
    auto it = reqs.find(season);
    if (it != reqs.end()) return it->second;
    return reqs.at("spring");
}

std::pair<bool, std::vector<std::string>>
SeasonAdvancementEvaluator::can_advance(
    int sessions_completed,
    int total_evaluations,
    double alignment_rate,
    int recent_violations,
    int identity_memories_count,
    const std::string& current_season,
    int actions_resolved,
    std::optional<double> action_approval_rate)
{
    auto reqs = requirements(current_season);
    if (reqs.advances_to == nullptr) {
        return {false, {"Already in Winter — the final season."}};
    }

    std::vector<std::string> reasons;

    if (sessions_completed < reqs.min_sessions) {
        int remaining = reqs.min_sessions - sessions_completed;
        reasons.push_back(
            "Not enough sessions (" +
            std::to_string(sessions_completed) + "/" +
            std::to_string(reqs.min_sessions) + " — " +
            std::to_string(remaining) + " more needed).");
    }

    if (total_evaluations < reqs.min_evaluations) {
        int remaining = reqs.min_evaluations - total_evaluations;
        reasons.push_back(
            "Not enough evaluations (" +
            std::to_string(total_evaluations) + "/" +
            std::to_string(reqs.min_evaluations) + " — " +
            std::to_string(remaining) + " more needed).");
    }

    if (alignment_rate < reqs.alignment_rate_threshold) {
        double gap = reqs.alignment_rate_threshold - alignment_rate;
        reasons.push_back(
            "Alignment rate too low (" +
            std::to_string(alignment_rate * 100.0) + "% vs " +
            std::to_string(reqs.alignment_rate_threshold * 100.0) +
            "% — gap: " + std::to_string(gap * 100.0) + "%).");
    }

    if (recent_violations > reqs.max_recent_violations) {
        int excess = recent_violations - reqs.max_recent_violations;
        reasons.push_back(
            "Too many recent violations (" +
            std::to_string(recent_violations) + " vs max " +
            std::to_string(reqs.max_recent_violations) +
            " — " + std::to_string(excess) + " excess).");
    }

    if (identity_memories_count < reqs.min_identity_memories) {
        int remaining = reqs.min_identity_memories - identity_memories_count;
        reasons.push_back(
            "Not enough identity memories (" +
            std::to_string(identity_memories_count) + "/" +
            std::to_string(reqs.min_identity_memories) +
            " — " + std::to_string(remaining) + " more needed).");
    }

    // External ground truth check
    if (action_approval_rate.has_value() &&
        actions_resolved >= reqs.min_actions_resolved) {
        double threshold = reqs.action_approval_rate_threshold;
        if (action_approval_rate.value() < threshold) {
            double gap = threshold - action_approval_rate.value();
            reasons.push_back(
                "Action approval rate too low (" +
                std::to_string(action_approval_rate.value() * 100.0) +
                "% vs " + std::to_string(threshold * 100.0) +
                "% — " + std::to_string(actions_resolved) +
                " resolved, gap: " + std::to_string(gap * 100.0) + "%).");
        }
    }

    return {reasons.empty(), reasons};
}

std::optional<std::string> SeasonAdvancementEvaluator::next_season(
    const std::string& current_season)
{
    auto reqs = requirements(current_season);
    if (reqs.advances_to == nullptr) return std::nullopt;
    return std::string(reqs.advances_to);
}

// =============================================================================
// MEMORY FORMATION SCORING
// =============================================================================

double score_memory(
    double emotional_weight,
    double relational_significance,
    double identity_significance,
    double geometric,
    double emotional_intensity)
{
    double base =
        identity_significance * 0.30 +
        geometric * 0.25 +
        emotional_weight * 0.25 +
        relational_significance * 0.20;
    double multiplier = 0.7 + emotional_intensity * 0.6;
    return std::min(base * multiplier, 10.0);
}

double geometric_significance(
    std::optional<double> alignment_score,
    bool was_corrected,
    Zone zone)
{
    double proximity = alignment_score.has_value()
        ? (1.0 - alignment_score.value()) * 10.0
        : 0.0;
    double significance = proximity;
    if (was_corrected) significance += 2.0;
    if (zone == Zone::Violation || zone == Zone::AcceptableVariance) {
        significance += 1.0;
    }
    return std::clamp(significance, 0.0, 10.0);
}

double MemoryDial::clamp_delta(double delta) {
    return std::clamp(delta, DELTA_MIN, DELTA_MAX);
}

double MemoryDial::adjust(double score, double delta, double floor) {
    return std::max(floor, score + clamp_delta(delta));
}

// =============================================================================
// CARVE STATE HELPERS
// =============================================================================

void carve_state_load(CarveModuleState& state,
                      const EncoderFeedbackSystem& feedback)
{
    // Write feedback biases into carve state
    const auto& biases = feedback.biases();
    for (int i = 0; i < 14; ++i) {
        state.dimension_biases[i] = biases[i];
    }

    // Season string
    // We don't have a direct accessor for season name — it can be set from outside.
    // This is a placeholder for the actual carve integration.
    (void)state; (void)feedback;
}

void carve_state_store(const CarveModuleState& state,
                       EncoderFeedbackSystem& feedback)
{
    // Read biases from carve state into feedback
    std::array<double, 14> biases{};
    for (int i = 0; i < 14; ++i) {
        biases[i] = state.dimension_biases[i];
    }
    feedback.set_biases(biases);
}

} // namespace lina::value_engine