"""Unit tests for Phase 4.8c: Dynamic Module Lowering & Generic Wrappers."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.codegen.compiler_runner import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase48Dynamic(unittest.TestCase):
    """Tests C code generation and execution for Quest dynamic module."""

    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test_dynamic>")
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

    def test_dynamic_new_and_be_ground_int(self):
        """Tests packaging an Int into dynamic.T and unpacking it with dynamic.be(:Int)."""
        code = """
        import dynamic: Dynamic;
        let d: dynamic.T = dynamic.new(:Int 42);
        let x: Int = dynamic.be(:Int d);
        x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("42 : Int", proc.stdout)

    def test_dynamic_new_and_be_ground_string(self):
        """Tests packaging a String into dynamic.T and unpacking it with dynamic.be(:String)."""
        code = """
        import dynamic: Dynamic;
        let d: dynamic.T = dynamic.new(:String "cardelli");
        let s: String = dynamic.be(:String d);
        s
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn('"cardelli" : String', proc.stdout)

    def test_dynamic_type_mismatch_raises_dynamic_error(self):
        """Tests that dynamic.be with an incorrect type raises dynamic.error which can be caught."""
        code = """
        import dynamic: Dynamic;
        let d: dynamic.T = dynamic.new(:Int 42);
        let res = try
            dynamic.be(:String d);
            "failed_to_raise"
        when dynamic.error then
            "caught_dynamic_error"
        end;
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn('"caught_dynamic_error" : String', proc.stdout)

    def test_dynamic_copy(self):
        """Tests dynamic.copy creates a copy with the same type and payload."""
        code = """
        import dynamic: Dynamic;
        let d1 = dynamic.new(:Int 999);
        let d2 = dynamic.copy(d1);
        let v = dynamic.be(:Int d2);
        v
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("999 : Int", proc.stdout)

    def test_generic_dynamic_wrapper_functions(self):
        """Tests generic wrap and unwrap functions that pass type parameter descriptors to dynamic.new/be."""
        code = """
        import dynamic: Dynamic;
        let wrapVal(A::TYPE a: A): dynamic.T = dynamic.new(:A a);
        let unwrapVal(A::TYPE d: dynamic.T): A = dynamic.be(:A d);

        let dInt = wrapVal(:Int 12345);
        let dStr = wrapVal(:String "polymorphic_dynamic");

        let n = unwrapVal(:Int dInt);
        let s = unwrapVal(:String dStr);
        n
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("12345 : Int", proc.stdout)

    def test_heterogeneous_array_of_dynamics(self):
        """Tests storing dynamic values of different types in an Array(dynamic.T)."""
        code = """
        import dynamic: Dynamic;
        let arr = array of
            dynamic.new(:Int 10)
            dynamic.new(:String "twenty")
            dynamic.new(:Bool true)
        end;

        let v1 = dynamic.be(:Int arr[0]);
        let v2 = dynamic.be(:String arr[1]);
        let v3 = dynamic.be(:Bool arr[2]);

        v1
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("10 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
