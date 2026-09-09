"""Unit tests for Quest Module, Interface, and Import Elaboration (quest/modules.py)."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

import quest.ast as ast
from quest.diagnostics import QuestTypeError
from quest.env import Environment
from quest.modules import (
    elaborate_import,
    elaborate_interface,
    elaborate_module,
)
from quest.typed_ast import (
    TypedImport,
    TypedInterface,
    TypedModule,
)
from quest.types import (
    INT_TYPE,
    TYPE_KIND,
    QRecordType,
    QTypeVar,
)
from tests.python.helpers import parse_phrase


class TestModulesElaboration(unittest.TestCase):
    """Direct unit tests for quest.modules functions."""

    def setUp(self):
        self.env = Environment()

    def test_elaborate_interface_declarations(self):
        code = """
        interface Counter
        export
            T::TYPE
            Def Zero = Int
            new(): T
            inc(c: T): T
            get(c: T): Int
        end;
        """
        ast_node = parse_phrase(code)
        self.assertIsInstance(ast_node, ast.InterfaceDecl)
        typed_iface = elaborate_interface(ast_node, self.env)

        self.assertIsInstance(typed_iface, TypedInterface)
        self.assertEqual(typed_iface.name, "Counter")

        iface_scope = self.env.lookup_interface("Counter")
        self.assertIsNotNone(iface_scope)
        self.assertIn("T", iface_scope.types)
        self.assertIn("Zero", iface_scope.types)
        self.assertIn("new", iface_scope.values)
        self.assertIn("inc", iface_scope.values)
        self.assertIn("get", iface_scope.values)

        # Abstract type has None definition
        t_sym = iface_scope.lookup_type_local("T")
        self.assertIsNone(t_sym.definition)

        # Manifest type has concrete definition
        zero_sym = iface_scope.lookup_type_local("Zero")
        self.assertEqual(zero_sym.definition, INT_TYPE)

    def test_elaborate_module_conformance_success(self):
        iface_code = """
        interface Box
        export
            T::TYPE
            make(x: Int): T
            unbox(b: T): Int
        end;
        """
        iface_node = parse_phrase(iface_code)
        elaborate_interface(iface_node, self.env)

        mod_code = """
        module box : Box
        export
            Let T = Int;
            let make(x: Int): T = x;
            let unbox(b: T): Int = b;
        end;
        """
        mod_node = parse_phrase(mod_code)
        self.assertIsInstance(mod_node, ast.ModuleDecl)
        typed_mod = elaborate_module(mod_node, self.env)

        self.assertIsInstance(typed_mod, TypedModule)
        self.assertEqual(typed_mod.name, "box")
        self.assertEqual(typed_mod.interface_name, "Box")

        # Module is registered in environment
        mod_scope = self.env.lookup_module("box")
        self.assertIsNotNone(mod_scope)

        # Abstract type T is opaque in export scope
        exp_t = mod_scope.lookup_type_local("T")
        self.assertIsNone(exp_t.definition)

        # Module record value is bound in current scope
        val_sym = self.env.lookup_value("box")
        self.assertIsNotNone(val_sym)
        self.assertIsInstance(val_sym.type_val, QRecordType)

    def test_elaborate_module_missing_type_raises(self):
        iface_code = """
        interface I
        export
            T::TYPE
        end;
        """
        elaborate_interface(parse_phrase(iface_code), self.env)

        mod_code = """
        module m : I
        export
            let x = 1;
        end;
        """
        with self.assertRaises(QuestTypeError) as ctx:
            elaborate_module(parse_phrase(mod_code), self.env)
        self.assertIn("does not implement required type 'T'", str(ctx.exception))

    def test_elaborate_module_missing_value_raises(self):
        iface_code = """
        interface I
        export
            req: Int
        end;
        """
        elaborate_interface(parse_phrase(iface_code), self.env)

        mod_code = """
        module m : I
        export
            let other = 1;
        end;
        """
        with self.assertRaises(QuestTypeError) as ctx:
            elaborate_module(parse_phrase(mod_code), self.env)
        self.assertIn("does not implement required value 'req'", str(ctx.exception))

    def test_elaborate_module_value_type_mismatch_raises(self):
        iface_code = """
        interface I
        export
            num: Int
        end;
        """
        elaborate_interface(parse_phrase(iface_code), self.env)

        mod_code = """
        module m : I
        export
            let num = true;
        end;
        """
        with self.assertRaises(QuestTypeError) as ctx:
            elaborate_module(parse_phrase(mod_code), self.env)
        self.assertIn("not a subtype of interface signature", str(ctx.exception))

    def test_elaborate_import_builtin_modules(self):
        code = "import ascii: Ascii int: IntOp;"
        phrase = parse_phrase(code)
        self.assertIsInstance(phrase, ast.ImportPhrase)

        typed_imp = elaborate_import(phrase, self.env)
        self.assertIsInstance(typed_imp, TypedImport)
        self.assertEqual(len(typed_imp.items), 2)

        # ascii and int modules are declared in current scope
        self.assertIsNotNone(self.env.lookup_value("ascii"))
        self.assertIsNotNone(self.env.lookup_value("int"))

    def test_elaborate_import_direct_interface(self):
        code = "import : Ascii;"
        phrase = parse_phrase(code)
        typed_imp = elaborate_import(phrase, self.env)
        self.assertIsInstance(typed_imp, TypedImport)

        # Ascii interface types should be bound into scope
        iface = self.env.lookup_interface("Ascii")
        self.assertIsNotNone(iface)

    def test_elaborate_import_undefined_interface_raises(self):
        code = "import bogus: NonExistentInterface;"
        phrase = parse_phrase(code)
        with self.assertRaises(QuestTypeError) as ctx:
            elaborate_import(phrase, self.env)
        self.assertIn("Undefined interface 'NonExistentInterface'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
