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

    def test_array_of_subtyped_variants(self):
        """Tests storing subtyped variants in an array and matching on them."""
        code = """
        Let SubCircle = Variant
            circle: Int
        end;

        Let SubRect = Variant
            rect: Int
        end;

        Let Shape = Variant
            circle: Int
            rect: Int
            point: Ok
        end;

        let c = variant circle of SubCircle with 10 end;
        let r = variant rect of SubRect with 20 end;

        let shapes: Array(Shape) = array of c r end;

        let area(s: Shape): Int =
            case s
                when circle with rad: Int then rad * rad
                when rect with side: Int then side * 2
                else 0
            end;

        area(shapes[0]) + area(shapes[1])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("140 : Int", proc.stdout)

    def test_array_repetition_subtyped_variant(self):
        """Tests creating an array of subtyped variants via array repetition."""
        code = """
        Let Small = Variant
            val: Int
        end;

        Let Large = Variant
            val: Int
            other: String
        end;

        let s = variant val of Small with 7 end;
        let arr: Array(Large) = array of (3 s);

        let extract(v: Large): Int =
            case v
                when val with n: Int then n
                else 0
            end;

        extract(arr[0]) + extract(arr[1]) + extract(arr[2])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("21 : Int", proc.stdout)

    def test_array_index_assignment_subtyped_variant(self):
        """Tests assigning a subtyped variant into an array slot."""
        code = """
        Let Base = Variant
            alpha: Int
            beta: Int
        end;

        Let SubAlpha = Variant
            alpha: Int
        end;

        Let SubBeta = Variant
            beta: Int
        end;

        let a = variant alpha of SubAlpha with 100 end;
        let b = variant beta of SubBeta with 50 end;

        let arr: Array(Base) = array of a a end;
        arr[1] := b;

        let score(x: Base): Int =
            case x
                when alpha with n: Int then n
                when beta with n: Int then n * 2
            end;

        score(arr[0]) + score(arr[1])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("200 : Int", proc.stdout)

    def test_arrayOp_builtin_subtyped_variants(self):
        """Tests arrayOp.new and arrayOp.set with subtyped variants."""
        code = """
        Let Base = Variant
            tag1: Int
            tag2: Int
        end;

        Let Sub1 = Variant
            tag1: Int
        end;

        Let Sub2 = Variant
            tag2: Int
        end;

        let s1 = variant tag1 of Sub1 with 11 end;
        let s2 = variant tag2 of Sub2 with 22 end;

        let arr: Array(Base) = arrayOp.new(:Base)(2 s1);
        arrayOp.set(:Base)(arr 1 s2);

        let checkVal(v: Base): Int =
            case v
                when tag1 with n: Int then n
                when tag2 with n: Int then n
                else 0
            end;

        checkVal(arr[0]) + checkVal(arr[1])
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("33 : Int", proc.stdout)

    def test_tuple_with_subtyped_variant(self):
        """Tests storing subtyped variants in tuple fields."""
        code = """
        Let SubA = Variant
            a: Int
        end;

        Let SubB = Variant
            b: Int
        end;

        Let SuperVar = Variant
            a: Int
            b: Int
            c: Real
        end;

        Let Container = Tuple
            first: SuperVar
            second: SuperVar
        end;

        let va = variant a of SubA with 42 end;
        let vb = variant b of SubB with 10 end;

        let box: Container = tuple
            let first = va
            let second = vb
        end;

        let res1 = case box.first
            when a with n: Int then n
            else 0
        end;

        let res2 = case box.second
            when b with n: Int then n * 2
            else 0
        end;

        res1 + res2
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("62 : Int", proc.stdout)

    def test_nested_variant_in_variant(self):
        """Tests a variant whose payload is another variant coerced to a supertype."""
        code = """
        Let InnerSmall = Variant
            x: Int
        end;

        Let InnerLarge = Variant
            x: Int
            y: Real
        end;

        Let Outer = Variant
            wrapped: InnerLarge
        end;

        let inner = variant x of InnerSmall with 99 end;
        let outer = variant wrapped of Outer with inner end;

        case outer
            when wrapped with w: InnerLarge then
                case w
                    when x with n: Int then n
                    else 0
                end
        end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("99 : Int", proc.stdout)

    def test_variable_assignment_subtyped_variant(self):
        """Tests mutating a variable of super-variant type with a sub-variant."""
        code = """
        Let Sub = Variant
            alpha: Int
        end;

        Let Super = Variant
            alpha: Int
            beta: Real
        end;

        let s = variant alpha of Sub with 77 end;
        let var v: Super = variant beta of Super with 1.0 end;
        v := s;

        case v
            when alpha with n: Int then n
            else 0
        end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("77 : Int", proc.stdout)

    def test_variant_unboxed_zero_allocation(self):
        """Tests that variant creation, upcasting, checks, and pattern matches allocate zero heap memory."""
        code = """
        Let Sub = Variant
            red: Int
        end;

        Let Super = Variant
            red: Int
            green: Int
        end;

        let transform(v: Super): Super =
            if v?red then
                variant green of Super with v!red + 10 end
            else
                v
            end;

        let s = variant red of Sub with 42 end;
        let res = transform(s);
        case res
            when green with g: Int then g
            else 0
        end
        """
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        # Emitted C code should use QVariantVal and avoid heap allocation for variants
        self.assertIn("QVariantVal", c_code)
        self.assertNotIn("sizeof(QVariant)", c_code)
        self.assertNotIn("quest_alloc(sizeof(QVariantVal))", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("52 : Int", proc.stdout)

    def test_variant_polymorphic_boxing(self):
        """Tests that passing unboxed QVariantVal to an opaque polymorphic closure boxes into QVal."""
        code = """
        Let Color = Variant
            red: Int
            blue: Int
        end;

        let id(A::TYPE a: A): A = a;
        let clos = id;

        let c = variant red of Color with 123 end;
        let boxedAndBack = clos(:Color c);

        if boxedAndBack?red then
            boxedAndBack!red
        else
            0
        end
        """
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        # Should box on opaque closure call and unwrap on return
        self.assertIn("quest_variant_box", c_code)
        self.assertIn("(*((QVariantVal *)", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("123 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
