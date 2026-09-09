"""Comprehensive Unit Tests for Quest Typechecker (Phase 2)."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.elaborate_types import (
    elaborate_mutual_rec_type_group,
    elaborate_type,
    elaborate_type_binding,
)
from quest.env import (
    Environment,
    ValueSymbol,
)
from quest.tokens import SourceMap
from quest.typechecker import (
    TypeError as QuestTypeError,
    check_expr,
    synth_expr,
)
from quest.typed_ast import (
    TypedAssign,
    TypedBlock,
    TypedDerefCell,
    TypedFor,
    TypedIf,
    TypedInfix,
    TypedVar,
    TypedWhile,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    INT_TYPE,
    KindError,
    OK_TYPE,
    QVarType,
    REAL_TYPE,
    STRING_TYPE,
)
from tests.python.helpers import parse_expr, parse_phrase, parse_type


class TestTypecheckerPhase2(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

    def test_literals_synthesis(self):
        self.assertEqual(synth_expr(parse_expr("42"), self.env).type_val, INT_TYPE)
        self.assertEqual(synth_expr(parse_expr("3.14"), self.env).type_val, REAL_TYPE)
        self.assertEqual(synth_expr(parse_expr("true"), self.env).type_val, BOOL_TYPE)
        self.assertEqual(synth_expr(parse_expr("'z'"), self.env).type_val, CHAR_TYPE)
        self.assertEqual(synth_expr(parse_expr('"abc"'), self.env).type_val, STRING_TYPE)
        self.assertEqual(synth_expr(parse_expr("ok"), self.env).type_val, OK_TYPE)

    def test_variables_and_implicit_dereferencing(self):
        # Immutable variable: let x: Int = 10
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        self.env.global_scope.declare_value(sym_x)
        typed_x = synth_expr(parse_expr("x"), self.env)
        self.assertIsInstance(typed_x, TypedVar)
        self.assertEqual(typed_x.type_val, INT_TYPE)

        # Mutable variable: let var y: Int = 20
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_y)
        typed_y = synth_expr(parse_expr("y"), self.env)
        # Implicit dereference in value position
        self.assertIsInstance(typed_y, TypedDerefCell)
        self.assertEqual(typed_y.type_val, INT_TYPE)
        self.assertIsInstance(typed_y.target, TypedVar)
        self.assertEqual(typed_y.target.type_val, QVarType(INT_TYPE))

        # Undefined variable
        with self.assertRaises(QuestTypeError):
            synth_expr(parse_expr("undefinedVar"), self.env)

    def test_explicit_dereferencing(self):
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_y)
        # Explicit @y
        typed_at_y = synth_expr(parse_expr("@y"), self.env)
        self.assertIsInstance(typed_at_y, TypedDerefCell)
        self.assertEqual(typed_at_y.type_val, INT_TYPE)

        # Error when dereferencing non-var
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        self.env.global_scope.declare_value(sym_x)
        with self.assertRaises(QuestTypeError):
            synth_expr(parse_expr("@x"), self.env)

    def test_assignment_mutability_and_types(self):
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_x)
        self.env.global_scope.declare_value(sym_y)

        # Valid assignment to var: y := 42
        assign_ast = parse_expr("y := 42")
        typed_assign = synth_expr(assign_ast, self.env)
        self.assertIsInstance(typed_assign, TypedAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

        # Invalid assignment to immutable: x := 42
        bad_assign = parse_expr("x := 42")
        with self.assertRaises(QuestTypeError):
            synth_expr(bad_assign, self.env)

        # Type mismatch on assignment: y := "hello"
        type_mismatch = parse_expr('y := "hello"')
        with self.assertRaises(QuestTypeError):
            synth_expr(type_mismatch, self.env)

    def test_infix_arithmetic_and_no_numeric_coercion(self):
        # Valid Int arithmetic
        plus_int = parse_expr("1 + 2")
        typed_plus_int = synth_expr(plus_int, self.env)
        self.assertIsInstance(typed_plus_int, TypedInfix)
        self.assertEqual(typed_plus_int.type_val, INT_TYPE)

        # Valid Real arithmetic
        plus_real = parse_expr("1.0 + 2.5")
        typed_plus_real = synth_expr(plus_real, self.env)
        self.assertIsInstance(typed_plus_real, TypedInfix)
        self.assertEqual(typed_plus_real.type_val, REAL_TYPE)

        # Mixed Int + Real: STRICT REJECTION (no numeric coercion)
        mixed_plus = parse_expr("1 + 2.0")
        with self.assertRaises(QuestTypeError):
            synth_expr(mixed_plus, self.env)

        # % on Int vs % on Real
        mod_int = parse_expr("10 % 3")
        self.assertEqual(synth_expr(mod_int, self.env).type_val, INT_TYPE)

        mod_real = parse_expr("10.0 % 3.0")
        with self.assertRaises(QuestTypeError):
            synth_expr(mod_real, self.env)

    def test_short_circuit_logic_desugaring(self):
        and_expr = parse_expr("true andif false")
        typed_and = synth_expr(and_expr, self.env)
        self.assertIsInstance(typed_and, TypedIf)
        self.assertEqual(typed_and.type_val, BOOL_TYPE)

        or_expr = parse_expr("false orif true")
        typed_or = synth_expr(or_expr, self.env)
        self.assertIsInstance(typed_or, TypedIf)
        self.assertEqual(typed_or.type_val, BOOL_TYPE)

    def test_relational_and_equality_operators(self):
        # Relational <
        lt_expr = parse_expr("3 < 5")
        self.assertEqual(synth_expr(lt_expr, self.env).type_val, BOOL_TYPE)

        # Equality is
        is_expr = parse_expr('"a" is "b"')
        self.assertEqual(synth_expr(is_expr, self.env).type_val, BOOL_TYPE)

        # Incompatible comparison
        bad_cmp = parse_expr('3 < "hello"')
        with self.assertRaises(QuestTypeError):
            synth_expr(bad_cmp, self.env)

    def test_if_with_else_and_branch_join(self):
        if_expr = parse_expr("if true then 10 else 20 end")
        typed_if = synth_expr(if_expr, self.env)
        self.assertIsInstance(typed_if, TypedIf)
        self.assertEqual(typed_if.type_val, INT_TYPE)

        # Check bidirectional checking against expected type
        checked_if = check_expr(if_expr, INT_TYPE, self.env)
        self.assertEqual(checked_if.type_val, INT_TYPE)

    def test_if_without_else_ignores_then_return_value(self):
        # if cond then 42 end: then branch returns Int, but value is ignored and if returns Ok
        if_stmt = parse_expr("if true then 42 end")
        typed_if = synth_expr(if_stmt, self.env)
        self.assertIsInstance(typed_if, TypedIf)
        self.assertEqual(typed_if.type_val, OK_TYPE)
        self.assertEqual(typed_if.else_branch.type_val, OK_TYPE)

    def test_while_loop_and_exit(self):
        while_expr = parse_expr("while true do exit end")
        typed_while = synth_expr(while_expr, self.env)
        self.assertIsInstance(typed_while, TypedWhile)
        self.assertEqual(typed_while.type_val, OK_TYPE)

        # Exit outside of loop
        with self.assertRaises(QuestTypeError):
            synth_expr(parse_expr("exit"), self.env)

    def test_for_loop(self):
        # for i = 1 upto 10 do ... end
        for_expr = parse_expr("for i = 1 upto 10 do i end")
        typed_for = synth_expr(for_expr, self.env)
        self.assertIsInstance(typed_for, TypedFor)
        self.assertEqual(typed_for.type_val, OK_TYPE)
        self.assertEqual(typed_for.var_name, "i")
        self.assertEqual(typed_for.symbol.type_val, INT_TYPE)

    def test_block_expressions_and_scoping(self):
        # begin let a = 10; let b = 20; a + b end
        block_ast = parse_expr("begin let a = 10; let b = 20; a + b end")
        typed_block = synth_expr(block_ast, self.env)
        self.assertIsInstance(typed_block, TypedBlock)
        self.assertEqual(typed_block.type_val, INT_TYPE)
        self.assertEqual(len(typed_block.bindings), 2)
        self.assertEqual(typed_block.result.type_val, INT_TYPE)

        # Scoped bindings do not leak into outer environment
        self.assertIsNone(self.env.lookup_value("a"))
        self.assertIsNone(self.env.lookup_value("b"))

    def test_error_formatting_with_source(self):
        source = "let x: Int = true;"
        sm = SourceMap(source, "test.quest")
        type_err = QuestTypeError("Type mismatch: expected Int, got Bool", offset=13)
        formatted = type_err.format_with_source(sm, length=4)
        self.assertIn("test.quest:1:14: error: Type mismatch", formatted)
        self.assertIn("let x: Int = true;", formatted)
        self.assertIn("^^^^", formatted)

        kind_err = KindError("Kind mismatch", offset=4)
        kind_formatted = kind_err.format_with_source(sm, length=1)
        self.assertIn("test.quest:1:5: error: Kind mismatch", kind_formatted)
        self.assertIn("^", kind_formatted)


class TestRecursiveContractiveness(unittest.TestCase):
    """Tests for recursive type contractiveness verification (C \succ X)."""

    def setUp(self):
        self.env = Environment()

    def test_valid_contractive_recursive_types(self):
        # 1. Recursive Record: Let Rec List = Tuple head: Int tail: List end;
        list_ast = parse_phrase("Let Rec List = Tuple head: Int tail: List end;")
        sym = elaborate_type_binding(list_ast, self.env)
        self.assertEqual(sym.name, "List")

        # 2. Recursive Function: Let Rec FunType = Tuple f: Tuple arg: Int res: FunType end end;
        fun_ast = parse_phrase("Let Rec FunType = Tuple f: Tuple arg: Int res: FunType end end;")
        sym_fun = elaborate_type_binding(fun_ast, self.env)
        self.assertEqual(sym_fun.name, "FunType")

        # 3. Recursive Option: Let Rec Tree = Option empty node with t: Tree end end;
        tree_ast = parse_phrase("Let Rec Tree = Option empty node with t: Tree end end;")
        sym_tree = elaborate_type_binding(tree_ast, self.env)
        self.assertEqual(sym_tree.name, "Tree")

    def test_reject_immediate_bare_recursion(self):
        # Let Rec Bad = Bad;
        bad_ast = parse_phrase("Let Rec Bad = Bad;")
        with self.assertRaises(KindError) as ctx:
            elaborate_type_binding(bad_ast, self.env)
        self.assertIn("not contractive", str(ctx.exception))

    def test_reject_nested_bare_recursion(self):
        # Rec(Bad::TYPE) Rec(Inner::TYPE) Bad
        nested_ast = parse_type("Rec(Bad::TYPE) Rec(Inner::TYPE) Bad")
        with self.assertRaises(KindError) as ctx:
            elaborate_type(nested_ast, self.env)
        self.assertIn("not contractive", str(ctx.exception))

    def test_reject_mutual_bare_recursion(self):
        # Let Rec A = B and B = A;
        b1 = parse_phrase("Let Rec A = B;")
        b2 = parse_phrase("Let Rec B = A;")
        with self.assertRaises(KindError) as ctx:
            elaborate_mutual_rec_type_group([b1, b2], self.env)
        self.assertIn("not contractive", str(ctx.exception))

    def test_reject_inline_bare_rec_type(self):
        # Rec(X::TYPE) X
        inline_ast = parse_type("Rec(X::TYPE) X")
        with self.assertRaises(KindError) as ctx:
            elaborate_type(inline_ast, self.env)
        self.assertIn("not contractive", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
