"""Unit tests for Phase 5: Exceptions, Dynamic Types, and Type Inspection."""

import unittest

import quest.ast as ast
from quest.env import Environment, ValueSymbol
from quest.typechecker import TypeError, check_expr, synth_expr
from quest.typed_ast import (
    TypedException,
    TypedInspect,
    TypedRaise,
    TypedTry,
)
from quest.types import (
    BOOL_TYPE,
    BOTTOM_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QExceptionType,
    REAL_TYPE,
    STRING_TYPE,
    is_subtype,
)


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
        exc_decl1 = ast.ExprException(name="DivByZero", type_annot=ast.TypePath(("Ok",)))
        typed_exc1 = synth_expr(exc_decl1, env)
        self.assertIsInstance(typed_exc1, TypedException)
        self.assertEqual(typed_exc1.type_val, QExceptionType(OK_TYPE))

        # Check declared in env
        sym1 = env.lookup_value("DivByZero")
        self.assertIsNotNone(sym1)
        self.assertEqual(sym1.type_val, QExceptionType(OK_TYPE))

        # exception Fail: String end
        exc_decl2 = ast.ExprException(name="Fail", type_annot=ast.TypePath(("String",)))
        typed_exc2 = synth_expr(exc_decl2, env)
        self.assertEqual(typed_exc2.type_val, QExceptionType(STRING_TYPE))

    def test_raise_divergent_control_flow(self) -> None:
        """raise in checking mode satisfies any expected type via bottom divergence."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="DivByZero", type_val=QExceptionType(OK_TYPE)))

        # if cond then raise DivByZero end else 42 end
        if_expr = ast.ExprIf(
            cond=ast.ExprBool(value=True),
            then_branch=ast.ExprRaise(exc=ast.ExprId("DivByZero")),
            elsifs=(),
            else_branch=ast.ExprInt(value=42, lexeme="42"),
        )
        # In checking mode expecting Int
        checked_if = check_expr(if_expr, INT_TYPE, env)
        self.assertEqual(checked_if.type_val, INT_TYPE)

        # In synthesis mode: raise without as Type synthesizes Ok
        raise_bare = ast.ExprRaise(exc=ast.ExprId("DivByZero"))
        typed_raise = synth_expr(raise_bare, env)
        self.assertIsInstance(typed_raise, TypedRaise)
        self.assertEqual(typed_raise.type_val, OK_TYPE)

        # raise with explicit as Real
        raise_as = ast.ExprRaise(
            exc=ast.ExprId("DivByZero"),
            as_type=ast.TypePath(("Real",)),
        )
        typed_raise_as = synth_expr(raise_as, env)
        self.assertEqual(typed_raise_as.type_val, REAL_TYPE)

    def test_raise_payload_verification(self) -> None:
        """raise with payload checks payload type against exception definition."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="Fail", type_val=QExceptionType(STRING_TYPE)))

        # Valid payload: raise Fail with "error" end
        raise_ok = ast.ExprRaise(
            exc=ast.ExprId("Fail"),
            payload=ast.ExprString(value="error", lexeme='"error"'),
        )
        typed_ok = synth_expr(raise_ok, env)
        self.assertIsInstance(typed_ok, TypedRaise)

        # Invalid payload: raise Fail with 123 end
        raise_err = ast.ExprRaise(
            exc=ast.ExprId("Fail"),
            payload=ast.ExprInt(value=123, lexeme="123"),
        )
        with self.assertRaises(TypeError):
            synth_expr(raise_err, env)

        # Missing required payload
        raise_missing = ast.ExprRaise(exc=ast.ExprId("Fail"))
        with self.assertRaises(TypeError):
            synth_expr(raise_missing, env)

    def test_try_when_handling(self) -> None:
        """try body when DivByZero then 0 when Fail with msg then 1 else -1 end."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="DivByZero", type_val=QExceptionType(OK_TYPE)))
        env.current_scope.declare_value(ValueSymbol(name="Fail", type_val=QExceptionType(STRING_TYPE)))

        try_expr = ast.ExprTry(
            body=ast.ExprInt(value=100, lexeme="100"),
            branches=(
                ast.TryBranch(
                    exc_pattern=ast.ExprId("DivByZero"),
                    body=ast.ExprInt(value=0, lexeme="0"),
                ),
                ast.TryBranch(
                    exc_pattern=ast.ExprId("Fail"),
                    binder="msg",
                    body=ast.ExprInt(value=1, lexeme="1"),
                ),
            ),
            else_branch=ast.ExprInt(value=-1, lexeme="-1"),
        )
        typed_try = synth_expr(try_expr, env)
        self.assertIsInstance(typed_try, TypedTry)
        self.assertEqual(typed_try.type_val, INT_TYPE)

    def test_dynamic_polymorphic_constructor(self) -> None:
        """dynamic(42) and dynamic("hello") synthesize Dynamic via built-in function."""
        env = Environment()

        # dynamic(42)
        dyn_call1 = ast.ExprApp(
            func=ast.ExprId("dynamic"),
            args=(ast.ExprInt(value=42, lexeme="42"),),
        )
        typed1 = synth_expr(dyn_call1, env)
        self.assertEqual(typed1.type_val, DYNAMIC_TYPE)

        # dynamic("text")
        dyn_call2 = ast.ExprApp(
            func=ast.ExprId("dynamic"),
            args=(ast.ExprString(value="text", lexeme='"text"'),),
        )
        typed2 = synth_expr(dyn_call2, env)
        self.assertEqual(typed2.type_val, DYNAMIC_TYPE)

    def test_inspect_dynamic(self) -> None:
        """inspect d when Int with n then n when String with s then 0 end (optional else)."""
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="d", type_val=DYNAMIC_TYPE))

        # inspect without else clause (allowed per decision 3)
        inspect_expr = ast.ExprInspect(
            target=ast.ExprId("d"),
            branches=(
                ast.InspectBranch(
                    match_type=ast.TypePath(("Int",)),
                    binders=(("n", None),),
                    body=ast.ExprId("n"),
                ),
                ast.InspectBranch(
                    match_type=ast.TypePath(("String",)),
                    binders=(("s", None),),
                    body=ast.ExprInt(value=0, lexeme="0"),
                ),
            ),
            else_branch=None,
        )
        typed_inspect = synth_expr(inspect_expr, env)
        self.assertIsInstance(typed_inspect, TypedInspect)
        self.assertEqual(typed_inspect.type_val, INT_TYPE)

        # Non-dynamic target raises TypeError
        bad_inspect = ast.ExprInspect(
            target=ast.ExprInt(value=42, lexeme="42"),
            branches=(),
            else_branch=None,
        )
        with self.assertRaises(TypeError):
            synth_expr(bad_inspect, env)


if __name__ == "__main__":
    unittest.main()
