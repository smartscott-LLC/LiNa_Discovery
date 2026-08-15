from __future__ import annotations

import json
import math
import mmap
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator, Sequence

from sage.all import Integer, RealNumber, SymmetricGroup, cos, pi, sin, sqrt, vector
from sage.combinat.degree_sequences import DegreeSequences
from sage.combinat.words.paths import WordPaths
from sage.plot.plot3d.shapes import Sphere


@dataclass(frozen=True)
class HebrewLetter:
    symbol: str
    name: str
    literal: str
    pictorial: str
    numeric: int


HEBREW_ALPHABET: tuple[HebrewLetter, ...] = (
    HebrewLetter("א", "Aleph", "ox", "strength/leader", 1),
    HebrewLetter("ב", "Bet", "house", "household", 2),
    HebrewLetter("ג", "Gimel", "camel", "movement/provision", 3),
    HebrewLetter("ד", "Dalet", "door", "entry/path", 4),
    HebrewLetter("ה", "He", "window", "revelation/breath", 5),
    HebrewLetter("ו", "Vav", "hook", "connection", 6),
    HebrewLetter("ז", "Zayin", "weapon", "cut/separate", 7),
    HebrewLetter("ח", "Chet", "fence", "boundary/life", 8),
    HebrewLetter("ט", "Tet", "basket", "contain/coil", 9),
    HebrewLetter("י", "Yod", "hand", "work/act", 10),
    HebrewLetter("כ", "Kaf", "palm", "cover/open", 20),
    HebrewLetter("ל", "Lamed", "staff", "teach/direct", 30),
    HebrewLetter("מ", "Mem", "water", "flow/chaos", 40),
    HebrewLetter("נ", "Nun", "seed/fish", "continuity", 50),
    HebrewLetter("ס", "Samekh", "support", "uphold/protect", 60),
    HebrewLetter("ע", "Ayin", "eye", "watch/know", 70),
    HebrewLetter("פ", "Pe", "mouth", "speak/declare", 80),
    HebrewLetter("צ", "Tsadi", "hook/plant", "righteous trail", 90),
    HebrewLetter("ק", "Qof", "back of head", "horizon/cycle", 100),
    HebrewLetter("ר", "Resh", "head", "first/chief", 200),
    HebrewLetter("ש", "Shin", "tooth", "consume/transform", 300),
    HebrewLetter("ת", "Tav", "mark/sign", "covenant/seal", 400),
)


@dataclass(frozen=True)
class SpherePoint:
    index: int
    x: RealNumber
    y: RealNumber
    z: RealNumber
    letter: HebrewLetter


# ---------------------------------------------------------------------------
# Hebrew alphabet step vectors — one 3D unit vector per letter.
#
# Each vector points in the direction of the corresponding letter's Fibonacci
# position on a unit sphere (the same pole-first golden-angle spiral used by
# ImmutableAnasphere, but scaled to the 22-letter alphabet rather than the
# 2.2 M-point sphere).  Python math is used for the float arithmetic so the
# 22 vectors are computed cheaply; each component is wrapped in a Sage
# RealNumber so the vector lives in the passagemath type chain.
#
# These vectors are the required ``steps`` argument for WordPaths — without
# them, WordPaths has no built-in grid that supports a 22-symbol alphabet and
# would raise a ValueError.
# ---------------------------------------------------------------------------

def _compute_hebrew_step_vectors() -> list:
    """Return 22 Sage 3D vectors on a Fibonacci sphere, one per Hebrew letter."""
    _ga = math.pi * (3.0 - math.sqrt(5.0))  # golden angle in radians
    n = len(HEBREW_ALPHABET)
    result = []
    for i in range(n):
        y_f = 1.0 - 2.0 * i / (n - 1)
        radial_f = math.sqrt(max(0.0, 1.0 - y_f * y_f))
        theta_f = _ga * i
        x_f = math.cos(theta_f) * radial_f
        z_f = math.sin(theta_f) * radial_f
        result.append(vector([RealNumber(x_f), RealNumber(y_f), RealNumber(z_f)]))
    return result


# Module-level singletons — computed once on import.

