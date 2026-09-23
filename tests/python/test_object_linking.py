"""Unit and integration tests for Phase 4.16 Step 3: Client Compilation & Object Linking."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bootstrap" / "python"))

from quest.codegen.compiler_runner import run_binary
from quest.interface_compiler import compile_interface_file
from quest.module_compiler import compile_module_file
from quest_driver import run_compile, run_driver


class TestObjectLinking(unittest.TestCase):
    """Verifies that client programs can compile and link against precompiled .o modules."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. Create counter interface
        self.iface_file = self.dir_path / "counter.int.quest"
        self.iface_file.write_text(
            "interface Counter export\n"
            "    T::TYPE\n"
            "    create(init: Int): T\n"
            "    inc(c: T): Ok\n"
            "    get(c: T): Int\n"
            "end;\n",
            encoding="utf-8",
        )

        # 2. Create counter module implementation
        self.mod_file = self.dir_path / "counter.mod.quest"
        self.mod_file.write_text(
            "module counter : Counter export\n"
            "    Let T = Record var count: Int end;\n"
            "    let create(init: Int): T = record var count = init end;\n"
            "    let inc(c: T): Ok = c.count := c.count + 5;\n"
            "    let get(c: T): Int = c.count;\n"
            "end;\n",
            encoding="utf-8",
        )

        # Compile interface to .h + .qi
        self.h_file, self.qi_file = compile_interface_file(self.iface_file, output_dir=self.dir_path)
        self.assertTrue(self.qi_file.exists())
        self.assertTrue(self.h_file.exists())

        # Compile module to .c + .o
        self.c_file, self.o_file = compile_module_file(
            self.mod_file,
            output_dir=self.dir_path,
            include_paths=[self.dir_path],
        )
        self.assertTrue(self.c_file.exists())
        self.assertTrue(self.o_file.exists())

        # Remove the .mod.quest file to guarantee that client compilation does NOT rely on module source!
        self.mod_file.unlink()
        self.assertFalse(self.mod_file.exists())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_explicit_object_linking_and_execution(self) -> None:
        """Client compiles and links against explicitly provided .o file without module source."""
        main_file = self.dir_path / "main.quest"
        main_file.write_text(
            "import counter : Counter;\n"
            "import writer : Writer;\n"
            "import conv : Conv;\n"
            "let c = counter.create(10);\n"
            "counter.inc(c);\n"
            "counter.inc(c);\n"
            "writer.putString(writer.output conv.int(counter.get(c)));\n",
            encoding="utf-8",
        )
        out_bin = self.dir_path / "main_explicit"

        ret = run_compile([
            str(main_file),
            str(self.o_file),
            "-o", str(out_bin),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_bin.exists())

        proc = run_binary(out_bin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "20")

    def test_autodiscovery_object_linking(self) -> None:
        """Client automatically discovers counter.o in -I search path when imported."""
        main_file = self.dir_path / "main_auto.quest"
        main_file.write_text(
            "import counter : Counter;\n"
            "import writer : Writer;\n"
            "import conv : Conv;\n"
            "let c = counter.create(10);\n"
            "counter.inc(c);\n"
            "writer.putString(writer.output conv.int(counter.get(c)));\n",
            encoding="utf-8",
        )
        out_bin = self.dir_path / "main_auto"

        # Do NOT pass counter.o explicitly on the CLI: it must be auto-discovered in -I
        ret = run_compile([
            str(main_file),
            "-o", str(out_bin),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_bin.exists())

        proc = run_binary(out_bin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "15")

    def test_run_driver_cli_invocation_with_object(self) -> None:
        """Unified CLI driver 'quest main.quest counter.o -o main' compiles and links native binary."""
        main_file = self.dir_path / "main_driver.quest"
        main_file.write_text(
            "import counter : Counter;\n"
            "import writer : Writer;\n"
            "import conv : Conv;\n"
            "let c = counter.create(10);\n"
            "counter.inc(c);\n"
            "counter.inc(c);\n"
            "counter.inc(c);\n"
            "writer.putString(writer.output conv.int(counter.get(c)));\n",
            encoding="utf-8",
        )
        out_bin = self.dir_path / "main_driver"

        ret = run_driver([
            str(main_file),
            str(self.o_file),
            "-o", str(out_bin),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_bin.exists())

        proc = run_binary(out_bin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "25")

    def test_dual_calling_direct_and_closure(self) -> None:
        """Verifies both direct function calls and closure access through module record."""
        main_file = self.dir_path / "main_dual.quest"
        main_file.write_text(
            "import counter : Counter;\n"
            "import writer : Writer;\n"
            "import conv : Conv;\n"
            "let c = counter.create(10);\n"
            "counter.inc(c);\n"
            "let getFn = counter.get;\n"
            "writer.putString(writer.output conv.int(getFn(c)));\n",
            encoding="utf-8",
        )
        out_bin = self.dir_path / "main_dual"

        ret = run_compile([
            str(main_file),
            str(self.o_file),
            "-o", str(out_bin),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_bin.exists())

        proc = run_binary(out_bin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "15")

    def test_emitted_c_dual_declarations(self) -> None:
        """Checks that generated C contains extern declarations for module and direct C functions."""
        main_file = self.dir_path / "main_inspect.quest"
        main_file.write_text(
            "import counter : Counter;\n"
            "let c = counter.create(10);\n"
            "counter.inc(c);\n",
            encoding="utf-8",
        )

        c_out_file = self.dir_path / "main_inspect.c"
        ret = run_compile([
            str(main_file),
            str(self.o_file),
            "--emit-c",
            "-o", str(c_out_file),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(ret, 0)
        c_src = c_out_file.read_text(encoding="utf-8")

        # 1. Module record and initializer forward declarations
        self.assertIn("extern QRecordVal qv_counter;", c_src)
        self.assertIn("extern void qv_mod_counter_init(void);", c_src)

        # 2. Direct function extern declarations
        self.assertIn("extern void qv_counter_inc(", c_src)
        self.assertIn("extern QInt qv_counter_get(", c_src)

        # 3. Main entrypoint initializes the module
        self.assertIn("qv_mod_counter_init();", c_src)

        # 4. Direct call emitted
        self.assertIn("qv_counter_inc(", c_src)


if __name__ == "__main__":
    unittest.main()
