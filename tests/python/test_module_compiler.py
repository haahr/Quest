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

        self.assertTrue(c_file.is_file())
        self.assertTrue(o_file.is_file())

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


if __name__ == "__main__":
    unittest.main()
