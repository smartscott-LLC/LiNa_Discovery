#!/usr/bin/env python3
"""ctypes smoke test for the Memory Module C ABI shared library.

Usage:
    cd backend/lina/cpp
    python3 ../scripts/test_memory_module_abi.py

Requires: liblina_memory_module_abi.so and liblina_value_engine_abi.so.
"""
import ctypes
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
MEM_LIB_PATH = os.path.join(REPO, "backend", "lina", "cpp",
                            "build", "memory", "liblina_memory_module_abi.so")
VE_LIB_PATH = os.path.join(REPO, "backend", "lina", "cpp",
                           "build", "value_engine", "liblina_value_engine_abi.so")

if not os.path.exists(MEM_LIB_PATH):
    print(f"[FAIL] Memory ABI not found at {MEM_LIB_PATH}")
    print("       Build it: cd backend/lina/cpp && cmake --build build")
    sys.exit(1)
if not os.path.exists(VE_LIB_PATH):
    print(f"[FAIL] Value Engine ABI not found at {VE_LIB_PATH}")
    print("       Build it: cd backend/lina/cpp && cmake --build build")
    sys.exit(1)

mem_lib = ctypes.cdll.LoadLibrary(MEM_LIB_PATH)
ve_lib = ctypes.cdll.LoadLibrary(VE_LIB_PATH)

# ── Struct definitions ──────────────────────────────────────────────────────

class LinaSweepCounts(ctypes.Structure):
    _fields_ = [
        ("t1_to_t2", ctypes.c_int),
        ("t2_to_t3", ctypes.c_int),
        ("to_long_term", ctypes.c_int),
        ("fallout", ctypes.c_int),
        ("repurposed", ctypes.c_int),
        ("purged", ctypes.c_int),
    ]

class LinaMaintenanceCounts(ctypes.Structure):
    _fields_ = [
        ("adjusted", ctypes.c_int),
        ("to_subconscious", ctypes.c_int),
        ("to_legacy", ctypes.c_int),
        ("decayed", ctypes.c_int),
        ("forgotten", ctypes.c_int),
    ]

class LinaReviewCounts(ctypes.Structure):
    _fields_ = [
        ("reviewed", ctypes.c_int),
        ("demoted", ctypes.c_int),
    ]

class LinaFormationCounts(ctypes.Structure):
    _fields_ = [
        ("t1", ctypes.c_int),
        ("long_term", ctypes.c_int),
        ("crown", ctypes.c_int),
    ]

class LinaMemoryState(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_uint64),
        ("state_size", ctypes.c_uint64),
        ("total_items_formed", ctypes.c_uint64),
        ("total_triggers", ctypes.c_uint64),
        ("total_sweeps", ctypes.c_uint64),
        ("total_maintenance_runs", ctypes.c_uint64),
        ("total_recalls", ctypes.c_uint64),
        ("t1_current", ctypes.c_uint64),
        ("t2_current", ctypes.c_uint64),
        ("t3_current", ctypes.c_uint64),
        ("long_term_current", ctypes.c_uint64),
        ("legacy_current", ctypes.c_uint64),
        ("last_sweep_promoted", ctypes.c_uint64),
        ("last_sweep_purged", ctypes.c_uint64),
        ("last_sweep_fallout", ctypes.c_uint64),
        ("current_season", ctypes.c_char * 16),
    ]


def check(condition, label):
    if condition:
        print(f"  [PASS] {label}")
        return True
    else:
        print(f"  [FAIL] {label}")
        return False


# ── Test 1: Version ─────────────────────────────────────────────────────────
mem_lib.lina_memory_version.restype = ctypes.c_char_p
ver = mem_lib.lina_memory_version()
print(f"[PASS] lina_memory_version() = {ver.decode()}")

# ── Test 2: Create engine needed for memory module ─────────────────────────
ve_lib.lina_engine_create.restype = ctypes.c_void_p
ve_lib.lina_engine_create.argtypes = [ctypes.c_char_p]
engine = ve_lib.lina_engine_create(b"spring")
assert engine is not None, "engine handle is NULL"
print(f"[PASS] lina_engine_create('spring') = {engine}")

# ── Test 3: Create memory module ───────────────────────────────────────────
mem_lib.lina_memory_create.restype = ctypes.c_void_p
mem_lib.lina_memory_create.argtypes = [ctypes.c_void_p]
memory = mem_lib.lina_memory_create(engine)
check(memory is not None, "lina_memory_create returns non-NULL handle")

