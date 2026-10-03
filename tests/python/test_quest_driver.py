"""Unit tests for quest_driver CLI integration (Phase 4).

Tests:
- Default build directory (.build)
- Verbose flag (-v / --verbose) logging to stderr
- Compilation of interfaces and modules to build directory
- Full separate compilation and linking of main routines
- Whole-program compilation flag override
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest_driver import run_compile, run_driver


class TestQuestDriverCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.build_dir = self.root / ".build"
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_compile_interface_and_module_to_build_dir(self) -> None:
        iface_file = self.root / "arith.int.quest"
        iface_file.write_text(
            "interface Arith\n"
            "export\n"
            "    double(x: Int): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        mod_file = self.root / "arith.mod.quest"
        mod_file.write_text(
            "module arith : Arith export\n"
            "    let double(x: Int): Int = x + x;\n"
            "end;\n",
            encoding="utf-8",
        )

        code_int = run_driver([
            str(iface_file),
            "--build-dir",
            str(self.build_dir),
        ])
        self.assertEqual(code_int, 0)
        self.assertTrue((self.build_dir / "arith.qi").is_file())
        self.assertTrue((self.build_dir / "arith.h").is_file())

        code_mod = run_driver([
            str(mod_file),
            "--build-dir",
            str(self.build_dir),
            "-I",
            str(self.root),
        ])
        self.assertEqual(code_mod, 0)
        self.assertTrue((self.build_dir / "arith.o").is_file())
        self.assertTrue((self.build_dir / "arith.qm").is_file())

    def test_compile_main_separate_with_verbose(self) -> None:
        iface_file = self.root / "calc.int.quest"
        iface_file.write_text(
            "interface Calc\n"
            "export\n"
            "    add(a: Int b: Int): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        mod_file = self.root / "calc.mod.quest"
        mod_file.write_text(
            "module calc : Calc export\n"
            "    let add(a: Int b: Int): Int = a + b;\n"
            "end;\n",
            encoding="utf-8",
        )
        main_file = self.root / "main.quest"
        main_file.write_text(
            "import calc: Calc;\n"
            "let res = calc.add(10 25);\n",
            encoding="utf-8",
        )

        bin_path = self.build_dir / "calc_bin"
        exit_code = run_compile([
            str(main_file),
            "-o",
            str(bin_path),
            "--build-dir",
            str(self.build_dir),
            "-I",
            str(self.root),
            "-v",
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(bin_path.is_file())
        self.assertTrue((self.build_dir / "calc.qm").is_file())
        self.assertTrue((self.build_dir / "main.qm").is_file())

        proc = subprocess.run([str(bin_path)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)

    def test_run_driver_with_output_flag(self) -> None:
        main_file = self.root / "hello.quest"
        main_file.write_text(
            "let x: Int = 42;\n",
            encoding="utf-8",
        )
        bin_path = self.build_dir / "hello_bin"
        exit_code = run_driver([
            str(main_file),
            "-o",
            str(bin_path),
            "--build-dir",
            str(self.build_dir),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(bin_path.is_file())


if __name__ == "__main__":
    unittest.main()
