"""Unit tests for hierarchical module and interface namespaces with aliasing."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bootstrap" / "python"))

import quest.ast as ast
from quest.codegen.compiler_runner import run_binary
from quest.grammar import parse_quest_program
from quest.interface_compiler import compile_interface_file
from quest.module_compiler import compile_module_file
from quest.pipeline import CompilerContext, CompilerOptions, default_pipeline
from quest.runtime import QInt
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap
from quest_driver import run_compile


def _parse(code: str) -> ast.Program:
    source_map = SourceMap(code, "<test>")
    tokens = Tokenizer(code, "<test>").tokenize_all()
    prog = parse_quest_program(tokens, source_map)
    assert isinstance(prog, ast.Program)
    return prog


class TestHierarchicalModuleSyntax(unittest.TestCase):
    """Tests syntax variations for hierarchical imports and aliasing."""

    def test_parse_dual_alias(self) -> None:
        prog = _parse("import rnd : Rnd = util/random : util/Random;")
        self.assertEqual(len(prog.phrases), 1)
        imp = prog.phrases[0]
        self.assertIsInstance(imp, ast.ImportPhrase)
        self.assertEqual(len(imp.items), 1)
        item = imp.items[0]
        self.assertEqual(item.names, ("rnd",))
        self.assertEqual(item.interface_name, "Rnd")
        self.assertEqual(item.effective_module_paths, ("util/random",))
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_module_alias_only(self) -> None:
        prog = _parse("import rnd = util/random : util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ("rnd",))
        self.assertEqual(item.interface_name, "Random")
        self.assertEqual(item.effective_module_paths, ("util/random",))
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_interface_alias_with_module(self) -> None:
        prog = _parse("import :Rnd = util/random : util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ("random",))
        self.assertEqual(item.interface_name, "Rnd")
        self.assertEqual(item.effective_module_paths, ("util/random",))
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_interface_only_with_alias(self) -> None:
        prog = _parse("import :Rnd = :util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ())
        self.assertEqual(item.interface_name, "Rnd")
        self.assertEqual(item.effective_module_paths, ())
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_interface_only_unaliased(self) -> None:
        prog = _parse("import :util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ())
        self.assertEqual(item.interface_name, "Random")
        self.assertEqual(item.effective_module_paths, ())
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_hierarchical_unaliased(self) -> None:
        prog = _parse("import util/random : util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ("random",))
        self.assertEqual(item.interface_name, "Random")
        self.assertEqual(item.effective_module_paths, ("util/random",))
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_comma_separated_aliased_entries(self) -> None:
        prog = _parse("import r1 = p1/mod1, r2 = p2/mod2 : util/Random;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ("r1", "r2"))
        self.assertEqual(item.interface_name, "Random")
        self.assertEqual(item.effective_module_paths, ("p1/mod1", "p2/mod2"))
        self.assertEqual(item.effective_interface_path, "util/Random")

    def test_parse_deep_hierarchy(self) -> None:
        prog = _parse("import a/b/c/d : A/B/C/D;")
        item = prog.phrases[0].items[0]
        self.assertEqual(item.names, ("d",))
        self.assertEqual(item.interface_name, "D")
        self.assertEqual(item.effective_module_paths, ("a/b/c/d",))
        self.assertEqual(item.effective_interface_path, "A/B/C/D")

    def test_division_operator_undisturbed(self) -> None:
        prog = _parse("let x: Int = 10 / 2;")
        self.assertEqual(len(prog.phrases), 1)
        binding = prog.phrases[0]
        self.assertIsInstance(binding, ast.LetValueBinding)
        self.assertIsInstance(binding.value, ast.ExprInfix)
        self.assertEqual(binding.value.op, "/")


class TestHierarchicalModuleExecution(unittest.TestCase):
    """End-to-end tests for hierarchical module loading, typechecking, and execution."""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="quest_hier_test_")
        self.root = Path(self.test_dir)
        self.pipeline = default_pipeline()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def _run_pipeline(self, file_path: Path, options: CompilerOptions | None = None):
        source_text = file_path.read_text(encoding="utf-8")
        ctx = CompilerContext.create(source_text, file_name=str(file_path), options=options)
        res = self.pipeline.execute(source_text, file_name=str(file_path), options=options, ctx=ctx)
        return res, ctx

    def test_hierarchical_modules_interpreter(self) -> None:
        util_dir = self.root / "util"
        util_dir.mkdir(parents=True)

        (util_dir / "helper.int.quest").write_text(
            "interface Helper\n"
            "export\n"
            "    offset: Int\n"
            "end;\n",
            encoding="utf-8",
        )
        (util_dir / "helper.mod.quest").write_text(
            "module helper : Helper\n"
            "export\n"
            "    let offset: Int = 5;\n"
            "end;\n",
            encoding="utf-8",
        )

        (util_dir / "math.int.quest").write_text(
            "interface Math\n"
            "export\n"
            "    add(a: Int b: Int): Int\n"
            "    addWithOffset(a: Int): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        # Sibling import without prefix inside util/math.mod.quest
        (util_dir / "math.mod.quest").write_text(
            "module math : Math\n"
            "import helper : Helper;\n"
            "export\n"
            "    let add(a: Int b: Int): Int = a + b;\n"
            "    let addWithOffset(a: Int): Int = add(a helper.offset);\n"
            "end;\n",
            encoding="utf-8",
        )

        main_quest = self.root / "main.quest"
        main_quest.write_text(
            "import m : M = util/math : util/Math;\n"
            "let res1: Int = m.add(10 20);\n"
            "let res2: Int = m.addWithOffset(100);\n"
            "let result: Int = res1 + res2;\n",
            encoding="utf-8",
        )

        options = CompilerOptions(include_paths=[self.root])
        res, ctx = self._run_pipeline(main_quest, options=options)
        self.assertTrue(res.success, f"Pipeline diagnostics: {res.diagnostics}")
        val = ctx.runtime_env.lookup("result")
        self.assertEqual(val, QInt(135))

    def test_hierarchical_manifest_type_alias_interpreter(self) -> None:
        geom_dir = self.root / "geom"
        geom_dir.mkdir(parents=True)

        (geom_dir / "point.int.quest").write_text(
            "interface Point\n"
            "export\n"
            "    Def T = Record x: Int y: Int end\n"
            "    make(x: Int y: Int): T\n"
            "    sumCoords(p: T): Int\n"
            "end;\n",
            encoding="utf-8",
        )
        (geom_dir / "point.mod.quest").write_text(
            "module point : Point\n"
            "export\n"
            "    Let T = Record x: Int y: Int end;\n"
            "    let make(x: Int y: Int): T = record x = x y = y end;\n"
            "    let sumCoords(p: T): Int = p.x + p.y;\n"
            "end;\n",
            encoding="utf-8",
        )

        main_quest = self.root / "main.quest"
        main_quest.write_text(
            "import pt : Pt = geom/point : geom/Point;\n"
            "let p: Pt_T = pt.make(15 27);\n"
            "let result: Int = pt.sumCoords(p);\n",
            encoding="utf-8",
        )

        options = CompilerOptions(include_paths=[self.root])
        res, ctx = self._run_pipeline(main_quest, options=options)
        self.assertTrue(res.success, f"Pipeline diagnostics: {res.diagnostics}")
        val = ctx.runtime_env.lookup("result")
        self.assertEqual(val, QInt(42))

    def test_hierarchical_c_compilation_and_execution(self) -> None:
        util_dir = self.root / "util"
        util_dir.mkdir(parents=True)

        intf_file = util_dir / "calc.int.quest"
        intf_file.write_text(
            "interface Calc\n"
            "export\n"
            "    multiply(a: Int b: Int): Int\n"
            "end;\n",
            encoding="utf-8",
        )

        mod_file = util_dir / "calc.mod.quest"
        mod_file.write_text(
            "module calc : Calc\n"
            "export\n"
            "    let multiply(a: Int b: Int): Int = a * b;\n"
            "end;\n",
            encoding="utf-8",
        )

        # Precompile interface and module
        compile_interface_file(intf_file, output_dir=util_dir, include_paths=[self.root])
        compile_module_file(mod_file, output_dir=util_dir, include_paths=[self.root])

        # Remove source to ensure client links against precompiled .o
        mod_file.unlink()

        # Verify compiled artifacts were produced with correct paths
        self.assertTrue((util_dir / "calc.h").is_file())
        self.assertTrue((util_dir / "calc.qi").is_file())
        self.assertTrue((util_dir / "calc.o").is_file())

        main_quest = self.root / "main.quest"
        main_quest.write_text(
            "import c = util/calc : util/Calc;\n"
            "import writer : Writer;\n"
            "import conv : Conv;\n"
            "writer.putString(writer.output conv.int(c.multiply(6 7)));\n",
            encoding="utf-8",
        )

        out_bin = self.root / "main_bin"
        ret = run_compile([
            str(main_quest),
            str(util_dir / "calc.o"),
            "-o", str(out_bin),
            "-I", str(self.root),
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_bin.exists())

        proc = run_binary(out_bin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "42")


if __name__ == "__main__":
    unittest.main()
