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

    def test_conv_builtins_with_cardelli_tilde(self) -> None:
        """Tests Conv functions including Cardelli ~ tilde for negative numbers."""
        code = """
        import conv: Conv;
        import writer: Writer;

        writer.putString(writer.output conv.okay());
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.bool(true));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.bool(false));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(42));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(~42));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(3.14));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(~2.5));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.char('Z'));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.string("text"));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.strip().split("\n")
        self.assertEqual(lines[0], "ok")
        self.assertEqual(lines[1], "true")
        self.assertEqual(lines[2], "false")
        self.assertEqual(lines[3], "42")
        self.assertEqual(lines[4], "~42")
        self.assertEqual(lines[5], "3.14")
        self.assertEqual(lines[6], "~2.5")
        self.assertEqual(lines[7], "'Z'")
        self.assertEqual(lines[8], '"text"')

    def test_ascii_int_real_modules(self) -> None:
        """Tests Ascii, IntOp, and RealOp modules."""
        code = """
        import ascii: Ascii;
        import int: IntOp;
        import real: RealOp;
        import conv: Conv;
        import writer: Writer;

        let ch = ascii.char(66);
        let val = ascii.val(ch);
        let absVal = int.abs(~15);
        let maxVal = int.max(10 25);
        let minVal = int.min(10 25);
        let rFloor = real.floor(4.9);
        let rRound = real.round(4.4);
        let rPlus = real.plus(1.25 2.75);
        let rDiff = real.diff(5.5 1.5);
        let rMul = real.mul(2.5 4.0);
        let rDiv = real.div(9.0 3.0);
        let rSmaller = real.smaller(1.0 2.0);

        writer.putString(writer.output conv.char(ch));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(val));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(absVal));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(maxVal));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(minVal));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(rFloor));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.int(rRound));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(rPlus));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(rDiff));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(rMul));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.real(rDiv));
        writer.putString(writer.output "\n");
        writer.putString(writer.output conv.bool(rSmaller));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.strip().split("\n")
        self.assertEqual(lines[0], "'B'")
        self.assertEqual(lines[1], "66")
        self.assertEqual(lines[2], "15")
        self.assertEqual(lines[3], "25")
        self.assertEqual(lines[4], "10")
        self.assertEqual(lines[5], "4")
        self.assertEqual(lines[6], "4")
        self.assertEqual(lines[7], "4.0")
        self.assertEqual(lines[8], "4.0")
        self.assertEqual(lines[9], "10.0")
        self.assertEqual(lines[10], "3.0")
        self.assertEqual(lines[11], "true")

    def test_first_class_module_record(self) -> None:
        """Tests passing a builtin module as a first-class record value with closure fields."""
        code = """
        import writer: Writer;

        let w = writer;
        w.putString(w.output "First class module record dispatched!\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "First class module record dispatched!\n")

    def test_opaque_type_as_type_argument(self) -> None:
        """Tests passing Writer.T as a generic type argument to a polymorphic function."""
        code = """
        import writer: Writer;

        let id(A::TYPE a: A): A = a;
        let w = id(:Writer.T writer.output);
        writer.putString(w "Writer.T passed as generic argument!\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "Writer.T passed as generic argument!\n")


if __name__ == "__main__":
    unittest.main()
