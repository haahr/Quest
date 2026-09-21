"""Unit tests for Cardelli symbolic operators, first-class operators, and type operators in C transpiler."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline
from quest.runtime import QBool, QInt, QString
from tests.python.helpers import eval_test_source


class TestCardelliOperatorsC(unittest.TestCase):
    """Verifies Cardelli symbolic operators, first-class closures, and type operators in C transpiler."""

    def compile_and_run(self, code: str) -> subprocess.CompletedProcess[str]:
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

    def test_custom_symbolic_operator(self):
        """Verifies defining and calling custom symbolic infix operator <+>."""
        code = """
        let <+>(x: Int y: Int): Int = x + y + 100;
        10 <+> 20
        """
        self.assertEqual(eval_test_source(code), QInt(130))
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("130", proc.stdout)

    def test_prefix_builtin_operator_application(self):
        """Verifies direct prefix application of built-in operators +(10 20), *(5 6)."""
        code = """
        let a = +(10 20);
        let b = *(a 3);
        b
        """
        self.assertEqual(eval_test_source(code), QInt(90))
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("90", proc.stdout)

    def test_first_class_builtin_operator_closure(self):
        """Verifies referencing built-in operator as first-class closure {+} and calling it."""
        code = """
        let plus = {+};
        let apply(f(a: Int b: Int): Int a: Int b: Int): Int = f(a b);
        apply(plus 15 25)
        """
        self.assertEqual(eval_test_source(code), QInt(40))
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("40", proc.stdout)

    def test_first_class_relational_operator_closure(self):
        """Verifies referencing built-in relational operator {<} and calling it."""
        code = """
        let less = {<};
        less(10 20)
        """
        self.assertEqual(eval_test_source(code), QBool(True))
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("true", proc.stdout)

    def test_symbolic_type_operator_and_type_app(self):
        """Verifies symbolic type operator # and type application alias PairIntStr."""
        code = """
        Let #(A, B::TYPE)::TYPE = Tuple fst: A snd: B end;
        Let PairIntStr = #(Int String);
        let p: PairIntStr = tuple 42 "hello" end;
        p.fst
        """
        self.assertEqual(eval_test_source(code), QInt(42))
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42", proc.stdout)


if __name__ == "__main__":
    unittest.main()
