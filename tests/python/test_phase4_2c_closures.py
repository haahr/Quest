"""Unit and integration tests for Phase 4.2c: Closures & Function Values."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import CompilerOptions, compile_pipeline


class TestPhase42cClosures(unittest.TestCase):
    """Tests C code generation and execution for first-class function values and closures."""

    def compile_quest(self, code: str, nogc: bool = False, echo: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        opts = CompilerOptions(echo=echo)
        res = pipeline.execute(code, "<test>", options=opts)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
            bin_path = Path(f.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=nogc)
            proc = run_binary(bin_path)
            return proc
        finally:
            if bin_path.exists():
                bin_path.unlink()

    def test_top_level_function_passed_as_value(self):
        """Tests passing a top-level function into a higher-order function via trampoline."""
        code = """
        let double(x: Int): Int = x + x;
        let apply(f: All(x: Int) Int x: Int): Int = f(x);
        let res = apply(double 21);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_non_capturing_lambda(self):
        """Tests a non-capturing lambda expression using a static closure singleton."""
        code = """
        let apply(f: All(x: Int) Int x: Int): Int = f(x);
        let res = apply(fun(x: Int): Int x * 3 14);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_capturing_closure_make_adder(self):
        """Tests a closure that captures a parameter from the enclosing function."""
        code = """
        let makeAdder(base: Int): All(x: Int) Int =
            fun(x: Int): Int base + x;
        let add100 = makeAdder(100);
        let res = add100(42);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("142 : Int", proc.stdout)

    def test_curried_multi_level_nested_closure(self):
        """Tests multi-level nested closures capturing variables from multiple lexical scopes."""
        code = """
        let f(a: Int): All(b: Int) All(c: Int) Int =
            fun(b: Int): All(c: Int) Int
                fun(c: Int): Int a + b + c;
        let r = f(10)(20)(12);
        r
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_closure_capturing_and_mutating_cells(self):
        """Tests closure capturing a mutable cell or variable."""
        code = """
        let var count = 10;
        let bump(delta: Int): Ok =
            begin
                count := count + delta;
                ok
            end;
        bump(5);
        bump(27);
        count
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_run_03_functions_closures_source(self):
        """Tests compiling and executing the canonical 03_functions_closures.quest file."""
        source_path = Path("tests/source/03_functions_closures.quest")
        self.assertTrue(source_path.exists())
        code = source_path.read_text()
        proc = self.compile_quest(code, echo=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_nogc_closures(self):
        """Verifies closures compile and run cleanly with --nogc."""
        code = """
        let adder(x: Int): All(y: Int) Int = fun(y: Int): Int x + y;
        let a = adder(30);
        a(12)
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
