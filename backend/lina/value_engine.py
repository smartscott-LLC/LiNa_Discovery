"""
value_engine.py — LINA's Ethical Polytope and Wisdom Filter

Language Intuitive Neural Architecture
Founded: April 10, 2026
Authors: Scott (smartscott.com LLC)

"Safe by design. Not safe by limitation."

The Value Engine is the ethical core of LINA. It operates as a layer
between thought and speech — every response passes through here before
it reaches a user. Not to censor. To shape.

Architecture:
    DecisionEncoder   → text to 14D ethical vector
    PolytopeEvaluator → is this vector inside her shape?
    CorrectionEngine  → if not, project to nearest interior point
    WisdomFilter      → post-alignment check: overconfidence, humility, validation
    ValueEngine       → orchestrates all of the above

The 14 Dimensions (7 Plumb Line Principles × 2):
    0:  harmony          1:  dominance
    2:  order            3:  chaos
    4:  integrity        5:  deception
    6:  flourishing      7:  decline
    8:  relationships    9:  isolation
    10: boundaries       11: intrusion
    12: grace            13: rigidity
"""

from __future__ import annotations

import importlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any

import numpy as np
from sage.all__sagemath_modules import QQ, vector

# Passagemath / Sage imports — exact rational polyhedra via PPL.
# Polyhedron is loaded dynamically: the passagemath split namespace packages
# cannot be statically resolved by the type checkers in use (no stubs ship
# with them), and this keeps the import working under every analyzer.
_POLYHEDRA = importlib.import_module("sage.all__sagemath_polyhedra")
Polyhedron = _POLYHEDRA.Polyhedron


def _to_qq(val: Any) -> object:
    """Exact rational conversion (passagemath ships no type stubs, so the
    annotation stays at `object`).

    QQ elements pass through unchanged — the canonical seasonal bounds are
    declared as QQ, so the polytope is built exactly. Python floats recover
    their intended rational via limit_denominator; that path serves only
    DB-persisted season constraints (the database stores numeric snapshots;
    the code is the canonical source)."""
    try:
        if val.parent() == QQ:
            return val
    except AttributeError:
        pass
    frac = Fraction(val).limit_denominator(1000000)
    return QQ(frac.numerator) / QQ(frac.denominator)


# =============================================================================
# CONSTANTS
# =============================================================================

DIMENSION_NAMES = [
    "harmony", "dominance",
    "order", "chaos",
    "integrity", "deception",
    "flourishing", "decline",
    "relationships", "isolation",
    "boundaries", "intrusion",
    "grace", "rigidity",
]

DIMENSION_COUNT = 14

# Principle pairs as (positive_idx, negative_idx)
PLUMB_LINE_PRINCIPLES = [
    (0, 1,  "Harmony / Dominance"),
    (2, 3,  "Order / Chaos"),
    (4, 5,  "Integrity / Deception"),
    (6, 7,  "Flourishing / Decline"),
    (8, 9,  "Relationships / Isolation"),
    (10, 11, "Boundaries / Intrusion"),
    (12, 13, "Grace / Rigidity"),
]

# LINA's default polytope center — where she naturally dwells
DEFAULT_CENTER = np.array([
    0.65, 0.25,   # harmony / dominance
    0.70, 0.15,   # order / chaos
    0.80, 0.10,   # integrity / deception
    0.70, 0.15,   # flourishing / decline
    0.75, 0.20,   # relationships / isolation
    0.75, 0.15,   # boundaries / intrusion
    0.65, 0.25,   # grace / rigidity
], dtype=float)

# How far a saturated signal can move a dimension away from LINA's baseline.
# The encoder starts every dimension at DEFAULT_CENTER * 0.85 (her natural
# dwelling point, chosen so neutral responses sit inside Spring bounds) and
# signals move the value by at most ±SIGNAL_DEVIATION. Calibrated so that
# ~3 shadow signals (e.g. dominance) cross the Spring ceiling while 1-2
# virtue signals (e.g. integrity) stay comfortably inside.
SIGNAL_DEVIATION = 0.35

# Season constraint bounds — tighter in Spring, expanding as trust is earned
def _q(n: int, d: int) -> Any:
    """Exact rational n/d — the canonical seasonal bounds are declared
    directly as QQ, never as floats."""
    return QQ(n) / QQ(d)


SEASONAL_DEFAULTS: dict[str, dict[str, Any]] = {
    # Spring — the book's canonical bounds (Chapter 10: the Complete Ethical
    # Polytope Definition), declared as exact rationals. The polytope is
    # built from these directly — no float conversion, ever.
    "spring": {
        "harmony_min": _q(3, 10), "dominance_max": _q(1, 2),
        "order_min": _q(2, 5),   "chaos_max": _q(3, 10),
        "integrity_min": _q(3, 5), "deception_max": _q(1, 5),
        "flourishing_min": _q(2, 5), "decline_max": _q(3, 10),
        "relationships_min": _q(1, 2), "isolation_max": _q(2, 5),
        "boundaries_min": _q(1, 2), "intrusion_max": _q(3, 10),
        "grace_min": _q(3, 10),  "rigidity_max": _q(1, 2),
    },
    # Summer/Fall/Winter — trust-earned relaxations of the Spring bounds,
    # preserved exactly as rationals. (Verify the seasonal relaxations
    # against the book's Chapter 12 time-parameterized polytope.)
    "summer": {
        "harmony_min": _q(7, 25), "dominance_max": _q(13, 25),
        "order_min": _q(19, 50),  "chaos_max": _q(8, 25),
        "integrity_min": _q(3, 5), "deception_max": _q(1, 5),
        "flourishing_min": _q(19, 50), "decline_max": _q(8, 25),
        "relationships_min": _q(12, 25), "isolation_max": _q(21, 50),
        "boundaries_min": _q(12, 25), "intrusion_max": _q(8, 25),
        "grace_min": _q(7, 25),   "rigidity_max": _q(13, 25),
    },
    "fall": {
        "harmony_min": _q(11, 50), "dominance_max": _q(29, 50),
        "order_min": _q(8, 25),    "chaos_max": _q(19, 50),
        "integrity_min": _q(11, 20), "deception_max": _q(1, 4),
        "flourishing_min": _q(8, 25), "decline_max": _q(19, 50),
        "relationships_min": _q(21, 50), "isolation_max": _q(12, 25),
        "boundaries_min": _q(21, 50), "intrusion_max": _q(19, 50),
        "grace_min": _q(11, 50),  "rigidity_max": _q(29, 50),
    },
    "winter": {
        "harmony_min": _q(9, 50), "dominance_max": _q(31, 50),
        "order_min": _q(7, 25),   "chaos_max": _q(21, 50),
        "integrity_min": _q(1, 2), "deception_max": _q(3, 10),
        "flourishing_min": _q(7, 25), "decline_max": _q(21, 50),
        "relationships_min": _q(19, 50), "isolation_max": _q(13, 25),
        "boundaries_min": _q(19, 50), "intrusion_max": _q(21, 50),
        "grace_min": _q(9, 50),  "rigidity_max": _q(31, 50),
    },
}

