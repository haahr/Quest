"""Unit tests for Quest Interface Compiler (.int.quest -> .h + .qi).

Verifies Phase 4.16 Step 1:
- Compilation of interfaces with abstract types (erased to QVal in C headers).
- Compilation of manifest types (Def Point = Record ... end).
- Interface dependencies (import : Other) and recursive header inclusions.
- JSON/JSOG serialization parity using shadow Quest record schema.
- Direct loading of Scope from .qi files without .int.quest on disk.
- CLI driver invocation via `quest -c <file>.int.quest`.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from quest.env import Environment
from quest.interface_compiler import (
    compile_interface_file,
    load_interface_from_qi_file,
)
from quest.module_loader import load_interface


class TestInterfaceCompiler(unittest.TestCase):
    """Test suite for interface compilation (.int.quest -> .h and .qi)."""

    def test_compile_simple_interface(self) -> None:
        src = """
interface Counter
export
    T::TYPE
    new(init: Int): T
    inc(c: T): T
    get(c: T): Int
end;
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "counter.int.quest"
            p.write_text(src, encoding="utf-8")

            h_path, qi_path = compile_interface_file(p)
            self.assertTrue(h_path.exists())
            self.assertTrue(qi_path.exists())

            # Verify C header
            h_text = h_path.read_text(encoding="utf-8")
            self.assertIn("#ifndef QUEST_INTF_COUNTER_H", h_text)
            self.assertIn("typedef QVal quest_type_Counter_T;", h_text)
            self.assertIn("typedef QVal (*quest_sig_Counter_new)(QInt init);", h_text)
            self.assertIn("typedef QVal (*quest_sig_Counter_inc)(QVal c);", h_text)
            self.assertIn("typedef QInt (*quest_sig_Counter_get)(QVal c);", h_text)

            # Verify .qi metadata
            qi_text = qi_path.read_text(encoding="utf-8")
            self.assertIn('"name":"Counter"', qi_text)
            self.assertIn('"name":"T"', qi_text)
            self.assertIn('"isManifest":false', qi_text)
            self.assertIn('"name":"new"', qi_text)

            # Verify loading Scope from .qi
            env = Environment()
            scope = load_interface_from_qi_file(qi_path, env)
            self.assertIn("T", scope.types)
            self.assertIsNone(scope.types["T"].definition)
            self.assertIn("new", scope.values)
            self.assertIn("inc", scope.values)
            self.assertIn("get", scope.values)

    def test_compile_manifest_types(self) -> None:
        src = """
interface Geometry
export
    Def Point = Record x: Int y: Int end
    Shape::TYPE
    origin: Point
    area(s: Shape): Real
end;
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "geometry.int.quest"
            p.write_text(src, encoding="utf-8")

            h_path, qi_path = compile_interface_file(p)
            h_text = h_path.read_text(encoding="utf-8")
            self.assertIn("typedef struct quest_rec_Geometry_Point", h_text)
            self.assertIn("QInt x;", h_text)
            self.assertIn("QInt y;", h_text)
            self.assertIn("typedef QRecordVal quest_type_Geometry_Point;", h_text)
            self.assertIn("typedef QVal quest_type_Geometry_Shape;", h_text)

            env = Environment()
            scope = load_interface_from_qi_file(qi_path, env)
            self.assertIn("Point", scope.types)
            self.assertIsNotNone(scope.types["Point"].definition)
            self.assertIn("Shape", scope.types)
            self.assertIsNone(scope.types["Shape"].definition)

    def test_compile_interface_inheritance(self) -> None:
        c_src = """
interface BaseCounter
export
    T::TYPE
    new(init: Int): T
end;
"""
        ext_src = """
interface ExtCounter
import : BaseCounter
export
    reset(c: BaseCounter.T): BaseCounter.T
end;
"""
        with tempfile.TemporaryDirectory() as td:
            p_base = Path(td) / "basecounter.int.quest"
            p_base.write_text(c_src, encoding="utf-8")
            compile_interface_file(p_base)

            p_ext = Path(td) / "extcounter.int.quest"
            p_ext.write_text(ext_src, encoding="utf-8")
            h_ext, qi_ext = compile_interface_file(p_ext)

            h_text = h_ext.read_text(encoding="utf-8")
            self.assertIn('#include "basecounter.h"', h_text)
            self.assertIn("quest_sig_ExtCounter_reset", h_text)

            env = Environment()
            env.include_paths = [Path(td)]
            scope = load_interface_from_qi_file(qi_ext, env)
            self.assertIn("T", scope.types)
            self.assertIn("reset", scope.values)

    def test_module_loader_loads_qi_without_source(self) -> None:
        src = """
interface Tokenizer
export
    Token::TYPE
    nextToken(): Token
end;
"""
        with tempfile.TemporaryDirectory() as td:
            intf_file = Path(td) / "tokenizer.int.quest"
            intf_file.write_text(src, encoding="utf-8")
            _, qi_path = compile_interface_file(intf_file)

            # Delete the source interface file: only tokenizer.qi remains!
            intf_file.unlink()
            self.assertTrue(qi_path.exists())
            self.assertFalse(intf_file.exists())

            env = Environment()
            env.include_paths = [Path(td)]
            scope = load_interface("Tokenizer", env)
            self.assertIn("Token", scope.types)
            self.assertIn("nextToken", scope.values)

    def test_driver_cli_compile_only_interface(self) -> None:
        src = """
interface Calc
export
    add(a: Int b: Int): Int
end;
"""
        with tempfile.TemporaryDirectory() as td:
            intf_file = Path(td) / "calc.int.quest"
            intf_file.write_text(src, encoding="utf-8")

            driver_path = Path(__file__).parent.parent.parent / "bootstrap" / "python" / "quest_driver.py"
            cmd = [sys.executable, str(driver_path), "-c", str(intf_file)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Driver failed: {res.stderr}")

            h_file = Path(td) / "calc.h"
            qi_file = Path(td) / "calc.qi"
            self.assertTrue(h_file.exists())
            self.assertTrue(qi_file.exists())


if __name__ == "__main__":
    unittest.main()
