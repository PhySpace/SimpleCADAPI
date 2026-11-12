"""The quantizer behind geometry fingerprints must not split values that differ only by computation noise.

Issue #87: a body's fingerprint changed across a BREP round trip because two edge centers sat on a quantization boundary,
``(k + 0.5) * 1e-7`` mm, and the readback differed from the original by one or two units in the last place.
"""

from __future__ import annotations

import math
import random

import pytest

from simplecadapi.artifacts.geometry_interface import _q

TOL = 1.0e-7

# The two edge centers of the reporter's R02 body (issue #87): value before the readback, value after, as recorded in the
# issue.  Both pairs sit on a boundary and quantized to different integers (-33469081 / -33469082, -66530919 / -66530918).
ISSUE_PAIRS = [
    (-3.3469081499999995, -3.34690815),
    (-6.653091850000001, -6.653091849999999),
]


@pytest.mark.parametrize("before, after", ISSUE_PAIRS)
def test_values_from_the_issue_quantize_alike(before: float, after: float) -> None:
    assert _q(before, TOL) == _q(after, TOL)


def test_noise_around_a_boundary_never_splits_a_value() -> None:
    rng = random.Random(87)
    split = 0
    for _ in range(20000):
        magnitude = 10 ** rng.uniform(-3, 4)  # mm: a hair to ten metres
        k = int(magnitude / TOL)
        exact = (k + 0.5) * TOL * rng.choice((-1, 1))
        a, b = exact, exact
        for _ in range(rng.randint(0, 3)):  # up to three ulps of computation noise, each side
            a = math.nextafter(a, rng.choice((-math.inf, math.inf)))
            b = math.nextafter(b, rng.choice((-math.inf, math.inf)))
        split += _q(a, TOL) != _q(b, TOL)
    assert split == 0


def test_ordinary_values_quantize_as_before() -> None:
    """The snap window is far narrower than a quantum, so values away from a boundary keep their old integer.

    Fingerprints are stored in artifacts: a rule that moved many integers would invalidate them for no reason."""
    rng = random.Random(5)
    moved = 0
    for _ in range(50000):
        value = rng.uniform(-200.0, 200.0)
        moved += _q(value, TOL) != int(round(value / TOL))
    assert moved <= 5  # about 1e-5 of the values lie within the snap window of a boundary


def test_quantization_is_antisymmetric_and_exact_on_integers() -> None:
    for k in (0, 1, 7, 123456789):
        assert _q(k * TOL, TOL) == k
        assert _q(-k * TOL, TOL) == -k
