"""Unit tests for Stage 3 Cardelli Option types alignment.

Tests:
1. Option extraction (!) producing a tuple with 0-based integer ordinal followed by payload
2. Option payload member selection from extraction result (opt!tag.field)
3. Option creation by tag with bindings (with let x=..., with v1 v2)
4. Option creation by ordinal (option ordinal(n) of T with ... end)
5. Validation that option ordinal creation requires all branches to have identical signatures
6. Runtime boundary checks for option ordinal creation
"""

import unittest

from tests.python.helpers import assert_pipeline_failure, assert_pipeline_success, run_pipeline
from quest.runtime import QBool, QInt, QString, qvalue_to_str


class TestStage3Cardelli(unittest.TestCase):
    """Verifies Cardelli Typeful Programming §4.5 Stage 3 Option alignment."""

    def test_option_assert_tag_mismatch_raises(self):
        """Verifies that opt!tag raises a runtime error on tag mismatch (bOption!a)."""
        code = """
        Let T = Option a b with x:Bool end end;
        let bOption = option b of T with let x = true end;
        let failed = bOption!a;
        """
        assert_pipeline_failure(code, expected_substr="Variant tag mismatch in '!'")

    def test_option_construction_by_ordinal_heterogeneous_rejected(self):

        """Verifies rejection of option ordinal construction when signatures differ."""
        code = """
        Let Mixed =
          Option
            a with x: Int end
            b with y: Bool end
          end;
        let bad = option ordinal(0) of Mixed with 10 end;
        """
        assert_pipeline_failure(
            code, expected_substr="Option construction by ordinal requires all branches to have identical"
        )

    def test_option_construction_by_ordinal_out_of_bounds(self):
        """Verifies that out of bounds ordinal at runtime raises an error."""
        code = """
        Let Light = Option red green end;
        let bad = option ordinal(5) of Light end;
        """
        assert_pipeline_failure(code, expected_substr="out of bounds")


if __name__ == "__main__":
    unittest.main()
