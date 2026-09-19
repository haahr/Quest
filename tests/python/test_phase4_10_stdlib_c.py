"""Unit tests for Phase 4.10: Standard Library Builtins Completeness & OS Primitives in C.

Tests Cardelli standard library interfaces (Writer, Reader, Conv, Ascii, IntOp, RealOp, StringOp)
alongside OS primitives (System interface) in the C code generator.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase410StdlibC(unittest.TestCase):
    """Integration test suite verifying standard library builtins and OS primitives in C."""

    def compile_and_run(
        self, code: str, args: list[str] | None = None, nogc: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Compiles Quest code to C, builds binary, executes with arguments, and returns CompletedProcess."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
            bin_path = Path(f.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=nogc)
            proc = run_binary(bin_path, args=args)
            return proc
        finally:
            if bin_path.exists():
                bin_path.unlink()

    def test_system_args_and_sysexit(self) -> None:
        """Tests system.args length / contents and system.sysexit exit code."""
        code = """
        import system: System;
        import writer: Writer;
        import conv: Conv;

        let numArgs = arrayOp.size(system.args);
        writer.putString(writer.output conv.int(numArgs));
        writer.putString(writer.output "\n");
        let firstArg = arrayOp.get(:String system.args 1);
        writer.putString(writer.output firstArg);
        writer.putString(writer.output "\n");
        system.sysexit(42);
        """
        proc = self.compile_and_run(code, args=["hello", "world"])
        self.assertEqual(proc.returncode, 42)
        lines = proc.stdout.strip().split("\n")
        self.assertEqual(lines[0], "3")
        self.assertEqual(lines[1], "hello")

    def test_system_getenv_and_file_exists(self) -> None:
        """Tests system.getEnv (empty string if undefined) and system.fileExists."""
        os.environ["QUEST_TEST_ENV_VAR"] = "quest_success_value"
        try:
            code = """
            import system: System;
            import writer: Writer;
            import conv: Conv;

            let val = system.getEnv("QUEST_TEST_ENV_VAR");
            writer.putString(writer.output val);
            writer.putString(writer.output "\n");

            let missing = system.getEnv("NON_EXISTENT_VAR_ABCXYZ");
            let lenMissing = string.length(missing);
            writer.putString(writer.output conv.int(lenMissing));
            writer.putString(writer.output "\n");

            let hasRuntime = system.fileExists("runtime/quest_runtime.h");
            writer.putString(writer.output conv.bool(hasRuntime));
            writer.putString(writer.output "\n");

            let noFile = system.fileExists("does_not_exist_file_987654.txt");
            writer.putString(writer.output conv.bool(noFile));
            writer.putString(writer.output "\n");
            """
            proc = self.compile_and_run(code)
            self.assertEqual(proc.returncode, 0)
            lines = proc.stdout.strip().split("\n")
            self.assertEqual(lines[0], "quest_success_value")
            self.assertEqual(lines[1], "0")
            self.assertEqual(lines[2], "true")
            self.assertEqual(lines[3], "false")
        finally:
            os.environ.pop("QUEST_TEST_ENV_VAR", None)

    def test_writer_and_reader_file_roundtrip(self) -> None:
        """Tests file creation with Writer and reading back with Reader."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp_path = f.name

        try:
            code = f"""
            import writer: Writer;
            import reader: Reader;
            import conv: Conv;

            let w = writer.file("{tmp_path}");
            writer.putString(w "Hello from Quest Reader/Writer!\n");
            writer.putChar(w 'X');
            writer.putString(w "\n");
            writer.flush(w);
            writer.close(w);

            let r = reader.file("{tmp_path}");
            let m = reader.more(r);
            writer.putString(writer.output conv.bool(m));
            writer.putString(writer.output "\n");

            let firstLine = reader.getString(r 32);
            writer.putString(writer.output firstLine);

            let ch = reader.getChar(r);
            writer.putString(writer.output conv.char(ch));
            writer.putString(writer.output "\n");
            reader.close(r);
            """
            proc = self.compile_and_run(code)
            self.assertEqual(proc.returncode, 0)
            lines = proc.stdout.strip().split("\n")
            self.assertEqual(lines[0], "true")
            self.assertEqual(lines[1], "Hello from Quest Reader/Writer!")
            self.assertEqual(lines[2], "'X'")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

