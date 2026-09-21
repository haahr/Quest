"""Unit tests for Stage 2 Cardelli syntax and semantics alignment.

Tests:
1. Function call bindings with explicit type arguments (:Type, id(:Int 42), id(:Int)(42))
2. Function call bindings with lvalues and references (@a, @t.a, var(0))
3. Prefix monadic operators (not, extent, ordinal)
4. Listfix function application (sum of ... end, sum of(count init), array of :Type ...)
5. Type checking and validation for Stage 2 constructs
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.diagnostics import QuestTypeError
from quest.pipeline import compile_pipeline
from quest.runtime import QBool, QInt
from tests.python.helpers import eval_test_source, run_pipeline


class TestStage2Cardelli(unittest.TestCase):
    """Verifies Cardelli Typeful Programming §4 / §11 Stage 2 alignment."""

    def compile_quest(self, code: str) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
            bin_path = Path(f.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=False)
            proc = run_binary(bin_path)
            return proc
        finally:
            if bin_path.exists():
                bin_path.unlink()

    def test_var_param_identifier_interpreter_and_c(self):
        """Verifies passing @x to a var parameter in interpreter and C transpiler."""
        code = """
        let var x = 10;
        let inc(var n: Int): Ok = n := n + 1;
        inc(@x);
        x
        """
        self.assertEqual(eval_test_source(code), QInt(11))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("11 : Int", proc.stdout)

    def test_out_param_identifier_interpreter_and_c(self):
        """Verifies passing @x to an out parameter in interpreter and C transpiler."""
        code = """
        let var x = 0;
        let assign(out n: Int v: Int): Ok = n := v;
        assign(@x 42);
        x
        """
        self.assertEqual(eval_test_source(code), QInt(42))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_record_field_ref_interpreter_and_c(self):
        """Verifies passing @r.f to var parameter in interpreter and C transpiler."""
        code = """
        let r = record var f = 10 end;
        let inc(var n: Int): Ok = n := n + 1;
        inc(@r.f);
        r.f
        """
        self.assertEqual(eval_test_source(code), QInt(11))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("11 : Int", proc.stdout)

    def test_array_element_ref_interpreter_and_c(self):
        """Verifies passing @a[i] to var parameter in interpreter and C transpiler."""
        code = """
        let a = array of 10 20 30 end;
        let inc(var n: Int): Ok = n := n + 5;
        inc(@a[1]);
        a[1]
        """
        self.assertEqual(eval_test_source(code), QInt(25))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("25 : Int", proc.stdout)

    def test_var_cell_temporary_interpreter_and_c(self):
        """Verifies passing var(e) temporary cell to var parameter."""
        code = """
        let addFive(var n: Int): Int = begin
            n := n + 5;
            n
        end;
        addFive(var(10))
        """
        self.assertEqual(eval_test_source(code), QInt(15))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_pointer_forwarding_interpreter_and_c(self):
        """Verifies forwarding an existing pointer parameter (@y) to another callee."""
        code = """
        let inc(var x: Int): Ok = x := x + 1;
        let incTwice(var y: Int): Ok = begin
            inc(@y);
            inc(@y);
            ok
        end;
        let var a = 0;
        incTwice(@a);
        a
        """
        self.assertEqual(eval_test_source(code), QInt(2))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("2 : Int", proc.stdout)

    def test_chained_nested_path_ref_interpreter_and_c(self):
        """Verifies chained path expression @outer.mid.val to var parameter."""
        code = """
        let inner = record var val = 1 end;
        let outer = record var mid = inner end;
        let inc(var x: Int): Ok = x := x + 10;
        inc(@outer.mid.val);
        outer.mid.val
        """
        self.assertEqual(eval_test_source(code), QInt(11))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("11 : Int", proc.stdout)

    def test_top_level_var_in_closure_allowed(self):
        """Verifies top-level module var variable captured in closure is allowed."""
        code = """
        let var g = 10;
        let readG(dummy: Int): Int = begin
            let get = fun(d: Int): Int g;
            get(0)
        end;
        readG(0)
        """
        self.assertEqual(eval_test_source(code), QInt(10))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("10 : Int", proc.stdout)

    def test_monadic_not_prefix_without_parentheses_interpreter_and_c(self):
        """Verifies not without parentheses in interpreter and C transpiler."""
        code = """
        let a = not true;
        let b = not false;
        let c = not not true;
        let d = not {false \/ true};
        a orif b
        """
        self.assertEqual(eval_test_source(code), QBool(True))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("true : Bool", proc.stdout)

    def test_monadic_extent_prefix_without_parentheses_interpreter_and_c(self):
        """Verifies extent without parentheses in interpreter and C transpiler."""
        code = """
        let arr = array of 10 20 30 40 end;
        let l1 = extent arr;
        let l2 = extent array of 1 2 3 end;
        l1 + l2
        """
        self.assertEqual(eval_test_source(code), QInt(7))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("7 : Int", proc.stdout)

    def test_monadic_ordinal_prefix_without_parentheses_interpreter_and_c(self):
        """Verifies ordinal without parentheses in interpreter and C transpiler."""
        code = """
        Let Choice = Option a b c end;
        let cB = option b of Choice end;
        let cC = option c of Choice end;
        let ordB = ordinal cB;
        let ordC = ordinal cC;
        ordB + ordC
        """
        self.assertEqual(eval_test_source(code), QInt(3))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("3 : Int", proc.stdout)

    def test_monadic_bare_operator_rejected_at_typecheck(self):
        """Verifies using monadic operator as bare value without operand is rejected."""
        for op in ("not", "extent", "ordinal"):
            res, _ = run_pipeline(f"let f = {op};")
            self.assertFalse(res.success)
            self.assertTrue(
                any(
                    f"Monadic operator '{op}' cannot be used as a value without an operand" in d.message
                    for d in res.diagnostics
                )
            )


    def test_polymorphic_out_var_specialization_c(self):
        """Verifies polymorphic out and var parameters with scalars and records in C."""
        code = """
        Let Point = Record x: Int y: Int end;
        let setVal(A::TYPE out dest: A src: A): Ok = dest := src;
        let var a = 0;
        setVal(:Int @a 42);

        let var p = record x = 1 y = 2 end;
        let pt = record x = 100 y = 200 end;
        setVal(:Point @p pt);
        a + p.x + p.y
        """
        self.assertEqual(eval_test_source(code), QInt(342))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("342 : Int", proc.stdout)

    def test_polymorphic_out_var_fallback_closure_c(self):
        """Verifies polymorphic out and var through closures using shadow cell writeback."""
        code = """
        Let Point = Record x: Int y: Int end;
        let swapPoly(A::TYPE var a: A var b: A): Ok =
            begin
                let tmp = a;
                a := b;
                b := tmp;
            end;
        let swapClo = swapPoly;
        let var r1 = record x = 10 y = 20 end;
        let var r2 = record x = 70 y = 80 end;
        swapClo(:Point @r1 @r2);
        r1.x + r2.x
        """
        self.assertEqual(eval_test_source(code), QInt(80))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("80 : Int", proc.stdout)

    def test_generic_tuple_return_with_record_c(self):
        """Verifies generic tuple returning 16-byte record fat pointer."""
        code = """
        Let Point = Record x: Int y: Int end;
        let pair(A::TYPE B::TYPE a: A b: B): Tuple first: A second: B end =
            tuple let first = a let second = b end;
        let pt = record x = 25 y = 35 end;
        let p = pair(:Point :Int pt 10);
        p.first.x + p.first.y + p.second
        """
        self.assertEqual(eval_test_source(code), QInt(70))
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("70 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
