"""Unit and integration tests for Phase 4.2b: Tuples & Concrete Records."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase42bAggregates(unittest.TestCase):
    """Tests C code generation, struct definitions, and runtime execution for tuples and records."""

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

    def test_tuple_named_field_access(self):
        """Tests tuple construction and selection by named fields."""
        code = """
        Let T = Tuple
            x: Int
            y: Int
        end;
        let p: T = tuple
            let x = 10
            let y = 25
        end;
        p.x + p.y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("35 : Int", proc.stdout)

    def test_tuple_function_argument_and_return(self):
        """Tests passing and returning tuples across functions."""
        code = """
        Let Point = Tuple
            x: Int
            y: Real
        end;

        let add(p1: Point p2: Point): Point = tuple
            let x = p1.x + p2.x
            let y = p1.y ++ p2.y
        end;

        let p1: Point = tuple
            let x = 10
            let y = 1.5
        end;

        let p2: Point = tuple
            let x = 20
            let y = 2.5
        end;

        let p3 = add(p1 p2);
        p3.x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("30 : Int", proc.stdout)

    def test_record_construction_and_selection(self):
        """Tests concrete record creation and field selection."""
        code = """
        let r = record
            name = "quest"
            score = 100
        end;
        r.score
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("100 : Int", proc.stdout)

    def test_record_mutable_field_assignment(self):
        """Tests mutation of record var fields via TypedAssign."""
        code = """
        let r = record
            x = 10
            var y = 20
        end;
        r.y := 42;
        r.x + r.y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("52 : Int", proc.stdout)

    def test_nested_aggregates(self):
        """Tests nested tuples and records."""
        code = """
        let nested = tuple
            let pt = tuple
                let x = 7
                let y = 3
            end
            let meta = record
                tag = "center"
                weight = 10
            end
        end;
        nested.pt.x + nested.pt.y + nested.meta.weight
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("20 : Int", proc.stdout)

    def test_01_lexer_basics_quest_file(self):
        """Tests compiling and executing tests/source/01_lexer_basics.quest."""
        file_path = Path("tests/source/01_lexer_basics.quest")
        code = file_path.read_text()
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
