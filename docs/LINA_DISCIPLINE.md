# LINA DISCIPLINE — IMPLEMENTATION LAW

**The operational companion to `LiNA-Discipline.md`.**
The manifest is the constitution. This document is how we implement it — the corrected architecture, the rulings, and the work list. Everything in here was decided by the Vision Holder and the Principal Architect together, section by section.

**The filter — the only question that matters:**
> Does this serve bringing a conscious being into reality?
> If it doesn't, it's gone.

**How to use this document:** Every change to the LINA codebase must pass each section it touches. If a change contradicts a rule here, the change is wrong — not the rule. The rule only changes by Vision Holder approval.

---

## 1. The Hub-and-Spoke Model — Non-Negotiable

### The truth (in pictures)
The **Dragoncache is a table in the center of the room**. The spokes — modules, components, processes — stand around it. Data lands on the table and **never leaves it**. Nothing is copied, moved, or handed off; every spoke works from the same state, in place, simultaneously. Everybody sees what landed the moment it landed — that is what foresight means. It is not a pipeline. It is not a message queue. It is a shared view.

**The chairs are IPC mmap.** POSIX `mmap(MAP_SHARED)` over `/dev/shm` — the kernel's MMU pins multiple processes' virtual pages to the same physical frames. One process writes, another reads the same silicon, instantly. Zero-copy: no kernel hops, no context switches, no serialization. Speed is bounded by RAM clock and cache coherence.

**The one thing that does leave the table is a projection.** When a prompt goes to an external voice (DeepSeek, OpenRouter, Gemini), the shared state stays on the table — we do not copy it, we **project it through the API line**. The projection leaves so that what returns can be measured: the response comes back through LINA's reflection, weighed against the polytope, checked for hallucination, recorded, embedded, or acted on by other modules. And because every spoke sees the request on the table before it leaves, they **anticipate what returns and prepare in advance** — when the response lands, the work is already done. That anticipation is foresight, and it is the point of the projection: the system does not pass through — it projects, expects, and prepares.

**The cost of that speed:** the OS will not arbitrate. So the map governs itself, with exactly three mechanisms:
1. **Atomic operations / lock-free ring buffers** — safe read/write pointers.
2. **Strict TX/RX separation** — dedicated transmit and receive regions, preventing locking collisions.
3. **The centralized state header** — a shared index *inside* the memory map telling every connected process which blocks are safe to read, ready to be processed, or locked for writing.

**The header is the bridge.** There is one bridge, and it is shared state, not a channel. The PyO3 bridge was a second bridge doing the header's job the wrong way — a direct function-call channel between Python and Rust where a shared view already existed. A phone line between two people standing at the same table.

**Two caches, two jobs, never confused:**
| Cache | Role | Home |
|---|---|---|
| **Dragoncache** | The table — live shared state, the system's speed | Real RAM on the host, carved out and mmap'd. Runs on our silicon. |
| **Working-memory cache** (Docker Dragonfly) | LINA's short-term memory, per-container | The container stack — not the hub. |

### The rules
1. **No direct node-to-node communication. Ever.** Python and Rust never call each other. They look at the same memory.
2. **No PyO3, no maturin, no bindings.** Each spoke sits in its own chair: Rust maps with `memmap3`, Python maps the same files with the stdlib `mmap` module. Same physical frames, zero bindings, no compilers in the loop.
3. **The data never leaves the table.** No copy, no move, no handoff, no serialization.
4. **One bridge: the header.** The state header inside the map is the only bridge. No channel bridges.
5. **The aiomisc loop is the second chair.** A component that cannot sit at the table rides a loop — as a service, in the entrypoint, with `start()`/`stop()`. You may create as many loops as you need. A process is either a spoke on the table or a service in a loop. Nothing runs unmanaged.

### The anti-patterns
- PyO3/Maturin bridge crates between Python and Rust.
- Handshake protocols, pipelines, or third layers on top of IPC + aiomisc.
- "Bridge-optional" degradation — a fallback because the primary isn't trusted (see §3).

