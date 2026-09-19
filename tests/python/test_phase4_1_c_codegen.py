"""Unit and integration tests for Phase 4.1 C Code Generation & Runtime."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import CompilerOptions, compile_pipeline
from quest_driver import run_driver


class TestPhase41Codegen(unittest.TestCase):
    """Tests C emitter, runtime foundation, host compilation, and CLI driver."""

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

    def test_pipeline_phases(self):
        """Verifies compile_pipeline registers the expected phases."""
        p = compile_pipeline()
        self.assertEqual(p.phase_names(), ["tokenize", "parse", "typecheck", "codegen_c"])

    def test_integer_arithmetic(self):
        """Tests integer operations: +, -, *, /, %, literal ~."""
        code = """
        let a = 10 + 5;
        let b = 10 - 3;
        let c = 4 * 6;
        let d = 20 / 4;
        let e = 17 % 5;
        let f = ~42;
        let sum = a + b + c + d + e + f;
        sum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("11 : Int", proc.stdout)

    def test_real_arithmetic(self):
        """Tests real operations: ++, --, ^^, //, literal ~."""
        code = """
        let a = 1.5 ++ 2.5;
        let b = 5.0 -- 1.25;
        let c = 2.0 ^^ 3.0;
        let d = 10.0 // 4.0;
        let e = ~2.5;
        let sum = a ++ b ++ c ++ d ++ e;
        sum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15.75 : Real", proc.stdout)

    def test_boolean_and_relations(self):
        """Tests booleans, relations (int and real), and andif."""
        code = """
        let eq = 10 is 10;
        let ne = 10 isnot 5;
        let lt = 3 < 7;
        let le = 3 <= 3;
        let gt = 5 > 2;
        let ge = 5 >= 5;
        let rlt = 1.0 << 2.0;
        let rgt = 2.0 >> 1.0;
        let b = eq andif {ne} andif {lt} andif {le} andif {gt} andif {ge} andif {rlt} andif {rgt};
        b
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("true : Bool", proc.stdout)

    def test_string_and_char(self):
        """Tests string concatenation and char literals."""
        code = """
        let ch = 'Z';
        let s = "Hello, " <> "world!";
        s
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("\"Hello, world!\" : String", proc.stdout)

    def test_mutable_variables(self):
        """Tests let var and assignment."""
        code = """
        let var acc = 0;
        acc := acc + 10;
        acc := acc + 5;
        acc
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_conditional_if(self):
        """Tests if-then-else expressions and statements."""
        code = """
        let x = if 10 > 5 then 100 else 200 end;
        let y = if false then 100 else 200 end;
        x + y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("300 : Int", proc.stdout)

    def test_while_loop(self):
        """Tests while-do-end loops."""
        code = """
        let var i = 1;
        let var sum = 0;
        while i <= 5 do
            sum := sum + i;
            i := i + 1;
        end;
        sum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_loop_and_exit(self):
        """Tests infinite loop with exit."""
        code = """
        let var k = 0;
        loop
            k := k + 1;
            if k is 10 then exit end;
        end;
        k
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("10 : Int", proc.stdout)

    def test_for_upto_and_downto(self):
        """Tests for upto and for downto loops."""
        code = """
        let var sum = 0;
        for i = 1 upto 4 do
            sum := sum + i;
        end;
        for j = 4 downto 1 do
            sum := sum + j;
        end;
        sum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("20 : Int", proc.stdout)

    def test_block_expression(self):
        """Tests begin ... end blocks."""
        code = """
        let r = begin
            let u = 7;
            let v = 6;
            u * v
        end;
        r
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_nogc_compilation(self):
        """Tests compilation with --nogc."""
        code = """
        let greeting = "Quest " <> "C Backend";
        greeting
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("\"Quest C Backend\" : String", proc.stdout)

    def test_nogc_functions(self):
        """Verifies function code compiles and runs with --nogc."""
        code = """
        let f(x: Int): Int = x + 10;
        f(5)
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_nogc_closures(self):
        """Verifies closures compile and run cleanly with --nogc."""
        code = """
        let makeAdder(x: Int)(y: Int): Int = x + y;
        let add10 = makeAdder(10);
        add10(5)
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("15 : Int", proc.stdout)

    def test_nogc_arrays(self):
        """Tests compiling and running array operations with --nogc."""
        code = """
        let arr = array of 1 2 3 end;
        arr[1]
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("2 : Int", proc.stdout)

    def test_divide_by_zero_runtime_error(self):
        """Tests divide by zero raises runtime error with exit code 1."""
        code = """
        let zero = 0;
        let bad = 42 / zero;
        bad
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: DivideByZero", proc.stderr)

    def test_cli_driver_compile_and_run(self):
        """Tests quest compile CLI end-to-end."""
        with tempfile.NamedTemporaryFile(suffix=".quest", mode="w", delete=False) as src_f:
            src_f.write("let x = 123; x\n")
            src_path = Path(src_f.name)

        bin_path = src_path.with_suffix(".bin")

        try:
            exit_code = run_driver(["compile", str(src_path), "-o", str(bin_path)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(bin_path.exists())

            proc = run_binary(bin_path)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("123 : Int", proc.stdout)
        finally:
            if src_path.exists():
                src_path.unlink()
            if bin_path.exists():
                bin_path.unlink()


if __name__ == "__main__":
    unittest.main()
