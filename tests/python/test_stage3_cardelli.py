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

    def test_cardelli_section_4_5_example(self):
        """Replicates and verifies Cardelli §4.5 Option types example verbatim."""
        code = """
        Let T =
          Option
            a
            b with x:Bool end
            c with x,y:String end
          end;
        let aOption = option a of T end;
        let bOption = option b of T with let x = true end;
        let cOption = option c of T with "xString" "yString" end;

        let checkAa: Bool = aOption?a;
        let checkBa: Bool = bOption?a;
        let checkBb: Bool = bOption?b;

        let extractB = bOption!b;
        let extractBx: Bool = bOption!b.x;

        let extractA = aOption!a;
        let extractC = cOption!c;
        let extractCx: String = extractC.x;
        let extractCy: String = extractC.y;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env

        self.assertEqual(env.lookup("checkAa"), QBool(True))
        self.assertEqual(env.lookup("checkBa"), QBool(False))
        self.assertEqual(env.lookup("checkBb"), QBool(True))

        # bOption!b should have ordinal 1 and x=true
        extractB = env.lookup("extractB")
        self.assertEqual(qvalue_to_str(extractB), "tuple 1 x=true end")
        self.assertEqual(env.lookup("extractBx"), QBool(True))

        # aOption!a should have ordinal 0 and no payload
        extractA = env.lookup("extractA")
        self.assertEqual(qvalue_to_str(extractA), "tuple 0 end")

        # cOption!c should have ordinal 2 and x, y strings
        extractC = env.lookup("extractC")
        self.assertEqual(qvalue_to_str(extractC), 'tuple 2 x="xString" y="yString" end')
        self.assertEqual(env.lookup("extractCx"), QString("xString"))
        self.assertEqual(env.lookup("extractCy"), QString("yString"))

    def test_option_assert_tag_mismatch_raises(self):
        """Verifies that opt!tag raises a runtime error on tag mismatch (bOption!a)."""
        code = """
        Let T = Option a b with x:Bool end end;
        let bOption = option b of T with let x = true end;
        let failed = bOption!a;
        """
        assert_pipeline_failure(code, expected_substr="Variant tag mismatch in '!'")

    def test_option_construction_by_ordinal_homogeneous(self):
        """Verifies option creation by ordinal when branches share the same signature."""
        code = """
        Let Direction =
          Option
            north with step: Int end
            south with step: Int end
            east with step: Int end
            west with step: Int end
          end;

        let d0 = option ordinal(0) of Direction with let step = 10 end;
        let d1 = option ordinal(1) of Direction with let step = 20 end;
        let idx = 2;
        let d2 = option ordinal(idx) of Direction with 30 end;

        let isNorth = d0?north;
        let isSouth = d1?south;
        let isEast = d2?east;

        let ord0 = ordinal d0;
        let ord1 = ordinal d1;
        let ord2 = ordinal d2;

        let step0 = d0!north.step;
        let step1 = d1!south.step;
        let step2 = d2!east.step;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env

        self.assertEqual(env.lookup("isNorth"), QBool(True))
        self.assertEqual(env.lookup("isSouth"), QBool(True))
        self.assertEqual(env.lookup("isEast"), QBool(True))

        self.assertEqual(env.lookup("ord0"), QInt(0))
        self.assertEqual(env.lookup("ord1"), QInt(1))
        self.assertEqual(env.lookup("ord2"), QInt(2))

        self.assertEqual(env.lookup("step0"), QInt(10))
        self.assertEqual(env.lookup("step1"), QInt(20))
        self.assertEqual(env.lookup("step2"), QInt(30))

    def test_option_construction_by_ordinal_no_payload(self):
        """Verifies option creation by ordinal when branches have no payload."""
        code = """
        Let Light = Option red yellow green end;
        let r = option ordinal(0) of Light end;
        let y = option ordinal(1) of Light end;
        let g = option ordinal(2) of Light end;

        let isR = r?red;
        let isY = y?yellow;
        let isG = g?green;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env

        self.assertEqual(env.lookup("isR"), QBool(True))
        self.assertEqual(env.lookup("isY"), QBool(True))
        self.assertEqual(env.lookup("isG"), QBool(True))

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