#: 22 Fibonacci-sphere 3D step vectors, one per Hebrew letter.
HEBREW_STEP_VECTORS: list = _compute_hebrew_step_vectors()

#: Canonical WordPaths space for the 22 Hebrew letters with 3D Fibonacci steps.
#: Re-used by build_word_path() so the space is never rebuilt on repeated calls.
HEBREW_PATH_SPACE: WordPaths = WordPaths(
    alphabet="".join(h.symbol for h in HEBREW_ALPHABET),
    steps=HEBREW_STEP_VECTORS,
)


@dataclass(frozen=True)
class DegreeBlueprintKey:
    degree_sequence: tuple[int, ...]
    derangement: tuple[int, ...]
    shadow_distance: int

    def to_bytes(self) -> bytes:
        payload = {
            "degree_sequence": list(self.degree_sequence),
            "derangement": list(self.derangement),
            "shadow_distance": self.shadow_distance,
        }
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > 0xFFFF_FFFF:
            raise ValueError("encoded blueprint is too large")
        return len(encoded).to_bytes(4, "little") + encoded

    @staticmethod
    def from_bytes(blob: bytes) -> "DegreeBlueprintKey":
        if len(blob) < 4:
            raise ValueError("blueprint payload too small")
        size = int.from_bytes(blob[:4], "little")
        if len(blob) < 4 + size:
            raise ValueError("truncated blueprint payload")
        payload = json.loads(blob[4 : 4 + size].decode("utf-8"))
        return DegreeBlueprintKey(
            degree_sequence=tuple(int(v) for v in payload["degree_sequence"]),
            derangement=tuple(int(v) for v in payload["derangement"]),
            shadow_distance=int(payload["shadow_distance"]),
        )


class ImmutableAnasphere:
    """
    Deterministic 7-inch sphere model with 2.2M Fibonacci points anchored at a pole.

    The canonical geometric reference is a passagemath Sphere object
    (sage.plot.plot3d.shapes.Sphere) of radius 3.5 inches, exposed via the
    sage_sphere property.  2 200 000 surface points are distributed by a
    Fibonacci spiral starting at the north pole (index 0).  Each point is
    addressed by one of the 22 Hebrew letters cycling through HEBREW_ALPHABET,
    giving every point three simultaneous referential axes: literal, pictorial,
    and numeric.
    """

    def __init__(self, total_points: int = 2_200_000, diameter_inches: float = 7.0) -> None:
        if total_points < 2:
            raise ValueError("total_points must be at least 2")
        if diameter_inches <= 0:
            raise ValueError("diameter_inches must be positive")
        self._total_points = Integer(total_points)
        self._radius = RealNumber(diameter_inches) / Integer(2)
        self._golden_angle = pi * (Integer(3) - sqrt(Integer(5)))
        self._sage_sphere: Sphere = Sphere(self._radius)

    @property
    def total_points(self) -> int:
        return int(self._total_points)

    @property
    def radius_inches(self) -> float:
        return float(self._radius)

    @property
    def sage_sphere(self) -> Sphere:
        """The passagemath Sphere geometry object (sage.plot.plot3d.shapes.Sphere)."""
        return self._sage_sphere

    def point_at(self, index: int) -> SpherePoint:
        i = Integer(index)
        if i < 0 or i >= self._total_points:
            raise IndexError("sphere point index out of range")

        # Pole-first Fibonacci sphere
        y = Integer(1) - (Integer(2) * i) / (self._total_points - Integer(1))
        zero = RealNumber(0)
        radial = sqrt(max(zero, Integer(1) - y * y))
        theta = self._golden_angle * i
        x = self._radius * cos(theta) * radial
        z = self._radius * sin(theta) * radial
        y_scaled = self._radius * y

        letter = HEBREW_ALPHABET[int(i % Integer(len(HEBREW_ALPHABET)))]
        return SpherePoint(index=int(i), x=x, y=y_scaled, z=z, letter=letter)

    def iter_points(self, start: int = 0, stop: int | None = None) -> Iterator[SpherePoint]:
        begin = Integer(start)
        end = self._total_points if stop is None else Integer(stop)
        if begin < 0 or begin > self._total_points:
            raise ValueError("start is out of range")
        if end < begin or end > self._total_points:
            raise ValueError("stop is out of range")
        for i in range(int(begin), int(end)):
            yield self.point_at(i)


