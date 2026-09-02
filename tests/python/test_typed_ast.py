"""Comprehensive Unit Tests for Quest Typed Core AST (Typed AST)."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QArrayType,
    QFunType,
    QOptionField,
    QOptionType,
    QParam,
    QRecordField,
    QRecordType,
    QTupleType,
    QVarType,
    QVariantField,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
)
from quest.env import (
    Scope,
    TypeSymbol,
    ValueSymbol,
)
from quest.typed_ast import (
    TypedApp,
    TypedArray,
    TypedAssign,
    TypedBlock,
    TypedBool,
    TypedCase,
    TypedCaseBranch,
    TypedChar,
    TypedDerefCell,
    TypedException,
    TypedExit,
    TypedExprStmt,
    TypedFun,
    TypedIf,
    TypedIndex,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedOk,
    TypedOption,
    TypedParam,
    TypedProgram,
    TypedRaise,
    TypedReal,
    TypedRecord,
    TypedRecordField,
    TypedSelect,
    TypedString,
    TypedTry,
    TypedTryBranch,
    TypedTuple,
    TypedTypeApp,
    TypedVar,
    TypedVarCell,
    TypedVariant,
    TypedWhile,
    typed_ast_dump,
)


class TestTypedASTNodes(unittest.TestCase):
    def test_literals_and_types(self):
        t_int = TypedInt(42)
        self.assertEqual(t_int.value, 42)
        self.assertEqual(t_int.type_val, INT_TYPE)

        t_real = TypedReal(3.14)
        self.assertEqual(t_real.value, 3.14)
        self.assertEqual(t_real.type_val, REAL_TYPE)

        t_bool = TypedBool(True)
        self.assertTrue(t_bool.value)
        self.assertEqual(t_bool.type_val, BOOL_TYPE)

        t_char = TypedChar("c")
        self.assertEqual(t_char.value, "c")
        self.assertEqual(t_char.type_val, CHAR_TYPE)

        t_str = TypedString("hello")
        self.assertEqual(t_str.value, "hello")
        self.assertEqual(t_str.type_val, STRING_TYPE)

        t_ok = TypedOk()
        self.assertEqual(t_ok.type_val, OK_TYPE)

    def test_var_and_function_nodes(self):
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE)
        t_var = TypedVar(name="x", symbol=sym_x, type_val=INT_TYPE)
        self.assertEqual(t_var.name, "x")
        self.assertEqual(t_var.symbol, sym_x)

        # Fun(x: Int): Int x
        t_param = TypedParam(name="x", symbol=sym_x, type_val=INT_TYPE)
        fn_type = QFunType(params=(QParam("x", INT_TYPE),), result_type=INT_TYPE)
        t_fun = TypedFun(params=(t_param,), body=t_var, type_val=fn_type)
        self.assertEqual(t_fun.type_val, fn_type)

        # App: f(42)
        t_app = TypedApp(func=t_var, args=(TypedInt(42),), type_val=INT_TYPE)
        self.assertEqual(len(t_app.args), 1)
        self.assertEqual(t_app.type_val, INT_TYPE)

        # TypeApp: id[Int]
        t_tapp = TypedTypeApp(func=t_var, type_args=(INT_TYPE,), type_val=fn_type)
        self.assertEqual(t_tapp.type_args, (INT_TYPE,))

    def test_aggregates_and_projections(self):
        # Record { x = 1, y = 2 }
        rec_type = QRecordType((
            QRecordField("x", INT_TYPE),
            QRecordField("y", INT_TYPE),
        ))
        t_rec = TypedRecord(
            fields=(
                TypedRecordField("x", TypedInt(1)),
                TypedRecordField("y", TypedInt(2)),
            ),
            type_val=rec_type,
        )
        self.assertEqual(len(t_rec.fields), 2)
        self.assertEqual(t_rec.type_val, rec_type)

        # Select: t_rec.x
        t_sel = TypedSelect(target=t_rec, field="x", type_val=INT_TYPE)
        self.assertEqual(t_sel.field, "x")
        self.assertEqual(t_sel.type_val, INT_TYPE)

        # Tuple (1, "hi")
        tup_type = QTupleType((INT_TYPE, STRING_TYPE))
        t_tup = TypedTuple(elements=(TypedInt(1), TypedString("hi")), type_val=tup_type)
        self.assertEqual(len(t_tup.elements), 2)
        self.assertEqual(t_tup.type_val, tup_type)

    def test_references_and_mutation(self):
        # Var cell: var(42)
        var_type = QVarType(INT_TYPE)
        t_cell = TypedVarCell(value=TypedInt(42), type_val=var_type)
        self.assertEqual(t_cell.type_val, var_type)

        # Deref: !t_cell
        t_deref = TypedDerefCell(target=t_cell, type_val=INT_TYPE)
        self.assertEqual(t_deref.type_val, INT_TYPE)

        # Assign: t_cell := 100
        t_assign = TypedAssign(target=t_cell, value=TypedInt(100))
        self.assertEqual(t_assign.type_val, OK_TYPE)

    def test_control_flow_and_blocks(self):
        sym_x = ValueSymbol(name="x", type_val=INT_TYPE)
        let_bind = TypedLetValue(name="x", value=TypedInt(10), symbol=sym_x)
        t_var = TypedVar(name="x", symbol=sym_x, type_val=INT_TYPE)

        # Block: begin let x = 10; x end
        t_block = TypedBlock(bindings=(let_bind,), result=t_var, type_val=INT_TYPE)
        self.assertEqual(len(t_block.bindings), 1)
        self.assertEqual(t_block.type_val, INT_TYPE)

        # If: if true then 1 else 2 end
        t_if = TypedIf(
            cond=TypedBool(True),
            then_branch=TypedInt(1),
            else_branch=TypedInt(2),
            type_val=INT_TYPE,
        )
        self.assertEqual(t_if.type_val, INT_TYPE)

        # While: while true do exit end
        t_while = TypedWhile(cond=TypedBool(True), body=TypedExit())
        self.assertEqual(t_while.type_val, OK_TYPE)

    def test_variants_options_and_case(self):
        # Option: option some with 42 end
        opt_type = QOptionType((
            QOptionField("none"),
            QOptionField("some", INT_TYPE),
        ))
        t_opt = TypedOption(tag="some", payload=TypedInt(42), type_val=opt_type)
        self.assertEqual(t_opt.tag, "some")
        self.assertEqual(t_opt.type_val, opt_type)

        # Case: case t_opt when none => 0 when some => 1 end
        branch_none = TypedCaseBranch(tags=("none",), body=TypedInt(0))
        sym_v = ValueSymbol("val", INT_TYPE)
        branch_some = TypedCaseBranch(tags=("some",), binder=sym_v, body=TypedInt(1))
        t_case = TypedCase(
            target=t_opt,
            branches=(branch_none, branch_some),
            type_val=INT_TYPE,
        )
        self.assertEqual(len(t_case.branches), 2)
        self.assertEqual(t_case.type_val, INT_TYPE)

    def test_typed_ast_dump(self):
        t_int = TypedInt(42)
        self.assertEqual(typed_ast_dump(t_int), "(TypedInt 42 :type Int)")

        t_if = TypedIf(
            cond=TypedBool(True),
            then_branch=TypedInt(1),
            else_branch=TypedInt(2),
            type_val=INT_TYPE,
        )
        dump = typed_ast_dump(t_if)
        expected = (
            "(TypedIf :type Int\n"
            "  :cond (TypedBool true)\n"
            "  :then (TypedInt 1 :type Int)\n"
            "  :else (TypedInt 2 :type Int))"
        )
        self.assertEqual(dump, expected)


if __name__ == "__main__":
    unittest.main()
