# AnaStone

AnaStone is a deterministic, two-language data pipeline with a production-grade web GUI.
Raw data enters through a Rust ingest layer, is staged in shared memory, and is then
processed by a Python combinatorics layer (powered by **passagemath-combinat**) that maps
the data onto an immutable mathematical sphere and encodes it as compact, lossless
topological blueprints. No external API calls are made at any stage; the two layers
communicate exclusively through a file-backed IPC memory map.

A **Rust WebAssembly sidecar** powers the browser UI — computing Fibonacci sphere
coordinates, validating uploads, and building score histograms entirely client-side so the
pipeline's resident memory is never depleted by UI work.

## Repository layout

```
AnaStone/
├── src/
│   ├── lib.rs                        # Rust Pipeline 1 (ingest → cache → FIFO → mmap)
│   └── main.rs                       # CLI binary — anastone-pipeline
├── wasm/
│   ├── Cargo.toml                    # Rust WASM sidecar crate (cdylib + rlib + [[bin]])
│   └── src/
│       ├── lib.rs                    # fibonacci_sphere_points, validate_and_preview, …
│       └── main.rs                   # anastone-wasm-engine — standalone native CLI
├── python/
│   ├── requirements-phase2.txt       # passagemath-combinat dependency
│   ├── requirements-gui.txt          # FastAPI + uvicorn dependency
│   ├── anastone_phase2/
│   │   ├── __init__.py               # public exports
│   │   ├── phase2.py                 # Python Phase 2 — sphere, codec, IPC bridge
│   │   └── visualize.py              # Phase 2 GUI — 3D render of the Anasphere
│   └── anastone_gui/
│       ├── __init__.py               # GUI package
│       ├── app.py                    # FastAPI server — combined entrypoint + launcher
│       ├── pipeline_runner.py        # Subprocess bridge to anastone-pipeline binary
│       └── static/
│           ├── index.html            # SPA — upload, sphere, metrics
│           ├── app.js                # Three.js + WASM + WebSocket client
│           ├── style.css             # Dark glassmorphism design system
│           └── wasm/                 # Built WASM artifacts (auto-generated)
│               ├── anastone_wasm.js
│               └── anastone_wasm_bg.wasm
├── Cargo.toml
├── Makefile                          # Unified build: binary + WASM + Python deps
└── WORD_PATH_REFERENCE.md            # passagemath WordPaths API reference
```

---

## Quick Start — GUI Launcher

```bash
# 1. Build everything (Rust binary + WASM sidecar + Python deps)
make

# 2. Start the GUI server
make run
# → http://127.0.0.1:8000

# For production (multi-worker)
make run-prod
```

The GUI at `http://127.0.0.1:8000` provides:

- **Drag-and-drop file and folder upload** — accepts **all file types**: JSON lines, JSON arrays,
  CSV, TSV, TOML, YAML, NDJSON, JSONL, plain text, binary, and any other format.
  Use **Browse Files** to select individual files or **Browse Folder** to select an entire
  directory; dragging a folder onto the drop zone recursively collects every file inside.
- **Client-side preview** — the Rust WASM sidecar validates format, counts rows,
  and renders a live score-distribution histogram before any data leaves the browser.
- **3D Anasphere** — a WebGL particle system (Three.js + OrbitControls) renders
  100 000 Fibonacci surface points (sampled from the full 2.2 M canonical set) colored
  by their cyclic Hebrew-letter assignment.  All 22 canonical letter colors cycle through
  the displayed points regardless of the sampling stride.  Drag to orbit, scroll to zoom.
  After a pipeline run completes the sphere recolors to show the primary/shadow split:
  primary records keep full Hebrew-letter brightness; shadow records are dimmed.  Colors
  restore to the canonical palette after three seconds.
- **Real-time pipeline metrics** — a WebSocket streams NDJSON events from the Rust
  subprocess back to the browser: ingested, primary, shadow counts, throughput, and
  elapsed time update live as the pipeline runs.