class DegreeSequenceCodec:
    """
    Builds deterministic topological blueprints from byte blocks using
    passagemath DegreeSequences for Erdős-Gallai validation and enumeration.

    Pipeline:
      1. degree_sequence_from_block  — extract the block's adjacency degree sequence.
      2. nearest_graphic_sequence    — validate via DegreeSequences(n); if not graphic,
                                       enumerate to find the nearest valid sequence and
                                       record the L1 distance as shadow_distance.
      3. havel_hakimi_realization    — deterministically build the graph (forward pass).
      4. deterministic_derangement   — cyclic permutation that maps data positions to
                                       graph vertices (validated by Sage SymmetricGroup).
      5. reconstruct_edges           — reverse pass: given degree_sequence + derangement,
                                       rebuild the original edge set without storing edges.
    """

    @staticmethod
    def degree_sequence_from_block(block: bytes) -> tuple[int, ...]:
        if not block:
            return tuple()

        vertices = sorted(set(block))
        index = {v: i for i, v in enumerate(vertices)}
        edge_set: set[tuple[int, int]] = set()
        for left, right in zip(block, block[1:]):
            a = index[left]
            b = index[right]
            if a != b:
                edge_set.add((a, b) if a < b else (b, a))

        degrees = [0] * len(vertices)
        for a, b in edge_set:
            degrees[a] += 1
            degrees[b] += 1

        return tuple(sorted(degrees, reverse=True))

    @staticmethod
    def is_graphic(sequence: Sequence[int]) -> bool:
        """
        Return True if sequence is a valid graphic degree sequence.
        Uses passagemath DegreeSequences membership, which implements Erdős-Gallai
        internally, rather than a hand-rolled loop.
        """
        deg = sorted([int(v) for v in sequence if int(v) > 0], reverse=True)
        if not deg:
            return True
        return deg in DegreeSequences(len(deg))

    @staticmethod
    def _erdos_gallai_repair(deg: list[int]) -> tuple[list[int], int]:
        """
        Repair a non-graphic degree sequence using greedy Erdős-Gallai fixing.

        Operates on the **full original sequence** — no truncation, no bucketing,
        no information collapsed.  Runs in O(n²) time (the degree sum strictly
        decreases on every iteration, so the loop is bounded by the initial sum).

        Two kinds of fix are applied in each pass:

        1. **Parity**: a simple graph's degree sum must be even.  Reduce the
           largest degree by 1 (large degrees are also the primary source of
           Erdős-Gallai violations, so this fix does double duty).

        2. **Erdős-Gallai violation**: for the first violated prefix of length k,
           reduce the k largest degrees by the minimum total (excess) required to
           satisfy the condition, taking from the largest first.

        The cumulative total of all reductions is the returned ``l1_distance``.
        This becomes ``shadow_distance`` in the ``DegreeBlueprintKey`` — a
        faithful fingerprint of exactly how far the raw block's adjacency
        structure deviates from a realizable graph.  It is zero if and only if
        the input is already graphic, and is always computed over the unmodified
        original sequence length.
        """
        d = sorted(deg, reverse=True)
        n = len(d)
        edits = 0

        # Each iteration reduces the degree sum by at least 1, so this loop
        # terminates in at most initial_sum + 2 steps.
        for _ in range(sum(d) + 2):
            d.sort(reverse=True)

            # ── Parity fix ────────────────────────────────────────────────────
            # Reduce the largest degree by 1: fixes parity with the smallest
            # possible disruption to EG feasibility.
            if sum(d) % 2 != 0:
                d[0] -= 1
                edits += 1
                continue

            # ── Erdős-Gallai fix ──────────────────────────────────────────────
            # Find the first violated condition and remove the minimum excess.
            violated = False
            for k in range(1, n + 1):
                lhs = sum(d[:k])
                rhs = k * (k - 1) + sum(min(d[i], k) for i in range(k, n))
                if lhs > rhs:
                    excess = lhs - rhs
                    for j in range(k):
                        take = min(d[j], excess)
                        d[j] -= take
                        edits += take
                        excess -= take
                        if excess <= 0:
                            break
                    violated = True
                    break  # Re-sort and re-check from the beginning.

            if not violated:
                break  # All conditions satisfied — sequence is now graphic.

        return sorted(d, reverse=True), edits

    @classmethod
    def nearest_graphic_sequence(cls, sequence: Sequence[int]) -> tuple[tuple[int, ...], int]:
        """
        Return (nearest_graphic_sequence, l1_shadow_distance).

        Uses passagemath ``DegreeSequences(n)`` for the fast O(n) membership
        check (Erdős-Gallai internally).  If the sequence is already graphic,
        shadow_distance is 0 and no further work is done.

        For non-graphic sequences, ``_erdos_gallai_repair`` is called.  It
        works on the **full original sequence** (no truncation, no bucketing)
        and runs in O(n²) — polynomially bounded regardless of how many unique
        byte values a block contains.

        The returned shadow_distance is the total L1 edit applied to bring the
        original sequence to a realizable graph.  It is a faithful fingerprint
        of the raw block's adjacency structure: zero means the block is already
        realizable (Primary candidate); non-zero means it belongs to the Shadow
        partition and records exactly how far the block deviates from a valid
        graph.  The full original sequence length is always preserved — no
        information is collapsed before computing the fingerprint.
        """
        deg = sorted([int(v) for v in sequence if int(v) > 0], reverse=True)
        if not deg:
            return tuple(), 0
        ds = DegreeSequences(len(deg))
        if deg in ds:
            return tuple(deg), 0
        # Non-graphic: greedy Erdős-Gallai repair on the full sequence.
        repaired, shadow_distance = cls._erdos_gallai_repair(deg)
        return tuple(repaired), shadow_distance

    @staticmethod
    def havel_hakimi_realization(sequence: Sequence[int]) -> tuple[tuple[int, int], ...]:
        """
        Forward pass: deterministically realize a graphic degree sequence as an edge list.
        Because the algorithm is deterministic, the same sequence always produces the same
        graph — the edges never need to be stored alongside the key.
        """
        work = [(Integer(deg), Integer(i)) for i, deg in enumerate(sequence)]
        edges: list[tuple[int, int]] = []

        while True:
            work = [(deg, idx) for deg, idx in work if deg > 0]
            if not work:
                return tuple(sorted(edges))

            work.sort(reverse=True)
            deg, node = work.pop(0)
            if deg > Integer(len(work)):
                raise ValueError("sequence is not graphic by Havel-Hakimi")

            for i in range(int(deg)):
                next_deg, next_node = work[i]
                if next_deg <= 0:
                    raise ValueError("sequence is not graphic by Havel-Hakimi")
                work[i] = (next_deg - Integer(1), next_node)
                a = int(node)
                b = int(next_node)
                edges.append((a, b) if a < b else (b, a))

    @staticmethod
    def deterministic_derangement(size: int) -> tuple[int, ...]:
        """
        Return a cyclic permutation (i → i+1 mod n) as the fixed-point-free mapping
        from data positions to graph vertices.  Validated by Sage SymmetricGroup.
        """
        n = Integer(size)
        if n <= 1:
            return tuple()
        cyclic_permutation = tuple(((i + 1) % int(n)) for i in range(int(n)))
        group = SymmetricGroup(int(n))
        group([m + 1 for m in cyclic_permutation])  # Sage-side permutation validation
        return cyclic_permutation

    @classmethod
    def reconstruct_edges(cls, key: "DegreeBlueprintKey") -> tuple[tuple[int, int], ...]:
        """
        Reverse pass: reconstruct the original edge set from a DegreeBlueprintKey.

        Runs Havel-Hakimi deterministically on the stored degree_sequence to reproduce
        the graph, then maps each edge endpoint back through the inverse of the
        derangement to recover the original vertex labels.  No edges are stored in the
        key — the algorithm alone regenerates them.
        """
        edges = cls.havel_hakimi_realization(key.degree_sequence)
        if not key.derangement:
            return edges
        n = len(key.derangement)
        inverse = [0] * n
        for i, mapped in enumerate(key.derangement):
            inverse[mapped] = i
        reconstructed: set[tuple[int, int]] = set()
        for a, b in edges:
            if a < n and b < n:
                ra, rb = inverse[a], inverse[b]
                reconstructed.add((ra, rb) if ra < rb else (rb, ra))
        return tuple(sorted(reconstructed))

    @classmethod
    def blueprint_key_from_block(cls, block: bytes) -> "DegreeBlueprintKey":
        """
        Derive a lossless DegreeBlueprintKey from a raw byte block.

        Non-graphic degree sequences are handled gracefully: nearest_graphic_sequence
        finds the closest valid sequence via DegreeSequences enumeration and records
        the L1 deviation as shadow_distance (the "distance to a perfect graphic
        sequence" described in the spec).  The result is never rejected — non-graphic
        blocks simply carry a non-zero shadow_distance.
        """
        raw_sequence = cls.degree_sequence_from_block(block)
        degree_sequence, shadow_distance = cls.nearest_graphic_sequence(raw_sequence)
        _ = cls.havel_hakimi_realization(degree_sequence)
        derangement = cls.deterministic_derangement(len(block))
        return DegreeBlueprintKey(
            degree_sequence=degree_sequence,
            derangement=derangement,
            shadow_distance=shadow_distance,
        )


