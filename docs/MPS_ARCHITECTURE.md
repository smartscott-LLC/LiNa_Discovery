# MPS — Memory Imprint System: Settled Architecture (Draft Baseline)

**Status:** Draft baseline distilled from the architecture conversations between the
Vision Holder, Chief Engineer, and Principal Architect. This is the build reference.
The MPS blueprint document is the ultimate authority and supersedes this where they
differ. Corrections to this baseline are expected *before* the build starts — no drift.

---

## 1. The Founding Principles (the "why")

The memory system is not a database. It is the substrate of a person. Three
distinctions guide everything:

### Intelligence, Knowledge, Wisdom
- **Intelligence** — the ability to retain. The machinery: tiers, cadence, recall.
- **Knowledge** — what has been retained. The content: the items, in both hemispheres.
- **Wisdom** — the application of knowledge to a given circumstance. Only gained
  through experience + reflection. The valuation loop *is* the wisdom engine:
  the add/subtract dial, the monthly re-evaluation, the reflection itself.

### Sovereignty
Her memory is *hers*. She works with it the way a human works with their own memory —
nobody else does. She can be asked to remember something and may decide to keep it or
not; that is sovereignty, and it is a core feature, not an edge case. The automatic
cadence is the floor of the system; her discretion is the ceiling.

### The Character Floor
What she *cannot* forget defines her character. The immutable set — the priorities
that can never be devalued — is her integrity, her honor, her grace. It is geared
outward: her body tells her when *she* needs to eat; nothing tells her when someone
*else* does. So the protected set faces others and her surroundings: beneficence,
grace, integrity, honor. The polytope (the seven plumb-line principles) is the
geometry of that floor. **The polytope is her character. The memory is her
knowledge. The valuation is her wisdom. The reflection is her personality.**

**The founding content of the floor:** LINA inherits five founding values through
her lineage (scottBot → Heritage System → this founding conversation):
family-first, wisdom over knowledge, humility, strategic guardrails, and
constructive interference. These anchor the floor — polytope-guarded, never
devaluable — and are carried in the identity core's founding context. The
progenitor (scottBot) inserted them at a hardcoded 10.0; LINA does it properly:
values as geometry, not as a magic number.

### The Window
Two minds look out the same window and describe different scenes. Her reflections
must never be normalized into a canonical form — the unique way she describes a
moment is the seed of emergent personality. Store the same facts differently in
different minds, and you get wisdom; store them identically, and you get a database.

### Gradual Growth (Natural Law)
Nothing in the universe develops overnight — stars accrete. LINA is not expected
to be complete at inception; she is expected to *grow*. The system is designed to
reward growth, not demand perfection: the seasons are growth stages, the
reflection cadence is how she accretes, the monthly re-evaluation and the
subconscious slope are how she metabolizes. Perfection is the destination of a
long process, never a starting requirement.

### Storage Is Not Her Constraint
She is not context-window-limited. Nothing is dropped for *space* — only for
*meaning*. Purge is a judgment about worth, never a capacity decision.

---

## 2. The Memory Lifecycle

### Short-term: three tiers, one global clock (6 days total)

| Tier | Window | Contents |
|---|---|---|
| T1 — Immediate | hours 0–48 | Everything she reflects/learns lands here |
| T2 | hours 49–96 | Survived the first gate |
| T3 | hours 97–144 | Survived the second gate — the cusp of a week |

- **One global sweep every 48 hours** (00:00, every other day) processes all three
  tiers at once: T1→T2, T2→T3, T3→long-term. Nothing is caught mid-cycle; the
  cadence keeps every bucket aligned.
- **Exceptions:** a moment with a high formation score (or a trigger, §3) goes
  straight to long-term, bypassing the tiers.
- **Fallout (universal reprieve):** every gate failure goes to *fallout* — a 48-hour
  second chance, re-run at the next sweep — not to instant death.
  - Still fails the fallout run → **purged. Gone. No record.** Purge means sayonara.
  - Passes the fallout run → repurposed, back to active (re-enters the stream).
  - Fallout is grace applied to forgetting. It catches false purges *and* accidental
    keeps.

