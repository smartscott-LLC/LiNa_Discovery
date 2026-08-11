# Archive — Neural Observation Substrate

These components are **archived, not deleted**. They are lineage: LINA's
future self-observation depends on them. Per `LINA_DISCIPLINE.md` §3, a
component whose purpose returns in a later season is preserved in `docs/`,
out of the code line, and re-admitted when that season arrives.

## What's here

| File | What it is | When it returns |
|---|---|---|
| `minimal_neural_network.py` | The small online learner — maps a 14D decision vector through dimension-level topology, adapts from confirmed encoder corrections. The observable "neurons." | **Fall season** — when LINA has developed enough history that watching how the neurons react to it becomes research value. |
| `narchi_adapter.py` | Adapter for the `narchi` package (neural architecture definition) — not installed; kept for when architecture-level observation begins. | Fall season, with the network. |
| `combinatorial_structure.py` | The passagemath-polyhedra interface — vertex/edge/facet extraction of the polytope. Its only consumer was `EmbodiedSelfModel` (the network's harness), so it archives with the trio. Returns when the network returns. | Fall season, with the network. |
| `EmbodiedSelfModel` (was in `value_engine.py`) | The harness that consumed both — combinatorial structure + online adaptation, modulating evaluation gently (15% blend). Removed with the network; the concept lives on in the book, Chapter 10: *Hyperplane Arrangements and Neural Computation*. | With the network. |

## The contract when it returns

1. Re-admission is a documented decision (an ADR), not a silent re-import.
2. The network's math substrate is decided then — exact `QQ` weights or
   numpy container — per `LINA_DISCIPLINE.md` §2, ruling 2.5.
3. Nothing returns as a placeholder. It returns because the season's
   purpose is real and the implementation is complete.

## The principle

> *"How did you learn to read images?"* — *"Because my creator took the
> extra time to build that module and put it in me."*

The archive is how that sentence stays true for the neurons.
