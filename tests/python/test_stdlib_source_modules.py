"""Integration tests for standard library source modules loaded from lib/.

Verifies that standard library interfaces and modules are loaded directly from
Quest source files (.int.quest and .mod.quest) in lib/, and that both pure Quest
and external primitives execute properly in the tree-walking Python interpreter
and C backend.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.env import Environment
from quest.module_loader import (
    DEFAULT_LIB_DIR,
    load_interface,
    load_module,
    resolve_interface_file,
    resolve_module_file,
)
from quest.pipeline import compile_pipeline
from quest.runtime import FALSE_VALUE, TRUE_VALUE, QBool, QInt, QString
from tests.python.helpers import eval_test_source


class TestStdlibSourceModules(unittest.TestCase):
    """Test suite verifying standard library loading and execution from lib/ source files."""

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

    def test_disk_file_resolution(self) -> None:
        """Verifies that all standard library interfaces and modules resolve to lib/ files on disk."""
        modules = [
            ("Writer", "writer"),
            ("Reader", "reader"),
            ("Conv", "conv"),
            ("Ascii", "ascii"),
            ("IntOp", "int"),
            ("RealOp", "real"),
            ("StringOp", "string"),
            ("ArrayOp", "arrayop"),
            ("List", "list"),
            ("System", "system"),
        ]
        for iface_name, mod_name in modules:
            iface_path = resolve_interface_file(iface_name, None, [])
            self.assertIsNotNone(iface_path, f"Failed to resolve interface {iface_name}")
            self.assertTrue(iface_path.is_file())
            self.assertEqual(iface_path.parent, DEFAULT_LIB_DIR.resolve())

            mod_path = resolve_module_file(mod_name, None, [])
            self.assertIsNotNone(mod_path, f"Failed to resolve module {mod_name}")
            self.assertTrue(mod_path.is_file())
            self.assertEqual(mod_path.parent, DEFAULT_LIB_DIR.resolve())

    def test_module_elaboration_from_disk(self) -> None:
        """Verifies that each module in lib/ elaborates against its interface."""
        modules = [
            ("Writer", "writer"),
            ("Reader", "reader"),
            ("Conv", "conv"),
            ("Ascii", "ascii"),
            ("IntOp", "int"),
            ("RealOp", "real"),
            ("StringOp", "string"),
            ("ArrayOp", "arrayop"),
            ("List", "list"),
            ("System", "system"),
        ]
        for iface_name, mod_name in modules:
            env = Environment()
            iface_scope = load_interface(iface_name, env)
            self.assertIsNotNone(iface_scope, f"Failed to load interface {iface_name}")
            mod = load_module(mod_name, iface_name, env)
            self.assertEqual(mod.name.lower(), mod_name.lower())
            self.assertEqual(mod.interface_name, iface_name)

    def test_pure_quest_int_module(self) -> None:
        """Tests pure Quest functions in int module (abs, min, max) in interpreter and C backend."""
        code = """
        import int: IntOp;
        import writer: Writer;
        import conv: Conv;

        let a = int.abs(0 - 42);
        let b = int.min(10 20);
        let c = int.max(10 20);
        writer.putString(writer.output conv.int(a));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(b));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(c));
        writer.putString(writer.output "\n");
        """
        # C backend
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "42 10 20")

        # Python interpreter
        val_abs = eval_test_source("import int: IntOp; int.abs(0 - 99)")
        self.assertEqual(val_abs, QInt(99))
        val_min = eval_test_source("import int: IntOp; int.min(5 12)")
        self.assertEqual(val_min, QInt(5))
        val_max = eval_test_source("import int: IntOp; int.max(5 12)")
        self.assertEqual(val_max, QInt(12))

    def test_pure_quest_real_module(self) -> None:
        """Tests pure Quest arithmetic and relational functions in real module."""
        code = """
        import real: RealOp;
        import writer: Writer;
        import conv: Conv;

        let r1 = real.abs(0.0 -- 3.14);
        let r2 = real.min(1.5 2.5);
        let r3 = real.max(1.5 2.5);
        let r4 = real.plus(10.0 2.5);
        let r5 = real.diff(10.0 2.5);
        let r6 = real.mul(3.0 4.0);
        let b1 = real.smaller(1.0 2.0);
        let b2 = real.greater(2.0 1.0);
        let b3 = real.smallerEq(1.0 1.0);
        let b4 = real.greaterEq(1.0 1.0);

        writer.putString(writer.output conv.real(r1));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(r2));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(r3));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(r4));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(r5));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(r6));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.bool(b1));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.bool(b2));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "3.14 1.5 2.5 12.5 7.5 12.0 true true")

        # Python interpreter
        val_min = eval_test_source("import real: RealOp; real.min(4.0 9.0)")
        self.assertEqual(val_min.value, 4.0)
        val_plus = eval_test_source("import real: RealOp; real.plus(1.5 2.5)")
        self.assertEqual(val_plus.value, 4.0)

    def test_pure_quest_conv_module(self) -> None:
        """Tests pure Quest okay and bool functions alongside number conversions in conv module."""
        code = """
        import conv: Conv;
        import writer: Writer;

        writer.putString(writer.output conv.okay());
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.bool(true));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.bool(false));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(0 - 7));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.real(0.0 -- 2.5));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "ok true false ~7 ~2.5")

        # Python interpreter
        self.assertEqual(eval_test_source("import conv: Conv; conv.okay()"), QString("ok"))
        self.assertEqual(eval_test_source("import conv: Conv; conv.bool(true)"), QString("true"))
        self.assertEqual(eval_test_source("import conv: Conv; conv.bool(false)"), QString("false"))

    def test_pure_quest_list_module_in_c(self) -> None:
        """Tests 100% pure Quest list module operations compiled to C."""
        code = """
        import list: List;
        import writer: Writer;
        import conv: Conv;

        let l0 = list.nil(:Int);
        let b0 = list.null(:Int l0);
        let l1 = list.cons(:Int 10 l0);
        let l2 = list.cons(:Int 20 l1);
        let l3 = list.cons(:Int 30 l2);
        let len = list.length(:Int l3);
        let h = list.head(:Int l3);
        let t = list.head(:Int list.tail(:Int l3));

        writer.putString(writer.output conv.bool(b0));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(len));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(h));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(t));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "true 3 30 20")

    def test_pure_quest_list_module_in_interpreter(self) -> None:
        """Tests 100% pure Quest list module in tree-walking Python interpreter."""
        val_null = eval_test_source("import list: List; list.null(:Int list.nil(:Int))")
        self.assertEqual(val_null, TRUE_VALUE)

        val_head = eval_test_source(
            "import list: List; list.head(:Int list.cons(:Int 42 list.nil(:Int)))"
        )
        self.assertEqual(val_head, QInt(42))

        val_len = eval_test_source(
            "import list: List; list.length(:Int list.cons(:Int 1 list.cons(:Int 2 list.nil(:Int))))"
        )
        self.assertEqual(val_len, QInt(2))

    def test_pure_quest_arrayop_module(self) -> None:
        """Tests arrayOp functions in C backend and interpreter."""
        code = """
        import arrayOp: ArrayOp;
        import writer: Writer;
        import conv: Conv;

        let a = arrayOp.new(:Int 3 42);
        let sz = arrayOp.size(:Int a);
        let elem0 = arrayOp.get(:Int a 0);
        arrayOp.set(:Int a 1 99);
        let elem1 = arrayOp.get(:Int a 1);

        writer.putString(writer.output conv.int(sz));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(elem0));
        writer.putString(writer.output " ");
        writer.putString(writer.output conv.int(elem1));
        writer.putString(writer.output "\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "3 42 99")

        # Python interpreter
        val_sz = eval_test_source("import arrayOp: ArrayOp; arrayOp.size(:Int arrayOp.new(:Int 5 0))")
        self.assertEqual(val_sz, QInt(5))
        val_get = eval_test_source("import arrayOp: ArrayOp; arrayOp.get(:Int arrayOp.new(:Int 3 77) 2)")
        self.assertEqual(val_get, QInt(77))

    def test_dynamic_interface_from_disk(self) -> None:
        """Verifies that Dynamic interface resolves to lib/ file and works with C dynamic module."""
        iface_path = resolve_interface_file("Dynamic", None, [])
        self.assertIsNotNone(iface_path, "Failed to resolve interface Dynamic")
        self.assertTrue(iface_path.is_file())
        self.assertEqual(iface_path.parent, DEFAULT_LIB_DIR.resolve())

        code = """
        import dynamic: Dynamic;
        import writer: Writer;
        import conv: Conv;

        let d = dynamic.new(:Int 12345);
        let x: Int = dynamic.be(:Int d);
        writer.putString(writer.output conv.int(x));
        writer.putString(writer.output "\\n");
        """
        proc = self.compile_and_run(code)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "12345")


if __name__ == "__main__":
    unittest.main()

