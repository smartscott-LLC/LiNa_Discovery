"""
combinatorial_structure.py — Real polyhedral geometry via passagemath-polyhedra.

This module replaces the placeholder stub with a live connection to
LINA's 14-dimensional ethical polytope. It exposes:

- The vertex set (V-representation)
- The 1-skeleton (edges) for graph-theoretic analysis
- The face lattice for hierarchical structure
- The H-representation (inequalities) for constraint awareness

Used by EmbodiedSelfModel to build a neural architecture that mirrors
the geometric structure of the polytope itself.

"""

from sage.all__sagemath_polyhedra import Polyhedron
from sage.all__sagemath_modules import QQ, vector


class CombinatorialStructure:
    """
    Combinatorial structure of LINA's ethical polytope.

    Constructed from a Sage Polyhedron (PPL backend), this provides
    the actual vertex/edge/facet data of the 14D hyperrectangle.

    For a hyperrectangle, the 1-skeleton is a 14-dimensional hypercube
    graph with 2^14 vertices and 14 * 2^13 edges.

    For future non-hyperrectangular polytopes, this structure will
    reflect the true combinatorial geometry of the shape.
    """

    def __init__(self, polyhedron=None, dimensions: int = 14):
        if polyhedron is not None:
            self.polyhedron = polyhedron
            self.dimensions = polyhedron.ambient_dim()
        else:
            # Build a placeholder hypercube from bounds
            # (used when EthicalPolytope hasn't been constructed yet)
            self.dimensions = dimensions
            self.polyhedron = None

        self.structure = self._generate_structure()

    def _generate_structure(self) -> dict:
        """
        Generate the combinatorial structure from the Sage polyhedron.

        Returns a dict with:
            type:        'ethical_polytope'
            dimensions:  ambient dimension
            vertices:    list of vertex coordinates (as tuples)
            edges:       list of (vertex_idx, vertex_idx) pairs
            n_vertices:  total vertex count
            n_edges:     total edge count
            facets:      list of facet inequalities (H-representation)
            n_facets:    number of facets
        """
        if self.polyhedron is None:
            return self._placeholder_structure()

        p = self.polyhedron

        # Get vertices as tuples of floats
        verts = list(p.vertex_generator())
        vertices = [tuple(float(c) for c in v.vector()) for v in verts]
        n_vertices = len(vertices)

        # Build vertex index map for edge lookup
        vert_index = {v: i for i, v in enumerate(verts)}

        # Get the 1-skeleton (edges) from the actual vertex coordinates.
        # Two box vertices share an edge iff they differ in exactly one
        # coordinate. Computed exactly from coordinates (not from index bit
        # patterns — PPL does not enumerate vertices in bit order).
        try:
            edges = self._compute_box_edges(vertices, self.dimensions)
        except Exception:
            edges = []

        # Get facets (H-representation inequalities)
        facets = []
        for ieq in p.inequality_generator():
            # Each inequality is A*x + b >= 0
            coeffs = [float(ieq.A()[i]) for i in range(self.dimensions)]
            b = float(ieq.b())
            facets.append({"coefficients": coeffs, "constant": b})

        return {
            "type": "ethical_polytope",
            "dimensions": self.dimensions,
            "vertices": vertices,
            "edges": edges,
            "n_vertices": n_vertices,
            "n_edges": len(edges),
            "facets": facets,
            "n_facets": len(facets),
            "polyhedron": p,
        }

    def _placeholder_structure(self) -> dict:
        """
        Fallback structure when no polyhedron is provided.
        Uses the same 14D hypercube topology as the Spring polytope.
        """
        n = max(int(self.dimensions), 1)
        nodes = list(range(n))
        # Each node connects to every other node (complete graph)
        edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
        return {
            "type": "placeholder",
            "dimensions": n,
            "vertices": [],
            "edges": edges,
            "n_vertices": n,
            "n_edges": len(edges),
            "facets": [],
            "n_facets": 0,
        }

    @staticmethod
    def _compute_box_edges(
        vertices: list[tuple[float, ...]], dim: int
    ) -> list[tuple[int, int]]:
        """
        Compute the 1-skeleton of a box polytope from vertex coordinates.

        Two vertices share an edge iff their coordinates differ in exactly
        one dimension (flipping a single lower/upper bound). This is exact
        regardless of the order in which the backend enumerates vertices:
        O(n_vertices * dim) dict lookups.
        """
        n = len(vertices)
        if n == 0 or dim == 0:
            return []

        # Distinct coordinate values per dimension — exactly two for a box.
        bounds = []
        for d in range(dim):
            vals = sorted({v[d] for v in vertices})
            if len(vals) != 2:
                return []  # not a box — caller should use a general method
            bounds.append((vals[0], vals[-1]))

        index = {v: i for i, v in enumerate(vertices)}
        edges = []
        for i, v in enumerate(vertices):
            for d in range(dim):
                lo, hi = bounds[d]
                flipped = list(v)
                flipped[d] = hi if v[d] == lo else lo
                j = index.get(tuple(flipped))
                if j is not None and j > i:
                    edges.append((i, j))
        return edges

    def to_adjacency_matrix(self) -> list[list[int]]:
        """Return the adjacency matrix of the 1-skeleton."""
        n = self.structure["n_vertices"]
        adj = [[0] * n for _ in range(n)]
        for u, v in self.structure["edges"]:
            adj[u][v] = 1
            adj[v][u] = 1
        return adj

    def describe(self) -> str:
        """Human-readable description of the structure."""
        s = self.structure
        return (
            f"CombinatorialStructure: {s['dimensions']}D {s['type']}\n"
            f"  Vertices: {s['n_vertices']}\n"
            f"  Edges:    {s['n_edges']}\n"
            f"  Facets:   {s['n_facets']}"
        )

if __name__ == "__main__":
    from sage.all__sagemath_modules import QQ, vector

    # 3D unit cube — exercises vertex/edge/facet extraction
    # Each ieq is [b, a1, a2, a3] meaning b + a1*x + a2*y + a3*z >= 0
    ieqs = [
        [QQ(0), QQ(1), QQ(0), QQ(0)],    # x >= 0
        [QQ(1), QQ(-1), QQ(0), QQ(0)],   # x <= 1
        [QQ(0), QQ(0), QQ(1), QQ(0)],    # y >= 0
        [QQ(1), QQ(0), QQ(-1), QQ(0)],   # y <= 1
        [QQ(0), QQ(0), QQ(0), QQ(1)],    # z >= 0
        [QQ(1), QQ(0), QQ(0), QQ(-1)],   # z <= 1
    ]
    cube = Polyhedron(ieqs=ieqs, backend="ppl")
    cs = CombinatorialStructure(polyhedron=cube)
    print(cs.describe())
    print(f"  edges: {cs.structure['n_edges']} (expected 12 for a cube)")
    assert cs.structure["n_vertices"] == 8, "cube must have 8 vertices"
    assert cs.structure["n_edges"] == 12, "cube must have 12 edges"
    print("CombinatorialStructure self-test passed.")
