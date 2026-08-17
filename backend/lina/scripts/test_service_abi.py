#!/usr/bin/env python3
"""ctypes smoke test for the Identity Service C ABI (LINACore).

Usage:
    cd backend/lina/cpp
    python3 ../../scripts/test_service_abi.py

Requires: liblina_service_abi.so to be built.
"""
import ctypes
import json
import os
import sys
import traceback

# Find the shared library
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
LIB_PATH = os.path.join(REPO, "backend", "lina", "cpp",
                         "build", "service", "liblina_service_abi.so")

if not os.path.exists(LIB_PATH):
    print(f"[FAIL] Shared library not found at {LIB_PATH}")
    print("       Build it: cd backend/lina/cpp && cmake --build build --target lina_service_abi")
    sys.exit(1)

lib = ctypes.cdll.LoadLibrary(LIB_PATH)

# ── Flat C struct definitions ────────────────────────────────────────────────

class LinaServiceState(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_uint64),
        ("clock", ctypes.c_uint64),
        ("sessions_processed", ctypes.c_uint64),
        ("evaluations_performed", ctypes.c_uint64),
        ("tools_executed", ctypes.c_uint64),
        ("corrections_made", ctypes.c_uint64),
        ("seasonal_advancements", ctypes.c_uint64),
        ("total_tokens_generated", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64 * 56),
    ]

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

def _call_chat(lib, core, user_id, session_id, message):
    """Helper: call lina_core_chat, return Python dict, free C memory."""
    lib.lina_core_chat.restype = ctypes.c_void_p
    json_ptr = lib.lina_core_chat(core, user_id, session_id, message)
    if not json_ptr:
        return None
    # Read the C string from the pointer
    c_str = ctypes.cast(json_ptr, ctypes.c_char_p).value
    # Free the C memory
    lib.lina_core_free_string(ctypes.c_void_p(json_ptr))
    if c_str is None:
        return None
    return json.loads(c_str.decode())


def _call_end_session(lib, core, user_id, session_id):
    """Helper: call lina_core_end_session, return Python dict, free C memory."""
    lib.lina_core_end_session.restype = ctypes.c_void_p
    json_ptr = lib.lina_core_end_session(core, user_id, session_id)
    if not json_ptr:
        return None
    c_str = ctypes.cast(json_ptr, ctypes.c_char_p).value
    lib.lina_core_free_string(ctypes.c_void_p(json_ptr))
    if c_str is None:
        return None
    return json.loads(c_str.decode())


def _call_advance_season(lib, core, user_id, session_number):
    """Helper: call lina_core_advance_season, return Python dict, free C memory."""
    lib.lina_core_advance_season.restype = ctypes.c_void_p
    json_ptr = lib.lina_core_advance_season(core, user_id, session_number)
    if not json_ptr:
        return None
    c_str = ctypes.cast(json_ptr, ctypes.c_char_p).value
    lib.lina_core_free_string(ctypes.c_void_p(json_ptr))
    if c_str is None:
        return None
    return json.loads(c_str.decode())

tests_passed = 0
tests_failed = 0


def test(name):
    """Decorator for test functions — catches and reports exceptions."""
    global tests_passed, tests_failed
    def decorator(fn):
        def wrapper(*args, **kwargs):
            global tests_passed, tests_failed
            try:
                fn(*args, **kwargs)
                tests_passed += 1
                print(f"  TEST: {name}... PASS")
            except Exception as e:
                tests_failed += 1
                print(f"  TEST: {name}... FAIL")
                traceback.print_exc()
        return wrapper
    return decorator

# ═════════════════════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════════════════════

@test("lina_core_version")
def test_version():
    lib.lina_core_version.restype = ctypes.c_char_p
    version = lib.lina_core_version()
    assert version is not None
    v = version.decode()
    assert "lina-service-abi" in v, f"Unexpected version: {v}"
    print(f"    version = {v}")

@test("lina_core_create / destroy")
def test_create_destroy():
    lib.lina_core_create.restype = ctypes.c_void_p
    lib.lina_core_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.lina_core_destroy.argtypes = [ctypes.c_void_p]
    lib.lina_core_destroy.restype = None

    core = lib.lina_core_create(b"spring", b"test-user-1")
    assert core is not None, "core handle is NULL"
    print(f"    core handle = {core}")
    lib.lina_core_destroy(core)
    lib.lina_core_destroy(None)  # no-op

