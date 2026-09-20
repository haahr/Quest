"""Unit tests for Phase 3: Functions, Applications & Polymorphic Calls."""

import unittest

import quest.ast as ast
from quest.elaborate_types import elaborate_type
from quest.diagnostics import QuestTypeError as TypeError
from quest.env import Environment, ValueSymbol
from quest.typechecker import check_expr, synth_expr
from quest.typed_ast import (
    TypedApp,
    TypedFun,
    TypedTypeApp,
    TypedVar,
)
from quest.types import (
    INT_TYPE,
    OK_TYPE,
    QAllType,
    QFunType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTypeVar,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
)
from tests.python.helpers import (
    elaborate_test_type,
    parse_expr,
    synth_test_expr,
)


class Phase3FunctionsTest(unittest.TestCase):
    """Test suite for functions, applications, parameter modes, and polymorphism."""

    def test_fun_abstraction_synthesis(self) -> None:
        """fun(x: Int): Int x + 1 synthesizes QFunType(Int) -> Int."""
        typed = synth_test_expr("fun(x: Int): Int x + 1")
        self.assertIsInstance(typed, TypedFun)
        self.assertEqual(len(typed.params), 1)
        self.assertEqual(typed.params[0].name, "x")
        self.assertEqual(typed.params[0].type_val, INT_TYPE)
        self.assertEqual(typed.type_val, QFunType(params=(QParam("x", INT_TYPE),), result_type=INT_TYPE))

    def test_fun_abstraction_omitted_return_type(self) -> None:
        """fun(x: Int) x + 1 infers return type Int from body."""
        typed = synth_test_expr("fun(x: Int) x + 1")
        self.assertEqual(typed.type_val, QFunType(params=(QParam("x", INT_TYPE),), result_type=INT_TYPE))

    def test_fun_abstraction_checking_mode(self) -> None:
        """fun(x) x + 1 checked against (Int) -> Int infers parameter type."""
        expected_type = QFunType(params=(QParam("x", INT_TYPE),), result_type=INT_TYPE)
        # AST with unannotated parameter for checking mode
        fn_expr = ast.ExprFun(
            params=(
                ast.FormalParam(name="x", type_annot=None, mode=ast.ParamMode.VALUE),
            ),
            return_type=None,
            body=parse_expr("x + 1"),
        )
        typed = check_expr(fn_expr, expected_type)
        self.assertIsInstance(typed, TypedFun)
        self.assertEqual(typed.params[0].type_val, INT_TYPE)
        self.assertEqual(typed.type_val, expected_type)

    def test_function_application_monomorphic(self) -> None:
        """f(41) synthesizes Int."""
        fn_type = synth_test_expr("fun(x: Int): Int x + 1").type_val
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="f", type_val=fn_type))
        typed = synth_test_expr("f(41)", env)
        self.assertIsInstance(typed, TypedApp)
        self.assertEqual(typed.type_val, INT_TYPE)
        self.assertEqual(len(typed.args), 1)

    def test_multi_argument_application(self) -> None:
        """Multi-argument function application f(10, 2.5)."""
        env = Environment()
        fn_type = QFunType(
            params=(QParam("a", INT_TYPE), QParam("b", REAL_TYPE)),
            result_type=REAL_TYPE,
        )
        env.current_scope.declare_value(ValueSymbol(name="f", type_val=fn_type))

        typed = synth_test_expr("f(10 2.5)", env)
        self.assertIsInstance(typed, TypedApp)
        self.assertEqual(typed.type_val, REAL_TYPE)

    def test_var_parameter_mutability_and_invariance(self) -> None:
        """var parameters require mutable variable locations and are invariant."""
        env = Environment()
        # inc: fun(var count: Int): Ok
        inc_type = QFunType(params=(QParam("count", INT_TYPE, is_var=True),), result_type=OK_TYPE)
        env.current_scope.declare_value(ValueSymbol(name="inc", type_val=inc_type))

        # Mutable variable
        env.current_scope.declare_value(ValueSymbol(name="c", type_val=INT_TYPE, is_var=True))
        # Immutable variable
        env.current_scope.declare_value(ValueSymbol(name="imm", type_val=INT_TYPE, is_var=False))

        # Passing mutable variable with @ succeeds
        typed = synth_test_expr("inc(@c)", env)
        self.assertIsInstance(typed, TypedApp)
        self.assertEqual(typed.type_val, OK_TYPE)
        # Arg passed as lvalue location TypedVar
        self.assertIsInstance(typed.args[0], TypedVar)

        # Passing mutable variable without @ fails
        with self.assertRaises(TypeError):
            synth_test_expr("inc(c)", env)

        # Passing immutable variable fails
        with self.assertRaises(TypeError):
            synth_test_expr("inc(imm)", env)

        # Passing literal fails
        with self.assertRaises(TypeError):
            synth_test_expr("inc(5)", env)

    def test_out_parameter_covariance(self) -> None:
        """out parameters require a mutable location where param_type <= location_type."""
        env = Environment()
        # Supertype Animal = Record name: String end
        animal_type = QRecordType((QRecordField("name", STRING_TYPE),))
        # Subtype Dog = Record name: String breed: String end
        dog_type = QRecordType((QRecordField("name", STRING_TYPE), QRecordField("breed", STRING_TYPE)))
        # Subtype Terrier = Record name: String breed: String size: String end
        terrier_type = QRecordType((
            QRecordField("name", STRING_TYPE),
            QRecordField("breed", STRING_TYPE),
            QRecordField("size", STRING_TYPE),
        ))

        # getDog: fun(out x: Dog): Ok
        fn_type = QFunType(params=(QParam("x", dog_type, is_out=True),), result_type=OK_TYPE)
        env.current_scope.declare_value(ValueSymbol(name="getDog", type_val=fn_type))

        # Bare argument without @ raises TypeError
        with self.assertRaises(TypeError):
            synth_test_expr("getDog(pet)", env)

        # Destination variable of type Animal (Dog <= Animal: valid!)
        env.current_scope.declare_value(ValueSymbol(name="pet", type_val=animal_type, is_var=True))
        typed_ok = synth_test_expr("getDog(@pet)", env)
        self.assertEqual(typed_ok.type_val, OK_TYPE)

        # Destination variable of type Terrier (Dog <= Terrier is False: rejected!)
        env.current_scope.declare_value(ValueSymbol(name="tiny", type_val=terrier_type, is_var=True))
        with self.assertRaises(TypeError):
            synth_test_expr("getDog(@tiny)", env)

    def test_polymorphic_application_inference(self) -> None:
        """Polymorphic call id(42) infers X = Int and wraps in TypedTypeApp."""
        env = Environment()
        # id : All(X::TYPE) (x: X) -> X
        sym_id = env.fresh_symbol_id()
        x_quant = QQuantifier(name="X", symbol_id=sym_id, bound=TYPE_KIND)
        x_var = QTypeVar(name="X", symbol_id=sym_id)
        all_id_type = QAllType(
            quantifiers=(x_quant,),
            body=QFunType(params=(QParam("x", x_var),), result_type=x_var),
        )
        env.current_scope.declare_value(ValueSymbol(name="id", type_val=all_id_type))

        # id(42)
        typed = synth_test_expr("id(42)", env)
        self.assertIsInstance(typed, TypedApp)
        self.assertEqual(typed.type_val, INT_TYPE)
        self.assertIsInstance(typed.func, TypedTypeApp)
        self.assertEqual(typed.func.type_args, (INT_TYPE,))

        # id("hello")
        typed_str = synth_test_expr('id("hello")', env)
        self.assertIsInstance(typed_str, TypedApp)
        self.assertEqual(typed_str.type_val, STRING_TYPE)
        self.assertIsInstance(typed_str.func, TypedTypeApp)
        self.assertEqual(typed_str.func.type_args, (STRING_TYPE,))

    def test_let_function_shorthand_and_recursion(self) -> None:
        """let rec factorial(n: Int): Int = ... typechecks and binds properly."""
        typed_block = synth_test_expr(
            "begin let rec factorial(n: Int): Int = "
            "if n == 0 then 1 else n * factorial(n - 1) end; "
            "factorial(5) end"
        )
        self.assertEqual(typed_block.type_val, INT_TYPE)

    def test_let_rec_missing_return_type_raises_type_error(self) -> None:
        """let rec f(n: Int) = ... without return type raises TypeError."""
        with self.assertRaises(TypeError) as ctx:
            synth_test_expr("begin let rec fib(n: Int) = n; 1 end")
        self.assertIn(
            "Recursive function 'fib' requires an explicit return type annotation",
            str(ctx.exception),
        )

    def test_let_rec_missing_param_type_raises_type_error(self) -> None:
        """let rec f(n) : Int = ... with unannotated parameter raises TypeError."""
        # Grammar requires parameter annotations, but typechecker defends against AST without annotations.
        binding = ast.LetValueBinding(
            name="fib",
            params=(
                ast.FormalParam(
                    name="n",
                    type_annot=None,
                    mode=ast.ParamMode.VALUE,
                ),
            ),
            type_annot=ast.TypePath(path=("Int",)),
            value=ast.ExprId(name="n"),
            is_rec=True,
        )
        block = ast.ExprBlock(bindings=(binding, ast.ExprStmt(expr=ast.ExprInt(value=1, lexeme="1"))))
        with self.assertRaises(TypeError) as ctx:
            synth_expr(block)
        self.assertIn(
            "Parameter 'n' in recursive function 'fib' requires an explicit type annotation",
            str(ctx.exception),
        )

    def test_let_rec_value_missing_type_raises_type_error(self) -> None:
        """let rec f = 1 without type annotation raises TypeError."""
        with self.assertRaises(TypeError) as ctx:
            synth_test_expr("begin let rec f = 1; 1 end")
        self.assertIn(
            "Recursive definition 'f' requires an explicit type annotation",
            str(ctx.exception),
        )

    def test_all_type_as_function_type_elaboration(self) -> None:
        """All(y: Int) Int in elaborate_type elaborates to QFunType(y: Int) -> Int."""
        elaborated = elaborate_test_type("All(y: Int) Int")
        self.assertIsInstance(elaborated, QFunType)
        self.assertEqual(len(elaborated.params), 1)
        self.assertEqual(elaborated.params[0].name, "y")
        self.assertEqual(elaborated.params[0].type_val, INT_TYPE)
        self.assertEqual(elaborated.result_type, INT_TYPE)


if __name__ == "__main__":
    unittest.main()