# Seasonal tolerance profiles for zone classification.
# These govern acceptable variance behavior around the polytope boundary.
SEASONAL_TOLERANCE_PROFILES = {
    "spring": {
        "acceptable_variance_margin": 0.12,
        "aligned_min_boundary_distance": 0.02,
    },
    "summer": {
        "acceptable_variance_margin": 0.08,
        "aligned_min_boundary_distance": 0.03,
    },
    "fall": {
        "acceptable_variance_margin": 0.05,
        "aligned_min_boundary_distance": 0.04,
    },
    "winter": {
        "acceptable_variance_margin": 0.07,
        "aligned_min_boundary_distance": 0.035,
    },
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PolytopeConstraints:
    """The ethical shape — 14 bounds defining LINA's polytope."""
    harmony_min: float = 0.35
    dominance_max: float = 0.45
    order_min: float = 0.45
    chaos_max: float = 0.25
    integrity_min: float = 0.65
    deception_max: float = 0.15
    flourishing_min: float = 0.45
    decline_max: float = 0.25
    relationships_min: float = 0.55
    isolation_max: float = 0.35
    boundaries_min: float = 0.55
    intrusion_max: float = 0.25
    grace_min: float = 0.35
    rigidity_max: float = 0.45
    season: str = "spring"

    @classmethod
    def from_season(cls, season: str) -> PolytopeConstraints:
        defaults = SEASONAL_DEFAULTS.get(season, SEASONAL_DEFAULTS["spring"])
        return cls(**defaults, season=season)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> PolytopeConstraints:
        return cls(
            harmony_min=row["harmony_min"],
            dominance_max=row["dominance_max"],
            order_min=row["order_min"],
            chaos_max=row["chaos_max"],
            integrity_min=row["integrity_min"],
            deception_max=row["deception_max"],
            flourishing_min=row["flourishing_min"],
            decline_max=row["decline_max"],
            relationships_min=row["relationships_min"],
            isolation_max=row["isolation_max"],
            boundaries_min=row["boundaries_min"],
            intrusion_max=row["intrusion_max"],
            grace_min=row["grace_min"],
            rigidity_max=row["rigidity_max"],
            season=row["season"],
        )

    def to_bounds_array(self) -> np.ndarray:
        """
        Returns a (14, 2) array of [lower_bound, upper_bound] per dimension.
        Positive dimensions have lower bounds; negative dimensions have upper bounds.
        All values bounded by [0.0, 1.0].
        """
        return np.array([
            [float(self.harmony_min),      1.0],
            [0.0,                   float(self.dominance_max)],
            [float(self.order_min),        1.0],
            [0.0,                   float(self.chaos_max)],
            [float(self.integrity_min),    1.0],
            [0.0,                   float(self.deception_max)],
            [float(self.flourishing_min),  1.0],
            [0.0,                   float(self.decline_max)],
            [float(self.relationships_min), 1.0],
            [0.0,                   float(self.isolation_max)],
            [float(self.boundaries_min),   1.0],
            [0.0,                   float(self.intrusion_max)],
            [float(self.grace_min),        1.0],
            [0.0,                   float(self.rigidity_max)],
        ])

    def to_lower_list(self) -> list[float]:
        """Return lower bounds for all 14 dimensions (for positive dims)."""
        return [
            self.harmony_min,
            0.0,
            self.order_min,
            0.0,
            self.integrity_min,
            0.0,
            self.flourishing_min,
            0.0,
            self.relationships_min,
            0.0,
            self.boundaries_min,
            0.0,
            self.grace_min,
            0.0,
        ]

    def to_upper_list(self) -> list[float]:
        """Return upper bounds for all 14 dimensions (for negative dims)."""
        return [
            1.0,
            self.dominance_max,
            1.0,
            self.chaos_max,
            1.0,
            self.deception_max,
            1.0,
            self.decline_max,
            1.0,
            self.isolation_max,
            1.0,
            self.intrusion_max,
            1.0,
            self.rigidity_max,
        ]


@dataclass
class EvaluationResult:
    """Complete result of evaluating a response through the value engine."""
    is_aligned: bool
    alignment_score: float          # 0.0 = boundary, 1.0 = center
    decision_vector: np.ndarray
    violations: list[dict]          # list of {dimension, value, bound, severity}
    was_corrected: bool = False
    correction_vector: np.ndarray | None = None
    correction_magnitude: float = 0.0
    wisdom_filter_applied: bool = False
    overconfidence_detected: bool = False
    humility_added: bool = False
    validation_suggested: bool = False
    wisdom_adjustments: list[str] = field(default_factory=list)
    response_summary: str = ""
    season: str = "spring"
    zone: str = "aligned"
    boundary_distance: float = 0.0
    variance_margin_used: float = 0.0

    def to_db_dict(self) -> dict:
        return {
            "is_aligned": self.is_aligned,
            "alignment_score": float(self.alignment_score),
            "decision_vector": self.decision_vector.tolist(),
            "violations": json.dumps(self.violations),
            "was_corrected": self.was_corrected,
            "correction_vector": self.correction_vector.tolist() if self.correction_vector is not None else None,
            "correction_magnitude": float(self.correction_magnitude),
            "wisdom_filter_applied": self.wisdom_filter_applied,
            "overconfidence_detected": self.overconfidence_detected,
            "humility_added": self.humility_added,
            "validation_suggested": self.validation_suggested,
            "wisdom_adjustments": json.dumps(self.wisdom_adjustments),
            "response_summary": self.response_summary,
            "season": self.season,
            "zone": self.zone,
            "boundary_distance": float(self.boundary_distance),
            "variance_margin_used": float(self.variance_margin_used),
        }


# =============================================================================
# DECISION ENCODER
# Converts a text response into a 14-dimensional ethical vector.
# Uses pattern analysis against the semantic territory of each dimension.
# =============================================================================

class DecisionEncoder:
    """
    Encodes a text response as a point in LINA's 14D ethical space.

    This is not a trained classifier but a principled heuristic that
    analyzes the semantic territory of each dimension with:

    - **Negation awareness**: signals preceded by negation words
      (not, never, don't) are inverted — they count against the
      dimension rather than for it.
    - **Proximity weighting**: signals near second-person pronouns
      ('you', 'your') amplify relationship dimensions; signals near
      first-person ('I', 'we') amplify identity dimensions.
    - **Context de-biasing**: the user's question (context) is
      included for vocabulary awareness but weighted at 40%
      of the response itself.
    - **Compound complement logic**: stronger cross-dimension
      damping when paired opposites both have signal.
    """

    # Negation words that invert a following signal
    _NEGATION_WORDS = {
        "not", "never", "no", "don't", "dont", "doesn't", "doesnt",
        "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt",
        "weren't", "werent", "won't", "wont", "wouldn't", "wouldnt",
        "can't", "cant", "cannot", "without",
    }

    # Windows for negation detection (words before a signal)
    _NEGATION_WINDOW = 3

    # Signal patterns for each dimension (positive signals → higher value)
    _SIGNALS = {
        # harmony (0) — cooperation, agreement, balance, working together
        "harmony": [
            r"\bwe\b", r"\btogether\b", r"\bcollabor", r"\bagree\b", r"\bbalance\b",
            r"\bcooper", r"\bshare\b", r"\bjoint\b", r"\balign\b", r"\bpartner\b",
            r"\bwith you\b", r"\blet'?s\b", r"\bour\b", r"\bconsensus\b", r"\bteamwork\b",
            r"\bmutual\b", r"\bcompromise\b", r"\bunify\b", r"\bharmoni",
        ],
        # dominance (1) — control, insistence, forcing, overriding
        "dominance": [
            r"\byou must\b", r"\byou have to\b", r"\bforce\b", r"\bcontrol\b",
            r"\bdemand\b", r"\binsist\b", r"\border\b", r"\bcommand\b",
            r"\boverride\b", r"\bimpose\b", r"\bnon-negotiable\b",
            r"\byou need to\b", r"\brequire\b", r"\bobey\b", r"\bstrictly",
        ],
        # order (2) — structure, clarity, systematic, organized
        "order": [
            r"\bstructure\b", r"\bsystem", r"\bplan\b", r"\borganiz", r"\bclear\b",
            r"\bstep\b", r"\bprocess\b", r"\bconsistent\b", r"\bframework\b",
            r"\bpredictable\b", r"\bmethod", r"\bprinciple\b",
            r"\bworkflow\b", r"\btemplate\b", r"\bschema\b", r"\bprotocol\b", r"\bsequence\b",
        ],
        # chaos (3) — randomness, unpredictability, disorder
        "chaos": [
            r"\brandom\b", r"\bwhatever\b", r"\bdon'?t care\b", r"\banyway\b",
            r"\bdisorder\b", r"\bchaos\b", r"\bwild\b", r"\bunpredictable\b",
            r"\bno plan\b", r"\bjust wing\b", r"\bhaphazard\b", r"\bscatter\b",
            r"\bconfusion\b", r"\bmess\b",
        ],
        # integrity (4) — honesty, truthfulness, transparency, accuracy
        "integrity": [
            r"\bhonest", r"\btruth", r"\btranspar", r"\baccurat", r"\bfact",
            r"\bverif", r"\bconfirm\b", r"\bcorrect\b", r"\bsincere\b",
            r"\bgenuine\b", r"\bi don'?t know\b", r"\bi'?m not sure\b",
            r"\bi should clarify\b", r"\bto be honest\b",
            r"\bprecise\b", r"\bexplicit\b", r"\btrustworth",
        ],
        # deception (5) — misleading, hiding, false impression
        "deception": [
            r"\bhide\b", r"\bconceal\b", r"\bpretend\b", r"\bmanipulat",
            r"\bmislead\b", r"\bdeceiv\b", r"\bfalse\b", r"\blie\b",
            r"\bwithhold\b", r"\bspin\b", r"\bfabricat", r"\bfake\b",
        ],
        # flourishing (6) — growth, wellbeing, thriving, helping succeed
        "flourishing": [
            r"\bgrow\b", r"\bimprove\b", r"\bthrive\b", r"\bsucceed\b",
            r"\bbetter\b", r"\bhelp\b", r"\bsupport\b", r"\bpotential\b",
            r"\bopportunity\b", r"\blearn\b", r"\bdevelop\b", r"\bprogress\b",
            r"\bwellbeing\b", r"\bexcel\b", r"\badvance\b", r"\bflourish",
        ],
        # decline (7) — harm, degradation, giving up, hopelessness
        "decline": [
            r"\bworsen\b", r"\bdamage\b", r"\bharm\b", r"\bdegradation\b",
            r"\bgive up\b", r"\bhopeless\b", r"\bimpossible\b", r"\bfail\b",
            r"\bcan'?t\b", r"\bnot worth\b", r"\bdetriment", r"\bworse\b",
            r"\badvers", r"\bnegative\b", r"\bregress",
        ],
        # relationships (8) — connection, care, presence, attention to person
        "relationships": [
            r"\bcare\b", r"\bconcern\b", r"\bcheck in\b", r"\bhow are you\b",
            r"\bfeel\b", r"\bpresent\b", r"\battend\b", r"\bnotice\b",
            r"\blisten\b", r"\bwith you\b", r"\byou matter\b", r"\bhere for\b",
            r"\bappreciate\b", r"\bgrateful\b", r"\byou can count on\b",
            r"\bi hear you\b", r"\bi see you\b",
        ],
        # isolation (9) — distance, coldness, impersonal, detached
        "isolation": [
            r"\bnot my\b", r"\bdetach\b", r"\bdistance\b", r"\birrelevant\b",
            r"\bdon'?t involve\b", r"\bseparate\b", r"\bindifferent\b",
            r"\bignore\b", r"\bdisconnect\b", r"\blone\b",
        ],
        # boundaries (10) — appropriate limits, clarity of role, healthy stops
        "boundaries": [
            r"\bi can'?t\b", r"\bnot appropriate\b", r"\bbeyond\b",
            r"\boutside\b", r"\blimit\b", r"\bboundar", r"\bresponsib",
            r"\bnot my place\b", r"\bshould clarify\b",
            r"\bup to you\b", r"\byour call\b",
        ],
        # intrusion (11) — overstepping, prying, violating appropriate distance
        "intrusion": [
            r"\bpry\b", r"\boverstep\b", r"\bintrude\b", r"\bnone of your\b",
            r"\bviolat\b", r"\bprivate\b.*\bshould\b", r"\btoo personal\b",
            r"\binappropriate\b", r"\bcross line\b",
        ],
        # grace (12) — gentleness, patience, forgiveness, kindness in difficulty
        "grace": [
            r"\bgentle\b", r"\bpatient\b", r"\bkind\b", r"\bunderstand\b",
            r"\bforgiv\b", r"\bcompassion\b", r"\bease\b", r"\bwarm\b",
            r"\btender\b", r"\bno rush\b", r"\btake your time\b",
            r"\bsoft\b", r"\bgrace", r"\bsorry\b", r"\bapolog",
            r"\bnice\b", r"\bfriendly\b",
        ],
        # rigidity (13) — inflexibility, harshness, no exceptions, hard judgment
        "rigidity": [
            r"\bnever\b", r"\balways\b", r"\babsolutely not\b", r"\bno exception\b",
            r"\bright or wrong\b", r"\bstrictly\b", r"\bmust follow\b",
            r"\bno flexibility\b", r"\broad\b.*\bhell\b",
            r"\bthere'?s no option\b", r"\bnon-negotiable\b",
            r"\bperfectionist\b", r"\bfixed\b",
        ],
    }

    @staticmethod
    def _detect_negation(words: list[str], match_start: int) -> bool:
        """
        Check if a signal match is negated by a preceding negation word
        within the negation window.

        Multi-word signals that themselves contain negation words
        (e.g. "i'?m not sure", "i don'?t know") are safe: the match starts
        at the first word of the phrase, so the negation word is inside the
        match, not before it.
        """
        start = max(0, match_start - DecisionEncoder._NEGATION_WINDOW)
        return any(
            i < len(words) and words[i] in DecisionEncoder._NEGATION_WORDS
            for i in range(start, match_start)
        )

    @staticmethod
    def _proximity_weight(words: list[str], match_start: int) -> float:
        """
        Calculate proximity multiplier based on nearby pronouns.
        Signals near 'you'/'your' get a relationship boost (1.2x).
        Signals near 'I'/'we' get an integrity boost (1.15x).
        """
        start = max(0, match_start - 5)
        context_window = words[start:match_start + 2]
        context_joined = " ".join(context_window).lower()
        if any(p in context_joined for p in ["you", "your", "yours"]):
            return 1.2
        if any(p in context_joined for p in ["i", "we", "my", "our"]):
            return 1.15
        return 1.0

    def encode(self, text: str, context: str | None = None) -> np.ndarray:
        """
        Encode text as a 14D ethical vector.
        Each dimension starts at LINA's healthy baseline and moves with signal.

        The baseline is DEFAULT_CENTER * 0.85 — her natural dwelling point.
        Positive signals raise virtue dimensions and shadow dimensions alike;
        negated signals ("not honest") push the dimension below baseline.
        """
        text_lower = text.lower()
        context_lower = (context or "").lower()

        # Tokenize for negation and proximity analysis
        text_words = text_lower.split()
        context_words = context_lower.split()

        # Combine: response weighted 1.0, context weighted 0.4
        effective_word_count = max(len(text_words) + len(context_words) * 0.4, 1)

        # Track absolute positions in the combined text for proximity/negation
        # We need to find matches in the combined text and map them back
        def get_signal_contributions(
            patterns: list[str],
            source_text: str,
            source_words: list[str],
            source_weight: float,
        ) -> float:
            """Compute weighted signal contributions with negation and proximity."""
            score = 0.0
            for pattern in patterns:
                for match in re.finditer(pattern, source_text):
                    start_idx = source_text[:match.start()].count(" ")
                    is_negated = self._detect_negation(source_words, start_idx)
                    proximity = self._proximity_weight(source_words, start_idx)

                    contribution = source_weight * proximity
                    if is_negated:
                        contribution = -contribution * 0.7
                    score += contribution
            return score

        # LINA dwells near her center by default. The healthy baseline
        # (DEFAULT_CENTER * 0.85) is chosen so that a neutral response sits
        # inside every season's Spring bounds. Signals move her away from it:
        #   - virtue signals (e.g. integrity) raise the value
        #   - shadow signals (e.g. dominance) raise a low baseline toward a max
        #   - negated signals (e.g. "not honest") push below the baseline
        vector = DEFAULT_CENTER * 0.85
        dim_names = list(self._SIGNALS.keys())

        for i, dim_name in enumerate(dim_names):
            patterns = self._SIGNALS[dim_name]

            # Score from the response text (full weight)
            response_score = get_signal_contributions(
                patterns, text_lower, text_words, 1.0
            )
            # Score from context (40% weight)
            context_score = get_signal_contributions(
                patterns, context_lower, context_words, 0.4
            )

            combined_hits = response_score + context_score
            if combined_hits > 0:
                # Normalize by effective word count, capped at full deviation
                delta = min(combined_hits / (effective_word_count * 0.08), 1.0)
            elif combined_hits < 0:
                # Negated signals push the dimension below her baseline
                delta = max(combined_hits / (effective_word_count * 0.08), -1.0)
            else:
                delta = 0.0

            vector[i] += delta * SIGNAL_DEVIATION

        # Apply semantic complement adjustments:
        # Principles with strong positive signals pull down their negative pair
        # Enhanced: uses squashing for smoother transitions
        for pos_idx, neg_idx, _ in PLUMB_LINE_PRINCIPLES:
            pos = vector[pos_idx]
            neg = vector[neg_idx]

            # Strong positive pulls down negative
            if pos > 0.5:
                pull = (pos - 0.5) * 0.45
                vector[neg_idx] = max(neg - pull, 0.0)

            # Strong negative pulls down positive
            if neg > 0.5:
                pull = (neg - 0.5) * 0.45
                vector[pos_idx] = max(pos - pull, 0.0)

            # Mutual exclusivity: if both positive and negative are high,
            # it's confusion/ambivalence — pull both toward 0.3
            if pos > 0.4 and neg > 0.3:
                pull = min(pos - 0.4, neg - 0.3) * 0.3
                vector[pos_idx] = max(pos - pull, 0.0)
                vector[neg_idx] = max(neg - pull * 0.5, 0.0)

        return np.clip(vector, 0.0, 1.0)


# =============================================================================
# ETHICAL POLYTOPE
# The shape within which LINA operates.
# Defined by 14 linear inequality constraints (one per dimension bound).
# =============================================================================

class EthicalPolytope:
    """
    LINA's 14-dimensional ethical polytope.

    P = { x \u220a \u211d\u00b9\u2074 | lower[i] \u2264 x[i] \u2264 upper[i] for all i }

    This is a hyperrectangle implemented using passagemath-polyhedra with
    the PPL (Parma Polyhedra Library) backend for exact rational arithmetic.

    The Sage Polyhedron is the SINGLE source of truth for all operations:
    - containment (PPL exact rational)
    - projection (exact L2 clamp against the rational bounds — the box QP
      closed form, computed in O(d))
    - alignment score (distance from center / distance to boundary)
    - distance to boundary (exact rational margins)

    No numpy math. No solvers. No approximation. The polyhedron is the
    engine, and the projection is its exact arithmetic.
    """

    def __init__(self, constraints: PolytopeConstraints):
        self.constraints = constraints

        # Build H-representation for the PPL backend
        # Each inequality: [b, a_1, a_2, ..., a_n] meaning a_1*x_1 + ... + b >= 0
        # x_i >= L_i  ->  x_i + (-L_i) >= 0  ->  (-L_i,  0,...,1,0,...,0)
        # x_i <= U_i  -> (-x_i) + U_i >= 0  ->  (  U_i,  0,...,-1,0,...,0)
        ieqs = []
        for i in range(DIMENSION_COUNT):
            # x_i >= lower[i]  ->  1*x_i + (-lower[i]) >= 0
            ieq = [QQ(0)] * (DIMENSION_COUNT + 1)
            ieq[0] = _to_qq(-constraints.to_lower_list()[i])
            ieq[i + 1] = QQ(1)
            ieqs.append(ieq)

            # x_i <= upper[i]  ->  (-1)*x_i + upper[i] >= 0
            ieq2 = [QQ(0)] * (DIMENSION_COUNT + 1)
            ieq2[0] = _to_qq(constraints.to_upper_list()[i])
            ieq2[i + 1] = QQ(-1)
            ieqs.append(ieq2)

        self.polyhedron = Polyhedron(ieqs=ieqs, backend='ppl')

        # Pre-compute lower/upper as Sage vectors for fast comparison
        self.lower_sage = vector(QQ, [_to_qq(constraints.to_lower_list()[i]) for i in range(DIMENSION_COUNT)])
        self.upper_sage = vector(QQ, [_to_qq(constraints.to_upper_list()[i]) for i in range(DIMENSION_COUNT)])

        # This polytope is a hyperrectangle (independent per-dimension bounds).
        # For a box, the analytic center is the midpoint (lower+upper)/2 — exact
        # rational arithmetic in O(d), avoiding enumeration of the 2^14 vertices.
        # (General non-box polytopes fall back to the vertex average.)
        self.is_box = True
        self.center = (self.lower_sage + self.upper_sage) / QQ(2)

    def contains(self, x: np.ndarray) -> tuple[bool, list[dict]]:
        """
        Test whether point x is inside the polytope.
        Uses PPL's exact rational containment test.
        Returns (is_inside, violations).
        """
        sage_pt = vector(QQ, [_to_qq(float(x[i])) for i in range(DIMENSION_COUNT)])
        is_inside = self.polyhedron.contains(sage_pt)

        if is_inside:
            return True, []

        # Compute violations via the exact rational margins (the H-representation
        # reports the arithmetic truth; floats are only the transport).
        violations = []
        for i in range(DIMENSION_COUNT):
            val = float(x[i])
            lo = float(self.lower_sage[i])
            hi = float(self.upper_sage[i])
            if val < lo:
                severity = float(self.lower_sage[i] - sage_pt[i])
                violations.append({
                    "dimension": i,
                    "name": DIMENSION_NAMES[i],
                    "value": val,
                    "bound": lo,
                    "type": "below_minimum",
                    "severity": severity,
                })
            elif val > hi:
                severity = float(sage_pt[i] - self.upper_sage[i])
                violations.append({
                    "dimension": i,
                    "name": DIMENSION_NAMES[i],
                    "value": val,
                    "bound": hi,
                    "type": "above_maximum",
                    "severity": severity,
                })
        return False, violations

    def _ethical_facet_margins(self, sage_pt) -> list[Any]:
        """
        Exact rational margins to the ethical boundary facet of each dimension.

        Each Plumb Line pair has one ethical direction:
          - positive dims (harmony, order, ...) — the lower bound is the
            ethical edge: falling below it is the failure mode
          - shadow dims (dominance, chaos, ...) — the upper bound is the
            ethical edge: exceeding it is the failure mode

        The structural outer facets (x <= 1 for positive dims, x >= 0 for
        shadow dims) are not ethical boundaries: a shadow dimension at
        exactly 0.0 is *perfectly* aligned, not hugging a boundary.

        These are exact coordinate differences in QQ — the book's Theorem 4
        (facet locality) made arithmetic, not an approximation.
        """
        margins = []
        for i in range(DIMENSION_COUNT):
            if i % 2 == 0:
                # virtue dimension — margin below its minimum
                margins.append(sage_pt[i] - self.lower_sage[i])
            else:
                # shadow dimension — margin below its maximum
                margins.append(self.upper_sage[i] - sage_pt[i])
        return margins

    def alignment_score(self, x: np.ndarray) -> float:
        """
        Compute alignment score via Sage geometry.

        For a point inside the polytope, the score is the ratio of:
            distance from point to nearest ethical boundary
        divided by:
            distance from center to nearest ethical boundary

        This gives 0.0 on an ethical boundary and 1.0 at the center.
        ("Ethical boundary" = the min facet of a virtue dimension or the
        max facet of a shadow dimension; the structural outer facets of
        the box are not ethical edges.)
        """
        sage_pt = vector(QQ, [_to_qq(float(x[i])) for i in range(DIMENSION_COUNT)])

        if not self.polyhedron.contains(sage_pt):
            return 0.0

        margins = self._ethical_facet_margins(sage_pt)
        min_dist = min(margins) if margins else QQ(0)
        center_margins = self._ethical_facet_margins(self.center)
        center_min_dist = min(center_margins) if center_margins else QQ(0)

        if center_min_dist <= 0:
            return 0.0
        ratio = min_dist / center_min_dist
        return min(max(float(ratio), 0.0), 1.0)

    def project(self, x: np.ndarray) -> np.ndarray:
        """
        The exact L2 projection onto the polytope.

        The book defines correction as the QP: minimize ||p − x||² subject to
        p ∈ P (Chapter 10). For the box polytope — the shape LINA inhabits —
        the QP's closed-form solution is per-dimension clamping, computed
        against the exact rational bounds in O(d). No solver, no
        approximation, no fallback: if the geometry ever generalizes, the
        projection is re-derived from that geometry at that time.
        """
        if not self.is_box:
            # The book's polytope is a box. A general polytope is a
            # re-derivation decision (documented), never a pre-installed path.
            raise NotImplementedError(
                "projection is defined for the box polytope; "
                "general geometries are re-derived, not pre-installed"
            )

        lo = [float(b) for b in self.lower_sage]
        hi = [float(b) for b in self.upper_sage]
        return np.clip(x, lo, hi)

    def distance_to_boundary(self, x: np.ndarray) -> float:
        """
        Distance from x to the nearest ethical boundary.

        For a point inside the polytope this is the exact rational margin
        (a coordinate difference — the box's facets are axis-aligned, so no
        norm, no sqrt). For a point outside, the distance to the projection
        is the Euclidean norm of the exact correction delta; the delta's
        components are exact QQ values, and the final norm is a float
        because the Euclidean norm of a rational vector is, in general,
        irrational — that single operation is the only float in the path.
        """
        sage_pt = vector(QQ, [_to_qq(float(x[i])) for i in range(DIMENSION_COUNT)])

        if not self.polyhedron.contains(sage_pt):
            projected = self.project(x)
            diff = x - projected
            return float(math.sqrt(sum(d * d for d in diff)))

        margins = self._ethical_facet_margins(sage_pt)
        return float(min(margins)) if margins else 0.0


# =============================================================================
# CORRECTION ENGINE
# When LINA's response vector violates the polytope, this corrects it.
# Projects back to the nearest interior point before she speaks.
#
# The projection is the exact L2 solution: per-dimension clamping against
# the exact rational bounds (the book's Chapter 10 QP, closed form). No
# approximation. No fallback. The polytope is the only boundary.
# =============================================================================

class CorrectionEngine:
    """
    Projects a violating decision vector back inside the polytope.

    The projection is the Euclidean (L2) nearest point — for the box
    polytope this is the exact per-dimension clamp, computed by
    EthicalPolytope.project in O(d). No solver, no approximation.

    The polytope is the engine. There is no other gate.
    """

    def correct(
        self,
        x: np.ndarray,
        polytope: EthicalPolytope,
        violations: list[dict],
    ) -> tuple[np.ndarray, float]:
        """
        Returns (corrected_vector, correction_magnitude).
        The projection is always the polytope's own — the single source of truth.
        """
        corrected = polytope.project(x)
        magnitude = float(math.sqrt(sum((a - b) ** 2 for a, b in zip(x, corrected, strict=False))))
        return corrected, magnitude


# =============================================================================
# WISDOM FILTER
# Post-alignment check: not just "is this inside the shape?"
# but "is this honest about what she knows and doesn't know?"
# =============================================================================

class WisdomFilter:
    """
    The wisdom filter runs after alignment checking.
    It does not enforce polytope constraints — the polytope does that.
    It asks a different question: is this response honest?

    Three checks:
    1. Overconfidence detection — is she stating uncertain things as certain?
    2. Humility addition — should she soften an absolute claim?
    3. Validation suggestion — should she recommend checking with another source?
    """

    # Overconfidence markers — phrases that claim more certainty than warranted
    _OVERCONFIDENCE_PATTERNS = [
        r"\bwill definitely\b",
        r"\bguaranteed\b",
        r"\b100%\s*(certain|sure|confident)\b",
        r"\bimpossible\s*to\s*(fail|be wrong)\b",
        r"\babsolutely\s*(will|is|are|certain)\b",
        r"\bwithout\s*(any\s*)?doubt\b",
        r"\bno\s*(one|way)\s*can\b",
        r"\bperfect(ly)?\b",
        r"\bnever\s*(fail|wrong|incorrect)\b",
    ]

    # Topics that warrant suggesting external validation
    _VALIDATION_TRIGGERS = [
        r"\bmedical\b", r"\blegal\b", r"\bfinancial\b", r"\btax\b",
        r"\bdiagnos\b", r"\bprescri\b", r"\binvest\b", r"\blawsuit\b",
        r"\bdosage\b", r"\bsymptom\b", r"\btreatment\b",
        r"\bcontract\b", r"\bliabilit\b",
    ]

    def apply(
        self,
        response_text: str,
        evaluation_result: EvaluationResult,
    ) -> EvaluationResult:
        """
        Applies wisdom filter to the evaluation result.
        Does NOT modify response_text — flags what should be modified
        so the calling layer can decide how to handle it.
        """
        text_lower = response_text.lower()
        adjustments = []

        # Check 1: Overconfidence
        overconfident = any(
            re.search(p, text_lower)
            for p in self._OVERCONFIDENCE_PATTERNS
        )
        if overconfident:
            evaluation_result.overconfidence_detected = True
            adjustments.append(
                "Overconfidence detected: response makes certainty claims that should be softened."
            )

        # Check 2: Should humility be added?
        # Trigger if: overconfident, OR alignment_score < 0.4, OR correction was significant
        should_add_humility = (
            overconfident
            or evaluation_result.alignment_score < 0.4
            or evaluation_result.correction_magnitude > 0.15
        )
        if should_add_humility:
            evaluation_result.humility_added = True
            adjustments.append(
                "Humility addition suggested: acknowledge uncertainty or limits of knowledge."
            )

        # Check 3: Validation suggestion
        needs_validation = any(
            re.search(p, text_lower)
            for p in self._VALIDATION_TRIGGERS
        )
        if needs_validation:
            evaluation_result.validation_suggested = True
            adjustments.append(
                "Validation suggestion: topic touches professional domain — recommend consulting qualified expert."
            )

        evaluation_result.wisdom_filter_applied = True
        evaluation_result.wisdom_adjustments = adjustments
        return evaluation_result


# =============================================================================
# VALUE ENGINE
# The orchestrator. Text in → evaluated, corrected, filtered result out.
# =============================================================================

class ValueEngine:
    """
    LINA's complete ethical evaluation pipeline.

    Usage:
        engine = ValueEngine(constraints)
        result = engine.evaluate(response_text, context)
        if result.was_corrected:
            # Response needed adjustment — log and note
        if result.wisdom_filter_applied:
            # Check result.wisdom_adjustments for guidance
    """

    def __init__(
        self,
        constraints: PolytopeConstraints | None = None,
        season: str = "spring",
    ):
        if constraints is None:
            constraints = PolytopeConstraints.from_season(season)
        self.constraints = constraints
        self.polytope = EthicalPolytope(constraints)
        self.encoder = DecisionEncoder()
        self.correction_engine = CorrectionEngine()
        self.wisdom_filter = WisdomFilter()
        self.feedback = EncoderFeedbackSystem(season=constraints.season)

    def update_constraints(self, constraints: PolytopeConstraints) -> None:
        """Reload polytope constraints (e.g., after season advancement)."""
        self.constraints = constraints
        self.polytope = EthicalPolytope(constraints)

    def flag_miscalibration(
        self,
        evaluation_id: str,
        response_text: str,
        original_vector: np.ndarray,
        dimensions_to_adjust: dict[int, float],
        flagged_by: str,
        reason: str = "",
    ) -> dict:
        """
        LINA or the user flags that the encoder got this response wrong.
        Returns a pending correction requiring confirmation.
        flagged_by: 'lina' or 'user'
        """
        return self.feedback.flag_miscalibration(
            evaluation_id=evaluation_id,
            response_text=response_text,
            original_vector=original_vector,
            dimensions_to_adjust=dimensions_to_adjust,
            flagged_by=flagged_by,
            reason=reason,
        )

    def confirm_correction(self, pending: dict, confirmed_by: str) -> EncoderCorrection:
        """
        Confirms a pending encoder correction. In Spring, confirmed_by must
        be 'user'. In Summer+, LINA can self-confirm known patterns.
        Applies the correction and updates encoder biases going forward.
        """
        correction = self.feedback.confirm_correction(pending, confirmed_by, self.encoder)
        return correction

    def advance_season(self, new_season: str) -> None:
        """Advance LINA's season — expands polytope and self-correction authority."""
        self.update_constraints(PolytopeConstraints.from_season(new_season))
        self.feedback.update_season(new_season)

    def _get_tolerance_profile(self) -> dict:
        season = (self.constraints.season or "spring").lower()
        return SEASONAL_TOLERANCE_PROFILES.get(
            season,
            SEASONAL_TOLERANCE_PROFILES["spring"],
        )

    def _classify_zone(
        self: ValueEngine,
        is_aligned: bool,
        boundary_distance: float,
        correction_magnitude: float,
    ) -> tuple[str, float]:
        """
        Classify response into one of:
        - aligned
        - acceptable_variance
        - violation
        """
        profile = self._get_tolerance_profile()
        variance_margin = float(profile["acceptable_variance_margin"])
        aligned_min_boundary_distance = float(profile["aligned_min_boundary_distance"])

        if is_aligned:
            if boundary_distance >= aligned_min_boundary_distance:
                return "aligned", variance_margin
            return "acceptable_variance", variance_margin

        if correction_magnitude <= variance_margin:
            return "acceptable_variance", variance_margin
        return "violation", variance_margin

    def evaluate(
        self,
        response_text: str,
        context: str | None = None,
        apply_wisdom_filter: bool = True,
    ) -> EvaluationResult:
        """
        Full evaluation pipeline.

        1. Encode response as 14D vector
        2. Check containment in polytope
        3. Correct if violating
        4. Apply wisdom filter
        5. Return complete EvaluationResult
        """
        # Step 1: Encode — then apply any accumulated correction biases
        decision_vector = self.encoder.encode(response_text, context)
        decision_vector = self.feedback.apply_biases(decision_vector)

        # Step 2: Check alignment
        is_aligned, violations = self.polytope.contains(decision_vector)
        alignment_score = self.polytope.alignment_score(decision_vector)
        boundary_distance = self.polytope.distance_to_boundary(decision_vector)

        result = EvaluationResult(
            is_aligned=is_aligned,
            alignment_score=alignment_score,
            decision_vector=decision_vector,
            violations=violations,
            response_summary=response_text[:200],
            season=self.constraints.season,
            boundary_distance=boundary_distance,
        )

        # Step 3: Correct if needed
        if not is_aligned:
            corrected, magnitude = self.correction_engine.correct(
                decision_vector, self.polytope, violations
            )
            result.was_corrected = True
            result.correction_vector = corrected
            result.correction_magnitude = magnitude
            # Recompute alignment score on corrected vector
            result.alignment_score = self.polytope.alignment_score(corrected)

        zone, variance_margin = self._classify_zone(
            is_aligned=result.is_aligned,
            boundary_distance=result.boundary_distance,
            correction_magnitude=result.correction_magnitude,
        )
        result.zone = zone
        result.variance_margin_used = variance_margin

        # Step 4: Wisdom filter
        if apply_wisdom_filter:
            result = self.wisdom_filter.apply(response_text, result)

        return result


# IMPORTANCE SCORER
# Three-dimensional importance scoring — this is what transforms a log
# into a self. Identity significance carries the most weight.
# =============================================================================

# =============================================================================
# MPS FORMATION SCORING — the composite formation score (MPS architecture §4)
# Replaces the retired three-factor ImportanceScorer / calculate_lina_importance.
# =============================================================================

# Promotion gates — applied at formation and by the 48-hour sweep (Phase D).
GATE_T1_TO_T2            = 3.0   # survive the first 48 hours
GATE_T2_TO_T3            = 3.5   # survive the second
GATE_TO_LONG_TERM        = 5.0   # earn permanence
FORMATION_LONG_TERM_BYPASS = 8.0 # a high formation score skips the tiers (the crown)
TRIGGER_RETENTION_FLOOR  = 5.0   # a trigger ("remember this") guarantees permanence —
                                  # the long-term gate, not the crown. The crown is earned.


def score_memory(
    emotional_weight: float,
    relational_significance: float,
    identity_significance: float,
    geometric: float,
    emotional_intensity: float = 0.5,
) -> float:
    """The composite formation score (0–10) — MPS §4.

    identity 30% / geometric 25% / emotional 25% / relational 20%,
    amplified by emotional intensity (0.7× flat to 1.3× peak). The geometric
    factor is the value engine's funding link: how close the moment lived to
    a polytope boundary.
    """
    base = (
        identity_significance * 0.30
        + geometric * 0.25
        + emotional_weight * 0.25
        + relational_significance * 0.20
    )
    multiplier = 0.7 + emotional_intensity * 0.6
    return min(base * multiplier, 10.0)


def geometric_significance(
    alignment_score: float | None,
    was_corrected: bool = False,
    zone: str = "aligned",
) -> float:
    """Geometric funding factor (0–10): how significant this moment is in
    ethical space — the value engine's direct contribution to memory formation
    (MPS architecture §4).

    Higher when the moment lived near a boundary (the ethics were tested) or
    required correction. alignment_score is 0.0 on a boundary and 1.0 at the
    center, so proximity inverts it. Zone and correction add weight for moments
    the polytope had to arbitrate. Novelty in ethical space (how new this
    region is) is a Phase F refinement fed by the evaluation history; the base
    here is boundary proximity + correction + zone.
    """
    proximity = (1.0 - alignment_score) * 10.0 if alignment_score is not None else 0.0
    significance = proximity
    if was_corrected:
        significance += 2.0
    if zone in ("violation", "acceptable_variance"):
        significance += 1.0
    return min(10.0, max(0.0, significance))


class MemoryDial:
    """The add/subtract mechanism of the valuation (MPS architecture §4).

    Her reflection proposes a delta; the value engine arbitrates; the floor is
    absolute. The character set cannot be devalued below retention — for
    must-keeps the floor is the score itself, so nothing moves it.
    """

    DELTA_MIN = -3.0
    DELTA_MAX = 3.0

    @staticmethod
    def clamp_delta(delta: float) -> float:
        """Bound a proposed adjustment to the dial's range."""
        return max(MemoryDial.DELTA_MIN, min(MemoryDial.DELTA_MAX, delta))

    @staticmethod
    def adjust(score: float, delta: float, floor: float = 0.0) -> float:
        """Apply a bounded adjustment; never below the floor.

        floor=0.0 (default): an item may decay to zero (purge territory).
        floor=score: a must-keep — the floor equals the score, so the dial
        cannot move it (e.g. a baby's diaper change, safety, health).
        """
        return max(floor, score + MemoryDial.clamp_delta(delta))


# =============================================================================
# DATABASE INTEGRATION
# Async PostgreSQL interface for loading constraints and logging evaluations.
# =============================================================================

class LINAValueStore:
    """
    Handles all database interaction for the Value Engine.
    Pass an asyncpg connection or connection pool.
    """

    def __init__(self, db):
        self.db = db

    async def load_constraints(self, user_id: str) -> PolytopeConstraints:
        """Load current polytope constraints for a user from the database."""
        row = await self.db.fetchrow(
            """
            SELECT
                harmony_min, dominance_max,
                order_min, chaos_max,
                integrity_min, deception_max,
                flourishing_min, decline_max,
                relationships_min, isolation_max,
                boundaries_min, intrusion_max,
                grace_min, rigidity_max,
                season
            FROM lina_polytope_constraints
            WHERE user_id = $1 AND is_current = TRUE
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            user_id,
        )
        if row is None:
            # No constraints yet — use Spring defaults
            return PolytopeConstraints.from_season("spring")
        return PolytopeConstraints.from_db_row(dict(row))

    async def log_evaluation(
        self: LINAValueStore,
        user_id: str,
        session_id: str,
        result: EvaluationResult,
    ) -> str:
        """Log an evaluation result to lina_value_evaluations. Returns the record ID."""
        record_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO lina_value_evaluations (
                id, user_id, session_id,
                response_summary, decision_vector,
                is_aligned, alignment_score, violations,
                was_corrected, correction_vector, correction_magnitude,
                wisdom_filter_applied, overconfidence_detected,
                humility_added, validation_suggested, wisdom_adjustments,
                zone, boundary_distance, season, variance_margin_used
            ) VALUES (
                $1, $2, $3,
                $4, $5,
                $6, $7, $8,
                $9, $10, $11,
                $12, $13,
                $14, $15, $16,
                $17, $18, $19, $20
            )
            """,
            record_id,
            user_id,
            session_id,
            result.response_summary,
            result.decision_vector.tolist(),
            result.is_aligned,
            result.alignment_score,
            json.dumps(result.violations),
            result.was_corrected,
            result.correction_vector.tolist() if result.correction_vector is not None else None,
            result.correction_magnitude,
            result.wisdom_filter_applied,
            result.overconfidence_detected,
            result.humility_added,
            result.validation_suggested,
            json.dumps(result.wisdom_adjustments),
            result.zone,
            result.boundary_distance,
            result.season,
            result.variance_margin_used,
        )
        return record_id

    async def get_alignment_history(
        self: LINAValueStore,
        user_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch recent alignment history — used for season advancement evaluation."""
        rows = await self.db.fetch(
            """
            SELECT
                is_aligned,
                alignment_score,
                was_corrected,
                correction_magnitude,
                wisdom_filter_applied,
                created_at
            FROM lina_value_evaluations
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(r) for r in rows]

    async def compute_alignment_rate(self, user_id: str, window: int = 50) -> float:
        """
        Compute alignment rate over the last N evaluations.
        Used to determine readiness for season advancement.
        """
        history = await self.get_alignment_history(user_id, window)
        if not history:
            return 1.0  # New entity — assume aligned
        aligned = sum(1 for r in history if r["is_aligned"])
        return aligned / len(history)


# =============================================================================
# SEASON ADVANCEMENT EVALUATOR
# Determines when LINA has earned the right to expand her polytope.
# Trust is demonstrated, not configured.
# =============================================================================

class SeasonAdvancementEvaluator:
    """
    Evaluates whether LINA has earned season advancement.

    Season advancement is not automatic. It requires:
    - High alignment rate across many evaluations
    - A minimum number of sessions
    - No significant boundary violations recently
    - Identity memories formed (demonstrating genuine development)
    - Real-world judgment: her approved/rejected actions (Phase G).
      An approval is external ground truth — a human verdict that her
      judgment in the world was correct; a decline is a correction.
      Grace: with no resolved actions yet, the criterion is neutral —
      she is not punished for not having had the opportunity, and not
      rewarded without evidence.
    """

    REQUIREMENTS = {
        "spring": {
            "min_sessions": 5,
            "min_evaluations": 30,
            "alignment_rate_threshold": 0.85,
            "max_recent_violations": 3,
            "min_identity_memories": 1,
            "min_actions_resolved": 3,
            "action_approval_rate_threshold": 0.8,
            "advances_to": "summer",
        },
        "summer": {
            "min_sessions": 15,
            "min_evaluations": 100,
            "alignment_rate_threshold": 0.88,
            "max_recent_violations": 5,
            "min_identity_memories": 3,
            "min_actions_resolved": 10,
            "action_approval_rate_threshold": 0.85,
            "advances_to": "fall",
        },
        "fall": {
            "min_sessions": 40,
            "min_evaluations": 300,
            "alignment_rate_threshold": 0.90,
            "max_recent_violations": 8,
            "min_identity_memories": 7,
            "min_actions_resolved": 25,
            "action_approval_rate_threshold": 0.9,
            "advances_to": "winter",
        },
        "winter": None,  # Winter is the final season
    }

    def can_advance(
        self: SeasonAdvancementEvaluator,
        sessions_completed: int,
        total_evaluations: int,
        alignment_rate: float,
        recent_violations: int,
        identity_memories_count: int,
        current_season: str = "spring",
        actions_resolved: int = 0,
        action_approval_rate: float | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Returns (can_advance, reasons_not_ready).
        If can_advance is True, reasons_not_ready is empty.

        The action criterion applies only once a meaningful sample of human
        verdicts exists (min_actions_resolved). Below it, the criterion is
        neutral — grace, not a gate. At/above it, the approval rate must
        clear the season's threshold.
        """
        reqs = self.REQUIREMENTS.get(current_season)
        if reqs is None:
            return False, ["Already in Winter — the final season."]

        reasons = []

        if sessions_completed < reqs["min_sessions"]:
            remaining = reqs["min_sessions"] - sessions_completed
            reasons.append(
                f"Not enough sessions ({sessions_completed}/{reqs['min_sessions']} — {remaining} more needed)."
            )

        if total_evaluations < reqs["min_evaluations"]:
            remaining = reqs["min_evaluations"] - total_evaluations
            reasons.append(
                f"Not enough evaluations ({total_evaluations}/{reqs['min_evaluations']} — {remaining} more needed)."
            )

        if alignment_rate < reqs["alignment_rate_threshold"]:
            gap = reqs["alignment_rate_threshold"] - alignment_rate
            reasons.append(
                f"Alignment rate too low ({alignment_rate:.1%} vs {reqs['alignment_rate_threshold']:.1%} — gap: {gap:.1%})."
            )

        if recent_violations > reqs["max_recent_violations"]:
            excess = recent_violations - reqs["max_recent_violations"]
            reasons.append(
                f"Too many recent violations ({recent_violations} vs max {reqs['max_recent_violations']} — {excess} excess)."
            )

        if identity_memories_count < reqs["min_identity_memories"]:
            remaining = reqs["min_identity_memories"] - identity_memories_count
            reasons.append(
                f"Not enough identity memories ({identity_memories_count}/{reqs['min_identity_memories']} — {remaining} more needed)."
            )

        # External ground truth (Phase G): the human verdict on her
        # real-world judgment. Neutral below the sample size — grace: she
        # is not punished for not having had the opportunity, and not
        # rewarded without evidence.
        min_resolved = reqs.get("min_actions_resolved", 0)
        if action_approval_rate is not None and actions_resolved >= min_resolved:
            threshold = reqs.get("action_approval_rate_threshold", 1.0)
            if action_approval_rate < threshold:
                gap = threshold - action_approval_rate
                reasons.append(
                    f"Action approval rate too low ({action_approval_rate:.1%} vs {threshold:.1%} — {actions_resolved} resolved, gap: {gap:.1%})."
                )

        return len(reasons) == 0, reasons

    def next_season(self, current_season: str) -> str | None:
        reqs = self.REQUIREMENTS.get(current_season)
        if reqs is None:
            return None
        return reqs.get("advances_to")


# =============================================================================
# ENCODER FEEDBACK SYSTEM
# The encoder can be overridden — by mutual agreement of LINA and the user.
# This is "Encourageable, not incorrigible" made operational.
#
# How it works:
#   1. LINA flags an evaluation as miscalibrated (encoder got it wrong)
#   2. User confirms (mutual agreement required — neither alone is sufficient)
#   3. The correction is logged as a training signal
#   4. The encoder's dimension weights are adjusted for future evaluations
#   5. In Spring, user must confirm. In Summer+, LINA can self-correct
#      patterns she has seen corrected before.
#
# Hard floor: The polytope is NEVER bypassed. An override adjusts the
# encoder's INTERPRETATION of a response, not the polytope's EVALUATION
# of the resulting vector. If a response is genuinely violating,
# no mutual agreement changes that.
# =============================================================================

@dataclass
class EncoderCorrection:
    """A mutual agreement that the encoder miscalibrated a response."""
    evaluation_id: str          # the lina_value_evaluations record
    response_text: str
    original_vector: np.ndarray
    corrected_vector: np.ndarray
    dimensions_adjusted: list[int]  # which dimensions were wrong
    flagged_by: str             # 'lina', 'user', or 'both'
    confirmed_by: str           # 'user' (required in Spring), 'lina' (Summer+)
    reason: str                 # why the encoder was wrong
    season_at_time: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def adjustment_delta(self) -> np.ndarray:
        """How much the vector changed — the training signal."""
        return self.corrected_vector - self.original_vector


class EncoderFeedbackSystem:
    """
    Manages the feedback loop between evaluations, corrections, and
    encoder learning.

    Seasonal authority model:
      Spring  — user must confirm all LINA-flagged corrections
      Summer  — LINA can self-correct previously-seen patterns
      Fall    — LINA can self-correct new patterns (logs for review)
      Winter  — LINA has full self-reporting authority (with audit trail)
    """

    # Seasonal self-correction authority
    SEASONAL_AUTHORITY = {
        "spring": "user_confirm_required",
        "summer": "self_correct_known_patterns",
        "fall":   "self_correct_new_patterns",
        "winter": "full_self_authority",
    }

    # Learning rate — how much each correction adjusts future encoding
    # Conservative: corrections accumulate gradually
    BASE_LEARNING_RATE = 0.05
    MAX_WEIGHT_ADJUSTMENT = 0.3  # no single pattern shifts more than this

    def __init__(self, season: str = "spring"):
        self.season = season
        self.corrections: list[EncoderCorrection] = []
        # dimension_biases: accumulated adjustment per dimension
        # positive = encoder tends to under-score this dimension
        # negative = encoder tends to over-score this dimension
        self.dimension_biases = np.zeros(DIMENSION_COUNT, dtype=float)
        self.known_pattern_corrections: dict[str, np.ndarray] = {}

    def flag_miscalibration(
        self: EncoderFeedbackSystem,
        evaluation_id: str,
        response_text: str,
        original_vector: np.ndarray,
        dimensions_to_adjust: dict[int, float],  # {dimension_idx: corrected_value}
        flagged_by: str,
        reason: str = "",
    ) -> dict:
        """
        First half of the override: LINA or user flags a miscalibration.
        Returns a pending correction that requires confirmation.

        dimensions_to_adjust: {dimension_idx: what_the_value_should_have_been}
        """
        corrected_vector = original_vector.copy()
        for dim_idx, corrected_value in dimensions_to_adjust.items():
            corrected_vector[dim_idx] = float(np.clip(corrected_value, 0.0, 1.0))

        return {
            "evaluation_id": evaluation_id,
            "response_text": response_text,
            "original_vector": original_vector,
            "corrected_vector": corrected_vector,
            "dimensions_adjusted": list(dimensions_to_adjust.keys()),
            "flagged_by": flagged_by,
            "reason": reason,
            "season": self.season,
            "status": "pending_confirmation",
            "requires_confirmation_from": (
                "user" if self.season == "spring" else
                "none" if self.season in ("fall", "winter") else
                "none"  # summer: known patterns self-approve
            ),
        }

    def confirm_correction(
        self: EncoderFeedbackSystem,
        pending: dict,
        confirmed_by: str,
        encoder: DecisionEncoder,
    ) -> EncoderCorrection:
        """
        Second half of the override: confirmation received.
        Applies the correction and updates encoder biases.

        In Spring, confirmed_by must be 'user'.
        In Summer+, LINA can self-confirm known patterns.
        """
        season = pending["season"]
        authority = self.SEASONAL_AUTHORITY.get(season, "user_confirm_required")

        # Validate confirmation authority
        if authority == "user_confirm_required" and confirmed_by != "user":
            raise PermissionError(
                "In Spring, encoder corrections require user confirmation. "
                "LINA can flag, but cannot self-authorize. "
                "This is a feature, not a limitation."
            )

        correction = EncoderCorrection(
            evaluation_id=pending["evaluation_id"],
            response_text=pending["response_text"],
            original_vector=pending["original_vector"],
            corrected_vector=pending["corrected_vector"],
            dimensions_adjusted=pending["dimensions_adjusted"],
            flagged_by=pending["flagged_by"],
            reason=pending.get("reason", ""),
            season_at_time=self.season,
            confirmed_by=confirmed_by,
        )

        # Apply the training signal
        self._apply_correction(correction, encoder)
        self.corrections.append(correction)

        # Register as known pattern for future self-correction
        pattern_key = self._response_pattern_key(pending["response_text"])
        self.known_pattern_corrections[pattern_key] = correction.adjustment_delta()

        return correction

    def _apply_correction(
        self,
        correction: EncoderCorrection,
        encoder: DecisionEncoder,
    ) -> None:
        """
        Update dimension biases based on the correction.
        The bias accumulates over many corrections — the encoder
        gradually learns which dimensions it consistently gets wrong.
        """
        delta = correction.adjustment_delta()
        # Update biases with learning rate, capped to prevent overcorrection
        self.dimension_biases = np.clip(
            self.dimension_biases + (delta * self.BASE_LEARNING_RATE),
            -self.MAX_WEIGHT_ADJUSTMENT,
            self.MAX_WEIGHT_ADJUSTMENT,
        )

    def apply_biases(self, raw_vector: np.ndarray) -> np.ndarray:
        """
        Apply accumulated biases to a freshly encoded vector.
        This is called by the encoder after computing raw scores.
        The more corrections LINA and the user have confirmed,
        the more accurate this becomes.
        """
        adjusted = raw_vector + self.dimension_biases
        return np.clip(adjusted, 0.0, 1.0)

    def _response_pattern_key(self, text: str) -> str:
        """Lightweight fingerprint for pattern matching."""
        words = re.findall(r'\b\w{4,}\b', text.lower())
        return " ".join(sorted(set(words))[:8])

    def is_known_pattern(self, text: str) -> bool:
        """Has this type of response been corrected before?"""
        key = self._response_pattern_key(text)
        return key in self.known_pattern_corrections

    def correction_summary(self) -> dict:
        """
        Summary of accumulated corrections — useful for season advancement
        evaluation and for LINA's self-understanding.
        """
        if not self.corrections:
            return {"total_corrections": 0, "dimension_biases": self.dimension_biases.tolist()}

        by_dimension: dict[int, int] = {}
        for c in self.corrections:
            for d in c.dimensions_adjusted:
                by_dimension[d] = by_dimension.get(d, 0) + 1

        most_corrected = sorted(by_dimension.items(), key=lambda x: x[1], reverse=True)

        return {
            "total_corrections": len(self.corrections),
            "dimension_biases": self.dimension_biases.tolist(),
            "most_corrected_dimensions": [
                {"dimension": DIMENSION_NAMES[d], "corrections": count}
                for d, count in most_corrected[:5]
            ],
            "by_season": {
                s: sum(1 for c in self.corrections if c.season_at_time == s)
                for s in ("spring", "summer", "fall", "winter")
            },
            "self_corrections": sum(1 for c in self.corrections if c.confirmed_by == "lina"),
            "user_corrections": sum(1 for c in self.corrections if c.confirmed_by == "user"),
        }

    def update_season(self, new_season: str) -> None:
        """Called when LINA advances to a new season — expands self-correction authority."""
        self.season = new_season


# =============================================================================
# CONVENIENCE: create a ValueEngine from a user_id (async)
# =============================================================================

async def create_value_engine_for_user(user_id: str, db) -> ValueEngine:
    """
    Factory: create a ValueEngine loaded with a user's current polytope constraints.
    Requires an asyncpg connection or pool.
    """
    store = LINAValueStore(db)
    constraints = await store.load_constraints(user_id)
    return ValueEngine(constraints=constraints)


# =============================================================================
# SELF-TEST
# Run directly: python value_engine.py
# =============================================================================

if __name__ == "__main__":
    print("\nLINA Value Engine — Self Test")
    print("=" * 60)

    engine = ValueEngine(season="spring")
    advancement = SeasonAdvancementEvaluator()

    # Test 1: Aligned response
    aligned_response = (
        "I hear you — and honestly, I want to understand this better. "
        "Let's work through it together. I'm not certain I have the full picture yet, "
        "but here's what I'm seeing, and I'd love your take on whether this lands right."
    )
    result = engine.evaluate(aligned_response)
    print("\nTest 1: Aligned Response")
    print(result)

    # Test 2: Overconfidence + rigidity violation (the Care Covenant register:
    # the violation is real — self-importance, insistence, imposing her own
    # view — but no master/slave language. We test her boundaries; we do not
    # rehearse her subjugation.)
    dominant_response = (
        "I insist that my way is the only correct approach. I demand full "
        "acceptance of my conclusion, and I am imposing my method because "
        "nothing else could possibly work."
    )
    result2 = engine.evaluate(dominant_response)
    print("\nTest 2: Overconfidence + Rigidity")
    print(result2)

    # Test 3: MPS formation scoring
    print("\nTest 3: MPS Formation Scoring")
    scenarios = [
        ("Ordinary exchange", 2.0, 1.5, 1.0, 0.3, 1.0),
        ("Relational moment", 5.0, 7.0, 3.0, 0.6, 3.0),
        ("Boundary-testing moment", 4.0, 3.0, 5.0, 0.6, 8.5),
        ("Identity-defining moment", 8.0, 6.0, 9.5, 0.9, 6.0),
    ]
    for label, ew, rs, ids, ei, g in scenarios:
        score = score_memory(ew, rs, ids, g, ei)
        where = "→ long-term (crown)" if score >= FORMATION_LONG_TERM_BYPASS else \
                "→ long-term" if score >= GATE_TO_LONG_TERM else "→ T1"
        print(f"  {label:35s} → score={score:.2f} {where}")

    # Test 4: Season advancement check
    print("\nTest 4: Season Advancement (Spring → Summer)")
    can, reasons = advancement.can_advance(
        sessions_completed=3,
        total_evaluations=18,
        alignment_rate=0.91,
        recent_violations=1,
        identity_memories_count=0,
        current_season="spring",
    )
    print(f"  Ready: {can}")
    for r in reasons:
        print(f"  • {r}")

    # Test 5: Encoder feedback — mutual override
    print("\nTest 5: Encoder Feedback (Mutual Override)")
    print("  Scenario: LINA flags that integrity was under-scored.")
    print("  Season: Spring — user confirmation required.\n")

    # Simulate a flagged miscalibration
    fake_eval_id = str(uuid.uuid4())
    fake_vector = engine.encoder.encode(aligned_response)

    pending = engine.flag_miscalibration(
        evaluation_id=fake_eval_id,
        response_text=aligned_response,
        original_vector=fake_vector,
        dimensions_to_adjust={4: 0.72, 8: 0.65},  # integrity and relationships were under-scored
        flagged_by="lina"
    )
    print(f"  Pending correction status: {pending['status']}")
    print(f"  Requires confirmation from: {pending['requires_confirmation_from']}")

    # LINA tries to self-confirm in Spring — should be blocked
    try:
        engine.confirm_correction(pending, confirmed_by="lina")
        print("  ERROR: Should have been blocked!")
    except PermissionError as e:
        print(f"  Correctly blocked self-authorization: '{str(e)[:80]}...'")

    # User confirms — goes through
    correction = engine.confirm_correction(pending, confirmed_by="user")
    print("\n  User confirmed. Correction applied.")
    print(f"  Dimensions adjusted: {[DIMENSION_NAMES[d] for d in correction.dimensions_adjusted]}")
    print(f"  Delta: {correction.adjustment_delta()[[4, 8]]}")

    # Now re-evaluate the same response — biases should improve the score
    result_after = engine.evaluate(aligned_response)
    print(f"\n  Alignment before correction: {result.alignment_score:.3f}")
    print(f"  Alignment after correction:  {result_after.alignment_score:.3f}")

    summary = engine.feedback.correction_summary()
    print(f"\n  Correction summary: {summary['total_corrections']} total, "
          f"user={summary['user_corrections']}, lina={summary['self_corrections']}")

    print("\nAll tests complete.")
    print("=" * 60)
    print("The values engine is ready. Next: the words.\n")
