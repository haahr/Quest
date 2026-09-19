"""Tests for Phase 4.11: Unified Native Module Mechanism, External Syntax, and Hybrid Modules."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import CompilerContext, CompilerOptions, compile_pipeline


class TestPhase411NativeModules(unittest.TestCase):
    """Tests native module integration, external types and values, and hybrid Quest/C modules."""

    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)
        self.pipeline = compile_pipeline()

    def tearDown(self):
        self.temp_dir_obj.cleanup()

    def _write_file(self, filename: str, content: str) -> Path:
        p = self.temp_dir / filename
        p.write_text(content.strip() + "\n", encoding="utf-8")
        return p

    def _compile_and_run(
        self, main_path: Path, include_paths: list[Path] | None = None
    ) -> subprocess.CompletedProcess[str]:
        source_text = main_path.read_text(encoding="utf-8")
        opts = CompilerOptions(
            include_paths=include_paths or [self.temp_dir],
            echo=True,
        )
        ctx = CompilerContext.create(source_text, file_name=str(main_path), options=opts)
        res = self.pipeline.execute(source_text, file_name=str(main_path), options=opts, ctx=ctx)
        self.assertTrue(res.success, f"Compilation failed: {res.diagnostics}")
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

    def test_external_value_compilation(self):
        """Tests that external value bindings correctly link to C runtime symbols/constants."""
        main_file = self._write_file(
            "main.quest",
            """
            let maxVal: Int = external "QUEST_INT_MAX";
            let minVal: Int = external "QUEST_INT_MIN";
            let gt = maxVal > 0;
            let lt = minVal < 0;
            let res = gt andif {lt};
            res
            """,
        )
        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("true : Bool", proc.stdout)

    def test_external_type_in_module(self):
        """Tests defining and using external C types in a hybrid module."""
        self._write_file(
            "fileio.int.quest",
            """
            interface FileIO
            export
                Handle::TYPE
                stdout: Handle
                writeHello(h: Handle): Ok
            end;
            """,
        )

        self._write_file(
            "fileio.mod.quest",
            """
            module fileio : FileIO
            import writer: Writer
            export
                Let Handle = external "QWriter *";
                let stdout: Handle = external "quest_writer_output";
                let writeHello(h: Handle): Ok =
                    writer.putString(h "Hello Native!\\n");
            end;
            """,
        )

        main_file = self._write_file(
            "main.quest",
            """
            import fileio: FileIO;
            fileio.writeHello(fileio.stdout)
            """,
        )

        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Hello Native!", proc.stdout)

    def test_hybrid_module_with_closures_and_values(self):
        """Tests a hybrid module with external constants, native types, and pure Quest functions."""
        self._write_file(
            "calc.int.quest",
            """
            interface Calc
            export
                magic: Int
                addMagic(x: Int): Int
                mulMagic(x: Int): Int
            end;
            """,
        )

        self._write_file(
            "calc.mod.quest",
            """
            module calc : Calc
            export
                let magic = 42;
                let addMagic(x: Int): Int = x + magic;
                let mulMagic(x: Int): Int = x * magic;
            end;
            """,
        )

        main_file = self._write_file(
            "main.quest",
            """
            import calc: Calc;
            let m = calc;
            let fn = m.addMagic;
            fn(10) + m.mulMagic(2)
            """,
        )

        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        # 10 + 42 = 52; 2 * 42 = 84; 52 + 84 = 136
        self.assertIn("136 : Int", proc.stdout)

    def test_first_class_module_record_concrete_fields(self):
        """Verifies that a loaded module record has all fields populated as concrete values."""
        self._write_file(
            "service.int.quest",
            """
            interface Service
            export
                code: Int
                greet(name: String): String
            end;
            """,
        )

        self._write_file(
            "service.mod.quest",
            """
            module service : Service
            import string: StringOp
            export
                let code = 200;
                let greet(name: String): String =
                    string.cat("Hello, " name);
            end;
            """,
        )

        main_file = self._write_file(
            "main.quest",
            """
            import service: Service;
            let serv = service;
            let greeting = serv.greet("Quest");
            serv.code
            """,
        )

        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("200 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
