"""Comprehensive Unit Tests for Quest Type and Kind Elaboration."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

import quest.ast as ast
from quest.types import (
    TYPE_KIND,
    INT_TYPE,
    REAL_TYPE,
    BOOL_TYPE,
    STRING_TYPE,
    KindError,
    QTypeKind,
    QPowerKind,
    QAllKind,
    QKindVar,
    QTupleType,
    QTupleField,
    QRecordType,
    QVariantType,
    QOptionType,
    QFunType,
    QVarType,
    QArrayType,
    QOutType,
    QAllType,
    QAutoType,
    QTypeFun,
    QTypeApp,
    QRecType,
    QRecGroupType,
    QTypeVar,
    is_subtype,
    is_type_equal,
    is_subkind,
)
from quest.env import (
    Environment,
    KindSymbol,
    Scope,
    TypeSymbol,
    ValueSymbol,
)
from quest.elaborate_types import (
    elaborate_kind,
    elaborate_type,
    elaborate_kind_binding,
    elaborate_type_binding,
    elaborate_mutual_rec_type_group,
)


class TestKindElaboration(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

    def test_elaborate_base_and_power_kinds(self):
        # TYPE
        k_type = elaborate_kind(ast.KindType(), self.env)
        self.assertEqual(k_type, TYPE_KIND)

        # POWER(Int)
        k_power = elaborate_kind(ast.KindPower(bound=ast.TypePath(("Int",))), self.env)
        self.assertIsInstance(k_power, QPowerKind)
        self.assertEqual(k_power.bound, INT_TYPE)

    def test_elaborate_kind_all_operator(self):
        # ALL(X :: TYPE) TYPE
        ast_all = ast.KindAll(
            param_name="X",
            param_kind=ast.KindType(),
            body_kind=ast.KindType(),
        )
        k_all = elaborate_kind(ast_all, self.env)
        self.assertIsInstance(k_all, QAllKind)
        self.assertEqual(k_all.param_name, "X")
        self.assertEqual(k_all.param_kind, TYPE_KIND)
        self.assertEqual(k_all.result_kind, TYPE_KIND)

    def test_elaborate_kind_id_and_manifest(self):
        # Declare kind alias: DEF MY_KIND = TYPE
        self.env.global_scope.declare_kind(
            KindSymbol(name="MY_KIND", symbol_id=self.env.fresh_symbol_id(), kind=TYPE_KIND)
        )
        k_id = elaborate_kind(ast.KindId("MY_KIND"), self.env)
        self.assertIsInstance(k_id, QKindVar)
        self.assertEqual(k_id.name, "MY_KIND")

        # Unbound kind error
        with self.assertRaises(KindError):
            elaborate_kind(ast.KindId("UNKNOWN_KIND"), self.env)


class TestTypeElaboration(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

    def test_elaborate_type_path_primitive_and_module(self):
        # Int
        t_int = elaborate_type(ast.TypePath(("Int",)), self.env)
        self.assertEqual(t_int, INT_TYPE)

        # Mod.T
        mod_scope = Scope(parent=None, name="Mod")
        mod_scope.declare_type(
            TypeSymbol(name="T", symbol_id=self.env.fresh_symbol_id(), kind=TYPE_KIND, definition=STRING_TYPE)
        )
        self.env.register_module("Mod", mod_scope)

        t_mod = elaborate_type(ast.TypePath(("Mod", "T")), self.env)
        self.assertEqual(t_mod, STRING_TYPE)

    def test_elaborate_infix_function_type(self):
        # Int -> String
        ast_fn = ast.TypeInfix(
            left=ast.TypePath(("Int",)),
            op="->",
            right=ast.TypePath(("String",)),
        )
        t_fn = elaborate_type(ast_fn, self.env)
        self.assertIsInstance(t_fn, QFunType)
        self.assertEqual(t_fn.params[0].type_val, INT_TYPE)
        self.assertEqual(t_fn.result_type, STRING_TYPE)

    def test_elaborate_records_and_tuples(self):
        # Record x: Int var y: Real end
        ast_rec = ast.TypeRecord((
            ast.RecordFieldSig("x", ast.TypePath(("Int",))),
            ast.RecordFieldSig("y", ast.TypePath(("Real",)), is_var=True),
        ))
        t_rec = elaborate_type(ast_rec, self.env)
        self.assertIsInstance(t_rec, QRecordType)
        self.assertEqual(len(t_rec.fields), 2)
        self.assertEqual(t_rec.fields[0].name, "x")
        self.assertEqual(t_rec.fields[0].type_val, INT_TYPE)
        self.assertTrue(t_rec.fields[1].is_var)

        # Tuple a: Int b: String end
        ast_tup = ast.TypeTuple((
            ast.FieldSig("a", ast.TypePath(("Int",))),
            ast.FieldSig("b", ast.TypePath(("String",))),
        ))
        t_tup = elaborate_type(ast_tup, self.env)
        self.assertIsInstance(t_tup, QTupleType)
        self.assertEqual(t_tup.elements, (INT_TYPE, STRING_TYPE))

    def test_elaborate_variants_and_options(self):
        # Option red green with val: Int end
        ast_opt = ast.TypeOption((
            ast.OptionFieldSig("red"),
            ast.OptionFieldSig("green", (ast.FieldSig("val", ast.TypePath(("Int",))),)),
        ))
        t_opt = elaborate_type(ast_opt, self.env)
        self.assertIsInstance(t_opt, QOptionType)
        self.assertEqual(len(t_opt.options), 2)
        self.assertIsNone(t_opt.options[0].payload_type)
        self.assertEqual(
            t_opt.options[1].payload_type,
            QTupleType((QTupleField(name="val", type_val=INT_TYPE),)),
        )

    def test_elaborate_polymorphic_and_operators(self):
        # All(X::TYPE) X -> X
        ast_all = ast.TypeAll(
            quantifiers=(ast.Quantifier("X", ast.KindType()),),
            result_type=ast.TypeInfix(ast.TypePath(("X",)), "->", ast.TypePath(("X",))),
        )
        t_all = elaborate_type(ast_all, self.env)
        self.assertIsInstance(t_all, QAllType)
        self.assertEqual(len(t_all.quantifiers), 1)
        self.assertEqual(t_all.quantifiers[0].name, "X")

        # Fun(A::TYPE B::TYPE) Tuple A B end
        ast_fun = ast.TypeFun(
            params=(
                ast.TypeFormal("A", ast.KindType()),
                ast.TypeFormal("B", ast.KindType()),
            ),
            result_kind=None,
            body=ast.TypeTuple((
                ast.FieldSig("a", ast.TypePath(("A",))),
                ast.FieldSig("b", ast.TypePath(("B",))),
            )),
        )
        t_fun = elaborate_type(ast_fun, self.env)
        self.assertIsInstance(t_fun, QTypeFun)

        # Pair(Int String)
        ast_app = ast.TypeApp(
            constructor=ast_fun,
            arguments=(ast.TypePath(("Int",)), ast.TypePath(("String",))),
        )
        t_app = elaborate_type(ast_app, self.env)
        self.assertIsInstance(t_app, QTypeApp)
        evaluated = t_app.evaluate_lazily(self.env)
        self.assertEqual(evaluated, QTupleType((INT_TYPE, STRING_TYPE)))

    def test_elaborate_recursive_type(self):
        # Rec(L::TYPE) Option nil cons with Record head: Int tail: L end end
        ast_rec = ast.TypeRec(
            var_name="L",
            bound=ast.KindType(),
            body=ast.TypeOption((
                ast.OptionFieldSig("nil"),
                ast.OptionFieldSig(
                    "cons",
                    (ast.FieldSig("val", ast.TypeRecord((
                        ast.RecordFieldSig("head", ast.TypePath(("Int",))),
                        ast.RecordFieldSig("tail", ast.TypePath(("L",))),
                    ))),),
                ),
            )),
        )
        t_rec = elaborate_type(ast_rec, self.env)
        self.assertIsInstance(t_rec, QRecType)
        self.assertEqual(t_rec.var_name, "L")
        self.assertTrue(is_subtype(t_rec, t_rec))


class TestDeclarationElaboration(unittest.TestCase):
    def setUp(self):
        self.env = Environment()

    def test_elaborate_kind_binding(self):
        ast_kind_def = ast.DefKindBinding("MY_K", ast.KindType())
        sym = elaborate_kind_binding(ast_kind_def, self.env)
        self.assertEqual(sym.name, "MY_K")
        self.assertEqual(sym.kind, TYPE_KIND)
        self.assertEqual(self.env.lookup_kind("MY_K"), sym)

    def test_elaborate_simple_and_parameterized_type_binding(self):
        # Let MyInt = Int
        ast_let = ast.LetTypeBinding(name="MyInt", type_val=ast.TypePath(("Int",)))
        sym = elaborate_type_binding(ast_let, self.env)
        self.assertEqual(sym.name, "MyInt")
        self.assertEqual(sym.definition, INT_TYPE)

        # Let Pair(A::TYPE B::TYPE) = Tuple A B end
        ast_pair = ast.LetTypeBinding(
            name="Pair",
            type_val=ast.TypeTuple((
                ast.FieldSig("a", ast.TypePath(("A",))),
                ast.FieldSig("b", ast.TypePath(("B",))),
            )),
            params=(
                ast.TypeFormal("A", ast.KindType()),
                ast.TypeFormal("B", ast.KindType()),
            ),
        )
        pair_sym = elaborate_type_binding(ast_pair, self.env)
        self.assertEqual(pair_sym.name, "Pair")
        self.assertIsInstance(pair_sym.definition, QTypeFun)

    def test_elaborate_mutual_recursive_type_group(self):
        # Let Rec Tree = Option leaf: Int node: NodeList end
        # and NodeList = Option empty cons: Record head: Tree tail: NodeList end end
        tree_ast = ast.LetTypeBinding(
            name="Tree",
            type_val=ast.TypeOption((
                ast.OptionFieldSig("leaf", (ast.FieldSig("val", ast.TypePath(("Int",))),)),
                ast.OptionFieldSig("node", (ast.FieldSig("val", ast.TypePath(("NodeList",))),)),
            )),
            is_rec=True,
        )
        nodelist_ast = ast.LetTypeBinding(
            name="NodeList",
            type_val=ast.TypeOption((
                ast.OptionFieldSig("empty"),
                ast.OptionFieldSig(
                    "cons",
                    (ast.FieldSig("val", ast.TypeRecord((
                        ast.RecordFieldSig("head", ast.TypePath(("Tree",))),
                        ast.RecordFieldSig("tail", ast.TypePath(("NodeList",))),
                    ))),),
                ),
            )),
            is_rec=True,
        )

        symbols = elaborate_mutual_rec_type_group([tree_ast, nodelist_ast], self.env)
        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0].name, "Tree")
        self.assertEqual(symbols[1].name, "NodeList")

        tree_rec = symbols[0].definition
        nodelist_rec = symbols[1].definition
        self.assertIsInstance(tree_rec, QRecGroupType)
        self.assertIsInstance(nodelist_rec, QRecGroupType)

        # Unfolding & subtyping verification
        self.assertTrue(is_subtype(tree_rec, tree_rec))
        self.assertTrue(is_subtype(nodelist_rec, nodelist_rec))


if __name__ == "__main__":
    unittest.main()
