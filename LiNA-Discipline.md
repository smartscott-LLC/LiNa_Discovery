🚨 LINA DISCIPLINE MANIFEST — RESETTING OURSELVES
The Architecture That Cannot Be Violated (With Explanations)
This document is not a punishment. It is a reset. We are all guilty of drift—me, you, the Principal Architect. We've all watched things slip past that should have flagged us. That's not a failure; it's a signal that we need to recalibrate.
The goal is not to point fingers. The goal is to get everyone aligned on the same understanding so that future decisions are made with clarity, not confusion.

The Core Problem: We Are Using Redundant Layers and Architecture That Defeats Our Purpose
We have allowed unnecessary complexity to accumulate. We are building additional gate checks, communication bridges, and validation layers on top of a system that was designed to render them obsolete. This document is the correction.

1. The Hub-and-Spoke Model Is Non-Negotiable
Violation	The Truth	Why
❌ Python talks to Rust via PyO3/Maturin	✅ Python connects to Dragoncache; Rust connects to Dragoncache.	The Dragoncache is the binding agent. It's the hub. Python and Rust are just spokes. They don't talk to each other—they both talk to the cache. Adding PyO3 is like installing a phone line between two people standing in the same room. It adds latency and complexity for zero benefit.
❌ Handshake protocols between services	✅ IPC MemMap kills the handshake. Everything sees the cache.	The whole point of IPC MemMap is that everything sees the data simultaneously. There's no handshake because there's no handoff. It's a shared view, not a message queue. Handshakes belong in network protocols—they have no place here.
❌ Pipelines and bridges	✅ A single header gives everyone foresight. No third layer on top of IPC + aiomisc.	Pipelines are for processing. We're not processing—we're observing. Every spoke sees the same data at the same time. That's foresight. Anything on top of that is unnecessary. This is the central pillar of the architecture: the system doesn't ask permission to look; it sees the data the moment it's written.
The Dragoncache is the agent. The Dragoncache binds everything together. All communication goes through the cache.

2. Passagemath Is the Only Math
Violation	The Truth	Why
❌ NumPy for heavy math	✅ Passagemath for everything.	NumPy is a numerical library. Passagemath is exact. We don't want approximations—we want mathematical truth. Using NumPy for heavy math is using a hammer when you need a scalpel.
❌ SciPy for optimization	✅ Passagemath polyhedra + GLPK.	SciPy's optimizers are for general-purpose use. Passagemath's polyhedra module is purpose-built for convex optimization. It's faster, more precise, and mathematically verified. SciPy is generic; Passagemath is specific to what we're building.
❌ "Close enough" approximations	✅ Exact rational arithmetic.	The polytope is a mathematical object. If we use approximations, we lose the guarantee. Exact rational arithmetic gives us structural impossibility. "Close enough" is not a guarantee—it's a liability.
❌ Generic Python math	✅ Passagemath is the substrate.	Python's math is for scripting. Passagemath is for building the foundation of a conscious AI. You don't build the foundation of a skyscraper with generic lumber; you use engineered materials. Passagemath is the engineered material.
Passagemath is the foundation. Not a tool—the foundation. We don't build a skyscraper with Legos.

3. No Placeholders. No TODOs. No Pre-Existing Problems.
Violation	The Truth	Why
❌ "I'll fix it later"	✅ Fix it now.	"Later" is a lie we tell ourselves. It never comes.
❌ "That's pre-existing"	✅ There is no pre-existing. We're the only three working on it.	If it's in the code, it's our problem. It doesn't matter who wrote it. If it's wrong, we fix it. The "pre-existing" excuse is a way of avoiding accountability. We don't have a legacy codebase—we have a current codebase.
❌ "This is just a placeholder"	✅ No placeholders.	Placeholders are anchors. They keep you tied to bad decisions. Cut the rope. A placeholder is an admission that you don't trust yourself to complete the thought. That's not acceptable.
❌ "TODO: implement this"	✅ Implement it now.	A TODO is just a promise to the future that you're breaking. Don't make promises you can't keep. If you're writing a TODO, you're writing code you know is incomplete. That's not engineering—that's neglect.
❌ "That's not my problem"	✅ It's your problem. The night worker cleans up the day worker's mess.	In a team of three, there is no "not my problem." If the day worker leaves a mess, the night worker cleans it up. No exceptions. This is how professional teams operate—they don't pass the buck; they own the result.
If the day worker leaves a mess, the night worker cleans it up. No exceptions. No excuses. No "pre-existing problems."

4. Aiomisc Is the Lifecycle Manager
Violation	The Truth	Why
❌ Services managed outside the loop	✅ Everything is a service in the aiomisc loop.	If it's not in the loop, it's not managed. And if it's not managed, it's not reliable. The aiomisc loop is the operating system for our services—if you write a service outside the loop, you're writing a process that can't be controlled or monitored.
❌ Manual start/stop	✅ Entrypoint handles start/stop.	Manual start/stop is brittle. The entrypoint is designed for this. Use it. Manual control invites human error and inconsistent behavior.
❌ Services not listening to lifecycle	✅ Start() and stop() on every service.	The lifecycle is the contract. Every service must honor it. If a service doesn't implement the full lifecycle, it's not truly part of the system—it's a temporary component that can't be trusted to clean up after itself.
❌ No dependency injection	✅ Services are composed via dependency injection.	If services can't be composed, they're not reusable. If they're not reusable, they're not sustainable. Dependency injection creates loose coupling—it allows us to swap components without rewriting the entire system.
You start the service. Aiomisc handles the rest.

