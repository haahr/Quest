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

    def test_write_only_out_parameter_rejected(self):
        """Verifies reading from an out parameter raises a TypeError at typecheck."""
        res_read, _ = run_pipeline("let f(out x: Int): Int = x;")
        self.assertFalse(res_read.success)
        self.assertTrue(
            any("Cannot read from write-only 'out' parameter 'x'" in d.message for d in res_read.diagnostics)
        )

        res_expr, _ = run_pipeline("let f(out x: Int): Ok = begin x := x + 1; ok end;")
        self.assertFalse(res_expr.success)
        self.assertTrue(
            any("Cannot read from write-only 'out' parameter 'x'" in d.message for d in res_expr.diagnostics)
        )

    def test_callsite_strict_at_syntax_rejected(self):
        """Verifies passing bare variable without @ to out/var parameter is rejected."""
        res, _ = run_pipeline("""
        let inc(var x: Int): Ok = x := x + 1;
        let var a = 0;
        inc(a);
        """)
        self.assertFalse(res.success)
        self.assertTrue(
            any("Argument to 'var' parameter must be passed with '@' or 'var(...)'" in d.message
                for d in res.diagnostics)
        )

    def test_closure_capture_of_var_or_out_parameter_rejected(self):
        """Verifies capturing out/var parameters in escaping closure is rejected."""
        res_var, _ = run_pipeline("""
        let f(var x: Int): Fun() Int =
            fun(): Int x;
        """)
        self.assertFalse(res_var.success)
        self.assertTrue(
            any("Cannot capture 'var' parameter 'x' in closure" in d.message for d in res_var.diagnostics)
        )

        res_out, _ = run_pipeline("""
        let f(out x: Int): Fun() Ok =
            fun(): Ok begin x := 1; ok end;
        """)
        self.assertFalse(res_out.success)
        self.assertTrue(
            any("Cannot capture 'out' parameter 'x' in closure" in d.message for d in res_out.diagnostics)
        )

    def test_closure_capture_of_local_var_stack_variable_rejected(self):
        """Verifies capturing local stack var variable in escaping closure is rejected."""
        res, _ = run_pipeline("""
        let f = fun() begin
            let var x = 10;
            fun(): Int x
        end;
        """)
        self.assertFalse(res.success)
        self.assertTrue(
            any("Cannot capture 'var' variable 'x' in closure" in d.message for d in res.diagnostics)
        )

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


if __name__ == "__main__":
    unittest.main()