def build_word_path(alphabet_word: str):
    """
    Build a word path over the 22-letter Hebrew alphabet on the Anasphere.

    The path space (``HEBREW_PATH_SPACE``) is a module-level singleton backed
    by 22 3D Fibonacci-sphere step vectors (``HEBREW_STEP_VECTORS``), one per
    Hebrew letter.  Each step moves in the unit-sphere direction of that
    letter's Fibonacci position — the same pole-first golden-angle spiral used
    by ``ImmutableAnasphere`` — so every word path traces a geometrically
    meaningful route on the sphere surface.

    The path space is constructed once and reused for all calls, so calling
    this function repeatedly is cheap (only the element creation varies).

    Args:
        alphabet_word: A string of Hebrew letter symbols drawn from
            ``HEBREW_ALPHABET`` (e.g. ``"אבגד"``).  Each character must be
            one of the 22 symbols; an unknown symbol raises ``ValueError``.

    Returns:
        A passagemath ``FiniteWordPath_3d`` instance for the given word.
        The full API is documented in ``WORD_PATH_REFERENCE.md``.  Key methods:

        **Geometry (FiniteWordPath_all / FiniteWordPath_3d)**

        - ``start_point()``              — always ``(0, 0, 0)`` (origin on the sphere)
        - ``end_point()``                — 3D coordinate where the path terminates
        - ``directive_vector()``         — net displacement vector (end − start);
                                           its magnitude encodes the total deviation
                                           from the sphere origin
        - ``points(include_last=True)``  — iterator of all waypoints as 3D coordinates
        - ``is_closed()``                — ``True`` if ``end_point() == start_point()``;
                                           primary (graphic) paths tend toward closure
        - ``is_simple()``                — ``True`` if all visited points are distinct
                                           (no self-intersection on the sphere surface)

        **3D-specific projection (FiniteWordPath_3d)**

        - ``plot_projection(v=None, ...)`` — project the path onto the plane
                                             orthogonal to *v* (defaults to the
                                             directive vector); produces a 2D/3D
                                             ``Graphics`` object suitable for
                                             visualising the shadow manifold
        - ``projected_path(v=None, ring=None)`` — return the projected word path
                                                   in the orthogonal subspace
        - ``projected_point_iterator(v=None, ring=None)`` — iterator of projected
                                                             2D coordinates; useful
                                                             for lightweight shadow
                                                             traversal without plotting

        **Export**

        - ``plot(...)``             — 3D ``Graphics3d`` object of the sphere path
        - ``tikz_trajectory()``     — LaTeX/TikZ string of the path trajectory

        **Word combinatorics (inherited from FiniteWord)**

        - ``crochemore_factorization()`` — Lyndon factorisation of the word
        - ``is_palindrome()``            — palindrome test
        - ``len()``                      — number of steps (= number of letters)

    See ``WORD_PATH_REFERENCE.md`` for the complete ``FiniteWordPath_all``,
    ``FiniteWordPath_3d``, and ``FiniteWordPath_square_grid`` API reference.
    """
    return HEBREW_PATH_SPACE(alphabet_word)


