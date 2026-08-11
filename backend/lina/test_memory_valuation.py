"""Phase A — MPS value mechanics: MemoryDial and geometric_significance.

Pure logic tests — no database, no services. The dial is the add/subtract
mechanism of the valuation; geometric_significance is the value engine's
direct funding link to memory formation (MPS architecture §4).
"""
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import pytest  # noqa: E402

from value_engine import MemoryDial, geometric_significance  # noqa: E402


class TestMemoryDial:
    """The add/subtract dial: bounded deltas, absolute floors."""

    def test_clamp_upper(self):
        assert MemoryDial.clamp_delta(5.0) == 3.0

    def test_clamp_lower(self):
        assert MemoryDial.clamp_delta(-5.0) == -3.0

    def test_clamp_mid(self):
        assert MemoryDial.clamp_delta(1.5) == 1.5

    def test_adjust_within_bounds(self):
        assert MemoryDial.adjust(6.0, 2.0) == 8.0

    def test_adjust_bounded_upper(self):
        assert MemoryDial.adjust(6.0, 9.0) == 9.0

    def test_adjust_bounded_lower(self):
        assert MemoryDial.adjust(6.0, -9.0) == 3.0

    def test_floor_enforced(self):
        # An item at the retention line cannot be devalued below it.
        assert MemoryDial.adjust(5.0, -3.0, floor=5.0) == 5.0

    def test_floor_default_decay(self):
        # Without a floor, decay to zero is allowed (purge territory).
        assert MemoryDial.adjust(2.0, -3.0) == 0.0

    def test_must_keep_immovable(self):
        # Floor equals the score: a must-keep at 10 stays at 10.
        assert MemoryDial.adjust(10.0, -3.0, floor=10.0) == 10.0

    def test_dial_never_breaks_the_floor(self):
        # Even a maximum subtraction cannot push below the floor.
        for start in (3.0, 5.0, 7.0, 10.0):
            assert MemoryDial.adjust(start, -3.0, floor=5.0) >= 5.0


class TestGeometricSignificance:
    """The geometric funding factor: boundary proximity + correction + zone."""

    def test_center_is_low(self):
        assert geometric_significance(alignment_score=1.0) == pytest.approx(0.0)

    def test_boundary_is_high(self):
        assert geometric_significance(alignment_score=0.0) == pytest.approx(10.0)

    def test_midpoint(self):
        assert geometric_significance(alignment_score=0.5) == pytest.approx(5.0)

    def test_none_score_is_zero(self):
        assert geometric_significance(alignment_score=None) == pytest.approx(0.0)

    def test_correction_bonus(self):
        assert geometric_significance(alignment_score=0.5, was_corrected=True) == pytest.approx(7.0)

    def test_zone_bonus(self):
        assert geometric_significance(alignment_score=0.8, zone="violation") == pytest.approx(3.0)

    def test_capped_at_ten(self):
        assert geometric_significance(
            alignment_score=0.0, was_corrected=True, zone="violation"
        ) == pytest.approx(10.0)

    def test_acceptable_variance_counts(self):
        assert geometric_significance(alignment_score=0.7, zone="acceptable_variance") == pytest.approx(4.0)

    def test_aligned_zone_no_bonus(self):
        assert geometric_significance(alignment_score=0.7, zone="aligned") == pytest.approx(3.0)