- **Blueprint key artifact recording** — immediately after the Rust pipeline finishes,
  the server reads every mmap record, derives a `DegreeBlueprintKey` via Phase 2
  (passagemath `DegreeSequenceCodec.blueprint_key_from_block`), and writes the full key
  set to `<job_dir>/keys.json`.  The lossless guarantee is encoded in every record:
  **Algorithm + Degree Sequence + Derangement + Shadow Distance = Original Structure**.
  `shadow_distance = 0` means the block was already a perfect graphic sequence;
  `shadow_distance > 0` records the exact L1 deviation.
- **View Keys** — after key generation completes, a **Blueprint Keys** panel appears in
  the left sidebar with a paginated table showing every record's key, node state (primary /
  shadow), score, shadow distance, and first 8 entries of the degree sequence.
- **Download Keys** — the full `keys.json` file can be downloaded via the **⬇ Download**
  button.  The server also exposes `GET /api/jobs/{job_id}/keys` (inline JSON) and
  `GET /api/jobs/{job_id}/keys/download` (file download).
- **Hebrew-letter legend** — every one of the 22 letters with its canonical color
  rendered as an interactive overlay on the sphere panel.

### Manual build steps

```bash
# Rust pipeline binary
cargo build --release

# WASM sidecar — run these from the repo root
# 1. Install prerequisites (once)
#    rust-toolchain.toml in the repo root declares the wasm32-unknown-unknown target,
#    so rustup will install it automatically when cargo runs.  If you hit
#    "can't find crate for `core`" it means the target is missing for the active
#    toolchain — running the line below fixes it:
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.118 --force  # --force ensures the pinned version replaces any other installed version

# 2. Compile the WASM crate (subshell keeps you in the repo root)
(cd wasm && cargo build --release --target wasm32-unknown-unknown)

# 3. Generate JS bindings (run from repo root)
wasm-bindgen --target web \
    --out-dir python/anastone_gui/static/wasm/ \
    wasm/target/wasm32-unknown-unknown/release/anastone_wasm.wasm

# Python packages — install as editable so the server is importable from anywhere
pip install -e python/

# Start the GUI server
cd python && uvicorn anastone_gui.app:app --host 127.0.0.1 --port 8000 --reload
# → http://127.0.0.1:8000
```

### Large-file uploads (1 GB – 10 GB+)

The server streams uploads in 8 MiB chunks — no artificial size limit.  For very large
datasets the main things to tune are:

- **`mmap_size`** in the pipeline config panel: set this to at least the number of records
  × 64 bytes.  Example: 10 M records → 640 MB mmap.  The default 64 MB is appropriate for
  ~1 M records.
- **Disk space**: the uploaded file is written to `$TMPDIR/anastone_jobs/<job_id>/` and the
  mmap is written alongside it.  Ensure the filesystem has at least `file_size + mmap_size`
  free.
- **Folder uploads** preserve their relative directory structure so files with the same
  basename in different sub-folders never overwrite each other.

### Rust toolchain

The repository pins the Rust toolchain to **1.95.0** via `rust-toolchain.toml`.
Rustup will install it automatically on first `cargo` invocation.

### Environment variables

| Variable          | Default       | Description                        |
|-------------------|---------------|------------------------------------|
| `ANASTONE_HOST`   | `127.0.0.1`   | Server listen address              |
| `ANASTONE_PORT`   | `8000`        | Server listen port                 |

---

## CLI Pipeline Binary

`anastone-pipeline` is a standalone binary for headless / scripted use:

```bash
# Single file
./target/release/anastone-pipeline data/input.json

# Multiple files
./target/release/anastone-pipeline data/a.json data/b.csv

# Entire folder (recursive, collects .json .csv .txt .ndjson .jsonl)
./target/release/anastone-pipeline data/

# Read from stdin
cat data/input.json | ./target/release/anastone-pipeline --stdin

# Stream progress events as NDJSON to stderr
./target/release/anastone-pipeline --stream data/input.json

# Full option reference
./target/release/anastone-pipeline --help
```

**Output** — JSON report on stdout:

```json
{
  "ingested": 3,
  "primary_written": 2,
  "shadow_written": 1,
  "mmap_path": "./data/pipeline.mmap",
  "elapsed_ms": 2,
  "throughput_fps": "1163.4"
}
```

**Stream events** (stderr, one NDJSON object per line):

