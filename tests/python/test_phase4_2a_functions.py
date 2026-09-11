"""Unit and integration tests for Phase 4.2a: Top-Level & Recursive Functions."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase42aFunctions(unittest.TestCase):
    """Tests direct C calling conventions, uncurried signatures, and recursion."""

    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
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

    def test_single_argument_function(self):
        """Tests a simple function with one scalar argument."""
        code = """
        let square(x: Int): Int = x * x;
        let res = square(7);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("49 : Int", proc.stdout)

    def test_multi_argument_function(self):
        """Tests a function with multiple uncurried arguments."""
        code = """
        let add3(a: Int b: Int c: Int): Int = a + b + c;
        let res = add3(10 20 30);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("60 : Int", proc.stdout)

    def test_curried_function_definition_and_call(self):
        """Tests a function defined with curried syntax and invoked curried."""
        code = """
        let sub(x: Int)(y: Int): Int = x - y;
        let res = sub(100)(42);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("58 : Int", proc.stdout)

    def test_self_recursion_factorial(self):
        """Tests self-recursive function (factorial)."""
        code = """
        let rec factorial(n: Int): Int =
            if n <= 1 then
                1
            else
                n * factorial(n - 1)
            end;
        let res = factorial(6);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("720 : Int", proc.stdout)

    def test_self_recursion_fibonacci(self):
        """Tests multiple self-recursive calls (fibonacci)."""
        code = """
        let rec fib(n: Int): Int =
            if n <= 0 then
                0
            elsif n == 1 then
                1
            else
                fib(n - 1) + fib(n - 2)
            end;
        let res = fib(10);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("55 : Int", proc.stdout)

    def test_ok_returning_function(self):
        """Tests function returning Ok (void in C) and mutating a top-level variable."""
        code = """
        let var count = 0;

        let increment(step: Int): Ok =
            begin
                count := count + step;
                ok
            end;

        let doWork(dummy: Int): Int =
            begin
                increment(5);
                increment(10);
                count
            end;

        let res = doWork(0);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_multiple_top_level_functions_calling_each_other(self):
        """Tests top-level functions calling earlier top-level functions."""
        code = """
        let square(x: Int): Int = x * x;
        let doubleVal(x: Int): Int = x + x;
        let combine(a: Int b: Int): Int = square(a) + doubleVal(b);
        let res = combine(5 3);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("31 : Int", proc.stdout)

    def test_real_char_string_functions(self):
        """Tests functions accepting and returning Real, Char, and String."""
        code = """
        let scale(x: Real factor: Real): Real = x ** factor;
        let greet(name: String): String = "Hello, " <> name;
        let choose(b: Bool): Char = if b then 'Y' else 'N' end;

        let r = scale(2.5 4.0);
        let s = greet("Quest");
        let c = choose(true);
        s
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"Hello, Quest" : String', proc.stdout)

    def test_nogc_compilation(self):
        """Verifies function code compiles and runs with --nogc."""
        code = """
        let rec fib(n: Int): Int =
            if n <= 1 then n else fib(n - 1) + fib(n - 2) end;
        fib(8)
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("21 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
