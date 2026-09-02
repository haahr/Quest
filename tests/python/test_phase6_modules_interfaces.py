"""Unit tests for Phase 6: Modules, Interfaces, Conformance, and Information Hiding."""

import unittest

import quest.ast as ast
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap
from quest.typechecker import TypeError, elaborate_interface, elaborate_module, elaborate_program, synth_expr
from quest.typed_ast import (
    TypedInterface,
    TypedModule,
    TypedProgram,
    TypedSelect,
)
from quest.types import (
    INT_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    QFunType,
    QParam,
    QRecordType,
    QTupleType,
    QTypeVar,
)


class Phase6ModulesInterfacesTest(unittest.TestCase):
    """Test suite for interface declarations, module conformance, opacity, and qualified dot access."""

    def test_interface_elaboration_and_scope(self) -> None:
        """Elaborate an interface with abstract types and function signatures."""
        env = Environment()
        interface_decl = ast.InterfaceDecl(
            name="IntStack",
            signatures=(
                ast.TypeFormal(name="Stack", bound=ast.KindType()),
                ast.FieldSig(name="empty", type_sig=ast.TypePath(("Stack",))),
                ast.FieldSig(
                    name="push",
                    type_sig=ast.TypeAll(
                        quantifiers=(
                            ast.Quantifier(name="s", bound=ast.KindPower(bound=ast.TypePath(("Stack",)))),
                            ast.Quantifier(name="x", bound=ast.KindPower(bound=ast.TypePath(("Int",)))),
                        ),
                        result_type=ast.TypePath(("Stack",)),
                    ),
                ),
                ast.FieldSig(
                    name="pop",
                    type_sig=ast.TypeAll(
                        quantifiers=(
                            ast.Quantifier(name="s", bound=ast.KindPower(bound=ast.TypePath(("Stack",)))),
                        ),
                        result_type=ast.TypePath(("Int",)),
                    ),
                ),
            ),
        )

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
        interface_decl = ast.InterfaceDecl(
            name="IntStack",
            signatures=(
                ast.TypeFormal(name="Stack", bound=ast.KindType()),
                ast.FieldSig(name="empty", type_sig=ast.TypePath(("Stack",))),
            ),
        )
        elaborate_interface(interface_decl, env)

        module_decl = ast.ModuleDecl(
            name="intStack",
            interface_name="IntStack",
            bindings=(
                ast.LetTypeBinding(
                    name="Stack",
                    type_val=ast.TypeTuple(
                        fields=(
                            ast.FieldSig(
                                name="items",
                                type_sig=ast.TypeArray(element_type=ast.TypePath(("Int",))),
                            ),
                            ast.FieldSig(name="top", type_sig=ast.TypePath(("Int",))),
                        )
                    ),
                ),
                ast.LetValueBinding(
                    name="empty",
                    value=ast.ExprTuple(
                        fields=(
                            ast.TupleBinding(
                                name="items",
                                value=ast.ExprArrayRep(count=ast.ExprInt(10, "10"), init_val=ast.ExprInt(0, "0")),
                            ),
                            ast.TupleBinding(name="top", value=ast.ExprInt(0, "0")),
                        )
                    ),
                ),
            ),
        )

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
        source_map = SourceMap(source, "test")
        tokens = Tokenizer(source, "test").tokenize_all()
        program = parse_quest_program(tokens, source_map)
        elaborate_program(program, env)

        # 1. Qualified dot access: intStack.empty
        select_empty = ast.ExprSelect(target=ast.ExprId(name="intStack"), field="empty")
        typed_empty = synth_expr(select_empty, env)
        self.assertIsInstance(typed_empty, TypedSelect)
        self.assertIsInstance(typed_empty.type_val, QTypeVar)
        self.assertEqual(typed_empty.type_val.name, "intStack.Stack")

        # 2. Qualified function call: intStack.push(intStack.empty 42)
        call_push = ast.ExprApp(
            func=ast.ExprSelect(target=ast.ExprId(name="intStack"), field="push"),
            args=(select_empty, ast.ExprInt(42, "42")),
        )
        typed_push = synth_expr(call_push, env)
        self.assertEqual(typed_push.type_val, typed_empty.type_val)

        # 3. Qualified function call: intStack.pop(intStack.empty)
        call_pop = ast.ExprApp(
            func=ast.ExprSelect(target=ast.ExprId(name="intStack"), field="pop"),
            args=(select_empty,),
        )
        typed_pop = synth_expr(call_pop, env)
        self.assertEqual(typed_pop.type_val, INT_TYPE)

        # 4. Information hiding: client cannot select .items on opaque intStack.Stack
        select_items = ast.ExprSelect(target=select_empty, field="items")
        with self.assertRaises(TypeError) as context:
            synth_expr(select_items, env)
        self.assertIn("Cannot select field 'items' from non-record/tuple type 'intStack.Stack'", str(context.exception))

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
        source_map = SourceMap(source, "test")
        tokens = Tokenizer(source, "test").tokenize_all()
        program = parse_quest_program(tokens, source_map)
        elaborate_program(program, env)

        select_zero = ast.ExprSelect(target=ast.ExprId(name="math"), field="zero")
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
        source_map = SourceMap(source, "test")
        tokens = Tokenizer(source, "test").tokenize_all()
        program = parse_quest_program(tokens, source_map)
        elaborate_program(program, env)

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
        source_map = SourceMap(source, "test")
        tokens = Tokenizer(source, "test").tokenize_all()
        program = parse_quest_program(tokens, source_map)
        with self.assertRaises(TypeError) as context:
            elaborate_program(program, env)
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
        source_map = SourceMap(source, "test")
        tokens = Tokenizer(source, "test").tokenize_all()
        program = parse_quest_program(tokens, source_map)
        with self.assertRaises(TypeError) as context:
            elaborate_program(program, env)
        self.assertIn("is not a subtype of interface signature", str(context.exception))

    def test_whole_program_elaboration_golden_file(self) -> None:
        """Whole-program elaboration on tests/source/06_interfaces_modules.quest succeeds."""
        env = Environment()
        with open("tests/source/06_interfaces_modules.quest") as f:
            text = f.read()

        source_map = SourceMap(text, "06_interfaces_modules.quest")
        tokens = Tokenizer(text, "06_interfaces_modules.quest").tokenize_all()
        ast_prog = parse_quest_program(tokens, source_map)
        typed_prog = elaborate_program(ast_prog, env)

        self.assertIsInstance(typed_prog, TypedProgram)
        self.assertEqual(len(typed_prog.phrases), 2)
        self.assertIsInstance(typed_prog.phrases[0], TypedInterface)
        self.assertIsInstance(typed_prog.phrases[1], TypedModule)


if __name__ == "__main__":
    unittest.main()