```
{"type":"start",    "data":{"queue_capacity":4096,"mmap_size":67108864,...}}
{"type":"file_read","data":{"path":"data/input.json","bytes":128}}
{"type":"parsing",  "data":{"bytes":128}}
{"type":"complete", "data":{"ingested":3,"primary_written":2,"shadow_written":1,"elapsed_ms":2}}
```

---

## Rust WASM Sidecar

The sidecar crate lives in `wasm/` and exposes five functions via `wasm-bindgen`:

| Function | Signature | Description |
|---|---|---|
| `fibonacci_sphere_points` | `(total: u32, radius: f32, stride: u32) → Float32Array` | Packed `[x,y,z,r,g,b, ...]` point data for the Three.js particle system |
| `validate_and_preview` | `(data: &[u8], max_rows: u32) → String` | JSON: format, row counts, preview rows |
| `score_histogram` | `(data: &[u8], bucket_count: u32) → String` | JSON: histogram buckets + statistics |
| `letter_colors_hex` | `() → String` | JSON array of 22 canonical Hebrew-letter hex colors |
| `hebrew_alphabet_json` | `() → String` | JSON array of 22 `[symbol, name, literal, pictorial, numeric]` entries |

The sidecar never touches the Rust pipeline library — it is a completely separate crate
compiled exclusively to WebAssembly.

### WASM Engine — Standalone Native Binary

The same sidecar code also compiles as a fully independent native CLI binary,
`anastone-wasm-engine`, with **no WASM tooling required**:

```bash
# Build the standalone engine
cd wasm && cargo build --release
./wasm/target/release/anastone-wasm-engine --help

# Subcommands
anastone-wasm-engine sphere    [--total N] [--radius R] [--stride N] [--points]
anastone-wasm-engine validate  <file> [--max-rows N]
anastone-wasm-engine histogram <file> [--buckets N]
anastone-wasm-engine alphabet
anastone-wasm-engine colors
```

This confirms the sidecar is **100% independent** — the same engine logic runs in the
browser as WASM and on the command line as a native binary, sharing zero code with the
`anastone-pipeline` crate.



---

## Pipeline 1 — Rust (Ingest → Cache → FIFO → Formation)

Pipeline 1 is a lock-minimised, high-throughput Rust library that ingests **all data formats** —
JSON (lines and arrays), CSV, TSV, TOML, YAML, plain text, and raw binary — and writes
deterministic fixed-width records into a memory-mapped file. Format detection is automatic:
`nom` boundary-sniffs each byte stream, `serde_json` / `serde_yaml` / `toml` / the `csv` crate
then deserialize into a unified `Fragment` with flexible key+score extraction that tries
well-known field names and falls back gracefully for arbitrary structures. It is the
**data producer** whose mmap output the Python layer reads from and writes keys back into.

### Why each stage exists

| Stage | Name | Why |
|---|---|---|
| 1 | Ingest — The Hounds | `nom` boundary-sniffs the stream without full parsing, keeping memory flat and bounded. |
| 2 | Dragonfly Cache | `DashMap` provides sharded, lock-free staging so multiple ingest threads never contend on a single mutex. |
| 3 | Foresight FIFO | Only 64-bit IDs travel through the channel; payloads stay in the cache. This keeps the queue shallow and gives the formation stage deterministic look-ahead. |
| 4 | BRAM Controller | Atomic back-pressure prevents the ingest thread from outrunning formation. Throttling triggers at 80 % of `queue_capacity`; status is observable without locking. |
| 5 | Formation — The Tree Guy | `memmap2::MmapMut` writes records directly to a pre-allocated file region, eliminating heap allocation and copy overhead at write time. |

### Stage 1 — Ingest (The Hounds)

- `nom` splits the raw byte stream line-by-line without loading the whole input.
- Format detection is automatic and multi-format:
  - Whole-file JSON arrays (`[…]`), YAML (starts with `---`), and TOML (heuristic detection)
    are parsed as complete documents first.
  - Line-by-line fallback handles JSON objects (`{…}`), JSON arrays, TSV, CSV, and plain text.
  - Invalid UTF-8 falls back to binary chunking (256-byte blocks, FNV-1a score).