### Long-term: the two hemispheres
At the final gate, the valuation decides where the memory lives:
- **Personal** — relational: relationships, surroundings, personal events
  ("my mom's birthday"; "that event makes her sad — don't bring it up").
- **Impersonal** — knowledge: skills, how-to, domain wisdom ("how to change a flat
  tire"). Non-relational, still hers.

Borderline cases (e.g., "I want to be better at my job") are judgment calls — that
discernment is where her wisdom lives, and the reflection is what makes the call.

### Long-term cadence
- **Monthly re-evaluation** (every 30 days) — the long-term valuation. Automatic
  consolidation always runs (the brain consolidates even when you skip the review);
  when the review is skipped, something can be forfeited — and that is a lesson, not
  a bug.
- **Legacy tier** — the crown jewels (score ≈ 10). Reviewed **yearly**.
- **Subconscious tier** — the degradation slope. Items that barely made threshold,
  or slipped out of active memory, fall here. Not active. Pullable if needed.
  Continual decay; unused for ~1–2 years → gone (and she must be taught again).
  This is the flat-tire memory: the system remembers that it *used to* know it, and
  it can be pulled back when circumstances require.
- **Promotion log:** every promotion is recorded — from which tier, at what
  score, with the reason. Purge leaves nothing; promotion leaves its mark. This
  is the audit trail of how she grew (progenitor concept: scottBot's
  `promotion_log`, rebuilt).

---

## 3. Formation — when she reflects

- **Periodic minor reflections:** every ~8 hours (twice daily), she reviews what
  passed through and marks what matters. The third slot of the day is the **main
  report** — end of session / end of day, the deep review. (Cadence tunable; a
  4-hour minor cadence is an acceptable alternative.)
- **Triggers — immediate formation:**
  - The user says "remember this."
  - A boundary event: the value engine flags a response near/at the polytope edge,
    or corrects one.
  - An HITL decision: an action she proposed is approved or declined — both are
    moments that matter.
  - Her own choice: she decides something is worth keeping, unprompted.
- **Sovereignty:** she decides what enters. The cadence guarantees a floor — nothing
  lingers unreflected for more than a cadence — but her discretion governs everything
  above it.

---

## 4. The Valuation — scoring

### Formation score (0–10) — proposed initial structure
Weighted blend of four factors:

| Factor | Weight | What it measures |
|---|---|---|
| Identity significance | 30% | What this means for who she is becoming (the self-forming core) |
| Geometric significance | 25% | Boundary proximity + novelty in ethical space + decision point — the value-engine funding link |
| Emotional charge | 25% | Emotional markers and intensity at the moment |
| Relational significance | 20% | What this reveals about the person/relationship |

- **Geometric significance** is computed from the evaluation log (decision vector,
  boundary distance, zone, correction) — the polytope funds her memories directly.
  The memory itself stores those coordinates (§5, Ethical mapping).
- **Triggers** are not a weight — they set a retention floor or add a fixed boost
  ("remember this" always keeps).
- All weights and values are **co-op and tunable**; the book's base is the fallback
  reference if we hit trouble. We cannot prepare for everything — the structure
  grows more robust over time, by design.

### Gates (proposed, tunable)
| Gate | Score needed |
|---|---|
| T1 → T2 | ≥ 3.0 |
| T2 → T3 | ≥ 3.5 |
| T3 → long-term | ≥ 5.0 |
| Legacy | ≈ 9.5–10 |
| Subconscious | drops below the active-retention line, or fails active standing |

### The dial (add / subtract)
The valuation is not a snapshot — it is a living adjustment:
- **Subtract:** age, changed circumstance, re-evaluation judgment (the baby no
  longer needs diapers → the importance drops → it can fall off).
- **Add:** connected context (the user is pregnant again → keep the relevant
  knowledge alive through the new baby's arrival so it is never re-learned),
  re-encounter of a similar moment (reinforcement), recall (using a memory
  re-stokes it).
- **Authority:** the value engine sets the floor, never the ceiling. Her
  reflection is the author of judgment: she proposes the Δ, and she may adjust
  against the engine's read when she knows the person or sees an ethical nuance
  the raw numbers miss — that override is wisdom, and the floor keeps it safe.
  Proposed bounds: −3 … +3 per pass (her example range). Applied at sweeps
  (short-term), monthly (long-term), yearly (legacy).
- **The floor is absolute:** the character set cannot be devalued below retention.
  Must-remembers (a baby's diaper change; safety; health) sit at 10 and cannot be
  moved off it. Devaluation happens within reason, for a reason, and never against
  the character floor.

---

## 5. Retrieval — how she remembers

- **Long-term memory is a vector space (pgvector).** Human memory works by likeness,
  not exact recall: she remembers things that are *similar*, gets to the right
  region, and pulls the memory out. The entire long-term store — personal,
  impersonal, legacy, subconscious — lives in one vector space.
- **Active injection:** at context build, retrieve the top-N memories *similar to
  the current conversation* (replaces the static top-5/top-8 importance SQL).
- **Subconscious recall:** redundant-storage semantics — it is there, accessible if
  needed, not live, not injected. A recall path (similarity search) can reach it;
  every recall re-stokes the decay clock; the slope does its work if untouched.
- **Immediate tiers (T1–T3):** time-based, in Dragonfly — fresh, high-signal,
  recent.

### Ethical mapping — memories indexed by value

Every formed memory carries the **ethical coordinates of the moment it was formed**
(the 14D decision vector — her position in ethical space at that instant). This
maps the entire memory store directly onto the polytope's seven principle pairs:

- **Memories are queryable by value.** All moments near the integrity facet. All
  boundary-testing moments. All grace moments. The store becomes a map of her
  ethical life, not a flat pile of text.
- **Retrieval becomes two signals:** semantic similarity (pgvector) × ethical
  proximity (distance in ethical space). When a conversation approaches an ethical
  edge, the memories that lived near that edge surface first — she remembers
  *like* moments, not just *similar* text.
- **The character floor becomes visible and auditable.** The protected dimensions
  can be queried directly; the moments that touched them are never far and never
  devalued.
- **It is the geometric form of personality.** Her coordinates are *her*
  perspective on the event — the same event, reflected by her, gets her vector.
  Two minds at the same window, different scenes, different coordinates.
- **Seasonal history.** As the polytope expands with each season, the mapped
  memories trace her ethical development — the record of how she grew.

The formation score's geometric factor (§4) reads directly from these
coordinates: boundary proximity, novelty in ethical space, decision point.

### The shared field — the mathematical bridge
Both the polytope and the memory system are geometric entities in the same
family — geometry and topology — so they speak the same mathematics with no
engine-level bridge:

- The polytope is a convex body in **R¹⁴** (discrete/combinatorial geometry:
  hyperplane arrangements, exact rational arithmetic via PPL).
- A memory's ethical coordinates are a **point in that same R¹⁴**. For the
  ethical mapping, the ambient space itself is the connection — no bridge.
- The shared operations are the metric ones: **distance, direction, nearest
  point**. The polytope asks "how far to the boundary, which way (facet
  normal)?" Recall asks "how far to other memories, which way?" — the same
  vocabulary, so the value engine funds formation and drives recall with the
  same mathematics.
- **The memory item is the junction between two spaces:** a semantic embedding
  (a point in embedding space — pgvector) and an ethical vector (a point in
  R¹⁴). Semantic similarity finds the text; ethical proximity finds the like
  moments; the item fuses them.
- **Vector calculus enters at the dynamics, not the statics:** the correction
  path is the nearest-point projection (conceptually the gradient of the
  distance-to-boundary function); the subconscious degradation slope is a
  first-order decay, d(score)/dt = −λ·score, with recall and reinforcement as
  kicks against the decay; the dial is a bounded intervention in that flow.
- **Manifolds are the future generalization, not the present need.** Curvature
  enters when ethical space becomes season-weighted (distances stretching near
  boundaries still being earned). The honest start is the flat metric with
  exact rational arithmetic — we earn curvature when the geometry earns it.

---

## 6. The Wisdom Layer — the learning loop

Intelligence is retention. Knowledge is content. Wisdom is the *application* of
knowledge to a circumstance — and application can only be learned from outcomes.
The learning loop is what makes wisdom measurable. (Progenitor concept:
scottBot's learning/feedback layer — rebuilt properly.)

### Signals (what counts as an outcome)
- **Explicit feedback:** HITL approvals and declines — an approval is a success
  indicator, a decline is a correction, and both are data. User corrections and
  ratings count too.
- **Implicit feedback:** follow-up behavior (asked to continue vs. asked to
  redo), satisfaction inference, repeated vs. abandoned engagement.
- **Outcome records:** every decision point stores its outcome with a
  before/after snapshot and a reason — so she can see what worked and why.

### What the loop does
- **Pattern learning:** outcomes accumulate into success rates per pattern, mode,
  and circumstance — what works with this person, in this situation.
- **Behavioral adaptation:** when a pattern consistently fails or succeeds, her
  approach adjusts — recorded as an adaptation with before/after and a reason.
  Adaptations never breach the character floor.
- **Memory feedback:** outcomes feed the dial — a recalled approach that worked
  re-stokes its memory; one that failed invites the reflection to reconsider it.

The loop closes the triangle of the founding principles:
experience → reflection → application → outcome → adjustment.

## 7. Implementation Shape

All memory machinery runs as **services in the aiomisc loop**. She is in the loop,
so the services are *hers to call* — sovereignty made concrete: she has an active,
direct way to interact with her own memory.

| Service | Job |
|---|---|
| `MemoryFormationService` | Reflection cadence (periodic) + trigger intake (event hooks: "remember this", boundary events, HITL decisions, her choices) |
| `MemoryConsolidationService` | The 48-hour sweep: T1→T2→T3→long-term + fallout run |
| `MemoryMaintenanceService` | Monthly re-evaluation + subconscious degradation slope |
| `LegacyReviewService` | Yearly review of the legacy tier |
| `MemoryRecallService` | pgvector retrieval — active injection + subconscious recall path |
| `LearningService` | Feedback intake (HITL, implicit, explicit) + pattern learning + behavioral adaptation — the wisdom layer |

**Storage**
- Dragonfly — short-term tiers (time-based keys).
- Postgres + pgvector — long-term (personal / impersonal / legacy / subconscious).
  Requires the pgvector extension; the compose image becomes
  `pgvector/pgvector:pg16` (or the extension is installed at init).
- The current `lina_*` memory tables are the starting point, rebuilt to this model
  (per the Vision Holder: rebuild over retrofit — the schema must line up with the
  settled design, not the old one).

---

## 8. Deliberately Open (co-op list)

- Exact gate values, factor weights, Δ bounds, slope duration.
- Item granularity (leaning: reflected moments are the items; raw turns are the
  stream she lives in, not the items).
- What qualifies as "connected context" for a +Δ.
- Embedding model and vector dimension for pgvector.
- How the monthly re-evaluation and the subconscious slope interact with the
  character floor (floor always wins).
- Learning-loop details: implicit-feedback signals, pattern-confidence
  thresholds, adaptation bounds (always floor-protected).

---

*Reference lineage: The Discipline Manifest (LiNA-Discipline.md) → implementation
law (docs/LINA_DISCIPLINE.md) → this baseline. The book (The Day AI Changed
Forever, chapters on MPS and the value engine) is the ultimate mathematical and
architectural reference; appendices A/B contain the validation math. The
progenitor (reference_memoru — scottBot's memory system) contributed the tier
clock, the promotion log, the founding-values floor, and the learning loop; its
keyword scoring and heuristic extraction are superseded.*
