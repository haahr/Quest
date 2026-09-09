"""Unit tests for Quest builtins module builder, qchecked decorator, and registry."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.builtins import BuiltinModuleRegistry, ModuleBuilder, qchecked
from quest.interpreter import QuestException, QuestRuntimeError
from quest.runtime import QExceptionVal, QInt, QString
from quest.types import INT_TYPE, QAllType, QFunType, STRING_TYPE, TYPE_KIND


class TestBuiltinWrappers(unittest.TestCase):
    """Tests for qchecked decorator and ModuleBuilder."""

    def test_qchecked_success(self):
        err_exc = QExceptionVal("test.error")

        @qchecked(err_exc, QInt, QString)
        def dummy(n: QInt, s: QString) -> str:
            return f"{s.value}:{n.value}"

        res = dummy(QInt(42), QString("answer"))
        self.assertEqual(res, "answer:42")

    def test_qchecked_type_mismatch_raises_error_exc(self):
        err_exc = QExceptionVal("test.error")

        @qchecked(err_exc, QInt, QString)
        def dummy(n: QInt, s: QString) -> str:
            return f"{s.value}:{n.value}"

        with self.assertRaises(QuestException) as ctx:
            dummy(QString("not-int"), QString("valid"))
        self.assertEqual(ctx.exception.exc_val, err_exc)

    def test_qchecked_arg_count_mismatch_raises_error_exc(self):
        err_exc = QExceptionVal("test.error")

        @qchecked(err_exc, QInt)
        def dummy(n: QInt) -> int:
            return n.value

        with self.assertRaises(QuestException) as ctx:
            dummy()
        self.assertEqual(ctx.exception.exc_val, err_exc)

        with self.assertRaises(QuestException) as ctx:
            dummy(QInt(1), QInt(2))
        self.assertEqual(ctx.exception.exc_val, err_exc)

    def test_qchecked_without_error_exc_raises_descriptive_error(self):
        @qchecked(None, QInt)
        def dummy(n: QInt) -> int:
            return n.value

        with self.assertRaises(QuestRuntimeError) as ctx:
            dummy(QString("hello"))
        self.assertIn("Expected argument of type QInt, got QString", str(ctx.exception))

        with self.assertRaises(QuestRuntimeError) as ctx:
            dummy()
        self.assertIn("Expected 1 arguments, got 0", str(ctx.exception))

    def test_module_builder_declaration_and_finish(self):
        builder = ModuleBuilder("testMod", "TestMod", BuiltinModuleRegistry)
        builder.def_type("T", 9999, TYPE_KIND)
        builder.def_const("zero", INT_TYPE, QInt(0))
        builder.def_fn("succ", [("n", INT_TYPE)], INT_TYPE, lambda n: QInt(n.value + 1))
        builder.def_scope_val("hidden", STRING_TYPE)
        builder.def_poly_fn(
            "id",
            "A",
            9998,
            [("x", INT_TYPE)],
            INT_TYPE,
            lambda x: x,
        )

        try:
            rec = builder.finish()
            self.assertIn("zero", rec.fields)
            self.assertIn("succ", rec.fields)
            self.assertIn("id", rec.fields)
            self.assertNotIn("hidden", rec.fields)

            scope = BuiltinModuleRegistry.get_interface("TestMod")
            self.assertIsNotNone(scope)
            self.assertIn("T", scope.types)
            self.assertIn("zero", scope.values)
            self.assertIn("succ", scope.values)
            self.assertIn("hidden", scope.values)
            self.assertIn("id", scope.values)

            fn_sym = scope.lookup_value("succ")
            self.assertIsInstance(fn_sym.type_val, QFunType)

            poly_sym = scope.lookup_value("id")
            self.assertIsInstance(poly_sym.type_val, QAllType)

            mod_type = BuiltinModuleRegistry.get_module_type("testMod")
            self.assertIsNotNone(mod_type)
            field_names = [f.name for f in mod_type.fields]
            self.assertIn("zero", field_names)
            self.assertIn("hidden", field_names)
            self.assertIn("succ", field_names)
            self.assertIn("id", field_names)
        finally:
            BuiltinModuleRegistry._modules.pop("testMod", None)
            BuiltinModuleRegistry._interfaces.pop("TestMod", None)
            BuiltinModuleRegistry._module_types.pop("testMod", None)


if __name__ == "__main__":
    unittest.main()