def word_path_from_blueprint(key: "DegreeBlueprintKey"):
    """
    Map a ``DegreeBlueprintKey`` to a ``FiniteWordPath_3d`` on the Anasphere.

    Each entry in the blueprint's ``derangement`` tuple is a vertex index from
    the Havel-Hakimi graph realisation.  Vertices are assigned Hebrew letters
    by their position modulo 22 (the same cyclic mapping used by
    ``ImmutableAnasphere``).  The derangement sequence then determines the
    order in which those letter-steps are walked on the Fibonacci sphere.

    The resulting path is a first-class ``FiniteWordPath_3d`` object; every
    method in ``WORD_PATH_REFERENCE.md`` is available directly on it:

    - ``end_point()``          — 3D sphere coordinate where the blueprint's
                                 graph walk terminates
    - ``directive_vector()``   — net displacement; for shadow blueprints
                                 (``shadow_distance > 0``) this vector is
                                 typically non-zero, encoding the geometric
                                 "distance to the primary manifold"
    - ``is_closed()``          — ``True`` if the walk returns to the sphere
                                 origin; graphic blueprints (``shadow_distance
                                 == 0``) are more likely to yield closed paths
    - ``is_simple()``          — ``True`` if no two visited sphere positions
                                 coincide; self-intersection mirrors the
                                 non-graphicness of the underlying block
    - ``plot_projection(v)``   — project the shadow path onto the plane
                                 orthogonal to *v* (defaults to
                                 ``directive_vector()``); produces a 2D shadow
                                 image of the block's deviation on the sphere
    - ``projected_path(v)``    — the shadow as a lower-dimensional word path
    - ``plot()``                — 3D ``Graphics3d`` visualisation on the sphere
    - ``tikz_trajectory()``    — LaTeX/TikZ export of the path

    Args:
        key: A ``DegreeBlueprintKey`` as returned by
             ``DegreeSequenceCodec.blueprint_key_from_block``.

    Returns:
        A ``FiniteWordPath_3d`` instance whose length equals
        ``len(key.derangement)``.  Returns an empty path for empty blueprints.
    """
    if not key.derangement:
        return HEBREW_PATH_SPACE("")
    symbols = "".join(
        HEBREW_ALPHABET[key.derangement[i] % len(HEBREW_ALPHABET)].symbol
        for i in range(len(key.derangement))
    )
    return HEBREW_PATH_SPACE(symbols)


