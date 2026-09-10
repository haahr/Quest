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

    def test_call_bindings_explicit_type_arguments(self):
        """Verifies explicit type arguments :Type in polymorphic calls."""
        code = """
        let id(A::TYPE a: A): A = a;
        let v1 = id(:Int 42);
        let v2 = id(:Int)(43);
        let pair(A::TYPE B::TYPE a: A b: B): Tuple :A :B end = tuple a b end;
        let p = pair(:Int :String 100 "test");
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("v1"), QInt(42))
        self.assertEqual(ctx.runtime_env.lookup("v2"), QInt(43))

    def test_call_bindings_lvalues_and_references(self):
        """Verifies @a, @t.a, and var(e) in actual-parameter bindings."""
        code = """
        let var a = 0;
        let assign(out x: Int y: Int): Ok = x := y;
        assign(@a 7);

        let t = record var a = 10 end;
        let inc(out x: Int): Ok = x := x + 1;
        inc(@t.a);

        let addFive(var x: Int): Int =
          begin
            x := x + 5
            x
          end;
        let r = addFive(var(10));
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("a").deref(), QInt(7))
        t_rec = ctx.runtime_env.lookup("t")
        self.assertEqual(t_rec.get("a").deref(), QInt(11))
        self.assertEqual(ctx.runtime_env.lookup("r"), QInt(15))

    def test_call_bindings_polymorphic_out(self):
        """Verifies polymorphic function with out parameter and explicit type argument."""
        code = """
        let assignPoly(A::TYPE out x: A y: A): Ok = x := y;
        let var a = 0;
        assignPoly(:Int @a 99);
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("a").deref(), QInt(99))

    def test_monadic_not(self):
        """Verifies 'not' operator on boolean values."""
        code = """
        let a = not true;
        let b = not false;
        let c = not(true);
        let d = not not true;
        let e = {not true} andif false;
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("a"), QBool(False))
        self.assertEqual(ctx.runtime_env.lookup("b"), QBool(True))
        self.assertEqual(ctx.runtime_env.lookup("c"), QBool(False))
        self.assertEqual(ctx.runtime_env.lookup("d"), QBool(True))
        self.assertEqual(ctx.runtime_env.lookup("e"), QBool(False))

    def test_monadic_extent(self):
        """Verifies 'extent' operator on arrays."""
        code = """
        let arr = array of 10 20 30 40 end;
        let len1 = extent arr;
        let len2 = extent(arr);
        let len3 = extent(array of :Int end);
        let len4 = extent(array of(7 0));
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("len1"), QInt(4))
        self.assertEqual(ctx.runtime_env.lookup("len2"), QInt(4))
        self.assertEqual(ctx.runtime_env.lookup("len3"), QInt(0))
        self.assertEqual(ctx.runtime_env.lookup("len4"), QInt(7))

    def test_monadic_ordinal(self):
        """Verifies 'ordinal' operator on option values."""
        code = """
        Let Color = Option red green blue end;
        let c0 = option red of Color end;
        let c1 = option green of Color end;
        let c2 = option blue of Color end;
        let ord0 = ordinal c0;
        let ord1 = ordinal(c1);
        let ord2 = ordinal c2;
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("ord0"), QInt(0))
        self.assertEqual(ctx.runtime_env.lookup("ord1"), QInt(1))
        self.assertEqual(ctx.runtime_env.lookup("ord2"), QInt(2))

    def test_listfix_syntax(self):
        """Verifies listfix application (Cardelli §4.8 sum example and typed array of)."""
        code = """
        let sum(a: Array(Int)): Int =
          begin
            let var total = 0
            for i = 0 upto extent(a) - 1 do
              total := total + a[i]
            end
            total
          end;

        let s1 = sum of 0 1 2 3 4 end;
        let s2 = sum of(5 1);
        let s3 = sum of :Int 10 20 30 end;
        """
        res, ctx = run_pipeline(code)
        self.assertTrue(res.success, f"Diagnostics: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("s1"), QInt(10))
        self.assertEqual(ctx.runtime_env.lookup("s2"), QInt(5))
        self.assertEqual(ctx.runtime_env.lookup("s3"), QInt(60))

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