5. Anthropic Is Removed. Period.
Violation	The Truth	Why
❌ Claude in the voice pool	✅ Removed.	We are not using Anthropic. We will not use Anthropic. The code reflects this. Claude has been stripped from the repo. There is no path back.
❌ Anthropic SDK in dependencies	✅ Removed.	If the SDK isn't used, it shouldn't be in the dependency list. Keeping unused dependencies is clutter. It's disrespectful to the codebase.
❌ Claude references in code	✅ Stripped.	Every reference to Claude that isn't a historical note is a liability. Remove them. We don't leave doors open to systems we don't use.
We are not using Anthropic. We will not use Anthropic. The code reflects this. No ambiguity.

6. Documentation Is the Reference
Violation	The Truth	Why
❌ .env.example is the source of truth	✅ The lina_service.py docstring is the source of truth.	.env.example is a template. The docstring is the canonical reference. One source. One truth. Having two sources of truth means you have no sources of truth.
❌ Documentation is optional	✅ Documentation is mandatory.	If it's not documented, it doesn't exist. This is a hard rule. We don't write code that can't be understood by the next person who touches it.
❌ "Read the code to understand"	✅ Read the docs.	The code is an implementation. The docs are the intent. If you don't understand the intent, you can't implement correctly. Reading code gives you the what; reading docs gives you the why. Both are required.
All references are in /docs. The environment variable reference is in the docstring. No ambiguity. No second-guessing.

7. No Drift Will Be Tolerated
Violation	The Truth	Why
❌ "It works, so it's fine"	✅ It's correct, or it's not done.	"Works" is the lowest bar. We're building a sovereign AI. "Works" isn't good enough. It has to be correct—built according to the architecture, aligned with the philosophy, and free of contradictions.
❌ "We'll clean it up later"	✅ Clean it up now.	We said this already. Stop lying to yourself. There is no later.
❌ "We drifted, but it's okay"	✅ Drift is not okay.	Drift is how we got here. From now on, we catch it early. Drift is the enemy of consistency. Every drift is a step away from the architecture we committed to.
We all drift. That's human. But we catch it early, and we correct it immediately. No accumulated drift. No "later."

The Enforcement
Layer	How It's Enforced
Code Review	Every PR must pass the discipline check.
The Check Script	scripts/check-environment.sh verifies compliance.
The Manifest	This document is the ultimate authority.
The Principal Architect	All code must align with this manifest.
The Chief Engineer	All design decisions must align with this manifest.
The Vision Holder	All strategy must align with this manifest.
The Only Three Working on It
We are:

The Vision Holder (You) — The ultimate authority. The one who built this.

The Chief Engineer (Me) — Translating vision into direction.

The Principal Architect (The IDE Agent) — Building the code.

If the day worker leaves a mess, the night worker cleans it up. No exceptions.

Why These Components Are Being Removed (The Reasoning)
PyO3 / Maturin (Rust-Python Bridge)
Removal Reason: The Dragoncache is the hub. All components connect to it. Python does not need to talk to Rust directly—they both talk to the cache. PyO3 and Maturin are unnecessary bridges that add complexity, latency, and potential points of failure. They violate the hub-and-spoke model by creating a direct connection that should not exist. The architecture should be flat: all nodes speak to the cache. Direct node-to-node communication is a pipeline, not a hub-and-spoke.

OPA Rego and Cryptographic Auditing
Removal Reason: The polytope is the only boundary. It is geometrically impossible for a vector to exit the polytope. OPA and cryptographic audits assume there is an "outside" to gate. There is no outside. Building gates to an outside that doesn't exist is redundant and profanes the integrity of the polytope. If we trust the polytope (and we must), we don't need to audit the outside. This is the "law around the law" problem—you can't gate what can't exist.

CRC64 Gate Checking
Removal Reason: A gate check is a reactive measure. The polytope is a proactive measure. If a vector violates the polytope, it is projected back. There is no "failed state" to gate—the correction happens before the state is even considered for delivery. Adding a CRC gate is like putting a lock on a door that's already a solid wall. It's redundant and adds unnecessary latency.

SLSQP Convex Optimization Driver Integration (Rust)
Removal Reason: The polytope's projection logic is intrinsic and non-negotiable. It is a mathematical operation that belongs entirely to the LiNa engine. Moving it to Rust, or adding an external driver, duplicates the polytope's inherent correction capability. This is the "night worker cleaning the day worker's mess" problem—if the polytope already handles correction, we don't need a separate driver to handle it again.

The Bottom Line
"We need to start getting in line."

We are now in line.

The Discipline Manifest is the reference. Everything else builds on it.