- Each line or document entry becomes a `Fragment`:
  - `id: u64` — monotonically assigned, starts at 1.
  - `source: SourceType` — `Json`, `Csv`, `Tsv`, `Toml`, `Yaml`, `Text`, or `Binary`.
  - `key: String` and `score: f64` — extracted from well-known field names or positional fallbacks.
  - `raw: Arc<[u8]>` — preserved original bytes for integrity and downstream handoff.

### Stage 2 — Dragonfly Cache (Staging Ground)

- `DashMap<u64, Arc<Fragment>>` provides concurrent, sharded staging.
- `claim(id)` removes and returns the fragment atomically, preventing duplicate processing.

### Stage 3 — Foresight FIFO

- `crossbeam-channel::bounded` carries only fragment IDs, not payloads.
- The channel capacity equals `queue_capacity`, providing natural back-pressure.
- Formation receives IDs in arrival order, then claims the corresponding `Arc<Fragment>` from the cache.

### Stage 4 — Software BRAM Controller (Deterministic Arbiter)

`BRAMController` arbitrates write pressure with fully atomic state:

- `request_write()` — returns `true` only when `buffer_depth < max_capacity` and health is OK; uses a CAS loop so no mutex is needed.
- `signal_completion()` — decrements depth after each formation write.
- Status transitions: `Idle` → `Running` → `Throttled` (≥ 80 % full) → `Error` (unhealthy).
- `set_health(false)` puts the controller into `Error` immediately, blocking further ingest.

### Stage 5 — Formation (The Tree Guy)

`FormationWriter` owns the `MmapMut` and splits it at its midpoint:

- **Lower half `[0, midpoint)`** — Primary records (`score <= primary_threshold`).
- **Upper half `[midpoint, size)`** — Shadow records (`score > primary_threshold`).

#### Mmap record layout (64 bytes, fixed-width)

| Bytes | Field | Encoding |
|---|---|---|
| 0 – 7 | Fragment ID | `u64` little-endian |
| 8 | Source type | `1` = JSON, `2` = CSV, `3` = TSV, `4` = TOML, `5` = YAML, `6` = Text, `7` = Binary |
| 9 | Node state | `1` = Primary, `2` = Shadow |
| 10 – 17 | Score | `f64` little-endian |
| 18 – 19 | Key length | `u16` little-endian |
| 20 – 61 | Key bytes | UTF-8, up to 42 bytes |
| 62 – 63 | Raw length | `u16` little-endian (original byte count, capped at 65 535) |

Records are written in arrival order within each half. Offsets are fully predictable: record `n`
in the primary half starts at `n * 64`; record `n` in the shadow half starts at
`midpoint + n * 64`.

### Rust API usage

```rust
use anastone::{run_pipeline, PipelineConfig};
use std::path::PathBuf;

let config = PipelineConfig {
    queue_capacity: 1024,
    mmap_size: 8 * 1024 * 1024,
    primary_threshold: 1.0,
    mmap_path: PathBuf::from("./data/pipeline1.mmap"),
};

let input = br#"{"key":"alpha","score":0.2}
beta,1.6
{"key":"gamma","score":0.8}
"#;

let report = run_pipeline(input, &config)?;
assert_eq!(report.ingested, 3);
assert_eq!(report.primary_written, 2);
assert_eq!(report.shadow_written, 1);
```

### Rust validation

Also validates the CLI binary (`src/main.rs`) and WASM sidecar (`wasm/`):

```bash
cargo test
cargo clippy --all-targets --all-features -- -D warnings
```

Tests cover:

- BRAM back-pressure and high-watermark throttling.
- Universal format ingest parsing: JSON lines/arrays, CSV, TSV, TOML, YAML, plain text, binary.
- End-to-end ingest → cache → FIFO → mmap formation, verifying primary/shadow region split.

---

## Phase 2 — Python + passagemath-combinat (Graph Blueprint Layer)

Phase 2 is where "The Tree Guy meets the Mathematician." Instead of storing raw data fragments,
this layer translates each data block into a **topological blueprint** — a compact, lossless
description that can deterministically reconstruct the original structure through algorithm alone.

**All access to the Rust mmap is via shared memory (`IPCMmapBridge`). There are no API calls,
no network cache clients, and no remote handshakes. Python reads and writes the same
file-backed mmap that Rust writes into, using the OS IPC mmap mechanism directly.**

