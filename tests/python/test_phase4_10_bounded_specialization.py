"""Tests for Phase 3: Bounded Specialization for Records and Variants in Quest."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase410BoundedSpecialization(unittest.TestCase):
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

    def get_c_code(self, code: str) -> str:
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)
        return c_code

    def test_bounded_record_field_access(self):
        """Tests that field access on bounded type variable A <: Point uses offset dictionary."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        Let Point3D = Record
            x: Int
            y: Int
            z: Int
        end;

        let getX(A <: Point p: A): Int = p.x;

        let p = record
            x = 42
            y = 100
            z = 999
        end;

        getX(:Point3D p)
        """
        c_code = self.get_c_code(code)

        # Retains runtime QTypeDescriptor * for bounded functions
        self.assertIn("descriptor_A", c_code)

        # Uses offset dictionary for field access on bounded record
        self.assertIn("->offset_x", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_bounded_record_return_caller_restores_dictionary(self):
        """Tests that caller restores concrete subtype dictionary when function returns bounded type variable."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        Let Point3D = Record
            x: Int
            y: Int
            z: Int
        end;

        let identity(A <: Point p: A): A = p;

        let p: Point3D = record
            x = 10
            y = 20
            z = 999
        end;

        let res: Point3D = identity(:Point3D p);
        res.z
        """
        c_code = self.get_c_code(code)

        # Emitted C should restore Point3D identity offset dictionary on return
        self.assertIn("offsetdict_Point3D_Point3D", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("999 : Int", proc.stdout)

    def test_bounded_variant_call_site_tag_alignment(self):
        """Tests bounded variant parameter uses call-site tag alignment and zero-allocation tag remapping."""
        code = """
        Let Color = Variant
            red: Int
            green: Int
            blue: Int
        end;

        Let WarmColor = Variant
            red: Int
            green: Int
        end;

        let matchColor(V <: Color v: V): Int =
            case v
                when red with r then r
                when green with g then g
                else 0
            end;

        let w = variant green of WarmColor with 77 end;
        matchColor(:WarmColor w)
        """
        c_code = self.get_c_code(code)

        # Runtime descriptor retained
        self.assertIn("descriptor_V", c_code)

        # Call-site tag alignment via static tagmap table
        self.assertIn("tagmap_QVariant_red_Int_green_Int_blue_Int_QVariant_red_Int_green_Int", c_code)

        # Callee switches directly on v.tag without heap allocation
        self.assertNotIn("quest_alloc(sizeof(QVariantVal))", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("77 : Int", proc.stdout)

    def test_bounded_variant_check_and_assert(self):
        """Tests ? and ! operators on bounded variant variable V <: Color."""
        code = """
        Let Color = Variant
            red: Int
            blue: Int
        end;

        Let RedOnly = Variant
            red: Int
        end;

        let extractRed(V <: Color v: V): Int =
            if v?red then
                v!red
            else
                0
            end;

        let r = variant red of RedOnly with 123 end;
        extractRed(:RedOnly r)
        """
        c_code = self.get_c_code(code)
        self.assertIn("descriptor_V", c_code)
        self.assertIn("tagmap_QVariant_red_Int_blue_Int_QVariant_red_Int", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("123 : Int", proc.stdout)

    def test_bounded_record_field_mutation(self):
        """Tests mutating a field through a bounded record type variable A <: Counter."""
        code = """
        Let Counter = Record
            var count: Int
        end;

        Let NamedCounter = Record
            name: String
            var count: Int
        end;

        let increment(A <: Counter c: A): Int =
            begin
                c.count := c.count + 1;
                c.count
            end;

        let nc = record
            name = "hits"
            var count = 41
        end;

        increment(:NamedCounter nc)
        """
        c_code = self.get_c_code(code)
        self.assertIn("->offset_count", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_bounded_record_implicit_type_argument(self):
        """Tests that bounded type parameter A <: Point is inferred without explicit type argument."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        Let Point3D = Record
            x: Int
            y: Int
            z: Int
        end;

        let getX(A <: Point p: A): Int = p.x;

        let p: Point3D = record
            x = 55
            y = 66
            z = 77
        end;

        getX(p)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("55 : Int", proc.stdout)

    def test_bounded_record_closure(self):
        """Tests that first-class closures support bounded type parameters A <: Point."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        Let Point3D = Record
            x: Int
            y: Int
            z: Int
        end;

        let f = fun(A <: Point p: A): Int p.x;

        let p: Point3D = record
            x = 88
            y = 100
            z = 999
        end;

        f(:Point3D p)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("88 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
