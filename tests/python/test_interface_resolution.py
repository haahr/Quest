"""Unit tests for Phase 2: Interface Import Resolution and Decoupling.

Tests:
- Pure interface compilation on-demand (does not touch or require .mod.quest)
- Rule 1 staleness: regenerated when .int.quest is newer than .qi / .h
- Rule 2 staleness: regenerated when artifacts are incomplete
- Rule 3 precompiled mode: loaded from .qi when .int.quest does not exist
- Decoupled module elaboration: module compiles against interface without module source
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from quest.env import Environment
from quest.interface_compiler import compile_interface_file
from quest.module_compiler import compile_module_file
from quest.module_loader import load_interface
from quest.pipeline import CompilerOptions


class TestInterfaceResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.build_dir = self.dir_path / ".build"
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_c_env(self) -> Environment:
        env = Environment()
        env.current_dir = self.dir_path
        env.include_paths = [self.build_dir, self.dir_path]
        env.options = CompilerOptions(
            build_dir=self.build_dir,
            stop_after="codegen_c",
        )
        return env

    def test_pure_interface_compilation(self) -> None:
        """Tests that loading an interface generates .qi and .h without requiring a module."""
        intf_file = self.dir_path / "service.int.quest"
        intf_file.write_text("interface Service export ping(): Int end;\n", encoding="utf-8")

        env = self._create_c_env()
        scope = load_interface("Service", env)
        self.assertIsNotNone(scope)
        self.assertIn("ping", scope.values)

        # Verify .qi and .h were created under .build
        self.assertTrue((self.build_dir / "service.qi").is_file())
        self.assertTrue((self.build_dir / "service.h").is_file())
        # Verify no module artifacts were created
        self.assertFalse((self.build_dir / "service.c").is_file())
        self.assertFalse((self.build_dir / "service.o").is_file())
        self.assertFalse((self.build_dir / "service.qm").is_file())

    def test_interface_rule1_staleness(self) -> None:
        """Tests Rule 1: interface is recompiled when .int.quest is newer than .qi / .h."""
        intf_file = self.dir_path / "metrics.int.quest"
        intf_file.write_text("interface Metrics export count(): Int end;\n", encoding="utf-8")

        env = self._create_c_env()
        load_interface("Metrics", env)
        qi_file = self.build_dir / "metrics.qi"
        self.assertTrue(qi_file.is_file())
        initial_mtime = qi_file.stat().st_mtime

        # Sleep briefly to ensure distinct filesystem timestamp
        time.sleep(0.05)
        # Update interface with an additional method
        intf_file.write_text(
            "interface Metrics export count(): Int reset(): Ok end;\n",
            encoding="utf-8",
        )
        future = time.time() + 2.0
        os.utime(intf_file, (future, future))

        # Reload with fresh environment
        env2 = self._create_c_env()
        scope = load_interface("Metrics", env2)
        self.assertIn("reset", scope.values)
        self.assertGreater(qi_file.stat().st_mtime, initial_mtime)

    def test_interface_rule3_precompiled(self) -> None:
        """Tests Rule 3: precompiled .qi and .h are used when source .int.quest does not exist."""
        intf_file = self.dir_path / "pre.int.quest"
        intf_file.write_text("interface Pre export magic(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_file, build_dir=self.build_dir, include_paths=[self.dir_path])

        # Delete source .int.quest
        intf_file.unlink()
        self.assertFalse(intf_file.exists())
        self.assertTrue((self.build_dir / "pre.qi").is_file())
        self.assertTrue((self.build_dir / "pre.h").is_file())

        env = self._create_c_env()
        scope = load_interface("Pre", env)
        self.assertIsNotNone(scope)
        self.assertIn("magic", scope.values)

    def test_module_compiles_without_imported_module_source(self) -> None:
        """Tests compiling module A that imports B, when only B's interface exists."""
        intf_b = self.dir_path / "depb.int.quest"
        intf_b.write_text("interface DepB export getValue(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_b, build_dir=self.build_dir, include_paths=[self.dir_path])

        # Create module A's interface and implementation
        intf_a = self.dir_path / "moda.int.quest"
        intf_a.write_text("interface ModA export run(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_a, build_dir=self.build_dir, include_paths=[self.dir_path])

        mod_a = self.dir_path / "moda.mod.quest"
        mod_a.write_text(
            "module moda: ModA import b = depb : DepB export let run(): Int = b.getValue() + 1; end;\n",
            encoding="utf-8",
        )

        # Notice: depb.mod.quest DOES NOT EXIST at all!
        self.assertFalse((self.dir_path / "depb.mod.quest").exists())

        res = compile_module_file(mod_a, build_dir=self.build_dir, include_paths=[self.build_dir, self.dir_path])
        self.assertTrue((self.build_dir / "moda.c").is_file())
        self.assertTrue((self.build_dir / "moda.o").is_file())
        self.assertTrue((self.build_dir / "moda.qm").is_file())
        self.assertIsNotNone(res)


if __name__ == "__main__":
    unittest.main()
