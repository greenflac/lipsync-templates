"""Gates for the arithmetic core of the identity verdict.

`cosine_distance` is the only number the identity gate ever compares against a
bar, so every bar in the product inherits its scale: 0 for the same vector, 1
for an unrelated one, 2 for the opposite one. Every expectation below is a
literal computed by hand, never imported from the module under test.
"""

import math
import unittest

from lipsync.identity_arcface import cosine_distance


class TheScaleIsZeroToTwo(unittest.TestCase):
    def test_identical_vectors_are_zero(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]), 0.0)
        self.assertEqual(cosine_distance([0.3, -0.4, 0.5], [0.3, -0.4, 0.5]), 0.0)

    def test_orthogonal_vectors_are_one(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0], [0.0, 1.0]), 1.0)
        self.assertEqual(cosine_distance([2.0, 0.0, 0.0], [0.0, 0.0, 7.0]), 1.0)

    def test_opposite_vectors_are_two(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0], [-1.0, 0.0]), 2.0)
        self.assertEqual(cosine_distance([0.6, 0.8], [-0.6, -0.8]), 2.0)

    def test_a_known_angle_lands_on_its_hand_computed_value(self) -> None:
        """45 degrees: 1 - cos(45) = 1 - 0.70710678... = 0.2929 at 4 places."""
        self.assertEqual(cosine_distance([1.0, 0.0], [1.0, 1.0]), 0.2929)

    def test_a_sixty_degree_angle_is_a_half(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0], [1.0, 3.0**0.5]), 0.5)


class LengthDoesNotChangeTheVerdict(unittest.TestCase):
    """Embeddings arrive normed, but the bar must not move if one is not."""

    def test_scaling_either_side_leaves_the_distance_alone(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0], [1000.0, 0.0]), 0.0)
        self.assertEqual(cosine_distance([0.001, 0.0], [1.0, 0.0]), 0.0)
        self.assertEqual(cosine_distance([3.0, 4.0], [30.0, 40.0]), 0.0)

    def test_scaling_does_not_move_a_middling_distance(self) -> None:
        self.assertEqual(cosine_distance([1.0, 0.0], [5.0, 5.0]), 0.2929)


class TheUnmeasurableInputSaysUnrelated(unittest.TestCase):
    """A zero vector carries no direction: it must not read as a match."""

    def test_a_zero_vector_is_one_not_zero(self) -> None:
        self.assertEqual(cosine_distance([0.0, 0.0, 0.0], [1.0, 0.0, 0.0]), 1.0)
        self.assertEqual(cosine_distance([1.0, 0.0, 0.0], [0.0, 0.0, 0.0]), 1.0)

    def test_two_zero_vectors_are_one_not_zero(self) -> None:
        self.assertEqual(cosine_distance([0.0, 0.0], [0.0, 0.0]), 1.0)


class TheOutputIsBounded(unittest.TestCase):
    def test_float_error_never_produces_a_negative_distance(self) -> None:
        """float64 puts the self-similarity of [0.1, 0.1, 0.3] at 1 + 2.2e-16,
        so 1 - sim is negative and rounds to -0.0, which the verdict note would
        print verbatim. `assertEqual(-0.0, 0.0)` is true, so the guard has to
        read the sign: this is the one input on which the clamp is observable at
        the function's 4-decimal resolution."""
        v = [0.1, 0.1, 0.3]
        got = cosine_distance(v, list(v))
        self.assertEqual(got, 0.0)
        self.assertEqual(math.copysign(1.0, got), 1.0, "distance is a negative zero")
        self.assertGreaterEqual(cosine_distance([1e-8, 1.0], [0.0, 1.0]), 0.0)

    def test_the_result_is_rounded_to_four_places(self) -> None:
        """0.0001 is the resolution every bar in the product is written at."""
        got = cosine_distance([1.0, 0.0], [1.0, 1.0])
        self.assertEqual(got, round(got, 4))
        self.assertIsInstance(got, float)


class TheInstrumentCanTellVectorsApart(unittest.TestCase):
    """Negative control: a metric that returns one number for everything passes
    every equality above by accident."""

    def test_three_different_pairs_give_three_different_numbers(self) -> None:
        near = cosine_distance([1.0, 0.0], [1.0, 0.1])
        mid = cosine_distance([1.0, 0.0], [1.0, 1.0])
        far = cosine_distance([1.0, 0.0], [0.0, 1.0])
        self.assertEqual(len({near, mid, far}), 3)
        self.assertLess(near, mid)
        self.assertLess(mid, far)


if __name__ == "__main__":
    unittest.main()
