"""Tests for Stage 1: Whole-Program Module Compilation in Phase 4.7."""

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


class TestPhase47WholeProgramModules(unittest.TestCase):
    """Tests whole-program module compilation to native C99 binaries."""

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

    def _compile_and_run(self, main_path: Path, include_paths: list[Path] | None = None) -> subprocess.CompletedProcess[str]:
        source_text = main_path.read_text(encoding="utf-8")
        opts = CompilerOptions(
            include_paths=include_paths or [],
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

    def test_single_module_compilation(self):
        """Tests importing an interface and module from files and executing via C backend."""
        self._write_file(
            "counter.int.quest",
            """
            interface Counter
            export
                T::TYPE
                new(init: Int): T
                inc(c: T): T
                get(c: T): Int
            end;
            """,
        )

        self._write_file(
            "counter.mod.quest",
            """
            module counter : Counter
            export
                Let T = Int;
                let new(init: Int): T = init;
                let inc(c: T): T = c + 1;
                let get(c: T): Int = c;
            end;
            """,
        )

        main_file = self._write_file(
            "main.quest",
            """
            import counter: Counter;
            let c0 = counter.new(10);
            let c1 = counter.inc(c0);
            let result = counter.get(c1);
            result
            """,
        )

        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("11 : Int", proc.stdout)

    def test_diamond_module_dependency(self):
        """Tests diamond dependency graph with singleton evaluation in C backend."""
        # Base module with state
        self._write_file(
            "base.int.quest",
            """
            interface Base
            export
                bump(step: Int): Int
                read(step: Int): Int
            end;
            """,
        )
        self._write_file(
            "base.mod.quest",
            """
            module base : Base
            export
                let var count: Int = 0;
                let bump(step: Int): Int =
                    begin
                        count := count + step;
                        count
                    end;
                let read(step: Int): Int = count;
            end;
            """,
        )

        # Left module importing base
        self._write_file(
            "left.int.quest",
            """
            interface Left
            export
                leftBump(step: Int): Int
            end;
            """,
        )
        self._write_file(
            "left.mod.quest",
            """
            module left : Left
            import base: Base
            export
                let leftBump(step: Int): Int = base.bump(step);
            end;
            """,
        )

        # Right module importing base
        self._write_file(
            "right.int.quest",
            """
            interface Right
            export
                rightBump(step: Int): Int
            end;
            """,
        )
        self._write_file(
            "right.mod.quest",
            """
            module right : Right
            import base: Base
            export
                let rightBump(step: Int): Int = base.bump(step);
            end;
            """,
        )

        # Main importing left and right
        main_file = self._write_file(
            "main.quest",
            """
            import left: Left;
            import right: Right;
            let l = left.leftBump(1);
            let r = right.rightBump(1);
            l + r
            """,
        )

        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        # First bump: 1, second bump: 2 => sum = 3
        self.assertIn("3 : Int", proc.stdout)

    def test_builtin_modules_interop(self):
        """Tests built-in modules (e.g. arrayOp) being called within user modules in C backend."""
        self._write_file(
            "store.int.quest",
            """
            interface Store
            export
                makeStore(size: Int val: Int): Array(Int)
                getElem(arr: Array(Int) idx: Int): Int
            end;
            """,
        )
        self._write_file(
            "store.mod.quest",
            """
            module store : Store
            import arrayOp: ArrayOp
            export
                let makeStore(size: Int val: Int): Array(Int) = arrayOp.new(:Int size val);
                let getElem(arr: Array(Int) idx: Int): Int = arr[idx];
            end;
            """,
        )
        main_file = self._write_file(
            "main.quest",
            """
            import store: Store;
            let s = store.makeStore(5 42);
            let v = store.getElem(s 2);
            v
            """,
        )
        proc = self._compile_and_run(main_file)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("42 : Int", proc.stdout)


if __name__ == "__main__":
    unittest.main()
