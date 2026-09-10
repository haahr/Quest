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

    def test_out_parameter_mode_and_out_type(self):
        """Verifies 'out' parameter mode and 'Out' type operator can both be used."""
        code = """
        let f(o: Out(Int)): Ok = ok;
        let g(x: Int out y: Int): Ok = ok;
        """
        res = self.pipeline.execute(code, "<test_out>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")

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

    def test_anonymous_tuple_mut_syntax(self):
        """Verifies :Var(T), :Out(T), var :T, and out :T in signatures."""
        code = """
        Let MutTup1 = Tuple :Var(Int) :Out(String) end;
        Let MutTup2 = Tuple var :Int out :String end;
        """
        res = self.pipeline.execute(code, "<test_mut_tup>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")

    def test_curried_value_and_type_declarations(self):
        """Verifies curried functions and polymorphic functions desugar and evaluate."""
        code = """
        let add(x: Int)(y: Int): Int = x + y;
        let sum = add(10)(20);
        let id(A::TYPE a: A): A = a;
        let num = id(42);
        """
        res = self.pipeline.execute(code, "<test_currying>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        val = res.artifacts.get("interpret")
        self.assertEqual(val, QInt(42))

    def test_curried_higher_order_function(self):
        """Verifies let double(f(a:Int):Int)(a:Int):Int = f(f(a))."""
        code = """
        let double(f(a: Int): Int)(a: Int): Int = f(f(a));
        let inc(x: Int): Int = x + 1;
        let res = double(inc)(5);
        """
        res = self.pipeline.execute(code, "<test_double>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        val = res.artifacts.get("interpret")
        self.assertEqual(val, QInt(7))

    def test_symbolic_operator_as_function_prefix_and_braced(self):
        """Verifies prefix +(1 2) and stand-alone {+} evaluation."""
        code = """
        let a = +(10 20);
        let plus = {+};
        let b = plus(1 2);
        """
        res = self.pipeline.execute(code, "<test_symbolic>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        val = res.artifacts.get("interpret")
        self.assertEqual(val, QInt(3))

    def test_symbolic_type_operator_and_application(self):
        """Verifies Let #(A,B::TYPE)::TYPE = Tuple fst:A snd:B end and #(Int String)."""
        code = """
        Let #(A, B::TYPE)::TYPE = Tuple fst: A snd: B end;
        Let PairIntStr = #(Int String);
        Let BracedHash = {#};
        let p: PairIntStr = tuple 1 "one" end;
        """
        res = self.pipeline.execute(code, "<test_hash>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")

    def test_custom_infix_operator_definition(self):
        """Verifies custom infix operator declaration and application."""
        code = """
        let <+>(x: Int y: Int): Int = x + y + 100;
        let res = 10 <+> 20;
        """
        res = self.pipeline.execute(code, "<test_custom_infix>")
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        val = res.artifacts.get("interpret")
        self.assertEqual(val, QInt(130))

    def test_syntax_error_trailing_operator(self):
        """Verifies that incomplete infix expression halts at parse phase."""
        res = self.pipeline.execute("let x = 1 +;", "<test_err>")
        self.assertFalse(res.success)
        self.assertEqual(res.final_phase, "parse")


if __name__ == "__main__":
    unittest.main()