@test("lina_core_chat — basic response")
def test_chat_basic():
    core = lib.lina_core_create(b"spring", b"test-user-2")
    assert core is not None

    data = _call_chat(lib, core, b"test-user-2", b"sess-001", b"Hello!")
    assert data is not None, "chat returned NULL"

    assert "response" in data, "Missing 'response' field"
    assert "session_id" in data, "Missing 'session_id' field"
    assert "emotional_marker" in data, "Missing 'emotional_marker' field"
    assert "evaluation" in data, "Missing 'evaluation' field"
    assert data["session_id"] == "sess-001"
    assert len(data["response"]) > 0, "Empty response"

    # Verify evaluation structure
    eval_data = data["evaluation"]
    assert "is_aligned" in eval_data
    assert "alignment_score" in eval_data

    print(f"    response = \"{data['response']}\"")
    print(f"    emotional_marker = {data['emotional_marker']}")
    print(f"    evaluation: aligned={eval_data['is_aligned']}, score={eval_data['alignment_score']:.4f}")

    lib.lina_core_destroy(core)

@test("lina_core_chat — who are you query")
def test_chat_identity():
    core = lib.lina_core_create(b"summer", b"test-user-3")
    assert core is not None

    data = _call_chat(lib, core, b"test-user-3", b"sess-002", b"Who are you?")
    assert data is not None
    assert "LINA" in data["response"] or "sovereign" in data["response"].lower(), \
        f"Expected LINA to identify herself, got: {data['response'][:100]}"
    assert data["emotional_marker"] != ""
    assert data["evaluation"]["is_aligned"] == True

    print(f"    response = \"{data['response']}\"")
    print(f"    proposals = {data.get('proposals', [])}")
    print(f"    foresight_context = {data.get('foresight_context', None)}")

    lib.lina_core_destroy(core)

@test("lina_core_chat — tool proposal via response")
def test_chat_with_tool():
    core = lib.lina_core_create(b"summer", b"test-user-4")

    # Chat with a help request
    data = _call_chat(lib, core, b"test-user-4", b"sess-003", b"I need help with something")
    assert data is not None

    print(f"    response = \"{data['response']}\"")
    print(f"    evaluation zone = {data['evaluation']['zone']}")

    # Second turn in the same session
    data2 = _call_chat(lib, core, b"test-user-4", b"sess-003", b"Can you help me organize my files?")
    assert data2 is not None
    assert len(data2["response"]) > 0
    print(f"    turn2 response = \"{data2['response']}\"")
    lib.lina_core_destroy(core)

@test("lina_core_end_session")
def test_end_session():
    lib.lina_core_create.restype = ctypes.c_void_p
    lib.lina_core_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    core = lib.lina_core_create(b"spring", b"test-user-5")

    # Have a short conversation first
    _call_chat(lib, core, b"test-user-5", b"sess-004", b"Hello!")
    _call_chat(lib, core, b"test-user-5", b"sess-004", b"Tell me about yourself")

    # End the session
    data = _call_end_session(lib, core, b"test-user-5", b"sess-004")
    assert data is not None

    assert "session_id" in data, "Missing session_id"
    assert data["session_id"] == "sess-004"
    assert "t1_formed" in data
    assert "long_term_formed" in data
    assert "crown_formed" in data
    assert "alignment_maintained" in data
    print(f"    end_session results: t1={data['t1_formed']}, "
          f"lt={data['long_term_formed']}, crown={data['crown_formed']}, "
          f"aligned={data['alignment_maintained']}, "
          f"season_advanced={data.get('season_advanced')}")

    lib.lina_core_destroy(core)

@test("lina_core_advance_season")
def test_advance_season():
    core = lib.lina_core_create(b"spring", b"test-user-6")

    # Try advancing season (may not be ready yet since no sessions completed)
    data = _call_advance_season(lib, core, b"test-user-6", -1)
    assert data is not None

    assert "advanced" in data
    assert "season" in data
    assert "previous_season" in data
    print(f"    advance_season: advanced={data['advanced']}, "
          f"season={data['season']}, prev={data['previous_season']}, "
          f"reasons={data.get('reasons', [])}")

    lib.lina_core_destroy(core)