### Why passagemath-combinat?

passagemath-combinat provides production-grade, exact arithmetic combinatorics structures
(`Integer`, `RealNumber`, `SymmetricGroup`, `WordPaths`, `DegreeSequences`, `Sphere`, etc.)
that are not available in general-purpose numeric libraries. All computations in Phase 2 use
passagemath's structures exclusively — numpy, scipy, and similar libraries are not used
directly even though they may appear as transitive dependencies.

### Design: data as a graph realization

1. Python pulls fragment blocks from the IPC mmap (written by Rust).
2. A **degree sequence** — a non-increasing list of integers representing vertex connections
   — is derived from the byte-level adjacency relationships within each block.
3. **`DegreeSequences(n)`** (passagemath's Erdős-Gallai enumerator) validates whether the
   sequence is graphically realizable via membership test.
4. If the block's degree sequence is **not graphic**, `DegreeSequences(n)` is enumerated in
   full to find the nearest valid graphic sequence by L1 distance. That distance becomes the
   `shadow_distance` — a precise measure of how far the raw block deviates from a realizable
   graph. Non-graphic blocks are never rejected; they are handled in the shadow layer.
5. **Havel-Hakimi forward pass** deterministically realizes the (nearest) graphic sequence as
   an edge list. Because the algorithm is deterministic, the same degree sequence always
   produces the same graph; the edges never need to be stored.
6. A **cyclic derangement** — a fixed-point-free permutation validated by Sage's
   `SymmetricGroup` — maps data positions to graph vertices and is stored alongside the
   sequence. Together they form the `DegreeBlueprintKey`.
7. **Havel-Hakimi reverse pass** (`reconstruct_edges`) re-runs the forward algorithm on the
   stored sequence, then maps edge endpoints back through the **inverse derangement** to
   recover the original vertex labels. No edges are stored — the algorithm alone regenerates
   them.
8. The key is serialized and written back to the IPC mmap at a known offset, ready for Rust
   to read.

The lossless guarantee is: **Algorithm + Degree Sequence + Derangement + Shadow Distance =
Original Structure**. `shadow_distance = 0` means the block was already a perfect graphic
sequence. `shadow_distance > 0` means it wasn't, and that deviation is recorded exactly.

### The Immutable Anasphere — why it is the constant stone

The **Anasphere** is a fixed, pre-computed 7-inch sphere with 2 200 000 points distributed
by a **Fibonacci spiral**, anchored at one pole. It is immutable by design: the sphere is a
constant reference frame — the "stone of recall" — against which all data blueprints are mapped.

The geometric reference is a passagemath `Sphere` object
(`sage.plot.plot3d.shapes.Sphere(radius)`) of radius 3.5 inches, exposed as
`ImmutableAnasphere.sage_sphere`. The Fibonacci point coordinates are computed as
`RealNumber` values on that sphere's surface.

Points are assigned using the **22 letters of the Hebrew alphabet** in a cyclic pattern. This
choice is deliberate: each Hebrew letter carries three independent layers of meaning —
**literal**, **pictorial**, and **numeric** — which triples the information density of each
point reference without storing extra data. For example, `Aleph (א)` encodes "ox" (literal),
"strength/leader" (pictorial), and `1` (numeric). A point labelled `Aleph` therefore carries
three simultaneous referential axes.

| Symbol | Name | Literal | Pictorial | Numeric |
|---|---|---|---|---|
| א | Aleph | ox | strength/leader | 1 |
| ב | Bet | house | household | 2 |
| ג | Gimel | camel | movement/provision | 3 |
| ד | Dalet | door | entry/path | 4 |
| ה | He | window | revelation/breath | 5 |
| ו | Vav | hook | connection | 6 |
| ז | Zayin | weapon | cut/separate | 7 |
| ח | Chet | fence | boundary/life | 8 |
| ט | Tet | basket | contain/coil | 9 |
| י | Yod | hand | work/act | 10 |
| כ | Kaf | palm | cover/open | 20 |
| ל | Lamed | staff | teach/direct | 30 |
| מ | Mem | water | flow/chaos | 40 |
| נ | Nun | seed/fish | continuity | 50 |
| ס | Samekh | support | uphold/protect | 60 |
| ע | Ayin | eye | watch/know | 70 |
| פ | Pe | mouth | speak/declare | 80 |
| צ | Tsadi | hook/plant | righteous trail | 90 |
| ק | Qof | back of head | horizon/cycle | 100 |
| ר | Resh | head | first/chief | 200 |
| ש | Shin | tooth | consume/transform | 300 |
| ת | Tav | mark/sign | covenant/seal | 400 |

The Fibonacci spiral ensures even, deterministic coverage with no clustering: starting at the
north pole (index 0), each successive point advances by the golden angle
`π(3 − √5) ≈ 2.399 radians`. The sphere coordinates are Sage `RealNumber` values scaled to
a radius of 3.5 inches.

### Word paths

`build_word_path(alphabet_word)` builds a `WordPaths` path object over the full 22-symbol
Hebrew alphabet using passagemath's `sage.combinat.words.paths.WordPaths`. This enables
combinatoric path tracing across the sphere surface — for example, computing areas, testing
self-intersection, or calculating inertia moments of the path in linear time.

### IPC mmap bridge — shmem only, no API

`IPCMmapBridge` is the sole mechanism for data exchange between Rust and Python. It maps the
same file that `FormationWriter` creates, using the standard POSIX `mmap` call via Python's
built-in `mmap` module. No socket, no HTTP client, no cache API.

- Persistent handle: the file descriptor and mmap object are opened once and reused across
  multiple reads/writes, then closed explicitly on `close()` or context-manager exit.
- `write_blueprint(offset, key)` — serializes a `DegreeBlueprintKey` and writes it at the
  given byte offset.
- `read_blueprint(offset)` — reads the 4-byte length header then the payload, deserializes,
  and returns a `DegreeBlueprintKey`.
- All offsets and lengths are bounds-checked before any memory access.

### Python setup

```bash
pip install -r python/requirements-phase2.txt
```

`python/requirements-phase2.txt` pins `passagemath-combinat>=10.0,<11.0`.

### Python API reference

| Export | Module | Type | Description |
|---|---|---|---|
| `ImmutableAnasphere` | `phase2` | class | Deterministic Fibonacci sphere, 2.2M points, 7-inch diameter |
| `ImmutableAnasphere.sage_sphere` | `phase2` | property | `sage.plot.plot3d.shapes.Sphere(3.5)` — the passagemath sphere geometry object |
| `SpherePoint` | `phase2` | dataclass | A single sphere point: `index`, `x`, `y`, `z`, `letter` |
| `HebrewLetter` | `phase2` | dataclass | `symbol`, `name`, `literal`, `pictorial`, `numeric` |
| `HEBREW_ALPHABET` | `phase2` | constant | Ordered tuple of all 22 `HebrewLetter` instances |
| `DegreeSequenceCodec` | `phase2` | class | Blueprint construction pipeline; all methods are static/class methods |
| `DegreeSequenceCodec.degree_sequence_from_block` | `phase2` | static | Extract byte-adjacency degree sequence from a block |
| `DegreeSequenceCodec.is_graphic` | `phase2` | static | `DegreeSequences(n)` membership test — Erdős-Gallai via passagemath |
| `DegreeSequenceCodec.nearest_graphic_sequence` | `phase2` | static | Enumerate `DegreeSequences(n)` to find nearest valid seq + L1 shadow distance |
| `DegreeSequenceCodec.havel_hakimi_realization` | `phase2` | static | Forward pass: degree sequence → deterministic edge list |
| `DegreeSequenceCodec.reconstruct_edges` | `phase2` | class | Reverse pass: `DegreeBlueprintKey` → original edge set via inverse derangement |
| `DegreeSequenceCodec.deterministic_derangement` | `phase2` | static | Cyclic permutation validated by Sage `SymmetricGroup` |
| `DegreeSequenceCodec.blueprint_key_from_block` | `phase2` | class | Full pipeline: block → `DegreeBlueprintKey` (never raises on non-graphic input) |
| `DegreeBlueprintKey` | `phase2` | dataclass | Lossless key: `degree_sequence`, `derangement`, `shadow_distance` |
| `IPCMmapBridge` | `phase2` | class | IPC shared-memory bridge; context manager; no API calls |
| `build_word_path` | `phase2` | function | Returns a passagemath `WordPaths` path over the 22 Hebrew symbols |
| `render_anasphere` | `visualize` | function | Build the 3D scene of the Anasphere with Fibonacci point markers (see below) |

---

## Visualization — Phase 2 GUI

`render_anasphere` produces the **visual representation of the immutable constant stone**: the
7-inch sphere with its 2.2 million Fibonacci-spiral surface points, each colored by its
Hebrew-letter assignment. It is implemented in `python/anastone_phase2/visualize.py` and
uses only passagemath's native 3D rendering stack — no matplotlib, no plotly, no external
GUI frameworks.

### Why the Sphere-primitive rendering approach

The spec specifies `sage.plot.plot3d.shapes.Sphere` as the rendering primitive because it is
the fastest object supported by both the Tachyon ray-tracer and the Jmol viewer that ship
with passagemath. Every Fibonacci point is drawn as a small `Sphere(radius)` translated to
its exact surface coordinates — the same primitive the spec quotes with `Sphere center x y z
Rad r texture...` in the Tachyon output format.

### Display decimation — computation is never reduced

`render_anasphere` accepts a `display_stride` argument (default `10`). This controls how
many Fibonacci markers are **rendered**, not how many are **computed**:

- All 2.2 million point indices are always available in the sphere's canonical index space.
- `point_at(i)` is called with the exact full index (0, 10, 20, …, 2 199 990) so every
  coordinate uses the correct Fibonacci golden-angle position on the full sphere.
- Only 220 000 markers are placed in the Graphics3d scene (every 10th point), which renders
  comfortably in Jmol and Tachyon.
- Setting `display_stride=1` renders all 2.2 million markers — fully supported, memory
  permitting.

### Color scheme

Each of the 22 Hebrew letters is assigned a fixed, visually distinct color that is consistent
across all renders regardless of which points happen to be sampled:

| Index | Letter | Color |
|---|---|---|
| 0 | א Aleph | vivid red `#E63946` |
| 1 | ב Bet | burnt orange `#F4A261` |
| 2 | ג Gimel | golden yellow `#E9C46A` |
| 3 | ד Dalet | teal `#2A9D8F` |
| 4 | ה He | dark slate `#264653` |
| 5 | ו Vav | steel blue `#457B9D` |
| 6 | ז Zayin | pale cyan `#A8DADC` |
| 7 | ח Chet | sky blue `#48CAE4` |
| 8 | ט Tet | deep navy `#023E8A` |
| 9 | י Yod | purple `#7B2D8B` |
| 10 | כ Kaf | lavender `#C77DFF` |
| 11 | ל Lamed | coral `#FF6B6B` |
| 12 | מ Mem | bright yellow `#FFD93D` |
| 13 | נ Nun | lime green `#6BCB77` |
| 14 | ס Samekh | bright blue `#4D96FF` |
| 15 | ע Ayin | amber `#FF9F1C` |
| 16 | פ Pe | peach `#FFBF69` |
| 17 | צ Tsadi | mint `#CBF3F0` |
| 18 | ק Qof | turquoise `#2EC4B6` |
| 19 | ר Resh | terracotta `#E76F51` |
| 20 | ש Shin | off-white `#F1FAEE` |
| 21 | ת Tav | sage green `#A8C5A0` |

### Usage

```python
from anastone_phase2 import ImmutableAnasphere, render_anasphere

sphere = ImmutableAnasphere()          # 2.2M points, 7-inch diameter

# Default: render every 10th point → 220,000 markers
scene = render_anasphere(sphere, display_stride=10)
scene.show(aspect_ratio=1)             # Jmol interactive viewer

# Ray-trace with Tachyon (uses native Sphere center x y z Rad r texture... format)
scene.show(viewer='tachyon', aspect_ratio=1)

# Export to a raster image
scene.save('anasphere.png', aspect_ratio=1)

# Render all 2.2M points (slow but mathematically complete)
full_scene = render_anasphere(sphere, display_stride=1)
full_scene.show(viewer='tachyon', aspect_ratio=1)
```

The `render_anasphere` function is also importable directly from the sub-module:

```python
from anastone_phase2.visualize import render_anasphere
```

### Python usage example (full pipeline + visualization)

```python
from anastone_phase2 import (
    DegreeSequenceCodec,
    HEBREW_ALPHABET,
    IPCMmapBridge,
    ImmutableAnasphere,
    SpherePoint,
    build_word_path,
    render_anasphere,
)

# Build the immutable sphere reference frame
sphere = ImmutableAnasphere(total_points=2_200_000, diameter_inches=7.0)
print(sphere.sage_sphere)           # Sage Sphere(3.5) geometry object

north_pole: SpherePoint = sphere.point_at(0)
print(north_pole.letter.name)       # "Aleph"
print(north_pole.letter.numeric)    # 1
print(north_pole.letter.pictorial)  # "strength/leader"

# Iterate a slice of points
for pt in sphere.iter_points(0, 22):
    print(pt.index, pt.letter.symbol, pt.x, pt.y, pt.z)

# Derive a blueprint key from a data block
block = b"alpha,beta,gamma"
key = DegreeSequenceCodec.blueprint_key_from_block(block)
# shadow_distance == 0 means the block was already a perfect graphic sequence;
# shadow_distance > 0 is the L1 distance to the nearest graphic sequence.
print(key.degree_sequence)
print(key.shadow_distance)

# Reconstruct the original edge set from the key (Havel-Hakimi reverse pass)
edges = DegreeSequenceCodec.reconstruct_edges(key)

# Exchange the key with Rust via IPC shared memory — no API calls
with IPCMmapBridge("./data/pipeline1.mmap", size=8 * 1024 * 1024) as bridge:
    bridge.write_blueprint(0, key)
    round_trip = bridge.read_blueprint(0)
    assert round_trip == key

# Build a combinatoric word path over the Hebrew alphabet
path = build_word_path("אבגד")
print(path.area())

# Render the immutable Anasphere — every 10th point, colored by Hebrew letter
scene = render_anasphere(sphere, display_stride=10)
scene.show(aspect_ratio=1)
```

---

## FastAPI GUI Server — API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | SPA `index.html` |
| `/api/health` | GET | `{"status":"ok","binary_exists":true}` |
| `/api/jobs` | POST | Create + queue a pipeline job; returns `{"job_id":"...","status":"queued"}` |
| `/ws/jobs/{job_id}` | WebSocket | Stream NDJSON pipeline events; emits `keys_ready` when blueprint keys are available |
| `/api/jobs/{job_id}` | GET | Poll job status, result, `key_file`, and `key_record_count` |
| `/api/jobs/{job_id}/keys` | GET | Return full `keys.json` as inline JSON |
| `/api/jobs/{job_id}/keys/download` | GET | Download `keys.json` as a file attachment |
| `/static/*` | GET | Static assets (JS, CSS, pre-built WASM) |

### Blueprint keys JSON schema

```json
{
  "job_id": "...",
  "generated_at": "2024-01-01T00:00:00+00:00",
  "record_count": 42,
  "lossless_guarantee": "Algorithm + Degree Sequence + Derangement + Shadow Distance = Original Structure. ...",
  "keys": [
    {
      "fragment_id": 1,
      "source_type": "json",
      "node_state": "primary",
      "score": 0.5,
      "key": "alpha",
      "raw_length": 32,
      "degree_sequence": [3, 2, 2, 1],
      "derangement": [1, 2, 3, 4, 0],
      "shadow_distance": 0,
      "lossless_guarantee": "Algorithm + Degree Sequence + Derangement + Shadow Distance = Original Structure"
    }
  ]
}
```

`shadow_distance = 0` means the record's key bytes already form a perfect graphic
sequence.  `shadow_distance > 0` records the exact L1 deviation — the block was not
graphic and the deviation is preserved losslessly.

### POST /api/jobs — multipart/form-data fields

| Field | Type | Default | Description |
|---|---|---|---|
| `files` | `UploadFile[]` | required | One or more data files (all formats accepted) |
| `mmap_size` | `int` | `67108864` | mmap file size in bytes (64 MiB) |
| `queue_capacity` | `int` | `4096` | FIFO queue capacity |
| `primary_threshold` | `float` | `1.0` | Scores ≤ threshold → Primary; scores > threshold → Shadow |
