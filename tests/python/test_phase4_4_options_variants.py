"""Unit and integration tests for Phase 4.4: Options & Variants (Sums)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import CompilerOptions, compile_pipeline


class TestPhase44OptionsVariants(unittest.TestCase):
    """Tests C code generation and execution for Quest options and variants."""

    def compile_quest(self, code: str, nogc: bool = False, echo: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        opts = CompilerOptions(echo=echo)
        res = pipeline.execute(code, "<test>", options=opts)
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

    def test_valueless_option_and_check(self):
        """Tests valueless option injection and tag check '?'."""
        code = """
        Let Traffic = Option red yellow green end;
        let c = option red of Traffic end;
        if c?red then 1 else 0 end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("1 : Int", proc.stdout)

    def test_option_case_matching(self):
        """Tests case pattern matching over an option."""
        code = """
        Let Traffic = Option red yellow green end;
        let eval(t: Traffic): Int =
            case t
                when red then 10
                when yellow then 20
                when green then 30
                else 0
            end;
        eval(option yellow of Traffic end)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("20 : Int", proc.stdout)

    def test_option_with_payload_tuple(self):
        """Tests option with payload components and case branch binder."""
        code = """
        Let Color = Option
            red
            green
            blue with intensity: Int end
        end;

        let c = option blue of Color with tuple let intensity = 255 end end;
        let colorCode(col: Color): Int =
            case col
                when red then 1
                when green then 2
                when blue with b: Tuple intensity: Int end then b.intensity
                else 0
            end;
        colorCode(c)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("255 : Int", proc.stdout)

    def test_option_assert_operator(self):
        """Tests option '!' extraction returning ordinal prepended tuple."""
        code = """
        Let Color = Option
            red
            green
            blue with intensity: Int end
        end;
        let c = option blue of Color with tuple let intensity = 42 end end;
        let unp = c!blue;
        unp.intensity
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)

    def test_option_assert_failure_panic(self):
        """Tests that failed tag assertion triggers variant.tagMismatch diagnostic."""
        code = """
        Let Color = Option red green blue end;
        let c = option red of Color end;
        c!green
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: variant.tagMismatch", proc.stderr)

    def test_variant_injection_and_check(self):
        """Tests variant creation, check '?', and extraction '!'."""
        code = """
        Let Num = Variant int: Int real: Real end;
        let v = variant int of Num with 123 end;
        if v?int then v!int else 0 end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("123 : Int", proc.stdout)

    def test_variant_case_matching(self):
        """Tests case pattern matching over a variant with branch binders."""
        code = """
        Let Shape = Variant
            circle: Real
            rect: Tuple w: Real h: Real end
        end;

        let s = variant circle of Shape with 5.0 end;
        let area(sh: Shape): Real =
            case sh
                when circle with r: Real then r ** r
                else 0.0
            end;
        area(s)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("25.0 : Real", proc.stdout)

    def test_canonical_file_04(self):
        """Tests native compilation and execution of tests/source/04_records_variants_options.quest."""
        file_path = Path("tests/source/04_records_variants_options.quest")
        code = file_path.read_text(encoding="utf-8")
        proc = self.compile_quest(code, echo=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("10 : Int", proc.stdout)  # px = 10
        self.assertIn("1 : Int", proc.stdout)   # first = arr1[0] = 1


if __name__ == "__main__":
    unittest.main()