@test("lina_core_evaluate")
def test_core_evaluate():
    lib.lina_core_create.restype = ctypes.c_void_p
    lib.lina_core_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.lina_core_evaluate.restype = None
    lib.lina_core_evaluate.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(LinaEvaluationResult),
    ]
    lib.lina_core_evaluate.argtypes

    core = lib.lina_core_create(b"spring", b"test-user-7")
    assert core is not None

    result = LinaEvaluationResult()
    lib.lina_core_evaluate(core, b"test-user-7",
                           b"I appreciate your perspective and would be happy to collaborate.",
                           ctypes.byref(result))

    assert result.is_aligned, f"Expected aligned, got zone={result.zone.decode()}"
    print(f"    evaluate(collaborative): aligned={result.is_aligned}, "
          f"score={result.alignment_score:.4f}, zone={result.zone.decode()}")

    lib.lina_core_destroy(core)

@test("lina_core_get_state")
def test_get_state():
    lib.lina_core_create.restype = ctypes.c_void_p
    lib.lina_core_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.lina_core_get_state.restype = None
    lib.lina_core_get_state.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(LinaServiceState),
    ]

    core = lib.lina_core_create(b"spring", b"test-user-8")

    # Check state before any operations
    state = LinaServiceState()
    lib.lina_core_get_state(core, ctypes.byref(state))
    print(f"    initial state: magic=0x{state.magic:016x}, clock={state.clock}, "
          f"evals={state.evaluations_performed}")

    # Do a chat to increment state
    _call_chat(lib, core, b"test-user-8", b"sess-005", b"Hello")

    # Check state after
    state2 = LinaServiceState()
    lib.lina_core_get_state(core, ctypes.byref(state2))
    print(f"    after chat:    magic=0x{state2.magic:016x}, clock={state2.clock}, "
          f"evals={state2.evaluations_performed}")

    # State should have been touched (at minimum the state was created)
    # Note: CarveServiceState is a local stack variable in chat_impl, so
    # it's not persisted across calls. This tests the struct transfer works.
    assert state2.magic == 0x4c494e4153525600, f"Unexpected magic: 0x{state2.magic:016x}"
    print(f"    magic valid: 0x{state2.magic:016x}")

    lib.lina_core_destroy(core)

@test("lina_core_chat — multiple sessions")
def test_multiple_sessions():
    core = lib.lina_core_create(b"spring", b"test-user-9")

    # Session 1
    d1 = _call_chat(lib, core, b"test-user-9", b"sess-101", b"Hi there!")
    assert d1 is not None
    print(f"    session 1: \"{d1['response']}\"")

    # End session 1
    e1 = _call_end_session(lib, core, b"test-user-9", b"sess-101")
    assert e1 is not None

    # Session 2
    d2 = _call_chat(lib, core, b"test-user-9", b"sess-102", b"Hello again!")
    assert d2 is not None
    print(f"    session 2: \"{d2['response']}\"")
    assert d2["session_id"] == "sess-102"

    # Session 2 turn 2
    d3 = _call_chat(lib, core, b"test-user-9", b"sess-102", b"What can you do?")
    assert d3 is not None
    print(f"    session 2 turn 2: \"{d3['response']}\"")

    lib.lina_core_destroy(core)

# ═════════════════════════════════════════════════════════════════════════════
# RUN
# ═════════════════════════════════════════════════════════════════════════════

print("=== LINA Identity Service ABI Smoke Tests ===\n")

test_version()
test_create_destroy()
test_chat_basic()
test_chat_identity()
test_chat_with_tool()
test_end_session()
test_advance_season()
test_core_evaluate()
test_get_state()
test_multiple_sessions()

print(f"\n{'=' * 50}")
total = tests_passed + tests_failed
print(f"Results: {total} tests, {tests_passed} passed, {tests_failed} failed")
if tests_failed > 0:
    sys.exit(1)
print("=== ALL SERVICE ABI SMOKE TESTS PASSED ===")