class IPCMmapBridge:
    """
    Shared-memory bridge for Rust/Python key exchange over mmap.
    """

    def __init__(self, path: str | Path, size: int) -> None:
        self._handle: IO[bytes] | None = None
        self._mm: mmap.mmap | None = None
        if size < 8:
            raise ValueError("size must be at least 8 bytes")
        self.path = Path(path)
        self.size = size

    def _ensure_open(self) -> None:
        if self._handle is not None and self._mm is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._handle = self.path.open("r+b")
        self._handle.truncate(self.size)
        self._mm = mmap.mmap(self._handle.fileno(), self.size, access=mmap.ACCESS_WRITE)

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "IPCMmapBridge":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def write(self, offset: int, payload: bytes) -> None:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        end = offset + len(payload)
        if end > self.size:
            raise ValueError("payload exceeds mmap bounds")
        self._ensure_open()
        assert self._mm is not None
        self._mm[offset:end] = payload
        self._mm.flush()

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("offset and size must be non-negative")
        end = offset + size
        if end > self.size:
            raise ValueError("read exceeds mmap bounds")
        self._ensure_open()
        assert self._mm is not None
        return bytes(self._mm[offset:end])

    def write_blueprint(self, offset: int, key: DegreeBlueprintKey) -> None:
        self.write(offset, key.to_bytes())

    def read_blueprint(self, offset: int) -> DegreeBlueprintKey:
        header = self.read(offset, 4)
        size = int.from_bytes(header, "little")
        return DegreeBlueprintKey.from_bytes(header + self.read(offset + 4, size))
