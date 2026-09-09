"""Unit tests for Phase 6: Modules, Interfaces, Conformance, and Information Hiding."""

import unittest

from quest.diagnostics import QuestTypeError as TypeError
from quest.env import Environment
from quest.modules import (
    elaborate_interface,
    elaborate_module,
)
from quest.typechecker import (
    elaborate_program,
    synth_expr,
)
from quest.typed_ast import (
    TypedInterface,
    TypedModule,
    TypedProgram,
    TypedSelect,
)
from quest.types import (
    INT_TYPE,
    QRecordType,
    QTypeVar,
)
from tests.python.helpers import parse_expr, parse_phrase, run_source


class Phase6ModulesInterfacesTest(unittest.TestCase):
    """Test suite for interface declarations, module conformance, opacity, and qualified dot access."""

    def test_interface_elaboration_and_scope(self) -> None:
        """Elaborate an interface with abstract types and function signatures."""
        env = Environment()
        interface_src = """
        interface IntStack export
            Stack::TYPE
            empty: Stack
            push(s: Stack x: Int): Stack
            pop(s: Stack): Int
        end;
        """
        interface_decl = parse_phrase(interface_src)
        typed_interface = elaborate_interface(interface_decl, env)
        self.assertIsInstance(typed_interface, TypedInterface)
        self.assertEqual(typed_interface.name, "IntStack")

        # Verify registration in environment
        interface_scope = env.lookup_interface("IntStack")
        self.assertIsNotNone(interface_scope)
        self.assertIn("Stack", interface_scope.types)
        self.assertIn("empty", interface_scope.values)
        self.assertIn("push", interface_scope.values)
        self.assertIn("pop", interface_scope.values)

        stack_sym = interface_scope.lookup_type_local("Stack")
        self.assertIsNotNone(stack_sym)
        self.assertIsNone(stack_sym.definition)  # Abstract in interface

    def test_module_conformance_and_opaque_export(self) -> None:
        """Module implementing IntStack with concrete tuple representation."""
        env = Environment()
        interface_src = """
        interface IntStack export
            Stack::TYPE
            empty: Stack
        end;
        """
        elaborate_interface(parse_phrase(interface_src), env)

        module_src = """
        module intStack : IntStack export
            Let Stack = Tuple
                items: Array(Int)
                top: Int
            end;
            let empty = tuple
                let items = array of (10 0);
                let top = 0;
            end;
        end;
        """
        module_decl = parse_phrase(module_src)
        typed_module = elaborate_module(module_decl, env)
        self.assertIsInstance(typed_module, TypedModule)
        self.assertEqual(typed_module.name, "intStack")

        # Exported scope must have opaque abstract type outside the module
        module_scope = env.lookup_module("intStack")
        self.assertIsNotNone(module_scope)
        exported_stack = module_scope.lookup_type_local("Stack")
        self.assertIsNotNone(exported_stack)
        self.assertIsNone(exported_stack.definition)  # Information hiding!

        # Module value declared in environment
        mod_val_sym = env.lookup_value("intStack")
        self.assertIsNotNone(mod_val_sym)
        self.assertIsInstance(mod_val_sym.type_val, QRecordType)

    def test_module_qualified_access_and_information_hiding(self) -> None:
        """Accessing intStack.empty synthesizes intStack.Stack; accessing fields is rejected."""
        env = Environment()
        source = """
        interface IntStack export
            Stack::TYPE
            empty: Stack
            push(s: Stack x: Int): Stack
            pop(s: Stack): Int
        end;

        module intStack : IntStack export
            Let Stack = Tuple
                items: Array(Int)
                top: Int
            end;

            let empty = tuple
                let items = array of(10 0)
                let top = 0
            end;

            let push(s: Stack x: Int): Stack = s;
            let pop(s: Stack): Int = 0;
        end;
        """
        res = run_source(source, env=env)
        self.assertTrue(res.success)

        # 1. Qualified dot access: intStack.empty
        select_empty = parse_expr("intStack.empty")
        typed_empty = synth_expr(select_empty, env)
        self.assertIsInstance(typed_empty, TypedSelect)
        self.assertIsInstance(typed_empty.type_val, QTypeVar)
        self.assertEqual(typed_empty.type_val.name, "intStack.Stack")

        # 2. Qualified function call: intStack.push(intStack.empty 42)
        call_push = parse_expr("intStack.push(intStack.empty 42)")
        typed_push = synth_expr(call_push, env)
        self.assertEqual(typed_push.type_val, typed_empty.type_val)

        # 3. Qualified function call: intStack.pop(intStack.empty)
        call_pop = parse_expr("intStack.pop(intStack.empty)")
        typed_pop = synth_expr(call_pop, env)
        self.assertEqual(typed_pop.type_val, INT_TYPE)

        # 4. Information hiding: client cannot select .items on opaque intStack.Stack
        select_items = parse_expr("intStack.empty.items")
        with self.assertRaises(TypeError) as context:
            synth_expr(select_items, env)
        self.assertIn(
            "Cannot select field 'items' from non-record/tuple type 'intStack.Stack'",
            str(context.exception),
        )

    def test_manifest_type_transparency(self) -> None:
        """Manifest types in interfaces remain transparent outside the module."""
        env = Environment()
        source = """
        interface Math export
            Def Number = Int
            zero: Number
        end;

        module math : Math export
            Let Number = Int;
            let zero = 0;
        end;
        """
        res = run_source(source, env=env)
        self.assertTrue(res.success)

        select_zero = parse_expr("math.zero")
        typed_zero = synth_expr(select_zero, env)
        self.assertEqual(typed_zero.type_val, INT_TYPE)

    def test_interface_imports(self) -> None:
        """An interface can import types and values from another interface."""
        env = Environment()
        source = """
        interface Base export
            T::TYPE
            init: T
        end;

        interface Extended import T, init : Base; export
            step(x: T): T
        end;
        """
        res = run_source(source, env=env)
        self.assertTrue(res.success)

        extended_scope = env.lookup_interface("Extended")
        self.assertIsNotNone(extended_scope)
        self.assertIn("T", extended_scope.types)
        self.assertIn("init", extended_scope.values)
        self.assertIn("step", extended_scope.values)

    def test_module_missing_member_fails(self) -> None:
        """Module failing to implement an exported interface member raises TypeError."""
        env = Environment()
        source = """
        interface Counter export
            Count::TYPE
            zero: Count
            inc(c: Count): Count
        end;

        module counter : Counter export
            Let Count = Int;
            let zero = 0;
        end;
        """
        # Parsing succeeds, elaboration fails
        program = parse_phrase(source)
        with self.assertRaises(TypeError) as context:
            # We can run full program elaboration
            res = run_source(source, env=env)
            if res.has_errors:
                raise TypeError(res.diagnostics[0].message)
        self.assertIn("does not implement required value 'inc'", str(context.exception))

    def test_module_incompatible_type_fails(self) -> None:
        """Module implementing a value with an incompatible type raises TypeError."""
        env = Environment()
        source = """
        interface Greeter export
            greet: String
        end;

        module greeter : Greeter export
            let greet = 42;
        end;
        """
        with self.assertRaises(TypeError) as context:
            res = run_source(source, env=env)
            if res.has_errors:
                raise TypeError(res.diagnostics[0].message)
        self.assertIn("is not a subtype of interface signature", str(context.exception))

    def test_whole_program_elaboration_golden_file(self) -> None:
        """Whole-program elaboration on tests/source/06_interfaces_modules.quest succeeds."""
        env = Environment()
        with open("tests/source/06_interfaces_modules.quest") as f:
            text = f.read()

        res = run_source(text, env=env)
        self.assertTrue(res.success)
        typed_prog = res.artifacts.get("typecheck")
        self.assertIsInstance(typed_prog, TypedProgram)
        self.assertEqual(len(typed_prog.phrases), 2)
        self.assertIsInstance(typed_prog.phrases[0], TypedInterface)
        self.assertIsInstance(typed_prog.phrases[1], TypedModule)


if __name__ == "__main__":
    unittest.main()