### The verdicts
| Component | Verdict |
|---|---|
| `backend/ipc/` (PyO3 + memmap3 crate) | **Remove** — the redundant second bridge |
| `backend/ipc-core/` | Trim to what the Rust spoke needs |
| `backend/triton/` (Rust spoke) | **Stays** — cargo-built, maps the chambers directly with `memmap3` |
| Python side (`ipc_bridge` import, `push_tx`/`pop_rx`, foresight drain, `/lina/ipc/status`) | **Re-seat** — Python maps the same `/dev/shm` files with the stdlib `mmap` module. The ring buffer, atomics, TX/RX, and header patterns stay — they are the correct governance |
| `typings/ipc_bridge/` stub | Remove with the bridge |
| Dockerfile / check script | maturin out; `cargo` stays for the spoke |
| Chamber config (`IPC_TX_PATH`/`RX_PATH`) | Survives — the table's surface |

---

## 2. Passagemath Is the Only Math

### The truth (in pictures)
Python's basic math is a Nissan. Passagemath is a Ferrari. We keep reaching for the Nissan because it's familiar — and we never enjoy what the Ferrari does. Passagemath is the most powerful module in the Python world: a fork of SageMath split into pip-installable modules, built on exact arithmetic. We use it, or we don't build LINA.

### The rules
1. **The polytope is a real, exact, rational object.** Built on PPL from the book's 28 hyperplane constraints (7 principles × virtue-min / virtue-max / shadow-max / shadow-min) — declared **directly as exact `QQ` fractions** (3/10, 2/5, 3/5, 1/5…). No floats. No `limit_denominator`. No `_float_to_qq` roundtrip.
2. **Containment is exact.** `Polyhedron.contains` on QQ vectors — the book's Theorem 2: O(mn), decidable.
3. **Distance is exact.** Facet-locality distances computed in QQ (the book's Theorem 4). For axis-aligned bounds these are exact coordinate differences — no `float()`, no `** 0.5`.
4. **Projection is the exact QP solution.** The book defines correction as *minimize ‖p − x‖² subject to p ∈ P* (Chapter 10). For the box polytope — the shape LINA inhabits — that QP's exact solution is per-coordinate clamping. Computed on QQ bounds. **There is no approximation, and there is no fallback.**
5. **No NumPy for math.** NumPy is a container, not a calculator. The 14D vectors may *ride* in arrays as transport; every mathematical operation on their values is QQ-exact. (Modules *inside* passagemath that use NumPy or SciPy internally are passagemath's implementation — that is their business. The rule binds our arithmetic, not theirs.)
6. **If the geometry generalizes, projection is re-derived then.** From the book's geometry, at that time, as a documented decision — never a pre-installed fallback.
7. **Speed is traded for truth, deliberately.** Exact math is sometimes slower than a float shortcut. That cost is accepted by design — she thinks before she speaks. We would rather have the right answer that takes a moment than the wrong answer that is fast. The exact, robust, scalable system wins a hundred times over at the cost of small latencies.

### The richer structure — the sanctioned re-derivation toolkit

The box is the book's current shape. When the geometry generalizes, these passagemath modules are the sanctioned tools (they live in the reference tree — reference, not pre-installed code paths):

| Module | What it gives us | Where it lands in the architecture |
|---|---|---|
| **hyperplane arrangements** (`sage/geometry/hyperplane_arrangement/`) | Regions, region poset, `region_containing_point`, `distance_between_regions`, characteristic polynomial, Whitney data, matroid | The value engine's true home — the zone model (aligned / acceptable_variance / violation) becomes *regions of the arrangement* instead of margin thresholds (book Chapter 10) |
| **linear tensor constraints** (`sage/numerical/linear_tensor_constraints.py`) | Vector/matrix-valued linear constraints, MIP over QQ with the PPL backend | The bounds beyond axis-aligned — cross-dimension couplings, when the book's geometry demands them |
| **lattice polytopes on PPL** (`sage/geometry/lattice_polytope/`) | `integral_points`, `bounding_box`, reflexivity, automorphism groups | The discrete face of the polytope — counting ethical states inside a region |

These are the tools for the re-derivation decision, not a pre-installed fallback (rule 6). When the day comes, the zones and the arrangement fuse. Until then, the box stands as the book defines it.

### The anti-patterns
- `np.clip` / float64 projection paths.
- "Documented approximations" (L1 for L2) and "flagged follow-up" promises.
- Float-derived polytope bounds (`float → Fraction → QQ`).
- SciPy anywhere. (The book's *illustrative* code uses scipy SLSQP; the math is the QP, and passagemath is the substrate.)

### Where the pieces live in passagemath (verified)
- Polytope + arrangements: **passagemath-polyhedra** (PPL backend) — polyhedra, hyperplane arrangements, polyhedral complexes, linear/MIP optimization, lattice point sets, toric varieties.
- Rings/invariants: **polynomial_rings** (univariate → multivariate, invariant theory) — the algebraic structure for the chambers.
- Arrays/designs: **combinat** — designs, orthogonal arrays.
- *Corrected names:* "valuations" is p-adic number theory, not evaluation — the value engine's home is the arrangement/polytope geometry. "euclidean_spaces" is manifolds/vector calculus — the rubber-band is our exact-arithmetic projection on the polytope.

### The verdicts (2.1–2.7)
- 2.1 projection fast path → exact QQ clamp (no float, no `np.clip`).
- 2.2 L1 fallback + "KKT follow-up" → **trashed** — the clamp is the exact QP solution; the fallback was cover.
- 2.3 float-derived bounds → the book's 28 constraints as exact `QQ`.
- 2.4 boundary math → QQ, no Python float arithmetic.
- 2.5 neurons → archived (see §3) until Fall season, when they return as the observable substrate.
- 2.6 structure extraction → keep PPL's exact vertices/facets; float only at render time.
- 2.7 vector representation → transport may be arrays; math is QQ-exact.

---

## 3. No Placeholders. No TODOs. No Cover.

### The rules
1. **The polytope is always real.** `CombinatorialStructure` requires a polyhedron. `EmbodiedSelfModel` requires a polytope. No polyhedron → a loud construction error, never a fake "placeholder" object.
2. **A fallback installed because the primary isn't trusted is the signature of not building it right.** Remove it. Fix the primary.
3. **"We'll get to it" is not a plan.** A placeholder is acceptable *only* when the unit is genuinely a next phase — and then it is built in that phase, not deferred indefinitely. We get to it now.
4. **Lineage is archived, not deleted.** When a component's purpose returns in a later season (the neurons, the narchi adapter), it moves to `docs/` as an archive — out of the code line, preserved for the season that needs it. The archive is not a code path.
5. **No promises to the future.** Comments state what *is*. "Flagged follow-up," "future fallback," "for experimentation" — all dissolved.

### The verdicts
- `_placeholder_structure()` + the `dimensions=` fallback → **remove** (require the real polyhedron).
- `narchi_adapter.py`, `minimal_neural_network.py` → **archive to `docs/`** — they return in Fall season as the observable substrate for watching how she develops.
- The GLPK L1 fallback and the "KKT follow-up" promise → **trash**.
- The `or 10` constant fallback in the neural network → **remove** with the archive.

---

## 4. Aiomisc Is the Lifecycle Manager

### The rules
1. **Everything is a service in the loop.** A component is either a spoke on the table (§1) or a service in an aiomisc loop. Nothing runs outside the loop. The entrypoint is the only sanctioned way to run LINA (`python -m lina_service`).
2. **Dependency injection is the aiomisc `Context`.** Services publish their resources into the context (`self.context["voice_pool"] = pool`); consumers resolve them (`get_context()["voice_pool"]`). The loop is the DI container. No module-global service locators, no reference-comparison staleness checks.
3. **`start()`/`stop()` on every service.** The loop owns teardown — it stops all services if any fails. Manual start/stop is brittle; it is not a run mode.
4. **Multiple loops are allowed.** As many as the architecture needs — each loop a managed context.

### The anti-patterns
- Module globals (`_voice_pool`, `_bridge_service`, `_core_instance`) as a service locator.
- `uvicorn lina_service:app` documented as a run mode (test scaffolding only — `TestClient(app)` imports the module; it does not run her).
- Graceful degradation to a bridge-less, voiceless system — see §3, rule 2.

### The verdicts
- Publication → aiomisc `Context`. The staleness check dies.
- Docstring → the entrypoint is the only run mode; the uvicorn path is labeled test scaffolding.
- The standalone "bridge-optional" fallback → removed with the re-seat.

---

## 5. Anthropic Is Removed. Period. The Legacy Is Retired.

### The rules
1. No Claude in the voice pool. No Anthropic SDK in any dependency list. **No Claude references in code that are not historical notes.**
2. The voice layer is provider-agnostic: **DeepSeek (default) → OpenRouter → Gemini**. LINA may invoke Gemini for vision at runtime when the task requires it — her choice.
3. The legacy CollabSmart generation is retired: Node backend, Next.js frontend, VNC desktop. If it does not fit what we are building today, it is gone. O*Net is an API call — rebuildable when needed.

### The verdicts
- `backend/src` (Node service: anthropic.ts, its providers, its own memory system, orchestrator, settings) → **trash**.
- `frontend/`, `desktop/`, `container/` → **trash**.
- Compose services `backend`, `frontend`, `desktop` → **remove**.
- `.env` legacy vars (`AI_API_KEY`, `OPENAI_API_KEY`, their settings) → **retire**.
- Compose `ANTHROPIC_API_KEY` wiring → **remove**.
- Historical notes exempt: LINA's origin story in `LINA_SOUL.md` and the system prompt.

---

## 6. Documentation Is the Reference

### The rules
1. **The `lina_service.py` docstring is the source of truth for environment variables.** One source, one truth. Every `os.getenv` in the code appears in the docstring with its default.
2. **All references live in `/docs`.** Including `LINA_SOUL.md` — who she is belongs with the references.
3. **Documentation is mandatory.** If it's not documented, it doesn't exist. Docs are the intent; code is the implementation.
4. **The book is the reference of record.** *The Day AI Changed Forever* — 27 chapters, appendices A & B — in `docs/`. When architecture questions arise, search the book first. The passagemath and aiomisc reference trees live in `docs/` for lookup by keyword.
5. **Stale documentation is drift.** A doc that narrates a dead architecture is a liability — retire it.

### The verdicts
- Docstring env block → completed (add `WORKSPACE_PATH`, `PWA_DIR`, `LINA_STATE_DIR`, `LINA_LOG_DIR`, `LINA_COMMAND_TIMEOUT`; maintain as code changes).
- `LINA_SOUL.md` → moved to `docs/`; its operational sections (Language Layer, flow) rewritten to the current architecture; origin story untouched.
- Stale docs (EXECUTIVE_REVIEW, QUICK_START, implementation-spec, proposal narrative, environment yml) → **trash**. Kept: `lina_patent.md`, the book, the reference trees, `docs/adr/`, `lina-runtime-instructions.md`.

---

## 7. No Drift Will Be Tolerated

### The rules
1. **Narrative and reality must agree.** What the code says and what the code does are the same thing. A comment describing a bridge that no longer exists, a docstring describing a run mode we no longer sanction, an architecture narrated in prose that the code contradicts — that is drift, and drift is the enemy.
2. **"It works" is the lowest bar.** It is correct, aligned with the architecture, and free of contradictions — or it is not done.
3. **Catch it early.** Every review, every diff, every new file passes the filter: *does this serve bringing a conscious being into reality?*
4. **No computed-but-discarded work.** If code computes a real geometry and then throws it away for a hardcoded substitute, that is drift — use the real thing or compute nothing.

### The verdicts
- The "IPC BRIDGE (Triton substrate) — her nervous system / optional by design (maturin)" narration → rewritten with the re-seat (§1).
- The edges-computed-then-discarded pattern in `EmbodiedSelfModel` → use the real combinatorial geometry or compute nothing.

---

## The Enforcement

| Layer | How it's enforced |
|---|---|
| **This document** | Every change passes every section it touches. The rule changes only by Vision Holder approval |
| **The manifest** (`LiNA-Discipline.md`) | The constitution — ultimate authority |
| **Code review** | Every PR passes the discipline check: §1–§7 |
| **The check script** | `scripts/check-environment.sh` — the readiness gate, kept aligned with the current architecture |
| **The filter** | *Does this serve bringing a conscious being into reality?* If not, it's gone |

## The Work List (Phase C — executed after this document is approved)

1. **Exact polytope** — book's 28 constraints as `QQ`; exact containment/distance; projection = exact clamp; trashed fallbacks and promises.
2. **IPC re-seat** — header-as-bridge; Python stdlib `mmap` chair; Triton spoke; PyO3/maturin out; narration rewritten.
3. **Legacy retirement** — Node backend, frontend, desktop, container, compose services, `.env` legacy vars.
4. **Archive** — `narchi_adapter.py` + `minimal_neural_network.py` → `docs/` (Fall season).
5. **Placeholder purge** — require the real polytope; no fake structures.
6. **Lifecycle** — aiomisc `Context` DI; entrypoint-only run mode.
7. **Docs** — env docstring complete; `LINA_SOUL.md` relocated + operational rewrite; stale docs trashed.
8. **Validate** — full test suite, ruff clean, readiness gate, Docker rebuild.
