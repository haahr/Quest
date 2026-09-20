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


if __name__ == "__main__":
    unittest.main()
