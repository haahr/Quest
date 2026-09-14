"""Tests for aggregate subtyping (records in arrays, tuples, etc.) in Quest."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase49AggregateSubtyping(unittest.TestCase):
    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
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

    def test_array_of_subtyped_records(self):
        """Tests creating an array of subtyped records and accessing their fields."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let p1 = record
            x = 10
            y = 20
            color = "blue"
        end;

        let p2 = record
            x = 30
            y = 40
            weight = 5
        end;

        let points: Array(Point) = array of p1 p2 end;
        points[0].x + points[1].y
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("50 : Int", proc.stdout)

    def test_array_repetition_subtyped_records(self):
        """Tests creating an array using repetition with a subtyped record."""
        code = """
        Let Item = Record
            id: Int
        end;

        let detailed = record
            id = 42
            name = "widget"
            price = 99
        end;

        let arr: Array(Item) = array of (3 detailed);
        arr[0].id + arr[1].id + arr[2].id
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("126 : Int", proc.stdout)

    def test_array_index_assignment_subtyped_records(self):
        """Tests assigning a subtyped record into an array slot."""
        code = """
        Let Base = Record
            x: Int
        end;

        let r1 = record
            x = 1
        end;

        let r2 = record
            x = 100
            extra = "hello"
        end;

        let arr: Array(Base) = array of r1 r1 end;
        arr[1] := r2;
        arr[0].x + arr[1].x
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("101 : Int", proc.stdout)

    def test_tuple_with_subtyped_records(self):
        """Tests tuples holding multiple subtyped records."""
        code = """
        Let Counted = Record
            count: Int
        end;

        Let Sized = Record
            size: Int
        end;

        Let Pair = Tuple
            item1: Counted
            item2: Sized
        end;

        let fullObj = record
            count = 5
            size = 42
            version = 1
        end;

        let t: Pair = tuple
            let item1 = fullObj
            let item2 = fullObj
        end;
        t.item1.count + t.item2.size
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("47 : Int", proc.stdout)

    def test_pass_subtyped_array_element_to_function(self):
        """Tests reading a subtyped record from an array and passing it to a function expecting the base record."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let sumCoords(p: Point): Int =
            p.x + p.y;

        let p3d = record
            x = 7
            y = 13
            z = 99
        end;

        let arr: Array(Point) = array of p3d end;
        sumCoords(arr[0])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("20 : Int", proc.stdout)

    def test_array_of_returned_subtyped_records(self):
        """Tests storing results of functions returning subtyped records into an array."""
        code = """
        Let Shape = Record
            area: Int
        end;

        let makeSquare(s: Int): Shape =
            record
                area = s * s
                sides = 4
            end;

        let shapes: Array(Shape) = array of makeSquare(3) makeSquare(4) end;
        shapes[0].area + shapes[1].area
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("25 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
