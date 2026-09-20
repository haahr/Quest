"""Unit tests for Stage 2 Cardelli syntax and semantics alignment.

Tests:
1. Function call bindings with explicit type arguments (:Type, id(:Int 42), id(:Int)(42))
2. Function call bindings with lvalues and references (@a, @t.a, var(0))
3. Prefix monadic operators (not, extent, ordinal)
4. Listfix function application (sum of ... end, sum of(count init), array of :Type ...)
5. Type checking and validation for Stage 2 constructs
"""

import unittest

from tests.python.helpers import run_pipeline
from quest.runtime import QBool, QInt


class TestStage2Cardelli(unittest.TestCase):
    """Verifies Cardelli Typeful Programming §4 / §11 Stage 2 alignment."""


    def test_monadic_type_errors(self):
        """Verifies typecheck errors for invalid operands to monadic operators."""
        # not expects Bool
        res, _ = run_pipeline("not 42;")
        self.assertFalse(res.success)

        # extent expects Array
        res, _ = run_pipeline("extent 42;")
        self.assertFalse(res.success)

        # ordinal expects Option
        res, _ = run_pipeline("ordinal 42;")
        self.assertFalse(res.success)


if __name__ == "__main__":
    unittest.main()
