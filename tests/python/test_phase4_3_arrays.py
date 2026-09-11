"""Unit and integration tests for Phase 4.3: Arrays & Strings."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import CompilerOptions, compile_pipeline


class TestPhase43Arrays(unittest.TestCase):
    """Tests C code generation and execution for Quest arrays and strings."""

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

    def test_array_literal_and_indexing(self):
        """Tests array of elements construction and 0-based indexing."""
        code = """
        let arr = array of 10 20 30 40 end;
        arr[0] + arr[1] + arr[2] + arr[3]
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("100 : Int", proc.stdout)

    def test_array_rep_and_size(self):
        """Tests array of(count init) repetition."""
        code = """
        let arr = array of(5 42);
        arr[0] + arr[4]
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("84 : Int", proc.stdout)

    def test_array_mutation(self):
        """Tests array element mutation via a[i] := v."""
        code = """
        let arr = array of 1 2 3 end;
        arr[1] := 99;
        arr[0] + arr[1] + arr[2]
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("103 : Int", proc.stdout)

    def test_array_real_and_string_elements(self):
        """Tests arrays holding Real floats and String pointers."""
        code = """
        let rarr = array of 1.5 2.5 3.5 end;
        rarr[0] ++ rarr[1] ++ rarr[2]
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("7.5 : Real", proc.stdout)

    def test_array_with_strings(self):
        """Tests array of strings and concatenation."""
        code = """
        let sarr = array of "hello " "world" end;
        sarr[0] <> sarr[1]
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"hello world" : String', proc.stdout)

    def test_array_in_loop(self):
        """Tests mutating and reading array elements in a for loop."""
        code = """
        let a = array of(5 0);
        for i = 0 upto 4 do
            a[i] := i * 10
        end;
        let sum = a[0] + a[1] + a[2] + a[3] + a[4];
        sum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("100 : Int", proc.stdout)

    def test_array_bounds_check_upper(self):
        """Tests that indexing past array length triggers arrayOp.error."""
        code = """
        let a = array of 1 2 3 end;
        a[5]
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: arrayOp.error", proc.stderr)

    def test_array_bounds_check_negative(self):
        """Tests that negative array index triggers arrayOp.error."""
        code = """
        let a = array of 1 2 3 end;
        a[0 - 1]
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: arrayOp.error", proc.stderr)

    def test_array_rep_negative_count(self):
        """Tests that allocating array with negative size triggers arrayOp.error."""
        code = """
        let a = array of(0 - 5 0);
        a[0]
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: arrayOp.error", proc.stderr)

    def test_array_nogc_mode(self):
        """Tests compiling and running array operations with --nogc."""
        code = """
        let a = array of 100 200 end;
        a[0] := a[0] + a[1];
        a[0]
        """
        proc = self.compile_quest(code, nogc=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("300 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
