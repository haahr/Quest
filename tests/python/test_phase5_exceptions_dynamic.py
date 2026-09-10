"""Unit tests for Phase 5: Exceptions, Dynamic Types, and Type Inspection."""

import unittest

from quest.env import Environment, ValueSymbol
from quest.diagnostics import QuestTypeError as TypeError
from quest.typed_ast import (
    TypedException,
    TypedInspect,
    TypedRaise,
    TypedTry,
)
from quest.types import (
    BOTTOM_TYPE,
    DYNAMIC_TYPE,
    INT_TYPE,
    OK_TYPE,
    QExceptionType,
    REAL_TYPE,
    STRING_TYPE,
    is_subtype,
)
from tests.python.helpers import check_test_expr, synth_test_expr


class Phase5ExceptionsDynamicTest(unittest.TestCase):
    """Test suite for exceptions, divergent raise typing, dynamic values, and inspect."""

    def test_bottom_subtyping(self) -> None:
        """Bottom is a subtype of every type (Int, String, Dynamic, etc.)."""
        self.assertTrue(is_subtype(BOTTOM_TYPE, INT_TYPE))
        self.assertTrue(is_subtype(BOTTOM_TYPE, REAL_TYPE))
        self.assertTrue(is_subtype(BOTTOM_TYPE, STRING_TYPE))
        self.assertTrue(is_subtype(BOTTOM_TYPE, DYNAMIC_TYPE))
        self.assertTrue(is_subtype(BOTTOM_TYPE, OK_TYPE))

    def test_exception_declaration_and_payload(self) -> None:
        """exception DivByZero: Ok end and exception Fail: String end."""
        env = Environment()

        # exception DivByZero: Ok end
        typed_exc1 = synth_test_expr("exception DivByZero: Ok end", env)
        self.assertIsInstance(typed_exc1, TypedException)
        self.assertEqual(typed_exc1.type_val, QExceptionType(OK_TYPE))

        # Check declared in env
        sym1 = env.lookup_value("DivByZero")
        self.assertIsNotNone(sym1)
        self.assertEqual(sym1.type_val, QExceptionType(OK_TYPE))

        # exception Fail: String end
        typed_exc2 = synth_test_expr("exception Fail: String end", env)
        self.assertEqual(typed_exc2.type_val, QExceptionType(STRING_TYPE))

    def test_raise_divergent_control_flow(self) -> None:
        """raise in checking mode satisfies any expected type via bottom divergence."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="DivByZero", type_val=QExceptionType(OK_TYPE)))

        # if cond then raise DivByZero end else 42 end
        checked_if = check_test_expr("if true then raise DivByZero end else 42 end", INT_TYPE, env)
        self.assertEqual(checked_if.type_val, INT_TYPE)

        # In synthesis mode: raise without as Type synthesizes Ok
        typed_raise = synth_test_expr("raise DivByZero end", env)
        self.assertIsInstance(typed_raise, TypedRaise)
        self.assertEqual(typed_raise.type_val, OK_TYPE)

        # raise with explicit as Real
        typed_raise_as = synth_test_expr("raise DivByZero as Real end", env)
        self.assertEqual(typed_raise_as.type_val, REAL_TYPE)

    def test_raise_payload_verification(self) -> None:
        """raise with payload checks payload type against exception definition."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="Fail", type_val=QExceptionType(STRING_TYPE)))

        # Valid payload: raise Fail with "error" end
        typed_ok = synth_test_expr('raise Fail with "error" end', env)
        self.assertIsInstance(typed_ok, TypedRaise)

        # Invalid payload: raise Fail with 123 end
        with self.assertRaises(TypeError):
            synth_test_expr("raise Fail with 123 end", env)

        # Missing required payload
        with self.assertRaises(TypeError):
            synth_test_expr("raise Fail end", env)

    def test_try_when_handling(self) -> None:
        """try body when DivByZero then 0 when Fail with msg then 1 else 2 end."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="DivByZero", type_val=QExceptionType(OK_TYPE)))
        env.current_scope.declare_value(ValueSymbol(name="Fail", type_val=QExceptionType(STRING_TYPE)))

        typed_try = synth_test_expr(
            "try 100 when DivByZero then 0 when Fail with msg then 1 else 2 end",
            env,
        )
        self.assertIsInstance(typed_try, TypedTry)
        self.assertEqual(typed_try.type_val, INT_TYPE)

    def test_dynamic_polymorphic_constructor(self) -> None:
        """dynamic.new(42) and dynamic.new("text") synthesize Dynamic."""
        env = Environment()

        # dynamic.new(42)
        typed1 = synth_test_expr("dynamic.new(42)", env)
        self.assertEqual(typed1.type_val.evaluate_lazily(env), DYNAMIC_TYPE)

        # dynamic.new("text")
        typed2 = synth_test_expr('dynamic.new("text")', env)
        self.assertEqual(typed2.type_val.evaluate_lazily(env), DYNAMIC_TYPE)

        # dynamic.new(:Int 42)
        typed3 = synth_test_expr("dynamic.new(:Int 42)", env)
        self.assertEqual(typed3.type_val.evaluate_lazily(env), DYNAMIC_TYPE)

    def test_inspect_dynamic(self) -> None:
        """inspect d when Int with n then n when String with s then 0 end (optional else)."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="d", type_val=DYNAMIC_TYPE))

        # inspect without else clause
        typed_inspect = synth_test_expr(
            "inspect d when Int with n then n when String with s then 0 end",
            env,
        )
        self.assertIsInstance(typed_inspect, TypedInspect)
        self.assertEqual(typed_inspect.type_val, INT_TYPE)

        # Non-dynamic target raises TypeError
        with self.assertRaises(TypeError):
            synth_test_expr("inspect 42 end", env)


if __name__ == "__main__":
    unittest.main()
