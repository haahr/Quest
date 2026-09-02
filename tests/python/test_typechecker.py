"""Comprehensive Unit Tests for Quest Typechecker (Phase 2)."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

import quest.ast as ast
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    INT_TYPE,
    OK_TYPE,
    QVarType,
    REAL_TYPE,
    STRING_TYPE,
)
from quest.env import (
    Environment,
    ValueSymbol,
)
from quest.typechecker import (
    TypeError as QuestTypeError,
    check_expr,
    synth_expr,
)
from quest.typed_ast import (
    TypedAssign,
    TypedBlock,
    TypedBool,
    TypedChar,
    TypedDerefCell,
    TypedExit,
    TypedExprStmt,
    TypedFor,
    TypedIf,
    TypedInfix,
    TypedInt,
    TypedLetValue,
    TypedLoop,
    TypedOk,
    TypedReal,
    TypedString,
    TypedVar,
    TypedWhile,
)


class TestTypecheckerPhase2(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

    def test_literals_synthesis(self):
        self.assertEqual(synth_expr(ast.ExprInt(42, "42"), self.env).type_val, INT_TYPE)
        self.assertEqual(synth_expr(ast.ExprReal(3.14, "3.14"), self.env).type_val, REAL_TYPE)
        self.assertEqual(synth_expr(ast.ExprBool(True), self.env).type_val, BOOL_TYPE)
        self.assertEqual(synth_expr(ast.ExprChar("z", "'z'"), self.env).type_val, CHAR_TYPE)
        self.assertEqual(synth_expr(ast.ExprString("abc", '"abc"'), self.env).type_val, STRING_TYPE)
        self.assertEqual(synth_expr(ast.ExprOk(), self.env).type_val, OK_TYPE)

    def test_variables_and_implicit_dereferencing(self):
        # Immutable variable: let x: Int = 10
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        self.env.global_scope.declare_value(sym_x)
        typed_x = synth_expr(ast.ExprId("x"), self.env)
        self.assertIsInstance(typed_x, TypedVar)
        self.assertEqual(typed_x.type_val, INT_TYPE)

        # Mutable variable: let var y: Int = 20
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_y)
        typed_y = synth_expr(ast.ExprId("y"), self.env)
        # Implicit dereference in value position
        self.assertIsInstance(typed_y, TypedDerefCell)
        self.assertEqual(typed_y.type_val, INT_TYPE)
        self.assertIsInstance(typed_y.target, TypedVar)
        self.assertEqual(typed_y.target.type_val, QVarType(INT_TYPE))

        # Undefined variable
        with self.assertRaises(QuestTypeError):
            synth_expr(ast.ExprId("undefined_var"), self.env)

    def test_explicit_dereferencing(self):
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_y)
        # Explicit @y
        typed_at_y = synth_expr(ast.ExprDerefCell(target=ast.ExprId("y")), self.env)
        self.assertIsInstance(typed_at_y, TypedDerefCell)
        self.assertEqual(typed_at_y.type_val, INT_TYPE)

        # Error when dereferencing non-var
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        self.env.global_scope.declare_value(sym_x)
        with self.assertRaises(QuestTypeError):
            synth_expr(ast.ExprDerefCell(target=ast.ExprId("x")), self.env)

    def test_assignment_mutability_and_types(self):
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE, is_var=False)
        sym_y = ValueSymbol(name="y", type_val=INT_TYPE, is_var=True)
        self.env.global_scope.declare_value(sym_x)
        self.env.global_scope.declare_value(sym_y)

        # Valid assignment to var: y := 42
        assign_ast = ast.ExprInfix(left=ast.ExprId("y"), op=":=", right=ast.ExprInt(42, "42"))
        typed_assign = synth_expr(assign_ast, self.env)
        self.assertIsInstance(typed_assign, TypedAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

        # Invalid assignment to immutable: x := 42
        bad_assign = ast.ExprInfix(left=ast.ExprId("x"), op=":=", right=ast.ExprInt(42, "42"))
        with self.assertRaises(QuestTypeError):
            synth_expr(bad_assign, self.env)

        # Type mismatch on assignment: y := "hello"
        type_mismatch = ast.ExprInfix(left=ast.ExprId("y"), op=":=", right=ast.ExprString("hello", '"hello"'))
        with self.assertRaises(QuestTypeError):
            synth_expr(type_mismatch, self.env)

    def test_infix_arithmetic_and_no_numeric_coercion(self):
        # Valid Int arithmetic
        plus_int = ast.ExprInfix(left=ast.ExprInt(1, "1"), op="+", right=ast.ExprInt(2, "2"))
        typed_plus_int = synth_expr(plus_int, self.env)
        self.assertIsInstance(typed_plus_int, TypedInfix)
        self.assertEqual(typed_plus_int.type_val, INT_TYPE)

        # Valid Real arithmetic
        plus_real = ast.ExprInfix(left=ast.ExprReal(1.0, "1.0"), op="+", right=ast.ExprReal(2.5, "2.5"))
        typed_plus_real = synth_expr(plus_real, self.env)
        self.assertIsInstance(typed_plus_real, TypedInfix)
        self.assertEqual(typed_plus_real.type_val, REAL_TYPE)

        # Mixed Int + Real: STRICT REJECTION (no numeric coercion)
        mixed_plus = ast.ExprInfix(left=ast.ExprInt(1, "1"), op="+", right=ast.ExprReal(2.0, "2.0"))
        with self.assertRaises(QuestTypeError):
            synth_expr(mixed_plus, self.env)

        # mod on Int vs mod on Real
        mod_int = ast.ExprInfix(left=ast.ExprInt(10, "10"), op="mod", right=ast.ExprInt(3, "3"))
        self.assertEqual(synth_expr(mod_int, self.env).type_val, INT_TYPE)

        mod_real = ast.ExprInfix(left=ast.ExprReal(10.0, "10.0"), op="mod", right=ast.ExprReal(3.0, "3.0"))
        with self.assertRaises(QuestTypeError):
            synth_expr(mod_real, self.env)

    def test_short_circuit_logic_desugaring(self):
        and_expr = ast.ExprInfix(left=ast.ExprBool(True), op="andif", right=ast.ExprBool(False))
        typed_and = synth_expr(and_expr, self.env)
        self.assertIsInstance(typed_and, TypedIf)
        self.assertEqual(typed_and.type_val, BOOL_TYPE)

        or_expr = ast.ExprInfix(left=ast.ExprBool(False), op="orif", right=ast.ExprBool(True))
        typed_or = synth_expr(or_expr, self.env)
        self.assertIsInstance(typed_or, TypedIf)
        self.assertEqual(typed_or.type_val, BOOL_TYPE)

    def test_relational_and_equality_operators(self):
        # Relational <
        lt_expr = ast.ExprInfix(left=ast.ExprInt(3, "3"), op="<", right=ast.ExprInt(5, "5"))
        self.assertEqual(synth_expr(lt_expr, self.env).type_val, BOOL_TYPE)

        # Equality is
        is_expr = ast.ExprInfix(left=ast.ExprString("a", '"a"'), op="is", right=ast.ExprString("b", '"b"'))
        self.assertEqual(synth_expr(is_expr, self.env).type_val, BOOL_TYPE)

        # Incompatible comparison
        bad_cmp = ast.ExprInfix(left=ast.ExprInt(3, "3"), op="<", right=ast.ExprString("hello", '"hello"'))
        with self.assertRaises(QuestTypeError):
            synth_expr(bad_cmp, self.env)

    def test_if_with_else_and_branch_join(self):
        if_expr = ast.ExprIf(
            cond=ast.ExprBool(True),
            then_branch=ast.ExprInt(10, "10"),
            elsifs=(),
            else_branch=ast.ExprInt(20, "20"),
        )
        typed_if = synth_expr(if_expr, self.env)
        self.assertIsInstance(typed_if, TypedIf)
        self.assertEqual(typed_if.type_val, INT_TYPE)

        # Check bidirectional checking against expected type
        checked_if = check_expr(if_expr, INT_TYPE, self.env)
        self.assertEqual(checked_if.type_val, INT_TYPE)

    def test_if_without_else_ignores_then_return_value(self):
        # if cond then 42 end: then branch returns Int, but value is ignored and if returns Ok
        if_stmt = ast.ExprIf(
            cond=ast.ExprBool(True),
            then_branch=ast.ExprInt(42, "42"),
            elsifs=(),
            else_branch=None,
        )
        typed_if = synth_expr(if_stmt, self.env)
        self.assertIsInstance(typed_if, TypedIf)
        self.assertEqual(typed_if.type_val, OK_TYPE)
        self.assertEqual(typed_if.else_branch.type_val, OK_TYPE)

    def test_while_loop_and_exit(self):
        while_expr = ast.ExprWhile(
            cond=ast.ExprBool(True),
            body=ast.ExprExit(),
        )
        typed_while = synth_expr(while_expr, self.env)
        self.assertIsInstance(typed_while, TypedWhile)
        self.assertEqual(typed_while.type_val, OK_TYPE)

        # Exit outside of loop
        with self.assertRaises(QuestTypeError):
            synth_expr(ast.ExprExit(), self.env)

    def test_for_loop(self):
        # for i = 1 upto 10 do ... end
        for_expr = ast.ExprFor(
            var_name="i",
            start=ast.ExprInt(1, "1"),
            is_downto=False,
            stop=ast.ExprInt(10, "10"),
            body=ast.ExprId("i"),
        )
        typed_for = synth_expr(for_expr, self.env)
        self.assertIsInstance(typed_for, TypedFor)
        self.assertEqual(typed_for.type_val, OK_TYPE)
        self.assertEqual(typed_for.var_name, "i")
        self.assertEqual(typed_for.symbol.type_val, INT_TYPE)

    def test_block_expressions_and_scoping(self):
        # begin let a = 10; let b = 20; a + b end
        block_ast = ast.ExprBlock(bindings=(
            ast.LetValueBinding(name="a", value=ast.ExprInt(10, "10")),
            ast.LetValueBinding(name="b", value=ast.ExprInt(20, "20")),
            ast.ExprStmt(expr=ast.ExprInfix(left=ast.ExprId("a"), op="+", right=ast.ExprId("b"))),
        ))
        typed_block = synth_expr(block_ast, self.env)
        self.assertIsInstance(typed_block, TypedBlock)
        self.assertEqual(typed_block.type_val, INT_TYPE)
        self.assertEqual(len(typed_block.bindings), 2)
        self.assertEqual(typed_block.result.type_val, INT_TYPE)

        # Scoped bindings do not leak into outer environment
        self.assertIsNone(self.env.lookup_value("a"))
        self.assertIsNone(self.env.lookup_value("b"))


if __name__ == "__main__":
    unittest.main()
