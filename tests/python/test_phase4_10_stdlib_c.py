"""Unit tests for Phase 4.10: Standard Library Builtins Completeness & OS Primitives in C.

Tests Cardelli standard library interfaces (Writer, Reader, Conv, Ascii, IntOp, RealOp, StringOp)
alongside OS primitives (System interface) in the C code generator.
"""

from __future__ import annotations

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

