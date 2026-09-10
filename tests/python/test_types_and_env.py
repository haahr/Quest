"""Comprehensive Unit Tests for Quest Semantic Types, Kinds, Scoping, and Environments."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.types import (
    TYPE_KIND,
    INT_TYPE,
    REAL_TYPE,
    BOOL_TYPE,
    CHAR_TYPE,
    STRING_TYPE,
    OK_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    QTypeKind,
    QPowerKind,
    QAllKind,
    QKindVar,
    QTupleType,
    QRecordField,
    QRecordType,
    QVariantField,
    QVariantType,
    QOptionField,
    QOptionType,
    QParam,
    QFunType,
    QVarType,
    QArrayType,
    QOutType,
    QQuantifier,
    QAllType,
    QAutoType,
    QTypeFormal,
    QTypeFun,
    QTypeApp,
    QRecType,
    QRecGroupType,
    QTypeVar,
    QAbstractType,
    QTypeMeta,
    is_subtype,
    is_type_equal,
    is_subkind,
    is_kind_equal,
    KindError,
    check_kind_well_formed,
    check_kind,
    synth_kind,
    qtype_dump,
)
from quest.env import (
    Symbol,
    ValueSymbol,
    TypeSymbol,
    KindSymbol,
    Scope,
    Environment,
)


class TestSemanticTypesAndKinds(unittest.TestCase):
    def test_primitive_singletons_and_str(self):
        self.assertEqual(str(INT_TYPE), "Int")
        self.assertEqual(str(REAL_TYPE), "Real")
        self.assertEqual(str(BOOL_TYPE), "Bool")
        self.assertEqual(str(CHAR_TYPE), "Char")
        self.assertEqual(str(STRING_TYPE), "String")
        self.assertEqual(str(OK_TYPE), "Ok")
        self.assertEqual(str(DYNAMIC_TYPE), "Dynamic")
        self.assertEqual(str(EXCEPTION_TYPE), "Exception")
        self.assertEqual(str(TYPE_KIND), "TYPE")

    def test_kinds(self):
        power_kind = QPowerKind(bound=INT_TYPE)
        self.assertEqual(str(power_kind), "<: Int")

        all_kind = QAllKind(param_name="X", param_id=1, param_kind=TYPE_KIND, result_kind=TYPE_KIND)
        self.assertEqual(str(all_kind), "ALL(X :: TYPE) TYPE")

    def test_subkinding_rules(self):
        # 1. Reflexivity: K <= K
        self.assertTrue(is_subkind(TYPE_KIND, TYPE_KIND))
        self.assertTrue(is_kind_equal(TYPE_KIND, TYPE_KIND))

        # 2. Power to Type: POWER(T) <= TYPE
        power_int = QPowerKind(INT_TYPE)
        self.assertTrue(is_subkind(power_int, TYPE_KIND))
        self.assertFalse(is_subkind(TYPE_KIND, power_int))

        # 3. Power to Power: POWER(S) <= POWER(T) iff S <: T
        vehicle = QRecordType((QRecordField("id", INT_TYPE),))
        car = QRecordType((QRecordField("id", INT_TYPE), QRecordField("speed", REAL_TYPE),))

        power_veh = QPowerKind(vehicle)
        power_car = QPowerKind(car)

        # Car <: Vehicle => POWER(Car) <= POWER(Vehicle)
        self.assertTrue(is_subkind(power_car, power_veh))
        self.assertFalse(is_subkind(power_veh, power_car))

    def test_subkinding_higher_order_operators(self):
        # Base types: Car <: Vehicle
        vehicle = QRecordType((QRecordField("id", INT_TYPE),))
        car = QRecordType((QRecordField("id", INT_TYPE), QRecordField("speed", REAL_TYPE),))

        # Operator kinds:
        # K1 = ALL(X :: TYPE) POWER(Car)
        # K2 = ALL(Y :: TYPE) POWER(Vehicle)
        # K3 = ALL(Z :: POWER(Car)) TYPE
        # K4 = ALL(W :: POWER(Vehicle)) TYPE

        k1 = QAllKind(param_name="X", param_id=1, param_kind=TYPE_KIND, result_kind=QPowerKind(car))
        k2 = QAllKind(param_name="Y", param_id=2, param_kind=TYPE_KIND, result_kind=QPowerKind(vehicle))

        # Result covariance with alpha-renaming (X vs Y): K1 <= K2
        self.assertTrue(is_subkind(k1, k2))
        self.assertFalse(is_subkind(k2, k1))

        # Parameter contravariance:
        # Since POWER(Car) <= POWER(Vehicle), ALL(W :: POWER(Vehicle)) TYPE <= ALL(Z :: POWER(Car)) TYPE
        k3 = QAllKind(param_name="Z", param_id=3, param_kind=QPowerKind(car), result_kind=TYPE_KIND)
        k4 = QAllKind(param_name="W", param_id=4, param_kind=QPowerKind(vehicle), result_kind=TYPE_KIND)

        self.assertTrue(is_subkind(k4, k3))
        self.assertFalse(is_subkind(k3, k4))

    def test_kind_well_formedness(self):
        env = Environment()
        # Proper types in power kinds are well-formed
        check_kind_well_formed(TYPE_KIND, env)
        check_kind_well_formed(QPowerKind(INT_TYPE), env)

        # Power kind over a type operator is ILL-FORMED
        pair_ctor = QTypeFun(
            params=(QTypeFormal("A", 1, TYPE_KIND),),
            body=QTupleType((QTypeVar("A", 1),)),
        )
        with self.assertRaises(KindError):
            check_kind_well_formed(QPowerKind(pair_ctor), env)

    def test_kind_synthesis_primitives_and_composites(self):
        env = Environment()
        # Primitives
        self.assertEqual(synth_kind(INT_TYPE, env), TYPE_KIND)
        self.assertEqual(synth_kind(STRING_TYPE, env), TYPE_KIND)

        # Record
        rec = QRecordType((QRecordField("x", INT_TYPE), QRecordField("y", BOOL_TYPE)))
        self.assertEqual(synth_kind(rec, env), TYPE_KIND)

        # Type variable with power kind
        env.current_scope.declare_type(
            TypeSymbol(name="MyInt", symbol_id=50, kind=QPowerKind(INT_TYPE))
        )
        type_var = QTypeVar("MyInt", 50)
        self.assertEqual(synth_kind(type_var, env), QPowerKind(INT_TYPE))

        # check_kind verifies that MyInt is acceptable where TYPE is expected
        check_kind(type_var, TYPE_KIND, env)

    def test_kind_synthesis_type_operators_and_applications(self):
        env = Environment()
        # Pair = Fun(A::TYPE B::TYPE) Tuple A B end
        pair_ctor = QTypeFun(
            params=(
                QTypeFormal("A", 1, TYPE_KIND),
                QTypeFormal("B", 2, TYPE_KIND),
            ),
            body=QTupleType((
                QTypeVar("A", 1),
                QTypeVar("B", 2),
            )),
        )
        pair_kind = synth_kind(pair_ctor, env)
        self.assertIsInstance(pair_kind, QAllKind)
        self.assertEqual(pair_kind.param_name, "A")
        self.assertIsInstance(pair_kind.result_kind, QAllKind)
        self.assertEqual(pair_kind.result_kind.param_name, "B")

        # Application: Pair(Int String) => TYPE
        app = QTypeApp(constructor=pair_ctor, arguments=(INT_TYPE, STRING_TYPE))
        app_kind = synth_kind(app, env)
        self.assertEqual(app_kind, TYPE_KIND)

        # Ill-kinded application: applying non-operator
        bad_app = QTypeApp(constructor=INT_TYPE, arguments=(STRING_TYPE,))
        with self.assertRaises(KindError):
            synth_kind(bad_app, env)

    def test_kind_synthesis_recursive_and_groups(self):
        env = Environment()
        # Rec(L::TYPE) Option nil cons with Record head: Int tail: L end end
        list_type = QRecType(
            var_name="L",
            symbol_id=10,
            bound=TYPE_KIND,
            body=QOptionType((
                QOptionField("nil"),
                QOptionField(
                    "cons",
                    QRecordType((
                        QRecordField("head", INT_TYPE),
                        QRecordField("tail", QTypeVar("L", 10)),
                    )),
                ),
            )),
        )
        self.assertEqual(synth_kind(list_type, env), TYPE_KIND)

    def test_composite_types_str(self):
        tuple_type = QTupleType((INT_TYPE, STRING_TYPE))
        self.assertEqual(str(tuple_type), "Tuple :Int :String end")

        record_type = QRecordType((
            QRecordField("x", INT_TYPE),
            QRecordField("y", REAL_TYPE, is_var=True),
        ))
        self.assertEqual(str(record_type), "Record x: Int var y: Real end")

        variant_type = QVariantType((
            QVariantField("none"),
            QVariantField("some", INT_TYPE),
        ))
        self.assertEqual(str(variant_type), "Variant none some: Int end")

        option_type = QOptionType((
            QOptionField("red"),
            QOptionField("blue", INT_TYPE),
        ))
        self.assertEqual(str(option_type), "Option red blue with Int end")

    def test_record_subtyping_width_depth_permutation(self):
        # Point2D = Record x: Int y: Int end
        point_2d = QRecordType((
            QRecordField("x", INT_TYPE),
            QRecordField("y", INT_TYPE),
        ))
        # Point3D = Record x: Int y: Int z: Int end (Width subtyping)
        point_3d = QRecordType((
            QRecordField("x", INT_TYPE),
            QRecordField("y", INT_TYPE),
            QRecordField("z", INT_TYPE),
        ))
        # PointPermuted = Record y: Int x: Int end (Permutation subtyping)
        point_permuted = QRecordType((
            QRecordField("y", INT_TYPE),
            QRecordField("x", INT_TYPE),
        ))

        # Point3D <: Point2D
        self.assertTrue(is_subtype(point_3d, point_2d))
        self.assertFalse(is_subtype(point_2d, point_3d))

        # PointPermuted <: Point2D and Point2D <: PointPermuted
        self.assertTrue(is_subtype(point_permuted, point_2d))
        self.assertTrue(is_subtype(point_2d, point_permuted))
        self.assertTrue(is_type_equal(point_2d, point_permuted))

    def test_record_mutable_field_invariance(self):
        # Record var x: Sub end vs Record var x: Sup end (must be invariant)
        rec_val = QRecordType((QRecordField("x", INT_TYPE, is_var=False),))
        rec_var = QRecordType((QRecordField("x", INT_TYPE, is_var=True),))

        # Mutable is NOT a subtype of immutable without explicit subtyping rule
        self.assertFalse(is_subtype(rec_val, rec_var))
        self.assertTrue(is_subtype(rec_var, rec_val))

    def test_function_subtyping(self):
        # S1 <: T1, S2 <: T2
        # Base: Car <: Vehicle
        vehicle = QRecordType((QRecordField("id", INT_TYPE),))
        car = QRecordType((QRecordField("id", INT_TYPE), QRecordField("speed", REAL_TYPE),))

        # f1: Vehicle -> Car
        # f2: Car -> Vehicle
        f_veh_to_car = QFunType(params=(QParam("v", vehicle),), result_type=car)
        f_car_to_veh = QFunType(params=(QParam("c", car),), result_type=vehicle)

        # Vehicle -> Car <: Car -> Vehicle (Contravariant param, Covariant result)
        self.assertTrue(is_subtype(f_veh_to_car, f_car_to_veh))
        self.assertFalse(is_subtype(f_car_to_veh, f_veh_to_car))

    def test_reference_and_array_invariance(self):
        vehicle = QRecordType((QRecordField("id", INT_TYPE),))
        car = QRecordType((QRecordField("id", INT_TYPE), QRecordField("speed", REAL_TYPE),))

        var_veh = QVarType(vehicle)
        var_car = QVarType(car)
        self.assertFalse(is_subtype(var_car, var_veh))
        self.assertFalse(is_subtype(var_veh, var_car))

        arr_veh = QArrayType(vehicle)
        arr_car = QArrayType(car)
        self.assertFalse(is_subtype(arr_car, arr_veh))
        self.assertFalse(is_subtype(arr_veh, arr_car))

    def test_type_operator_lazy_evaluation(self):
        # Pair = Fun(A::TYPE B::TYPE) Tuple A B end
        pair_ctor = QTypeFun(
            params=(
                QTypeFormal("A", 1, TYPE_KIND),
                QTypeFormal("B", 2, TYPE_KIND),
            ),
            body=QTupleType((
                QTypeVar("A", 1),
                QTypeVar("B", 2),
            )),
        )
        # Pair(Int String)
        app = QTypeApp(constructor=pair_ctor, arguments=(INT_TYPE, STRING_TYPE))
        evaluated = app.evaluate_lazily()
        self.assertIsInstance(evaluated, QTupleType)
        self.assertEqual(evaluated.elements, (INT_TYPE, STRING_TYPE))
        self.assertEqual(str(evaluated), "Tuple :Int :String end")

    def test_single_recursive_type(self):
        # List = Rec(L::TYPE) Option nil cons with Record head: Int tail: L end end
        list_type = QRecType(
            var_name="L",
            symbol_id=10,
            bound=TYPE_KIND,
            body=QOptionType((
                QOptionField("nil"),
                QOptionField(
                    "cons",
                    QRecordType((
                        QRecordField("head", INT_TYPE),
                        QRecordField("tail", QTypeVar("L", 10)),
                    )),
                ),
            )),
        )

        # Lazy evaluation unfolds one layer
        unfolded = list_type.evaluate_lazily()
        self.assertIsInstance(unfolded, QOptionType)
        self.assertEqual(len(unfolded.options), 2)
        self.assertEqual(unfolded.options[0].name, "nil")
        self.assertEqual(unfolded.options[1].name, "cons")

        # Subtyping check with cycle detection
        self.assertTrue(is_subtype(list_type, list_type))
        self.assertTrue(is_type_equal(list_type, list_type))

    def test_mutual_recursive_type_group(self):
        # Let Rec Tree = Option leaf node with NodeList end
        # and NodeList = Option empty cons with Record head: Tree tail: NodeList end end
        tree_body = QOptionType((
            QOptionField("leaf", INT_TYPE),
            QOptionField("node", QTypeVar("NodeList", 20)),
        ))
        nodelist_body = QOptionType((
            QOptionField("empty"),
            QOptionField(
                "cons",
                QRecordType((
                    QRecordField("head", QTypeVar("Tree", 10)),
                    QRecordField("tail", QTypeVar("NodeList", 20)),
                )),
            ),
        ))

        bindings = (
            ("Tree", 10, TYPE_KIND, tree_body),
            ("NodeList", 20, TYPE_KIND, nodelist_body),
        )

        tree_rec = QRecGroupType(bindings=bindings, active_index=0)
        nodelist_rec = QRecGroupType(bindings=bindings, active_index=1)

        self.assertEqual(tree_rec.current_name, "Tree")
        self.assertEqual(nodelist_rec.current_name, "NodeList")

        # Lazy unfolding
        tree_unfolded = tree_rec.evaluate_lazily()
        self.assertIsInstance(tree_unfolded, QOptionType)
        self.assertEqual(tree_unfolded.options[0].name, "leaf")
        self.assertEqual(tree_unfolded.options[1].name, "node")

        # Cycle-safe subtyping
        self.assertTrue(is_subtype(tree_rec, tree_rec))
        self.assertTrue(is_subtype(nodelist_rec, nodelist_rec))
        self.assertFalse(is_subtype(tree_rec, nodelist_rec))

    def test_type_meta_unification(self):
        QTypeMeta.reset_counter()
        meta1 = QTypeMeta()
        meta2 = QTypeMeta()

        self.assertEqual(meta1.name, "?T1")
        self.assertEqual(meta2.name, "?T2")
        self.assertFalse(meta1.is_solved())

        # Unify meta1 with meta2, then meta2 with Int
        meta1.instance = meta2
        meta2.instance = INT_TYPE

        self.assertTrue(meta1.is_solved())
        self.assertEqual(meta1.prune(), INT_TYPE)
        self.assertEqual(str(meta1), "Int")
        self.assertTrue(is_type_equal(meta1, INT_TYPE))

    def test_qtype_dump_s_expressions(self):
        rec_type = QRecordType((
            QRecordField("x", INT_TYPE),
            QRecordField("y", REAL_TYPE, is_var=True),
        ))
        dump = qtype_dump(rec_type)
        expected = (
            "(QRecordType\n"
            "  :fields (\n"
            "    (QRecordField 'x' (QIntType))\n"
            "    (QRecordField 'y' :var (QRealType))\n"
            "  ))"
        )
        self.assertEqual(dump, expected)


class TestScopingAndEnvironment(unittest.TestCase):
    def test_environment_initial_builtins(self):
        env = Environment()

        # Built-in Types
        for name in ["Int", "Real", "Bool", "Char", "String", "Ok", "Dynamic", "Exception"]:
            sym = env.lookup_type(name)
            self.assertIsNotNone(sym, f"Built-in type {name} should exist")
            self.assertFalse(sym.is_abstract)

        # Built-in Values
        for name in ["true", "false", "ok"]:
            sym = env.lookup_value(name)
            self.assertIsNotNone(sym, f"Built-in value {name} should exist")

        # Built-in Kinds
        kind_sym = env.lookup_kind("TYPE")
        self.assertIsNotNone(kind_sym, "Built-in kind TYPE should exist")

    def test_scope_ordered_declarations(self):
        scope = Scope(name="test")
        v1 = scope.declare_value(ValueSymbol("a", INT_TYPE))
        t1 = scope.declare_type(TypeSymbol("T", 1, TYPE_KIND, INT_TYPE))
        v2 = scope.declare_value(ValueSymbol("b", STRING_TYPE))

        # Check strict declaration order
        decls = scope.declarations
        self.assertEqual(len(decls), 3)
        self.assertEqual(decls[0], v1)
        self.assertEqual(decls[1], t1)
        self.assertEqual(decls[2], v2)

    def test_environment_push_pop_scope_lexical_chain(self):
        env = Environment()
        env.global_scope.declare_value(ValueSymbol("global_var", INT_TYPE))

        # Push scope 1
        scope1 = env.push_scope("scope1")
        scope1.declare_value(ValueSymbol("local_var1", STRING_TYPE))
        scope1.declare_value(ValueSymbol("shadowed", INT_TYPE))

        # Push scope 2
        scope2 = env.push_scope("scope2")
        scope2.declare_value(ValueSymbol("shadowed", BOOL_TYPE))

        # Lookups in scope 2
        self.assertEqual(env.lookup_value("global_var").type_val, INT_TYPE)
        self.assertEqual(env.lookup_value("local_var1").type_val, STRING_TYPE)
        self.assertEqual(env.lookup_value("shadowed").type_val, BOOL_TYPE)

        # Pop scope 2
        popped = env.pop_scope()
        self.assertEqual(popped, scope2)
        self.assertEqual(env.current_scope, scope1)
        self.assertEqual(env.lookup_value("shadowed").type_val, INT_TYPE)

        # Pop scope 1
        env.pop_scope()
        self.assertEqual(env.current_scope, env.global_scope)
        self.assertIsNone(env.lookup_value("local_var1"))

    def test_type_symbol_definition_lazy_evaluation(self):
        env = Environment()
        # Declare type alias: MyInt = Int
        sym = env.current_scope.declare_type(
            TypeSymbol(name="MyInt", symbol_id=100, kind=TYPE_KIND, definition=INT_TYPE)
        )
        type_var = QTypeVar("MyInt", 100)

        # Lazy evaluation resolves the alias via the environment
        resolved = type_var.evaluate_lazily(env)
        self.assertEqual(resolved, INT_TYPE)


if __name__ == "__main__":
    unittest.main()
