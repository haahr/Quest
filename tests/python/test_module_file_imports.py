"""Unit tests for Quest Module & Interface File Loader (module_loader.py).

Tests:
- Interface resolution from <name.lower()>.int.quest
- Module resolution from <name.lower()>.mod.quest
- Implicit current directory precedence over -I include paths
- Case-insensitivity / case normalization in file search
- Nested imports in construct clauses
- Singleton module evaluation (shared mutable state across diamond imports)
- Strict validation: single definition, name matching, interface conformance
- Circular dependency detection
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.diagnostics import QuestTypeError
from quest.env import Environment
from quest.interpreter import RuntimeEnvironment
from quest.pipeline import CompilerContext, CompilerOptions, default_pipeline
from quest.runtime import QInt, QOk, QRecord, QString


class TestModuleFileImports(unittest.TestCase):
    """Tests for file-based module and interface imports."""

    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)
        self.pipeline = default_pipeline()

    def tearDown(self):
        self.temp_dir_obj.cleanup()

    def _write_file(self, filename: str, content: str, directory: Path | None = None) -> Path:
        target_dir = directory or self.temp_dir
        path = target_dir / filename
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return path

    def _run_pipeline(self, file_path: Path, options: CompilerOptions | None = None):
        source_text = file_path.read_text(encoding="utf-8")
        ctx = CompilerContext.create(source_text, file_name=str(file_path), options=options)
        res = self.pipeline.execute(source_text, file_name=str(file_path), options=options, ctx=ctx)
        return res, ctx

    def test_import_interface_and_module_from_current_dir(self):
        """Tests loading an interface and module located in the current file directory."""
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

        main_quest = self._write_file(
            "main.quest",
            """
            import counter: Counter;
            let c0 = counter.new(10);
            let c1 = counter.inc(c0);
            let result = counter.get(c1);
            """,
        )

        res, ctx = self._run_pipeline(main_quest)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        val = ctx.runtime_env.lookup("result")
        self.assertEqual(val, QInt(11))

    def test_case_normalization_in_search(self):
        """Tests that interface and module names are lowercased to find .int.quest and .mod.quest."""
        self._write_file(
            "mymath.int.quest",
            """
            interface MyMath
            export
                add(a: Int b: Int): Int
            end;
            """,
        )

        self._write_file(
            "mymath.mod.quest",
            """
            module MyMath : MyMath
            export
                let add(a: Int b: Int): Int = a + b;
            end;
            """,
        )

        main_quest = self._write_file(
            "main.quest",
            """
            import MyMath: MyMath;
            let ans = MyMath.add(20 22);
            """,
        )

        res, ctx = self._run_pipeline(main_quest)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("ans"), QInt(42))

    def test_include_path_search(self):
        """Tests that files in -I directories are found when not in current dir."""
        lib_dir = self.temp_dir / "lib"
        lib_dir.mkdir()

        self._write_file(
            "greeter.int.quest",
            """
            interface Greeter
            export
                greet(name: String): String
            end;
            """,
            directory=lib_dir,
        )

        self._write_file(
            "greeter.mod.quest",
            """
            module greeter : Greeter
            export
                let greet(name: String): String = "Hello " <> name;
            end;
            """,
            directory=lib_dir,
        )

        app_dir = self.temp_dir / "app"
        app_dir.mkdir()
        main_quest = self._write_file(
            "main.quest",
            """
            import greeter: Greeter;
            let msg = greeter.greet("World");
            """,
            directory=app_dir,
        )

        options = CompilerOptions(include_paths=[lib_dir])
        res, ctx = self._run_pipeline(main_quest, options=options)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("msg"), QString("Hello World"))

    def test_current_directory_precedence_over_include_path(self):
        """Tests that active file directory shadows files in -I include paths."""
        inc_dir = self.temp_dir / "inc"
        inc_dir.mkdir()

        self._write_file(
            "config.int.quest",
            """
            interface Config
            export
                value: Int
            end;
            """,
            directory=inc_dir,
        )
        self._write_file(
            "config.mod.quest",
            """
            module config : Config
            export
                let value = 100;
            end;
            """,
            directory=inc_dir,
        )

        app_dir = self.temp_dir / "app"
        app_dir.mkdir()
        self._write_file(
            "config.int.quest",
            """
            interface Config
            export
                value: Int
            end;
            """,
            directory=app_dir,
        )
        self._write_file(
            "config.mod.quest",
            """
            module config : Config
            export
                let value = 999;
            end;
            """,
            directory=app_dir,
        )

        main_quest = self._write_file(
            "main.quest",
            """
            import config: Config;
            let v = config.value;
            """,
            directory=app_dir,
        )

        options = CompilerOptions(include_paths=[inc_dir])
        res, ctx = self._run_pipeline(main_quest, options=options)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("v"), QInt(999))

    def test_nested_imports_in_interface_and_module_clauses(self):
        """Tests importing an interface/module that internally imports another."""
        self._write_file(
            "sub.int.quest",
            """
            interface Sub
            export
                mul2(x: Int): Int
            end;
            """,
        )
        self._write_file(
            "sub.mod.quest",
            """
            module sub : Sub
            export
                let mul2(x: Int): Int = x * 2;
            end;
            """,
        )

        self._write_file(
            "comp.int.quest",
            """
            interface Comp
            import : Sub
            export
                calc(x: Int): Int
            end;
            """,
        )
        self._write_file(
            "comp.mod.quest",
            """
            module comp : Comp
            import sub: Sub
            export
                let calc(x: Int): Int = sub.mul2(x) + 1;
            end;
            """,
        )

        main_quest = self._write_file(
            "main.quest",
            """
            import comp: Comp;
            let res = comp.calc(5);
            """,
        )

        res, ctx = self._run_pipeline(main_quest)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("res"), QInt(11))

    def test_singleton_module_shared_state(self):
        """Tests that a module is instantiated at most once at link time (Cardelli §7.1)."""
        self._write_file(
            "store.int.quest",
            """
            interface Store
            export
                inc(dummy: Ok): Ok
                get(dummy: Ok): Int
            end;
            """,
        )
        self._write_file(
            "store.mod.quest",
            """
            module store : Store
            export
                let var count = 0;
                let inc(dummy: Ok): Ok = begin count := count + 1; ok end;
                let get(dummy: Ok): Int = count;
            end;
            """,
        )

        self._write_file(
            "clienta.int.quest",
            """
            interface ClientA
            export
                doInc(dummy: Ok): Ok
            end;
            """,
        )
        self._write_file(
            "clienta.mod.quest",
            """
            module clienta : ClientA
            import store: Store
            export
                let doInc(dummy: Ok): Ok = store.inc(ok);
            end;
            """,
        )

        self._write_file(
            "clientb.int.quest",
            """
            interface ClientB
            export
                readVal(dummy: Ok): Int
            end;
            """,
        )
        self._write_file(
            "clientb.mod.quest",
            """
            module clientb : ClientB
            import store: Store
            export
                let readVal(dummy: Ok): Int = store.get(ok);
            end;
            """,
        )

        main_quest = self._write_file(
            "main.quest",
            """
            import clienta: ClientA clientb: ClientB;
            clienta.doInc(ok);
            clienta.doInc(ok);
            let finalCount = clientb.readVal(ok);
            """,
        )

        res, ctx = self._run_pipeline(main_quest)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        self.assertEqual(ctx.runtime_env.lookup("finalCount"), QInt(2))

    def test_missing_interface_file_raises_error(self):
        """Tests that referencing a nonexistent interface raises QuestTypeError."""
        main_quest = self._write_file(
            "main.quest",
            """
            import foo: NonExistentIface;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("cannot find interface file for 'NonExistentIface'" in d.message for d in res.diagnostics))

    def test_missing_module_file_raises_error(self):
        """Tests that referencing a nonexistent module raises QuestTypeError."""
        self._write_file(
            "dummy.int.quest",
            """
            interface Dummy
            export
                x: Int
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import missingMod: Dummy;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("cannot find module file for 'missingMod'" in d.message for d in res.diagnostics))

    def test_multiple_phrases_in_interface_file_rejected(self):
        """Tests that an interface file with more than one top-level phrase is rejected."""
        self._write_file(
            "bad.int.quest",
            """
            let x = 1;
            interface Bad
            export
                y: Int
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import : Bad;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("must contain only a single interface declaration" in d.message for d in res.diagnostics))

    def test_non_interface_in_interface_file_rejected(self):
        """Tests that a .int.quest containing a non-interface phrase is rejected."""
        self._write_file(
            "notiface.int.quest",
            """
            let x = 1;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import : NotIface;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("Expected interface declaration" in d.message for d in res.diagnostics))

    def test_interface_name_mismatch_rejected(self):
        """Tests that an interface whose declared name doesn't match filename is rejected."""
        self._write_file(
            "mismatch.int.quest",
            """
            interface ActualName
            export
                x: Int
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import : Mismatch;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("which does not match file name" in d.message for d in res.diagnostics))

    def test_module_name_mismatch_rejected(self):
        """Tests that a module whose declared name doesn't match filename is rejected."""
        self._write_file(
            "iface.int.quest",
            """
            interface Iface
            export
                x: Int
            end;
            """,
        )
        self._write_file(
            "modname.mod.quest",
            """
            module DifferentName : Iface
            export
                let x = 10;
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import modname: Iface;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("which does not match file name" in d.message for d in res.diagnostics))

    def test_module_interface_mismatch_rejected(self):
        """Tests that a module implementing a different interface than expected is rejected."""
        self._write_file(
            "iface1.int.quest",
            """
            interface Iface1
            export
                x: Int
            end;
            """,
        )
        self._write_file(
            "iface2.int.quest",
            """
            interface Iface2
            export
                y: Int
            end;
            """,
        )
        self._write_file(
            "m.mod.quest",
            """
            module m : Iface1
            export
                let x = 1;
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import m: Iface2;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("expected 'Iface2'" in d.message for d in res.diagnostics))

    def test_circular_interface_dependency_detected(self):
        """Tests that a cycle in interface imports is detected."""
        self._write_file(
            "cyca.int.quest",
            """
            interface CycA
            import : CycB
            export
                x: Int
            end;
            """,
        )
        self._write_file(
            "cycb.int.quest",
            """
            interface CycB
            import : CycA
            export
                y: Int
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import : CycA;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("Cyclic dependency detected in interface imports" in d.message for d in res.diagnostics))

    def test_circular_module_dependency_detected(self):
        """Tests that a cycle in module imports is detected."""
        self._write_file(
            "modia.int.quest",
            """
            interface ModIA
            export
                a(dummy: Ok): Int
            end;
            """,
        )
        self._write_file(
            "modib.int.quest",
            """
            interface ModIB
            export
                b(dummy: Ok): Int
            end;
            """,
        )
        self._write_file(
            "modma.mod.quest",
            """
            module modma : ModIA
            import modmb: ModIB
            export
                let a(dummy: Ok): Int = modmb.b(ok);
            end;
            """,
        )
        self._write_file(
            "modmb.mod.quest",
            """
            module modmb : ModIB
            import modma: ModIA
            export
                let b(dummy: Ok): Int = modma.a(ok);
            end;
            """,
        )
        main_quest = self._write_file(
            "main.quest",
            """
            import modma: ModIA;
            """,
        )
        res, _ = self._run_pipeline(main_quest)
        self.assertFalse(res.success)
        self.assertTrue(any("Cyclic dependency detected in module imports" in d.message for d in res.diagnostics))


if __name__ == "__main__":
    unittest.main()
