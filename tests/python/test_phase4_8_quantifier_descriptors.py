"""Unit tests for Phase 4.8b: Compiler Quantifier Calling Convention & Codegen."""

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


class TestPhase48QuantifierDescriptors(unittest.TestCase):
    """Tests C code generation for universal type quantifiers and descriptor passing."""

    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test_poly>")
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

    def test_polymorphic_identity_ground_calls(self):
        """Tests calling a polymorphic identity function with ground types :Int and :String."""
        code = """
        let id(A::TYPE a: A): A = a;
        let x = id(:Int 42);
        x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("42 : Int", proc.stdout)

    def test_polymorphic_multiple_instantiations(self):
        """Tests multiple invocations of a polymorphic function with different types."""
        code = """
        let id(A::TYPE a: A): A = a;
        let n = id(:Int 10);
        let s = id(:String "hello");
        n
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("10 : Int", proc.stdout)

    def test_generic_call_forwarding(self):
        """Tests forwarding a type parameter descriptor from one polymorphic function to another."""
        code = """
        let id(A::TYPE a: A): A = a;
        let forward(X::TYPE x: X): X = id(:X x);
        let res = forward(:Int 99);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("99 : Int", proc.stdout)

    def test_compound_type_descriptor_in_call(self):
        """Tests synthesizing a compound descriptor (Array(Int)) at a call site."""
        code = """
        let first(A::TYPE arr: Array(A)): A = arr[0];
        let a = array of 100 200 end;
        let v = first(:Int a);
        v
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("100 : Int", proc.stdout)

    def test_first_class_polymorphic_closure_trampoline(self):
        """Tests passing a polymorphic function as a first-class value through trampoline."""
        code = """
        let id(A::TYPE a: A): A = a;
        let apply(f: All(A::TYPE) A -> A): Int = f(:Int 77);
        let res = apply(id);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("77 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
