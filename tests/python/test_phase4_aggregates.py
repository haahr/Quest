"""Unit tests for Phase 4: Records, Tuples, Options, Variants, Patterns & Arrays."""

import unittest

from quest.diagnostics import QuestTypeError as TypeError
from quest.env import Environment, TypeSymbol, ValueSymbol
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
    TYPE_KIND,
)
from tests.python.helpers import check_test_expr, synth_test_expr


class Phase4AggregatesTest(unittest.TestCase):
    """Test suite for records, tuples, options, variants, case patterns, and arrays."""

    def test_record_synthesis_and_selection(self) -> None:
        """record x = 10 y = 20 end synthesizes Record x: Int y: Int end."""
        typed_rec = synth_test_expr("record x = 10 y = 20 end")
        self.assertIsInstance(typed_rec, TypedRecord)
        expected_rec_type = QRecordType((
            QRecordField("x", INT_TYPE, is_var=False),
            QRecordField("y", INT_TYPE, is_var=False),
        ))
        self.assertEqual(typed_rec.type_val, expected_rec_type)

        # Selection p.x
        typed_sel = synth_test_expr("record x = 10 y = 20 end.x")
        self.assertIsInstance(typed_sel, TypedSelect)
        self.assertEqual(typed_sel.type_val, INT_TYPE)

        # Missing field p.z
        with self.assertRaises(TypeError):
            synth_test_expr("record x = 10 y = 20 end.z")

    def test_record_mutable_field_assignment(self) -> None:
        """r.x := 42 succeeds when x is var, fails when immutable."""
        env = Environment()
        rec_type = QRecordType((
            QRecordField("x", INT_TYPE, is_var=True),
            QRecordField("y", INT_TYPE, is_var=False),
        ))
        env.current_scope.declare_value(ValueSymbol(name="r", type_val=rec_type))

        # Mutate var field
        typed_assign = synth_test_expr("r.x := 42", env)
        self.assertIsInstance(typed_assign, TypedAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

        # Attempt to mutate immutable field y
        with self.assertRaises(TypeError):
            synth_test_expr("r.y := 42", env)

    def test_tuple_synthesis_and_named_selection(self) -> None:
        """tuple let intensity = 100; end synthesizes Tuple intensity: Int end and supports .intensity."""
        typed_tup = synth_test_expr("tuple let intensity = 100; end")
        self.assertIsInstance(typed_tup, TypedTuple)
        self.assertEqual(typed_tup.type_val, QTupleType((QTupleField("intensity", INT_TYPE),)))

        # Access named field
        typed_sel = synth_test_expr("tuple let intensity = 100; end.intensity")
        self.assertEqual(typed_sel.type_val, INT_TYPE)

    def test_option_construction(self) -> None:
        """option red of Color end and option blue of Color with 42 end."""
        env = Environment()
        color_type = QOptionType((
            QOptionField("red", payload_type=None),
            QOptionField("green", payload_type=None),
            QOptionField("blue", payload_type=INT_TYPE),
        ))
        env.current_scope.declare_type(
            TypeSymbol(name="Color", symbol_id=env.fresh_symbol_id(), kind=TYPE_KIND, definition=color_type)
        )

        # option red of Color end
        typed_red = synth_test_expr("option red of Color end", env)
        self.assertIsInstance(typed_red, TypedOption)
        self.assertEqual(typed_red.type_val, color_type)

        # option blue of Color with 42 end
        typed_blue = synth_test_expr("option blue of Color with 42 end", env)
        self.assertIsInstance(typed_blue, TypedOption)
        self.assertEqual(typed_blue.type_val, color_type)

        # Missing payload for blue
        with self.assertRaises(TypeError):
            synth_test_expr("option blue of Color end", env)

        # Unexpected payload for red
        with self.assertRaises(TypeError):
            synth_test_expr("option red of Color with 1 end", env)

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
        typed_case = synth_test_expr(
            "case col when red then 1 when green then 2 when blue with b then b end",
            env,
        )
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
        with self.assertRaises(TypeError) as ctx:
            synth_test_expr("case col when red then 1 when green then 2 end", env)
        self.assertIn("Non-exhaustive case expression missing tags: blue", str(ctx.exception))

        # With else clause, non-exhaustive branches succeed
        typed_ok = synth_test_expr("case col when red then 1 else 0 end", env)
        self.assertEqual(typed_ok.type_val, INT_TYPE)

    def test_array_synthesis_and_indexing(self) -> None:
        """array of 1 2 3 end and arr[0] indexing."""
        typed_arr = synth_test_expr("array of 1 2 3 end")
        self.assertIsInstance(typed_arr, TypedArray)
        self.assertEqual(typed_arr.type_val, QArrayType(INT_TYPE))

        # Indexing arr[0]
        typed_idx = synth_test_expr("array of 1 2 3 end[0]")
        self.assertIsInstance(typed_idx, TypedIndex)
        self.assertEqual(typed_idx.type_val, INT_TYPE)

        # Index assignment arr[0] := 99
        env = Environment()
        env.current_scope.declare_value(ValueSymbol(name="arr", type_val=QArrayType(INT_TYPE)))
        typed_assign = synth_test_expr("arr[0] := 99", env)
        self.assertIsInstance(typed_assign, TypedIndexAssign)
        self.assertEqual(typed_assign.type_val, OK_TYPE)

    def test_empty_array_requires_checking_mode(self) -> None:
        """Empty array requires type annotation / checking mode."""
        with self.assertRaises(TypeError):
            synth_test_expr("array of end")

        # In checking mode with expected Array(Int), empty array succeeds
        typed_checked = check_test_expr("array of end", QArrayType(INT_TYPE))
        self.assertIsInstance(typed_checked, TypedArray)
        self.assertEqual(typed_checked.type_val, QArrayType(INT_TYPE))

    def test_array_repetition(self) -> None:
        """array of (10 0) synthesizes Array(Int)."""
        typed_rep = synth_test_expr("array of (10 0)")
        self.assertIsInstance(typed_rep, TypedArrayRep)
        self.assertEqual(typed_rep.type_val, QArrayType(INT_TYPE))


if __name__ == "__main__":
    unittest.main()
