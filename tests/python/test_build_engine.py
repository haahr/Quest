"""Unit tests for Phase 3: The Queue-Driven Build Engine."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.build.engine import BuildEngine, BuildError
from quest.interface_compiler import compile_interface_file
from quest.module_compiler import compile_module_file


class TestBuildEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.build_dir = self.root / ".build"
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.build_dir / "build.log"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_engine(self, verbose: bool = False) -> BuildEngine:
        return BuildEngine(
            build_dir=self.build_dir,
            include_paths=[self.root],
            verbose=verbose,
            log_file=self.log_file,
        )

    def test_build_main_simple(self) -> None:
        """Tests building and running a simple main routine with builtins."""
        main_file = self.root / "simple.quest"
        main_file.write_text(
            "import writer: Writer;\n"
            "let w = writer.output;\n"
            "writer.putString(w \"Hello from Quest!\\n\");\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        res = engine.build_main(main_file)

        self.assertTrue(res.output_binary.is_file())
        self.assertIn("simple", res.compiled_units)
        self.assertTrue((self.build_dir / "simple.qm").is_file())
        self.assertTrue((self.build_dir / "simple.c").is_file())
        self.assertTrue((self.build_dir / "simple.o").is_file())

        proc = subprocess.run([str(res.output_binary)], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "Hello from Quest!\n")

    def test_build_main_with_module_dependency(self) -> None:
        """Tests that a main routine importing a module automatically builds and links it."""
        intf_file = self.root / "calc.int.quest"
        intf_file.write_text("interface Calc export add(a: Int b: Int): Int end;\n", encoding="utf-8")

        mod_file = self.root / "calc.mod.quest"
        mod_file.write_text(
            "module calc : Calc export let add(a: Int b: Int): Int = a + b; end;\n",
            encoding="utf-8",
        )

        main_file = self.root / "app.quest"
        main_file.write_text(
            "import c = calc : Calc;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "let w = writer.output;\n"
            "writer.putString(w conv.int(c.add(10 32)));\n"
            "writer.putString(w \"\\n\");\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        res = engine.build_main(main_file)

        self.assertTrue(res.output_binary.is_file())
        self.assertIn("app", res.compiled_units)
        self.assertIn("calc", res.compiled_units)

        self.assertTrue((self.build_dir / "calc.qm").is_file())
        self.assertTrue((self.build_dir / "calc.c").is_file())
        self.assertTrue((self.build_dir / "calc.o").is_file())

        proc = subprocess.run([str(res.output_binary)], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "42\n")

    def test_transitive_module_dependencies(self) -> None:
        """Tests transitive module discovery (main -> service -> helper)."""
        helper_intf = self.root / "helper.int.quest"
        helper_intf.write_text("interface Helper export multiply(x: Int y: Int): Int end;\n", encoding="utf-8")
        helper_mod = self.root / "helper.mod.quest"
        helper_mod.write_text(
            "module helper : Helper export let multiply(x: Int y: Int): Int = x * y; end;\n",
            encoding="utf-8",
        )

        service_intf = self.root / "service.int.quest"
        service_intf.write_text("interface Service export compute(n: Int): Int end;\n", encoding="utf-8")
        service_mod = self.root / "service.mod.quest"
        service_mod.write_text(
            "module service : Service\n"
            "import h = helper : Helper;\n"
            "export let compute(n: Int): Int = h.multiply(n 3) + 1;\n"
            "end;\n",
            encoding="utf-8",
        )

        main_file = self.root / "main.quest"
        main_file.write_text(
            "import s = service : Service;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "let w = writer.output;\n"
            "writer.putString(w conv.int(s.compute(7)));\n"
            "writer.putString(w \"\\n\");\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        res = engine.build_main(main_file)

        self.assertTrue({"main", "service", "helper"}.issubset(set(res.compiled_units)))
        proc = subprocess.run([str(res.output_binary)], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "22\n")

    def test_incremental_build_rebuilds_nothing_when_up_to_date(self) -> None:
        """Tests that a clean rebuild with no changes compiles 0 units."""
        intf_file = self.root / "arith.int.quest"
        intf_file.write_text("interface Arith export double(n: Int): Int end;\n", encoding="utf-8")
        mod_file = self.root / "arith.mod.quest"
        mod_file.write_text("module arith : Arith export let double(n: Int): Int = n * 2; end;\n", encoding="utf-8")

        main_file = self.root / "driver.quest"
        main_file.write_text(
            "import m = arith : Arith;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "writer.putString(writer.output conv.int(m.double(21)));\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        res1 = engine.build_main(main_file)
        self.assertTrue({"driver", "arith"}.issubset(set(res1.compiled_units)))

        # Second build without changes
        res2 = engine.build_main(main_file)
        self.assertEqual(res2.compiled_units, [])

    def test_incremental_build_touch_module(self) -> None:
        """Tests that touching a module rebuilds only that module and relinks."""
        intf_file = self.root / "foo.int.quest"
        intf_file.write_text("interface Foo export getVal(): Int end;\n", encoding="utf-8")
        mod_file = self.root / "foo.mod.quest"
        mod_file.write_text("module foo : Foo export let getVal(): Int = 10; end;\n", encoding="utf-8")

        main_file = self.root / "run_foo.quest"
        main_file.write_text(
            "import f = foo : Foo;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "writer.putString(writer.output conv.int(f.getVal()));\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        engine.build_main(main_file)

        # Sleep and update foo.mod.quest
        time.sleep(0.05)
        future = time.time() + 2.0
        mod_file.write_text("module foo : Foo export let getVal(): Int = 99; end;\n", encoding="utf-8")
        os.utime(mod_file, (future, future))

        res2 = engine.build_main(main_file)
        self.assertEqual(res2.compiled_units, ["foo"])

        proc = subprocess.run([str(res2.output_binary)], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "99")

    def test_transitive_interface_invalidation(self) -> None:
        """Tests that updating an interface triggers recompilation of importing modules."""
        intf_file = self.root / "shared.int.quest"
        intf_file.write_text("interface Shared export value(): Int end;\n", encoding="utf-8")
        mod_file = self.root / "shared.mod.quest"
        mod_file.write_text("module shared : Shared export let value(): Int = 123; end;\n", encoding="utf-8")

        main_file = self.root / "show.quest"
        main_file.write_text(
            "import s = shared : Shared;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "writer.putString(writer.output conv.int(s.value()));\n",
            encoding="utf-8",
        )

        engine = self._create_engine()
        engine.build_main(main_file)

        # Touch shared.int.quest into the future
        time.sleep(0.05)
        future = time.time() + 2.0
        intf_file.write_text("interface Shared export value(): Int reset(): Ok end;\n", encoding="utf-8")
        mod_file.write_text(
            "module shared : Shared export let value(): Int = 123; let reset(): Ok = ok; end;\n",
            encoding="utf-8",
        )
        os.utime(intf_file, (future, future))

        res2 = engine.build_main(main_file)
        # Both show and shared import Shared, so both detect stale interface and rebuild
        self.assertIn("shared", res2.compiled_units)

    def test_colocated_file_conflict(self) -> None:
        """Tests that having m.quest and m.mod.quest at the same location raises BuildError."""
        main_file = self.root / "conflict.quest"
        main_file.write_text("import writer: Writer;\n", encoding="utf-8")
        mod_file = self.root / "conflict.mod.quest"
        mod_file.write_text("module conflict : Empty export end;\n", encoding="utf-8")

        engine = self._create_engine()
        with self.assertRaises(BuildError) as ctx:
            engine.build_main(main_file)
        self.assertIn("Conflict", str(ctx.exception))

    def test_module_cycle_detection(self) -> None:
        """Tests that cyclic module imports raise BuildError with cycle path."""
        intf_a = self.root / "cyca.int.quest"
        intf_a.write_text("interface CycA export ping(): Int end;\n", encoding="utf-8")
        intf_b = self.root / "cycb.int.quest"
        intf_b.write_text("interface CycB export pong(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_a, build_dir=self.build_dir, include_paths=[self.root])
        compile_interface_file(intf_b, build_dir=self.build_dir, include_paths=[self.root])

        # Precompile CycA and CycB with circular manifests
        mod_a = self.root / "cyca.mod.quest"
        mod_a.write_text(
            "module cyca : CycA import b = cycb : CycB export let ping(): Int = 1; end;\n",
            encoding="utf-8",
        )
        mod_b = self.root / "cycb.mod.quest"
        mod_b.write_text(
            "module cycb : CycB import a = cyca : CycA export let pong(): Int = 2; end;\n",
            encoding="utf-8",
        )
        compile_module_file(mod_a, build_dir=self.build_dir, include_paths=[self.build_dir, self.root])
        compile_module_file(mod_b, build_dir=self.build_dir, include_paths=[self.build_dir, self.root])

        main_file = self.root / "cycle_main.quest"
        main_file.write_text("import a = cyca : CycA;\n", encoding="utf-8")

        engine = self._create_engine()
        with self.assertRaises(BuildError) as ctx:
            engine.build_main(main_file)
        self.assertIn("Cyclic module dependency detected", str(ctx.exception))

    def test_build_logger_records_events(self) -> None:
        """Verifies that the build log captures structured entries."""
        main_file = self.root / "logged.quest"
        main_file.write_text("import writer: Writer;\n", encoding="utf-8")

        engine = self._create_engine()
        engine.build_main(main_file)

        self.assertTrue(self.log_file.is_file())
        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("BUILD START:", content)
        self.assertIn("QUEUE INIT:", content)
        self.assertIn("COMPILE MAIN:", content)
        self.assertIn("HOST LINK:", content)
        self.assertIn("BUILD COMPLETE:", content)

    def test_module_interface_conformance_mismatch(self) -> None:
        """Tests that importing a module with an incompatible interface raises BuildError."""
        intf_expected = self.root / "expected.int.quest"
        intf_expected.write_text("interface Expected export get(): Int end;\n", encoding="utf-8")
        intf_actual = self.root / "actual.int.quest"
        intf_actual.write_text("interface Actual export get(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_expected, build_dir=self.build_dir, include_paths=[self.root])
        compile_interface_file(intf_actual, build_dir=self.build_dir, include_paths=[self.root])

        mod_prov = self.root / "prov.mod.quest"
        mod_prov.write_text("module prov : Actual export let get(): Int = 42; end;\n", encoding="utf-8")

        main_file = self.root / "bad_import.quest"
        main_file.write_text("import p = prov : Expected;\n", encoding="utf-8")

        engine = self._create_engine()
        with self.assertRaises(BuildError) as ctx:
            engine.build_main(main_file)
        self.assertIn("Type error:", str(ctx.exception))
        self.assertIn("Expected", str(ctx.exception))
        self.assertIn("Actual", str(ctx.exception))

    def test_transitive_interface_mismatch_detected(self) -> None:
        """Tests that a transitive module importing another with a mismatched interface is caught."""
        intf_a = self.root / "ifacea.int.quest"
        intf_a.write_text("interface IfaceA export valA(): Int end;\n", encoding="utf-8")
        intf_b = self.root / "ifaceb.int.quest"
        intf_b.write_text("interface IfaceB export valB(): Int end;\n", encoding="utf-8")
        intf_c = self.root / "ifacec.int.quest"
        intf_c.write_text("interface IfaceC export valC(): Int end;\n", encoding="utf-8")
        compile_interface_file(intf_a, build_dir=self.build_dir, include_paths=[self.root])
        compile_interface_file(intf_b, build_dir=self.build_dir, include_paths=[self.root])
        compile_interface_file(intf_c, build_dir=self.build_dir, include_paths=[self.root])

        # prov implements IfaceC
        mod_prov = self.root / "prov2.mod.quest"
        mod_prov.write_text("module prov2 : IfaceC export let valC(): Int = 99; end;\n", encoding="utf-8")

        # mid implements IfaceB, but imports prov2 as IfaceA (mismatch!)
        mod_mid = self.root / "mid.mod.quest"
        mod_mid.write_text(
            "module mid : IfaceB import p = prov2 : IfaceA export let valB(): Int = p.valA(); end;\n",
            encoding="utf-8",
        )

        main_file = self.root / "main_trans.quest"
        main_file.write_text("import m = mid : IfaceB;\n", encoding="utf-8")

        engine = self._create_engine()
        with self.assertRaises(BuildError) as ctx:
            engine.build_main(main_file)
        self.assertIn("Type error:", str(ctx.exception))
        self.assertIn("IfaceA", str(ctx.exception))
        self.assertIn("IfaceC", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
