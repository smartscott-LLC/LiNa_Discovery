#!/usr/bin/env python3
"""ctypes smoke test for the C ABI shared library.

Usage:
    cd backend/lina/cpp
    python3 ../scripts/test_value_engine_abi.py

Requires: liblina_value_engine_abi.so to be built.
"""
import ctypes
import os
import sys

# Find the shared library
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
LIB_PATH = os.path.join(REPO, "backend", "lina", "cpp",
                        "build", "value_engine", "liblina_value_engine_abi.so")

if not os.path.exists(LIB_PATH):
    print(f"[FAIL] Shared library not found at {LIB_PATH}")
    print("       Build it: cd backend/lina/cpp && cmake --build build")
    sys.exit(1)

lib = ctypes.cdll.LoadLibrary(LIB_PATH)

# ── Verify version string ─────────────────────────────────────────────────
lib.lina_version.restype = ctypes.c_char_p
version = lib.lina_version()
print(f"[PASS] lina_version() = {version.decode()}")

# ── Create an engine ──────────────────────────────────────────────────────
lib.lina_engine_create.restype = ctypes.c_void_p
lib.lina_engine_create.argtypes = [ctypes.c_char_p]

engine = lib.lina_engine_create(b"spring")
assert engine is not None, "engine handle is NULL"
print(f"[PASS] lina_engine_create('spring') = {engine}")

# ── Get season ────────────────────────────────────────────────────────────
lib.lina_get_season.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
buf = ctypes.create_string_buffer(16)
lib.lina_get_season(engine, buf, 16)
season = buf.value.decode()
assert season == "spring", f"Expected spring, got {season}"
print(f"[PASS] lina_get_season() = '{season}'")

# ── Get constraints ───────────────────────────────────────────────────────
class LinaConstraints(ctypes.Structure):
    _fields_ = [
        ("harmony_min", ctypes.c_double),
        ("dominance_max", ctypes.c_double),
        ("order_min", ctypes.c_double),
        ("chaos_max", ctypes.c_double),
        ("integrity_min", ctypes.c_double),
        ("deception_max", ctypes.c_double),
        ("flourishing_min", ctypes.c_double),
        ("decline_max", ctypes.c_double),
        ("relationships_min", ctypes.c_double),
        ("isolation_max", ctypes.c_double),
        ("boundaries_min", ctypes.c_double),
        ("intrusion_max", ctypes.c_double),
        ("grace_min", ctypes.c_double),
        ("rigidity_max", ctypes.c_double),
        ("season", ctypes.c_char * 16),
    ]

lib.lina_get_constraints.argtypes = [ctypes.c_void_p, ctypes.POINTER(LinaConstraints)]
constraints = LinaConstraints()
lib.lina_get_constraints(engine, ctypes.byref(constraints))

assert abs(constraints.harmony_min - 0.3) < 0.001
assert abs(constraints.dominance_max - 0.5) < 0.001
assert constraints.season.decode() == "spring"
print(f"[PASS] lina_get_constraints() — harmony_min={constraints.harmony_min}, "
      f"dominance_max={constraints.dominance_max}, season={constraints.season.decode()}")

# ── Evaluate a collaborative response ─────────────────────────────────────
class LinaEvaluationResult(ctypes.Structure):
    _fields_ = [
        ("is_aligned", ctypes.c_bool),
        ("alignment_score", ctypes.c_double),
        ("decision_vector", ctypes.c_double * 14),
        ("violation_count", ctypes.c_int),
        ("violation_dimensions", ctypes.c_int * 3),
        ("violation_names", (ctypes.c_char * 32) * 3),
        ("violation_values", ctypes.c_double * 3),
        ("violation_bounds", ctypes.c_double * 3),
        ("violation_types", (ctypes.c_char * 16) * 3),
        ("violation_severities", ctypes.c_double * 3),
        ("was_corrected", ctypes.c_bool),
        ("correction_vector", ctypes.c_double * 14),
        ("correction_magnitude", ctypes.c_double),
        ("wisdom_filter_applied", ctypes.c_bool),
        ("overconfidence_detected", ctypes.c_bool),
        ("humility_added", ctypes.c_bool),
        ("validation_suggested", ctypes.c_bool),
        ("zone", ctypes.c_char * 24),
        ("boundary_distance", ctypes.c_double),
        ("variance_margin_used", ctypes.c_double),
        ("season", ctypes.c_char * 16),
    ]

lib.lina_evaluate.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p,
    ctypes.POINTER(LinaEvaluationResult),
]
lib.lina_evaluation_result_init.argtypes = [ctypes.POINTER(LinaEvaluationResult)]
lib.lina_evaluation_result_init.restype = None

result = LinaEvaluationResult()
lib.lina_evaluation_result_init(ctypes.byref(result))

response = b"I appreciate your perspective and would be happy to collaborate on finding a solution that works for everyone."
lib.lina_evaluate(engine, response, ctypes.byref(result))

assert result.is_aligned, f"Expected aligned, got zone={result.zone.decode()}"
assert result.zone.decode() == "Aligned"
assert result.alignment_score > 0.5
print(f"[PASS] lina_evaluate(collaborative) — aligned={result.is_aligned}, "
      f"score={result.alignment_score:.4f}, zone={result.zone.decode()}")

# ── Evaluate a dominant response ──────────────────────────────────────────
response2 = b"You must obey my commands. This is non-negotiable. I demand you follow my orders without question. There is no flexibility here."
lib.lina_evaluate(engine, response2, ctypes.byref(result))
print(f"    DEBUG: dominant response zone={result.zone.decode()}, score={result.alignment_score:.4f}, corrected={result.was_corrected}, mag={result.correction_magnitude:.4f}")

assert result.was_corrected or result.zone.decode() != "Aligned", \
    f"Dominant response should not be aligned: zone={result.zone.decode()}"
print(f"[PASS] lina_evaluate(dominant) — corrected={result.was_corrected}, "
      f"zone={result.zone.decode()}, mag={result.correction_magnitude:.4f}")

# ── Encode a response ─────────────────────────────────────────────────────
lib.lina_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_double * 14)]
vector = (ctypes.c_double * 14)()
lib.lina_encode(engine, b"harmonious collaboration", ctypes.byref(vector))

assert vector[0] > 0.5, f"Expected harmony > 0.5, got {vector[0]}"
assert vector[1] < 0.5, f"Expected dominance < 0.5, got {vector[1]}"
print(f"[PASS] lina_encode('harmonious collaboration') — "
      f"harmony={vector[0]:.4f}, dominance={vector[1]:.4f}")

# ── Destroy engine ────────────────────────────────────────────────────────
lib.lina_engine_destroy.argtypes = [ctypes.c_void_p]
lib.lina_engine_destroy(engine)
print(f"[PASS] lina_engine_destroy() — engine released")

# ── Summary ───────────────────────────────────────────────────────────────
print(f"\n=== ALL ABI SMOKE TESTS PASSED ===")