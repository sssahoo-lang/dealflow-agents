"""The percentile math behind the lag benchmark's p50/p99 numbers.

Kept as its own test because a benchmark script that isn't run in CI (it needs
a live Java consumer to measure anything) still has one part that's a pure
function -- and a wrong percentile calculation would make every number in
docs/benchmarks.md wrong in a way nothing else would catch.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench_outbox_lag import percentile  # noqa: E402


def test_p50_of_an_odd_length_list_is_the_middle_value():
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0


def test_p0_and_p100_are_the_extremes():
    values = [5.0, 1.0, 9.0, 3.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 9.0


def test_interpolates_between_the_two_closest_ranks():
    # Matches numpy.percentile's default (linear) convention: rank = p/100 *
    # (n-1). For [0, 10] at p=25, rank=0.25 -> 0 + 0.25*(10-0) = 2.5.
    assert percentile([0.0, 10.0], 25) == pytest.approx(2.5)


def test_a_single_value_is_every_percentile():
    assert percentile([42.0], 1) == 42.0
    assert percentile([42.0], 99) == 42.0


def test_input_order_does_not_matter():
    ordered = list(range(100))
    import random

    shuffled = ordered[:]
    random.Random(7).shuffle(shuffled)
    assert percentile(shuffled, 99) == percentile([float(x) for x in ordered], 99)


def test_empty_sequence_is_rejected_rather_than_silently_producing_nan():
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


@pytest.mark.parametrize("bad_p", [-1, 100.1, 101])
def test_percentile_out_of_range_is_rejected(bad_p):
    with pytest.raises(ValueError, match="within"):
        percentile([1.0, 2.0], bad_p)