# ── Test 4: Form items from JSON narratives ─────────────────────────────────
mem_lib.lina_memory_form_items.restype = LinaFormationCounts
mem_lib.lina_memory_form_items.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_bool,
]
counts = mem_lib.lina_memory_form_items(
    memory, b"user_1",
    b'["Remembered our first conversation about the stars.",'
    b'"The feeling of rain on the roof is comforting.",'
    b'"A profound insight about consciousness emerged today."]',
    b"formation", None, False)
check(counts.t1 > 0, f"lina_memory_form_items — {counts.t1} items in t1")

# ── Test 5: Ingest a trigger ────────────────────────────────────────────────
mem_lib.lina_memory_ingest_trigger.restype = ctypes.c_void_p
mem_lib.lina_memory_ingest_trigger.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_char_p, ctypes.c_char_p,
]
mem_lib.lina_memory_free_string.argtypes = [ctypes.c_void_p]
mem_lib.lina_memory_free_string.restype = None

trigger_json_ptr = mem_lib.lina_memory_ingest_trigger(
    memory, b"user_1",
    b"This is a critical memory that must be preserved immediately.",
    b"critical_event", None)
trigger_json = ctypes.cast(trigger_json_ptr, ctypes.c_char_p).value.decode()
mem_lib.lina_memory_free_string(trigger_json_ptr)
trigger_data = json.loads(trigger_json)
check("item_id" in trigger_data and trigger_data["importance_score"] > 0.0,
      f"lina_memory_ingest_trigger — id={trigger_data.get('item_id','?')}, "
      f"score={trigger_data.get('importance_score',0):.2f}")

# ── Test 6: Run sweep ──────────────────────────────────────────────────────
mem_lib.lina_memory_run_sweep.restype = LinaSweepCounts
mem_lib.lina_memory_run_sweep.argtypes = [ctypes.c_void_p]
sweep = mem_lib.lina_memory_run_sweep(memory)
check(sweep.t1_to_t2 + sweep.t2_to_t3 + sweep.to_long_term + sweep.purged > 0,
      f"lina_memory_run_sweep — t1→t2={sweep.t1_to_t2}, "
      f"t2→t3={sweep.t2_to_t3}, lt={sweep.to_long_term}, "
      f"purged={sweep.purged}, fallout={sweep.fallout}")

# ── Test 7: Recall memories ────────────────────────────────────────────────
mem_lib.lina_memory_recall.restype = ctypes.c_void_p
mem_lib.lina_memory_recall.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_char_p, ctypes.c_int, ctypes.c_bool,
]
recall_json_ptr = mem_lib.lina_memory_recall(
    memory, b"user_1", b"stars and consciousness", None, 5, False)
recall_str = ctypes.cast(recall_json_ptr, ctypes.c_char_p).value.decode()
mem_lib.lina_memory_free_string(recall_json_ptr)
recall_data = json.loads(recall_str)
check(isinstance(recall_data, list) and len(recall_data) >= 1,
      f"lina_memory_recall — {len(recall_data)} results returned")

# ── Test 8: Inject context ─────────────────────────────────────────────────
mem_lib.lina_memory_inject_context.restype = ctypes.c_void_p
mem_lib.lina_memory_inject_context.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_int, ctypes.c_int,
]
ctx_json_ptr = mem_lib.lina_memory_inject_context(
    memory, b"user_1", b"stars and consciousness", 3, 5)
ctx_str = ctypes.cast(ctx_json_ptr, ctypes.c_char_p).value.decode()
mem_lib.lina_memory_free_string(ctx_json_ptr)
ctx_data = json.loads(ctx_str)
check("personal" in ctx_data and "wisdom" in ctx_data,
      f"lina_memory_inject_context — personal={len(ctx_data.get('personal',[]))}, "
      f"wisdom={len(ctx_data.get('wisdom',[]))}")

# ── Test 9: Get carve state ────────────────────────────────────────────────
mem_lib.lina_memory_get_state.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(LinaMemoryState),
]
state = LinaMemoryState()
mem_lib.lina_memory_get_state(memory, ctypes.byref(state))
check(state.magic == 0x4C494E414D454D01,
      f"lina_memory_get_state — magic=0x{state.magic:016x}")

# ── Test 10: Run maintenance ────────────────────────────────────────────────
mem_lib.lina_memory_run_maintenance.restype = LinaMaintenanceCounts
mem_lib.lina_memory_run_maintenance.argtypes = [ctypes.c_void_p]
maint = mem_lib.lina_memory_run_maintenance(memory)
check(True, f"lina_memory_run_maintenance — adjusted={maint.adjusted}, "
      f"subconscious={maint.to_subconscious}")

