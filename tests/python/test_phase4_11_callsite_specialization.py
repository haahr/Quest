"""Tests for Phase 4: Call-Site Specialization for Unbounded Quantifiers (A::TYPE)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase411CallsiteSpecialization(unittest.TestCase):
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

    def test_generic_identity_record(self):
        """Tests that passing a record to an unbounded generic function uses unboxed QRecordVal."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let id(A::TYPE a: A): A = a;

        let p = record
            x = 42
            y = 100
        end;

        let res = id(:Point p);
        let check = res.x;
        """
        c_code = self.get_c_code(code)

        # Specialized clone was generated and called with unboxed QRecordVal
        self.assertIn("qv_id_spec_QRecord_x_Int_y_Int(QRecordVal qv_a)", c_code)
        self.assertIn("qv_res = qv_id_spec_QRecord_x_Int_y_Int(qv_p);", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)

    def test_generic_identity_variant(self):
        """Tests that passing a variant to an unbounded generic function uses unboxed QVariantVal."""
        code = """
        Let Color = Variant
            red: Int
            blue: Int
        end;

        let id(A::TYPE a: A): A = a;

        let c = variant blue of Color with 777 end;
        let res = id(:Color c);
        let isBlue = res?blue;
        """
        c_code = self.get_c_code(code)

        # Specialized clone was generated and called with unboxed QVariantVal
        self.assertIn("qv_id_spec_QVariant_red_Int_blue_Int(QVariantVal qv_a)", c_code)
        self.assertIn("qv_res = qv_id_spec_QVariant_red_Int_blue_Int(qv_c);", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)

    def test_generic_tuple_record_layout(self):
        """Tests that generic tuple constructor aligns with concrete tuple layout."""
        code = """
        Let Point = Record
            x: Int
            y: Int
        end;

        let pair(A::TYPE a: A): Tuple item: A end =
            tuple let item = a end;

        let p = record
            x = 42
            y = 99
        end;

        let res = pair(:Point p);
        let xVal = res.item.x;
        """
        c_code = self.get_c_code(code)

        # Verified specialized clone returns concrete tuple struct
        self.assertIn("qv_pair_spec_QRecord_x_Int_y_Int", c_code)
        self.assertIn("sizeof(QTuple_QRecord_x_Int_y_Int)", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)

    def test_generic_multi_type_tuple(self):
        """Tests generic function with multiple type arguments including records and scalars."""
        code = """
        Let Point = Record
            x: Int
        end;

        let mkPair(A::TYPE B::TYPE a: A b: B): Tuple first: A second: B end =
            tuple let first = a let second = b end;

        let p = record x = 55 end;
        let res = mkPair(:Point :Int p 123);
        let checkX = res.first.x;
        let checkB = res.second;
        """
        c_code = self.get_c_code(code)

        self.assertIn("qv_mkPair_spec_QRecord_x_Int_Int", c_code)
        self.assertIn("sizeof(QTuple_QRecord_x_Int_Int)", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)

    def test_chained_specialization(self):
        """Tests that a generic function calling another generic function specializes the callee."""
        code = """
        Let Point = Record
            x: Int
        end;

        let id(A::TYPE a: A): A = a;
        let forward(A::TYPE a: A): A = id(:A a);

        let p = record x = 88 end;
        let res = forward(:Point p);
        let check = res.x;
        """
        c_code = self.get_c_code(code)

        # Both forward and id are specialized
        self.assertIn("qv_forward_spec_QRecord_x_Int", c_code)
        self.assertIn("qv_id_spec_QRecord_x_Int", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)

    def test_scalar_and_aggregate_coexistence(self):
        """Tests that canonical unspecialized QVal implementation coexists with specialized clones."""
        code = """
        Let Point = Record x: Int end;
        Let Color = Variant red: Int blue: Int end;

        let id(A::TYPE a: A): A = a;

        let p = record x = 10 end;
        let c = variant red of Color with 20 end;

        let rInt = id(:Int 99);
        let rPoint = id(:Point p);
        let rColor = id(:Color c);
        """
        c_code = self.get_c_code(code)

        # Canonical unspecialized function called for Int
        self.assertIn("qv_id(&quest_type_Int", c_code)
        # Specialized functions called for Point and Color
        self.assertIn("qv_id_spec_QRecord_x_Int(qv_p)", c_code)
        self.assertIn("qv_id_spec_QVariant_red_Int_blue_Int(qv_c)", c_code)

        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
