"""Unit tests for Phase 4: Records, Tuples, Options, Variants, Patterns & Arrays."""

import unittest

import quest.ast as ast
from quest.elaborate_types import elaborate_type
from quest.env import Environment, ValueSymbol
from quest.typechecker import TypeError, check_expr, synth_expr
from quest.typed_ast import (
    TypedArray,
    TypedArrayRep,
    TypedAssign,
    TypedCase,
    TypedIndex,
    TypedIndexAssign,
    TypedOption,
    TypedRecord,
    TypedSelect,
    TypedTuple,
    TypedVariant,
)
from quest.types import (
    INT_TYPE,
    OK_TYPE,
    QArrayType,
    QOptionField,
    QOptionType,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QVariantField,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
)


class Phase4AggregatesTest(unittest.TestCase):
    """Test suite for records, tuples, options, variants, case patterns, and arrays."""

    def test_record_synthesis_and_selection(self) -> None:
        """record x = 10, y = 20 end synthesizes Record x: Int y: Int end."""
        rec_expr = ast.ExprRecord(
            fields=(
                ast.RecordBinding(name="x", value=ast.ExprInt(value=10, lexeme="10"), is_var=False),
                ast.RecordBinding(name="y", value=ast.ExprInt(value=20, lexeme="20"), is_var=False),
            )
        )
        typed_rec = synth_expr(rec_expr)
        self.assertIsInstance(typed_rec, TypedRecord)
        expected_rec_type = QRecordType((
            QRecordField("x", INT_TYPE, is_var=False),
            QRecordField("y", INT_TYPE, is_var=False),
        ))
        self.assertEqual(typed_rec.type_val, expected_rec_type)

        # Selection p.x
        sel_x = ast.ExprSelect(target=rec_expr, field="x")
        typed_sel = synth_expr(sel_x)
        self.assertIsInstance(typed_sel, TypedSelect)
        self.assertEqual(typed_sel.type_val, INT_TYPE)

        # Missing field p.z
        sel_z = ast.ExprSelect(target=rec_expr, field="z")
        with self.assertRaises(TypeError):
            synth_expr(sel_z)

    def test_record_mutable_field_assignment(self) -> None:
        """r.x := 42 succeeds when x is var, fails when immutable."""
        env = Environment()
        rec_type = QRecordType((
            QRecordField("x", INT_TYPE, is_var=True),
            QRecordField("y", INT_TYPE, is_var=False),
        ))
        env.current_scope.declare_value(ValueSymbol(name="r", type_val=rec_type))

        # Mutate var field
        assign_ok = ast.ExprInfix(
            left=ast.ExprSelect(target=ast.ExprId("r"), field="x"),
            op=":=",
            right=ast.ExprInt(value=42, lexeme="42"),
        )
        typed_assign = synth_expr(assign_ok, env)
        self.assertIsInstance(typed_assign, TypedAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

        # Attempt to mutate immutable field y
        assign_err = ast.ExprInfix(
            left=ast.ExprSelect(target=ast.ExprId("r"), field="y"),
            op=":=",
            right=ast.ExprInt(value=42, lexeme="42"),
        )
        with self.assertRaises(TypeError):
            synth_expr(assign_err, env)

    def test_tuple_synthesis_and_named_selection(self) -> None:
        """tuple intensity = 100 end synthesizes Tuple intensity: Int end and supports .intensity."""
        tup_expr = ast.ExprTuple(
            fields=(
                ast.TupleBinding(name="intensity", value=ast.ExprInt(value=100, lexeme="100")),
            )
        )
        typed_tup = synth_expr(tup_expr)
        self.assertIsInstance(typed_tup, TypedTuple)
        self.assertEqual(typed_tup.type_val, QTupleType((QTupleField("intensity", INT_TYPE),)))

        # Access named field
        sel_intensity = ast.ExprSelect(target=tup_expr, field="intensity")
        typed_sel = synth_expr(sel_intensity)
        self.assertEqual(typed_sel.type_val, INT_TYPE)

    def test_option_construction(self) -> None:
        """option red of Color end and option blue with 10 of Color end."""
        env = Environment()
        color_type = QOptionType((
            QOptionField("red", payload_type=None),
            QOptionField("green", payload_type=None),
            QOptionField("blue", payload_type=INT_TYPE),
        ))
        from quest.env import TypeSymbol
        from quest.types import TYPE_KIND
        env.current_scope.declare_type(
            TypeSymbol(name="Color", symbol_id=env.fresh_symbol_id(), kind=TYPE_KIND, definition=color_type)
        )

        # option red of Color end
        opt_red = ast.ExprOption(tag="red", option_type=ast.TypePath(("Color",)), payload=None)
        typed_red = synth_expr(opt_red, env)
        self.assertIsInstance(typed_red, TypedOption)
        self.assertEqual(typed_red.type_val, color_type)

        # option blue with 42 of Color end
        opt_blue = ast.ExprOption(
            tag="blue",
            option_type=ast.TypePath(("Color",)),
            payload=ast.ExprInt(value=42, lexeme="42"),
        )
        typed_blue = synth_expr(opt_blue, env)
        self.assertIsInstance(typed_blue, TypedOption)
        self.assertEqual(typed_blue.type_val, color_type)

        # Missing payload for blue
        opt_err1 = ast.ExprOption(tag="blue", option_type=ast.TypePath(("Color",)), payload=None)
        with self.assertRaises(TypeError):
            synth_expr(opt_err1, env)

        # Unexpected payload for red
        opt_err2 = ast.ExprOption(
            tag="red",
            option_type=ast.TypePath(("Color",)),
            payload=ast.ExprInt(value=1, lexeme="1"),
        )
        with self.assertRaises(TypeError):
            synth_expr(opt_err2, env)

    def test_case_pattern_matching_exhaustive(self) -> None:
        """Exhaustive case over Color joins branch types to Int."""
        env = Environment()
        color_type = QOptionType((
            QOptionField("red", payload_type=None),
            QOptionField("green", payload_type=None),
            QOptionField("blue", payload_type=INT_TYPE),
        ))
        env.current_scope.declare_value(ValueSymbol(name="col", type_val=color_type))

        # case col when red then 1 when green then 2 when blue with b then b end
        case_expr = ast.ExprCase(
            target=ast.ExprId("col"),
            branches=(
                ast.CaseBranch(tags=("red",), body=ast.ExprInt(value=1, lexeme="1")),
                ast.CaseBranch(tags=("green",), body=ast.ExprInt(value=2, lexeme="2")),
                ast.CaseBranch(
                    tags=("blue",),
                    binder="b",
                    body=ast.ExprId("b"),
                ),
            ),
            else_branch=None,
        )
        typed_case = synth_expr(case_expr, env)
        self.assertIsInstance(typed_case, TypedCase)
        self.assertEqual(typed_case.type_val, INT_TYPE)

    def test_case_non_exhaustive_error(self) -> None:
        """Case without else missing tags raises TypeError."""
        env = Environment()
        color_type = QOptionType((
            QOptionField("red", payload_type=None),
            QOptionField("green", payload_type=None),
            QOptionField("blue", payload_type=INT_TYPE),
        ))
        env.current_scope.declare_value(ValueSymbol(name="col", type_val=color_type))

        # Missing 'blue' tag without else clause
        case_err = ast.ExprCase(
            target=ast.ExprId("col"),
            branches=(
                ast.CaseBranch(tags=("red",), body=ast.ExprInt(value=1, lexeme="1")),
                ast.CaseBranch(tags=("green",), body=ast.ExprInt(value=2, lexeme="2")),
            ),
            else_branch=None,
        )
        with self.assertRaises(TypeError) as ctx:
            synth_expr(case_err, env)
        self.assertIn("Non-exhaustive case expression missing tags: blue", str(ctx.exception))

        # With else clause, non-exhaustive branches succeed
        case_ok = ast.ExprCase(
            target=ast.ExprId("col"),
            branches=(
                ast.CaseBranch(tags=("red",), body=ast.ExprInt(value=1, lexeme="1")),
            ),
            else_branch=ast.ExprInt(value=0, lexeme="0"),
        )
        typed_ok = synth_expr(case_ok, env)
        self.assertEqual(typed_ok.type_val, INT_TYPE)

    def test_array_synthesis_and_indexing(self) -> None:
        """array of 1 2 3 end and arr[0] indexing."""
        arr_expr = ast.ExprArray(
            elements=(
                ast.ExprInt(value=1, lexeme="1"),
                ast.ExprInt(value=2, lexeme="2"),
                ast.ExprInt(value=3, lexeme="3"),
            )
        )
        typed_arr = synth_expr(arr_expr)
        self.assertIsInstance(typed_arr, TypedArray)
        self.assertEqual(typed_arr.type_val, QArrayType(INT_TYPE))

        # Indexing arr[0]
        idx_expr = ast.ExprIndex(target=arr_expr, index=ast.ExprInt(value=0, lexeme="0"))
        typed_idx = synth_expr(idx_expr)
        self.assertIsInstance(typed_idx, TypedIndex)
        self.assertEqual(typed_idx.type_val, INT_TYPE)

        # Index assignment arr[0] := 99
        assign_expr = ast.ExprIndexAssign(
            target=arr_expr,
            index=ast.ExprInt(value=0, lexeme="0"),
            value=ast.ExprInt(value=99, lexeme="99"),
        )
        typed_assign = synth_expr(assign_expr)
        self.assertIsInstance(typed_assign, TypedIndexAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

    def test_empty_array_requires_checking_mode(self) -> None:
        """Empty array requires type annotation / checking mode."""
        empty_arr = ast.ExprArray(elements=())
        with self.assertRaises(TypeError):
            synth_expr(empty_arr)

        # In checking mode with expected Array(Int), empty array succeeds
        typed_checked = check_expr(empty_arr, QArrayType(INT_TYPE))
        self.assertIsInstance(typed_checked, TypedArray)
        self.assertEqual(typed_checked.type_val, QArrayType(INT_TYPE))

    def test_array_repetition(self) -> None:
        """array of (10 0) synthesizes Array(Int)."""
        rep_expr = ast.ExprArrayRep(
            count=ast.ExprInt(value=10, lexeme="10"),
            init_val=ast.ExprInt(value=0, lexeme="0"),
        )
        typed_rep = synth_expr(rep_expr)
        self.assertIsInstance(typed_rep, TypedArrayRep)
        self.assertEqual(typed_rep.type_val, QArrayType(INT_TYPE))


if __name__ == "__main__":
    unittest.main()