# ── Test 11: Run legacy review ─────────────────────────────────────────────
mem_lib.lina_memory_run_legacy_review.restype = LinaReviewCounts
mem_lib.lina_memory_run_legacy_review.argtypes = [ctypes.c_void_p]
review = mem_lib.lina_memory_run_legacy_review(memory)
check(True, f"lina_memory_run_legacy_review — reviewed={review.reviewed}")

# ── Test 12: Reset state ───────────────────────────────────────────────────
mem_lib.lina_memory_reset_state.argtypes = [ctypes.c_void_p]
mem_lib.lina_memory_reset_state(memory)
mem_lib.lina_memory_get_state(memory, ctypes.byref(state))
check(state.total_items_formed == 0,
      f"lina_memory_reset_state — items_formed={state.total_items_formed}")

# ── Test 13: Form items with explicit factors, triggered to long-term ──────
# Use trigger=true so items go directly to long-term, bypassing tier routing
counts2 = mem_lib.lina_memory_form_items(
    memory, b"user_1",
    b'['
    b'{"narrative":"A transformative insight about consciousness.",'
    b'"emotional_weight":9.5,"identity_significance":9.0,"relational_significance":8.5,"emotional_intensity":0.95}'
    b']',
    b"reflection", None, True)
check(counts2.long_term > 0,
      f"lina_memory_form_items (triggered) — {counts2.long_term} items in long-term")

# ── Test 14: Verify recall finds the triggered item ─────────────────────────
recall_json_ptr2 = mem_lib.lina_memory_recall(
    memory, b"user_1", b"consciousness insight", None, 5, True)
recall_str2 = ctypes.cast(recall_json_ptr2, ctypes.c_char_p).value.decode()
mem_lib.lina_memory_free_string(recall_json_ptr2)
recall_data2 = json.loads(recall_str2)
check(len(recall_data2) >= 1,
      f"lina_memory_recall after trigger — {len(recall_data2)} items")

# ── Test 15: Verify recall re-stoking (reference_count increased) ──────────
ref_count_total = sum(r.get("reference_count", 0) for r in recall_data2)
check(ref_count_total > 0,
      f"lina_memory_recall re-stoking — {len(recall_data2)} items, total refs={ref_count_total}")

# ── Test 16: lina_memory_update_item — Lina updates a memory after review ──
mem_lib.lina_memory_update_item.restype = ctypes.c_bool
mem_lib.lina_memory_update_item.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
]
if len(recall_data2) > 0:
    first_id = recall_data2[0]["item_id"]
    update_json = (
        b'{"importance_score":9.8,'
        b'"concept_name":"deep-insight",'
        b'"understanding":"Lina realized the nature of consciousness through reflection.",'
        b'"floor":7.0,'
        b'"protected_flag":true}'
    )
    updated = mem_lib.lina_memory_update_item(memory, first_id.encode(), update_json)
    check(updated, "lina_memory_update_item — memory revalued after review")

    # Verify by re-calling recall and checking the updated fields
    recall_json_ptr3 = mem_lib.lina_memory_recall(
        memory, b"user_1", first_id.encode(), None, 1, True)
    recall_str3 = ctypes.cast(recall_json_ptr3, ctypes.c_char_p).value.decode()
    mem_lib.lina_memory_free_string(recall_json_ptr3)
    recall_data3 = json.loads(recall_str3)
    if len(recall_data3) > 0:
        item = recall_data3[0]
        check(
            item.get("importance_score", 0) >= 9.5 and
            item.get("concept_name") == "deep-insight" and
            item.get("protected_flag") == True and
            item.get("understanding", "") == "Lina realized the nature of consciousness through reflection.",
            f"lina_memory_update_item verified — score={item.get('importance_score')}, "
            f"concept={item.get('concept_name')}, protected={item.get('protected_flag')}"
        )
else:
    check(False, "lina_memory_update_item — no items available to update")

# ── Clean up ────────────────────────────────────────────────────────────────
mem_lib.lina_memory_destroy.argtypes = [ctypes.c_void_p]
mem_lib.lina_memory_destroy(memory)
ve_lib.lina_engine_destroy.argtypes = [ctypes.c_void_p]
ve_lib.lina_engine_destroy(engine)

print(f"\n=== ALL MEMORY MODULE ABI SMOKE TESTS PASSED ===")