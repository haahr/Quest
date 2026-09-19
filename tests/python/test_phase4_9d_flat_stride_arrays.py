"""Unit tests for Phase 4.9d: Flat Stride Arrays (Array(Record) & Array(Variant)).

Tests flat 16-byte memory buffers for Array(Record) and Array(Variant) using
QArrayWideRecord and QArrayWideVariant with zero heap boxing.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase49dFlatStrideArrays(unittest.TestCase):
    """Integration test suite verifying flat stride arrays in generated C code."""

    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        """Compiles Quest code to C, builds binary, executes, and returns CompletedProcess."""
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

    def test_array_record_literal_and_inplace_update(self) -> None:
        """Tests Array(Record) flat contiguous buffer creation, indexing, and in-place update."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let p1 = record x = 10 y = 20 end;
        let p2 = record x = 30 y = 40 end;
        let p3 = record x = 50 y = 60 end;

        let pts: Array(Point) = array of p1 p2 p3 end;
        let initialSum = pts[0].x + pts[1].y + pts[2].x;

        pts[1] := record x = 100 y = 200 end;
        let updatedSum = pts[0].x + pts[1].y + pts[2].x;

        initialSum + updatedSum
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("360 : Int", proc.stdout)

    def test_array_record_repetition(self) -> None:
        """Tests [count of init_val] creating a flat QArrayWideRecord with in-place mutation."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let origin = record x = 5 y = 10 end;
        let arr: Array(Point) = array of (4 origin);

        arr[2] := record x = 50 y = 100 end;

        arr[0].x + arr[1].x + arr[2].x + arr[3].x + arr[2].y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("165 : Int", proc.stdout)

    def test_array_variant_flat_storage_and_pattern_match(self) -> None:
        """Tests Array(Variant) flat contiguous buffer with in-place update and case discrimination."""
        code = """
        Let Num = Variant
            intVal: Int
            realVal: Real
        end;

        let v1 = variant intVal of Num with 42 end;
        let v2 = variant intVal of Num with 10 end;

        let arr: Array(Num) = array of v1 v2 end;

        arr[1] := variant intVal of Num with 58 end;

        let getInt(v: Num): Int =
            case v
                when intVal with n: Int then n
                else 0
            end;

        getInt(arr[0]) + getInt(arr[1])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("100 : Int", proc.stdout)

    def test_array_subtyped_records_dictionary_coercion(self) -> None:
        """Tests storing wider subtyped records into Array(Base) verifying flat dictionary coercion."""
        code = """
        Let Base = Record
            id: Int
            val: Int
        end;

        let p1 = record id = 1 val = 10 color = "red" weight = 50 end;
        let p2 = record id = 2 val = 20 active = true end;

        let arr: Array(Base) = array of p1 p2 end;

        arr[0].id + arr[0].val + arr[1].id + arr[1].val
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("33 : Int", proc.stdout)

    def test_specialized_generic_function_on_array(self) -> None:
        """Tests call-site specialization for generic functions taking Array(Record)."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let sumPoints(A <: Point arr: Array(A)): Int =
            arr[0].x + arr[0].y + arr[1].x + arr[1].y;

        let p1 = record x = 10 y = 20 end;
        let p2 = record x = 30 y = 40 end;
        let pts: Array(Point) = array of p1 p2 end;

        sumPoints(:Point pts)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("100 : Int", proc.stdout)

    def test_generic_array_swap_inplace(self) -> None:
        """Tests generic in-place swap on Array(Record) using call-site specialization."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let swap(A::TYPE arr: Array(A) i: Int j: Int): Ok =
            begin
                let tmp = arr[i];
                arr[i] := arr[j];
                arr[j] := tmp
            end;

        let p1 = record x = 10 y = 20 end;
        let p2 = record x = 99 y = 88 end;
        let pts: Array(Point) = array of p1 p2 end;

        swap(:Point pts 0 1);

        pts[0].x * 1000 + pts[1].x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        # In Quest, infix operators associate right: pts[0].x * (1000 + pts[1].x)
        # pts[0] is 99, pts[1] is 10 => 99 * (1000 + 10) = 99 * 1010 = 99990
        self.assertIn("99990 : Int", proc.stdout)

    def test_nested_flat_arrays_and_record_fields(self) -> None:
        """Tests multi-dimensional arrays (Array(Array(Point))) and records containing flat arrays."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        Let Path = Record
            points: Array(Point)
            length: Int
        end;

        let p1 = record x = 1 y = 2 end;
        let p2 = record x = 3 y = 4 end;
        let row1: Array(Point) = array of p1 p2 end;

        let p3 = record x = 5 y = 6 end;
        let p4 = record x = 7 y = 8 end;
        let row2: Array(Point) = array of p3 p4 end;

        let grid: Array(Array(Point)) = array of row1 row2 end;

        let path = record
            points = row1
            length = 2
        end;

        grid[1][0].x + path.points[1].y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0, f"Execution failed:\n{proc.stderr}")
        self.assertIn("9 : Int", proc.stdout)

    def test_array_bounds_check_wide(self) -> None:
        """Tests that out-of-bounds access on flat wide arrays raises runtime exception."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let p = record x = 1 y = 2 end;
        let pts: Array(Point) = array of p end;
        pts[5].x
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: arrayOp.error", proc.stderr)


if __name__ == "__main__":
    unittest.main()
