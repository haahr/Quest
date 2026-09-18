"""Unit and integration tests for Phase 4.5: Structural Subtyping & Dynamic Dispatch."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase45Subtyping(unittest.TestCase):
    """Tests C code generation and execution for Quest structural subtyping."""

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

    def get_c_code(self, code: str) -> str:
        """Helper to get emitted C code without running."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)
        return c_code

    def test_tuple_prefix_subtyping(self):
        """Tests prefix tuple subtyping with static_assert generation."""
        code = """
        Let Pair = Tuple
            x: Int
            y: Real
        end;

        Let Triple = Tuple
            x: Int
            y: Real
            z: String
        end;

        let getX(p: Pair): Int = p.x;

        let t: Triple = tuple
            let x = 42
            let y = 3.14
            let z = "hello"
        end;

        getX(t)
        """
        c_code = self.get_c_code(code)
        self.assertIn("static_assert", c_code)
        self.assertIn("offsetof", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_record_width_subtyping_passed_to_function(self):
        """Tests passing a wider record to a function expecting fewer fields."""
        code = """
        Let Point2D = Record
            x: Int
            y: Int
        end;

        let sumCoords(pt: Point2D): Int = pt.x + pt.y;

        let p3d = record
            x = 10
            y = 20
            z = 30
        end;

        sumCoords(p3d)
        """
        c_code = self.get_c_code(code)
        self.assertIn("OffsetDict_", c_code)
        self.assertIn("offsetdict_", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("30 : Int", proc.stdout)

    def test_record_permutation_subtyping(self):
        """Tests record field permutation subtyping with different order."""
        code = """
        Let Point2D = Record
            x: Int
            y: Int
        end;

        let diffCoords(pt: Point2D): Int = pt.x - pt.y;

        let pPermuted = record
            y = 50
            x = 25
        end;

        diffCoords(pPermuted)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("-25 : Int", proc.stdout)

    def test_record_through_closure_and_hof(self):
        """Tests passing records and evidence dictionaries through closures."""
        code = """
        Let HasX = Record
            x: Int
        end;

        let applyFn(f: All(pt: HasX) Int r: HasX): Int = f(r);

        let p = record
            x = 100
            name = "quest"
            flag = true
        end;

        let extract(pt: HasX): Int = pt.x;

        applyFn(extract p)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("100 : Int", proc.stdout)

    def test_record_local_variable_upcast(self):
        """Tests upcasting a record upon binding to a local let-variable."""
        code = """
        Let Target = Record
            a: Int
            b: Int
        end;

        let orig = record
            extra = "extra"
            b = 77
            a = 33
        end;

        let upcasted: Target = orig;
        upcasted.a + upcasted.b
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("110 : Int", proc.stdout)

    def test_record_function_return(self):
        """Tests returning a subtyped record via QRecordResult fat structure."""
        code = """
        Let Point2D = Record
            x: Int
            y: Int
        end;

        let makePoint(dummy: Int): Point2D = record
            x = 12
            y = 34
            color = "red"
        end;

        let pt = makePoint(0);
        pt.x + pt.y
        """
        c_code = self.get_c_code(code)
        self.assertIn("QRecordVal", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("46 : Int", proc.stdout)

    def test_variant_subtyping_and_tagmap(self):
        """Tests variant subtyping with static tagmap remapping."""
        code = """
        Let Small = Variant
            alpha: Int
            beta: Real
        end;

        Let Large = Variant
            gamma: String
            beta: Real
            alpha: Int
        end;

        let evalLarge(v: Large): Int =
            case v
                when alpha with a: Int then a
                when beta with b: Real then 0
                when gamma with g: String then 99
                else 0
            end;

        let s = variant alpha of Small with 123 end;
        evalLarge(s)
        """
        c_code = self.get_c_code(code)
        self.assertIn("tagmap_", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("123 : Int", proc.stdout)

    def test_record_storage_in_tuple(self):
        """Verifies that storing subtyped records in tuples works via QRecordVal fat pointer."""
        code = """
        Let Base = Record
            x: Int
        end;

        Let Pair = Tuple
            item: Base
        end;

        let r = record
            x = 10
            y = 20
        end;

        let p: Pair = tuple
            let item = r
        end;
        p.item.x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("10 : Int", proc.stdout)

    def test_variant_storage_in_tuple_accepted(self):
        """Verifies that storing subtyped variants in tuples works via tag remapping."""
        code = """
        Let Small = Variant
            a: Int
        end;
        Let Large = Variant
            a: Int
            b: Real
        end;
        Let Cont = Tuple
            v: Large
        end;
        let s = variant a of Small with 42 end;
        let c: Cont = tuple
            let v = s
        end;
        case c.v
            when a with val: Int then val
            else 0
        end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
