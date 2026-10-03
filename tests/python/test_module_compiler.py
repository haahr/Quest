"""Unit and Integration Tests for Quest Module Compiler (Phase 4.16 Step 2).

Tests separate compilation of .mod.quest files into .c and .o, verifying:
- Dual linkage ABI: direct C functions and closure trampolines
- Module record variable (QRecordVal qv_<mod>) with external linkage
- Idempotent chained module initialization (void qv_mod_<mod>_init(void))
- Native object linking against host C driver
- CLI driver invocation (quest -c <file>.mod.quest)
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from quest.codegen.compiler_runner import find_c_compiler, get_runtime_dir
from quest.interface_compiler import compile_interface_file
from quest.module_compiler import compile_module_file
import quest_driver


class TestModuleCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.runtime_dir = get_runtime_dir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_basic_module_compilation(self) -> None:
        """Tests that .mod.quest compiles to .c and .o with correct ABI symbols."""
        intf_file = self.dir_path / "counter.int.quest"
        intf_file.write_text(
            "interface Counter export\n"
            "    T::TYPE\n"
            "    create(): T\n"
            "    read(c: T): Int\n"
            "    inc(c: T): Ok\n"
            "end;\n",
            encoding="utf-8",
        )
        h_file, qi_file = compile_interface_file(intf_file, output_dir=self.dir_path)
        self.assertTrue(h_file.is_file())
        self.assertTrue(qi_file.is_file())

        mod_file = self.dir_path / "counter.mod.quest"
        mod_file.write_text(
            "module counter: Counter export\n"
            "    Let T = Record var count: Int end;\n"
            "    let create(): T = record var count = 0 end;\n"
            "    let read(c: T): Int = c.count;\n"
            "    let inc(c: T): Ok = c.count := c.count + 1;\n"
            "end;\n",
            encoding="utf-8",
        )
        c_file, o_file = compile_module_file(
            mod_file,
            output_dir=self.dir_path,
            include_paths=[self.dir_path],
        )

        qm_file = self.dir_path / "counter.qm"
        self.assertTrue(qm_file.is_file())
        from quest.build.manifest import read_qm
        manifest = read_qm(qm_file)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, "counter")
        self.assertEqual(manifest.interface, "Counter")
        self.assertEqual(manifest.source, str(mod_file.resolve()))
        self.assertEqual(manifest.object, str(o_file.resolve()))
        self.assertEqual(len(manifest.imported_interfaces), 1)
        self.assertEqual(manifest.imported_interfaces[0].name, "Counter")

        c_source = c_file.read_text(encoding="utf-8")
        # Interface header included
        self.assertIn('#include "counter.h"', c_source)
        # Module record variable declared with external linkage
        self.assertIn("QRecordVal qv_counter;", c_source)
        # Idempotent initializer declared with external linkage
        self.assertIn("void qv_mod_counter_init(void) {", c_source)
        self.assertIn("if (qv_mod_counter_initialized) return;", c_source)
        # Direct C functions exported without static, conforming to interface ABI (QVal for abstract T)
        self.assertIn("QInt qv_counter_read(QVal qv_p_c) {", c_source)
        self.assertIn("void qv_counter_inc(QVal qv_p_c) {", c_source)
        self.assertNotIn("static QInt qv_counter_read(QVal", c_source)
        self.assertNotIn("static void qv_counter_inc(QVal", c_source)
        # Internal implementations take concrete module type QRecordVal
        self.assertIn("static QInt _qv_counter_read_impl(QRecordVal qv_counter_c) {", c_source)
        self.assertIn("static void _qv_counter_inc_impl(QRecordVal qv_counter_c) {", c_source)
        # Trampoline functions are static
        self.assertIn("static QInt qv_counter_read_trampoline(void *env", c_source)
        self.assertIn("static void qv_counter_inc_trampoline(void *env", c_source)

    def test_chained_module_initialization(self) -> None:
        """Tests that a module importing another module chains initialization calls."""
        # 1. Base interface & module
        base_intf = self.dir_path / "base.int.quest"
        base_intf.write_text(
            "interface Base export\n"
            "    val: Int\n"
            "end;\n",
            encoding="utf-8",
        )
        compile_interface_file(base_intf, output_dir=self.dir_path)

        base_mod = self.dir_path / "base.mod.quest"
        base_mod.write_text(
            "module base: Base export\n"
            "    let val: Int = 100;\n"
            "end;\n",
            encoding="utf-8",
        )
        compile_module_file(base_mod, output_dir=self.dir_path, include_paths=[self.dir_path])

        # 2. Client interface & module importing base
        client_intf = self.dir_path / "client.int.quest"
        client_intf.write_text(
            "interface Client export\n"
            "    compute(): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        compile_interface_file(client_intf, output_dir=self.dir_path)

        client_mod = self.dir_path / "client.mod.quest"
        client_mod.write_text(
            "module client: Client\n"
            "    import base: Base\n"
            "export\n"
            "    let compute(): Int = base.val + 42;\n"
            "end;\n",
            encoding="utf-8",
        )
        c_file, o_file = compile_module_file(
            client_mod,
            output_dir=self.dir_path,
            include_paths=[self.dir_path],
        )

        self.assertTrue(c_file.is_file())
        self.assertTrue(o_file.is_file())

        c_source = c_file.read_text(encoding="utf-8")
        # Check forward declaration for base init
        self.assertIn("extern void qv_mod_base_init(void);", c_source)
        self.assertIn("extern QRecordVal qv_base;", c_source)
        # Check call to base init inside client init
        self.assertIn("qv_mod_base_init();", c_source)

    def test_native_host_linking_and_execution(self) -> None:
        """Tests compiling a module and linking with a native C main runner."""
        intf_file = self.dir_path / "mathops.int.quest"
        intf_file.write_text(
            "interface MathOps export\n"
            "    add(a: Int b: Int): Int\n"
            "    multiply(a: Int b: Int): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        compile_interface_file(intf_file, output_dir=self.dir_path)

        mod_file = self.dir_path / "mathops.mod.quest"
        mod_file.write_text(
            "module mathops: MathOps export\n"
            "    let add(a: Int b: Int): Int = a + b;\n"
            "    let multiply(a: Int b: Int): Int = a * b;\n"
            "end;\n",
            encoding="utf-8",
        )
        c_file, o_file = compile_module_file(
            mod_file,
            output_dir=self.dir_path,
            include_paths=[self.dir_path],
            nogc=True,
        )

        # Write C test driver that exercises both direct function calling and closure calling
        driver_c = self.dir_path / "test_driver.c"
        driver_c.write_text(
            '#include <stdio.h>\n'
            '#include <assert.h>\n'
            '#include "quest_runtime.h"\n'
            '#include "mathops.h"\n'
            '\n'
            'extern QRecordVal qv_mathops;\n'
            'extern void qv_mod_mathops_init(void);\n'
            'extern QInt qv_mathops_add(QInt a, QInt b);\n'
            'extern QInt qv_mathops_multiply(QInt a, QInt b);\n'
            '\n'
            'int main(void) {\n'
            '    quest_gc_init();\n'
            '    qv_mod_mathops_init();\n'
            '    /* 1. Direct C function call */\n'
            '    QInt sum = qv_mathops_add(40, 2);\n'
            '    assert(sum == 42);\n'
            '    QInt prod = qv_mathops_multiply(6, 7);\n'
            '    assert(prod == 42);\n'
            '    /* 2. Closure call through module record */\n'
            '    assert(qv_mathops.val != NULL);\n'
            '    printf("SUCCESS: %lld, %lld\\n", sum, prod);\n'
            '    return 0;\n'
            '}\n',
            encoding="utf-8",
        )

        compiler = find_c_compiler()
        bin_file = self.dir_path / "test_driver_bin"
        runtime_c = self.runtime_dir / "quest_runtime.c"
        serialization_c = self.runtime_dir / "quest_serialization.c"

        cmd = [
            compiler,
            "-std=c99",
            f"-I{self.runtime_dir}",
            f"-I{self.dir_path}",
            "-DQUEST_NOGC",
            str(driver_c),
            str(o_file),
            str(runtime_c),
            str(serialization_c),
            "-o",
            str(bin_file),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Compilation failed: {res.stderr}")

        exec_res = subprocess.run([str(bin_file)], capture_output=True, text=True)
        self.assertEqual(exec_res.returncode, 0, f"Execution failed: {exec_res.stderr}")
        self.assertIn("SUCCESS: 42, 42", exec_res.stdout)

    def test_cli_driver_separate_module_compilation(self) -> None:
        """Tests running quest -c <name>.mod.quest via the CLI driver."""
        intf_file = self.dir_path / "store.int.quest"
        intf_file.write_text(
            "interface Store export\n"
            "    val: Int\n"
            "end;\n",
            encoding="utf-8",
        )
        ret_intf = quest_driver.run_driver(["-c", str(intf_file), "-I", str(self.dir_path)])
        self.assertEqual(ret_intf, 0)

        mod_file = self.dir_path / "store.mod.quest"
        mod_file.write_text(
            "module store: Store export\n"
            "    let val: Int = 99;\n"
            "end;\n",
            encoding="utf-8",
        )
        ret_mod = quest_driver.run_driver(["-c", str(mod_file), "-I", str(self.dir_path)])
        self.assertEqual(ret_mod, 0)

        c_file = self.dir_path / "store.c"
        o_file = self.dir_path / "store.o"
        self.assertTrue(c_file.is_file())
        self.assertTrue(o_file.is_file())

    def test_emit_deps_flag(self) -> None:
        """Tests that --emit-deps generates .deps/<stem>.d with correct prerequisites."""
        intf_c = self.dir_path / "depc.int.quest"
        intf_c.write_text("interface DepC export val: Int end;\n", encoding="utf-8")
        self.assertEqual(quest_driver.run_driver(["-c", str(intf_c), "-I", str(self.dir_path)]), 0)

        mod_c = self.dir_path / "depc.mod.quest"
        mod_c.write_text("module depc: DepC export let val: Int = 10; end;\n", encoding="utf-8")
        ret_c = quest_driver.run_driver(["--emit-deps", "-c", str(mod_c), "-I", str(self.dir_path)])
        self.assertEqual(ret_c, 0)
        dep_c_file = self.dir_path / ".deps" / "depc.d"
        self.assertTrue(dep_c_file.is_file())
        self.assertEqual(dep_c_file.read_text(encoding="utf-8").strip(), "depc.o:")

        intf_b = self.dir_path / "depb.int.quest"
        intf_b.write_text(
            "interface DepB import c = depc : DepC export val: Int end;\n",
            encoding="utf-8",
        )
        self.assertEqual(quest_driver.run_driver(["-c", str(intf_b), "-I", str(self.dir_path)]), 0)

        mod_b = self.dir_path / "depb.mod.quest"
        mod_b.write_text(
            "module depb: DepB import c = depc : DepC export let val: Int = c.val + 20; end;\n",
            encoding="utf-8",
        )
        ret_b = quest_driver.run_driver(["--emit-deps", "-c", str(mod_b), "-I", str(self.dir_path)])
        self.assertEqual(ret_b, 0)
        dep_b_file = self.dir_path / ".deps" / "depb.d"
        self.assertTrue(dep_b_file.is_file())
        self.assertIn("depb.o:", dep_b_file.read_text(encoding="utf-8"))
        self.assertIn("depc.o", dep_b_file.read_text(encoding="utf-8"))

    def test_transitive_deps_linking(self) -> None:
        """Tests that compiler driver reads .d files to transitively link dependent .o files."""
        intf_c = self.dir_path / "basec.int.quest"
        intf_c.write_text("interface BaseC export getVal(): Int end;\n", encoding="utf-8")
        self.assertEqual(quest_driver.run_driver(["-c", str(intf_c), "-I", str(self.dir_path)]), 0)

        mod_c = self.dir_path / "basec.mod.quest"
        mod_c.write_text("module basec: BaseC export let getVal(): Int = 42; end;\n", encoding="utf-8")
        self.assertEqual(
            quest_driver.run_driver(["--emit-deps", "-c", str(mod_c), "-I", str(self.dir_path)]),
            0,
        )

        intf_b = self.dir_path / "midb.int.quest"
        intf_b.write_text("interface MidB import c = basec : BaseC export compute(): Int end;\n", encoding="utf-8")
        self.assertEqual(quest_driver.run_driver(["-c", str(intf_b), "-I", str(self.dir_path)]), 0)

        mod_b = self.dir_path / "midb.mod.quest"
        mod_b.write_text(
            "module midb: MidB import c = basec : BaseC export let compute(): Int = c.getVal() * 2; end;\n",
            encoding="utf-8",
        )
        self.assertEqual(
            quest_driver.run_driver(["--emit-deps", "-c", str(mod_b), "-I", str(self.dir_path)]),
            0,
        )

        main_file = self.dir_path / "main.quest"
        main_file.write_text(
            "import b = midb : MidB;\n"
            "import writer: Writer;\n"
            "import conv: Conv;\n"
            "writer.putString(writer.output conv.int(b.compute()));\n",
            encoding="utf-8",
        )
        res = quest_driver.run_driver([
            "--stop-after", "run_c_compiled",
            str(main_file),
            "-I", str(self.dir_path),
        ])
        self.assertEqual(res, 0)

    def test_module_manifest_with_imports(self) -> None:
        """Tests that .qm metadata captures imported modules and interfaces."""
        from quest.build.manifest import read_qm

        intf_c = self.dir_path / "depc.int.quest"
        intf_c.write_text("interface DepC export val: Int end;\n", encoding="utf-8")
        compile_interface_file(intf_c, output_dir=self.dir_path, include_paths=[self.dir_path])

        mod_c = self.dir_path / "depc.mod.quest"
        mod_c.write_text("module depc: DepC export let val: Int = 10; end;\n", encoding="utf-8")
        compile_module_file(mod_c, output_dir=self.dir_path, include_paths=[self.dir_path])

        intf_b = self.dir_path / "depb.int.quest"
        intf_b.write_text(
            "interface DepB import c = depc : DepC export val: Int end;\n",
            encoding="utf-8",
        )
        compile_interface_file(intf_b, output_dir=self.dir_path, include_paths=[self.dir_path])

        mod_b = self.dir_path / "depb.mod.quest"
        mod_b.write_text(
            "module depb: DepB import c = depc : DepC export let val: Int = c.val + 20; end;\n",
            encoding="utf-8",
        )
        res_b = compile_module_file(mod_b, output_dir=self.dir_path, include_paths=[self.dir_path])
        self.assertTrue(res_b.qm_file.is_file())

        manifest = read_qm(res_b.qm_file)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, "depb")
        self.assertEqual(manifest.interface, "DepB")
        # Imported modules
        self.assertEqual(len(manifest.imported_modules), 1)
        self.assertEqual(manifest.imported_modules[0].name, "depc")
        self.assertEqual(manifest.imported_modules[0].interface, "DepC")
        # Imported interfaces (DepB and DepC)
        iface_names = {i.name for i in manifest.imported_interfaces}
        self.assertIn("DepB", iface_names)
        self.assertIn("DepC", iface_names)

    def test_build_dir_support(self) -> None:
        """Tests compiling into a dedicated build_dir."""
        from quest.build.manifest import read_qm

        build_dir = self.dir_path / ".build"
        intf = self.dir_path / "calc.int.quest"
        intf.write_text("interface Calc export add(a: Int b: Int): Int end;\n", encoding="utf-8")
        compile_interface_file(intf, build_dir=build_dir, include_paths=[self.dir_path])

        self.assertTrue((build_dir / "calc.qi").is_file())
        self.assertTrue((build_dir / "calc.h").is_file())

        mod = self.dir_path / "calc.mod.quest"
        mod.write_text(
            "module calc: Calc export let add(a: Int b: Int): Int = a + b; end;\n",
            encoding="utf-8",
        )
        res = compile_module_file(mod, build_dir=build_dir, include_paths=[self.dir_path])
        self.assertTrue((build_dir / "calc.qm").is_file())
        self.assertTrue((build_dir / "calc.c").is_file())
        self.assertTrue((build_dir / "calc.o").is_file())

        manifest = read_qm(build_dir / "calc.qm")
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, "calc")


if __name__ == "__main__":
    unittest.main()

