"""Unit tests for TypeElaborator class and its context managers."""

import unittest

import quest.ast as ast
from quest.diagnostics import QuestTypeError
from quest.env import Environment, ValueSymbol
from quest.typed_ast import TypedExprStmt, TypedLetValue
from quest.typechecker import TypeElaborator
from quest.types import BOOL_TYPE, DYNAMIC_TYPE, INT_TYPE, OK_TYPE
from helpers import parse_expr, parse_phrase


class TestTypeElaborator(unittest.TestCase):
    """Test suite verifying TypeElaborator instance methods and RAII context managers."""

    def test_init_defaults(self) -> None:
        """TypeElaborator creates its own Environment and sets loop_depth to 0 by default."""
        el = TypeElaborator()
        self.assertIsNotNone(el.env)
        self.assertEqual(el.loop_depth, 0)

    def test_init_custom_env_and_depth(self) -> None:
        """TypeElaborator retains supplied Environment and loop depth."""
        custom_env = Environment()
        el = TypeElaborator(env=custom_env, loop_depth=3)
        self.assertIs(el.env, custom_env)
        self.assertEqual(el.loop_depth, 3)

    def test_scope_context_manager(self) -> None:
        """with el.scope(name): pushes a named scope and pops on exit."""
        el = TypeElaborator()
        initial_scope = el.env.current_scope
        with el.scope("test_scope") as s:
            self.assertIs(el.env.current_scope, s)
            self.assertIs(s.parent, initial_scope)
            self.assertEqual(s.name, "test_scope")
            s.declare_value(ValueSymbol(name="x", type_val=INT_TYPE))
            self.assertIsNotNone(el.env.lookup_value("x"))
        self.assertIs(el.env.current_scope, initial_scope)
        self.assertIsNone(el.env.lookup_value("x"))

    def test_in_loop_context_manager(self) -> None:
        """with el.in_loop(): increments loop_depth and restores on exit."""
        el = TypeElaborator()
        self.assertEqual(el.loop_depth, 0)
        with el.in_loop():
            self.assertEqual(el.loop_depth, 1)
            with el.in_loop():
                self.assertEqual(el.loop_depth, 2)
            self.assertEqual(el.loop_depth, 1)
        self.assertEqual(el.loop_depth, 0)

    def test_in_function_context_manager(self) -> None:
        """with el.in_function(): resets loop_depth to 0 and restores outer depth on exit."""
        el = TypeElaborator(loop_depth=2)
        with el.in_function():
            self.assertEqual(el.loop_depth, 0)
            with el.in_loop():
                self.assertEqual(el.loop_depth, 1)
        self.assertEqual(el.loop_depth, 2)

    def test_synth_and_check_methods(self) -> None:
        """TypeElaborator.synth and .check properly elaborate expressions."""
        el = TypeElaborator()
        expr_int = parse_expr("42")
        typed_int = el.synth(expr_int)
        self.assertEqual(typed_int.type_val, INT_TYPE)

        checked_int = el.check(expr_int, INT_TYPE)
        self.assertEqual(checked_int.type_val, INT_TYPE)

        with self.assertRaises(QuestTypeError):
            el.check(expr_int, BOOL_TYPE)

    def test_stateful_phrases_across_single_elaborator(self) -> None:
        """A single TypeElaborator instance preserves bindings across sequential phrases."""
        el = TypeElaborator()
        prog = parse_phrase("let x = 10; x + 5", target="program")
        phrase1, phrase2 = prog.phrases
        typed_b = el.elaborate_phrase(phrase1)
        self.assertIsInstance(typed_b, TypedLetValue)
        self.assertEqual(typed_b.name, "x")

        typed_e = el.elaborate_phrase(phrase2)
        self.assertIsInstance(typed_e, TypedExprStmt)
        self.assertEqual(typed_e.expr.type_val, INT_TYPE)

    def test_elaborate_program(self) -> None:
        """elaborate_program processes all phrases in an entire unit."""
        el = TypeElaborator()
        prog = parse_phrase("let a = 1; let b = 2; a + b", target="program")
        typed_prog = el.elaborate_program(prog)
        self.assertEqual(len(typed_prog.phrases), 3)

    def test_if_check_and_synth(self) -> None:
        """if expressions with elsif desugaring elaborate correctly in synth and check modes."""
        el = TypeElaborator()
        expr = parse_expr("if true then 1 elsif false then 2 else 3 end")
        typed_synth = el.synth(expr)
        self.assertEqual(typed_synth.type_val, INT_TYPE)

        typed_check = el.check(expr, INT_TYPE)
        self.assertEqual(typed_check.type_val, INT_TYPE)

    def test_raise_check_and_synth(self) -> None:
        """raise expressions elaborate in check (any expected type) and synth modes."""
        el = TypeElaborator()
        el.elaborate_phrase(parse_phrase("exception Err : Int end"))
        expr = parse_expr("raise Err with 42 end")
        typed_synth = el.synth(expr)
        self.assertEqual(typed_synth.type_val, OK_TYPE)

        typed_check = el.check(expr, BOOL_TYPE)
        self.assertEqual(typed_check.type_val, BOOL_TYPE)

    def test_try_check_and_synth(self) -> None:
        """try expressions elaborate properly in both synth and check modes."""
        el = TypeElaborator()
        el.elaborate_phrase(parse_phrase("exception Err : Int end"))
        expr = parse_expr("try 1 when Err with x then x + 2 else 0 end")
        typed_synth = el.synth(expr)
        self.assertEqual(typed_synth.type_val, INT_TYPE)

        typed_check = el.check(expr, INT_TYPE)
        self.assertEqual(typed_check.type_val, INT_TYPE)

    def test_inspect_check_and_synth(self) -> None:
        """inspect expressions elaborate properly in both synth and check modes."""
        el = TypeElaborator()
        el.env.current_scope.declare_value(ValueSymbol(name="d", type_val=DYNAMIC_TYPE))
        expr = parse_expr("inspect d when Int with x then x + 1 else 0 end")
        typed_synth = el.synth(expr)
        self.assertEqual(typed_synth.type_val, INT_TYPE)

        typed_check = el.check(expr, INT_TYPE)
        self.assertEqual(typed_check.type_val, INT_TYPE)

    def test_array_index_assignment_delegation(self) -> None:
        """arr[i] := val in infix assignment delegates properly to index assignment."""
        el = TypeElaborator()
        el.elaborate_phrase(parse_phrase("let arr = array of 10 20 30 end"))
        expr = parse_expr("arr[1] := 99")
        typed_assign = el.synth(expr)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

    def test_env_scoped_context_manager(self) -> None:
        """Environment.scoped pushes child scope and pops reliably even on exception."""
        env = Environment()
        root_scope = env.current_scope
        with env.scoped("inner") as inner:
            self.assertIs(env.current_scope, inner)
            self.assertIs(inner.parent, root_scope)
            inner.declare_value(ValueSymbol(name="v", type_val=INT_TYPE))
            self.assertIsNotNone(env.lookup_value("v"))
        self.assertIs(env.current_scope, root_scope)
        self.assertIsNone(env.lookup_value("v"))

        with self.assertRaises(RuntimeError):
            with env.scoped("failing"):
                raise RuntimeError("forced failure")
        self.assertIs(env.current_scope, root_scope)

    def test_function_isolates_loop_depth_for_exit(self) -> None:
        """Function bodies isolate loop depth so exit within a nested function fails."""
        el = TypeElaborator()
        expr = parse_expr("loop begin let f = fun(): Ok exit; f() end end")
        with self.assertRaises(QuestTypeError) as cm:
            el.synth(expr)
        self.assertIn("Exit statement outside of any loop", str(cm.exception))

    def test_while_and_for_loop_depth_support_exit(self) -> None:
        """while and for loops increment loop depth to allow exit, but top-level exit fails."""
        el = TypeElaborator()
        typed_while = el.synth(parse_expr("while true do exit end"))
        self.assertEqual(typed_while.type_val, OK_TYPE)

        typed_for = el.synth(parse_expr("for i = 1 upto 5 do exit end"))
        self.assertEqual(typed_for.type_val, OK_TYPE)

        with self.assertRaises(QuestTypeError) as cm:
            el.synth(parse_expr("exit"))
        self.assertIn("Exit statement outside of any loop", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

