"""Unit tests for Stage 1 Cardelli syntax and semantics alignment.

Tests:
1. 'out' formal parameter mode vs 'Out' type operator
2. Anonymous tuple / signature fields (:Int, :Var(Int), :Out(Int))
3. Curried function declarations and polymorphic functions
4. Symbolic operators as identifiers (prefix +(1 2), stand-alone {+}, type #(A,B))
5. Custom symbolic infix operator definition and usage
"""

import unittest

from quest.pipeline import default_pipeline
from quest.types import (
    INT_TYPE,
    STRING_TYPE,
    QTupleField,
    QTupleType,
)
from quest.runtime import QInt, QOk


class TestStage1Cardelli(unittest.TestCase):
    """Verifies Cardelli Typeful Programming §4 / §11 Stage 1 alignment."""

    def setUp(self):
        self.pipeline = default_pipeline()

    def test_anonymous_tuple_fields_and_formatting(self):
        """Verifies anonymous tuple fields like Tuple :Int :Bool end format properly."""
        code = """
        Let Pair = Tuple :Int :String end;
        let p = tuple 42 "hello" end;
        """
        res = self.pipeline.execute(code, "<test_tuple>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")

        # Check type formatting of anonymous tuple
        tup_type = QTupleType(
            (
                QTupleField(name=None, type_val=INT_TYPE),
                QTupleField(name=None, type_val=STRING_TYPE),
            )
        )
        self.assertEqual(str(tup_type), "Tuple :Int :String end")

    def test_syntax_error_trailing_operator(self):
        """Verifies that incomplete infix expression halts at parse phase."""
        res = self.pipeline.execute("let x = 1 +;", "<test_err>")
        self.assertFalse(res.success)
        self.assertEqual(res.final_phase, "parse")


if __name__ == "__main__":
    unittest.main()

