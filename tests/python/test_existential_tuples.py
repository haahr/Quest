"""Unit tests for existential tuple signature elaboration and type representation."""

import unittest
from typing import Any

from quest.ast import (
    KindType,
    TypeFormal,
    TypeTuple,
)
from quest.elaborate_types import elaborate_type
from quest.env import Environment
from quest.interpreter import RuntimeEnvironment
from quest.pipeline import CompilerContext, default_pipeline
from quest.runtime import QClosure, QInt, QTuple, QTypeValue
from quest.diagnostics import QuestTypeError
from quest.types import (
    INT_TYPE,
    OK_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    KindError,
    QFunType,
    QPowerKind,
    QTupleField,
    QTupleType,
    QTupleTypeBinding,
    QTupleTypeFormal,
    QTypeVar,
    is_subtype,
)
from tests.python.helpers import (
    assert_pipeline_failure,
    assert_pipeline_success,
    elaborate_test_type,
    run_pipeline,
)


class TestExistentialTuplesPhase1(unittest.TestCase):
    """Verifies Phase 1: tuple type representation and signature elaboration."""

    def setUp(self) -> None:
        self.env = Environment()

    def run_source(self, source: str) -> None:
        assert_pipeline_success(source, env=self.env)

    def test_cardelli_abstract_tuple_signature_elaboration(self) -> None:
        """Cardelli §5.3: Let T = Tuple A::TYPE a:A f(x:A):Int end;"""
        self.run_source("Let T = Tuple A::TYPE a:A f(x:A):Int end;")

        sym = self.env.lookup_type("T")
        self.assertIsNotNone(sym)
        self.assertIsNotNone(sym.definition)

        tup_type = sym.definition
        self.assertIsInstance(tup_type, QTupleType)
        self.assertTrue(tup_type.is_existential)
        self.assertEqual(len(tup_type.fields), 3)

        # Component 0: A::TYPE
        formal = tup_type.fields[0]
        self.assertIsInstance(formal, QTupleTypeFormal)
        self.assertEqual(formal.name, "A")
        self.assertEqual(formal.bound, TYPE_KIND)

        # Component 1: a:A
        field_a = tup_type.fields[1]
        self.assertIsInstance(field_a, QTupleField)
        self.assertEqual(field_a.name, "a")
        self.assertIsInstance(field_a.type_val, QTypeVar)
        self.assertEqual(field_a.type_val.symbol_id, formal.symbol_id)

        # Component 2: f(x:A):Int -> Fun(x:A):Int
        field_f = tup_type.fields[2]
        self.assertIsInstance(field_f, QTupleField)
        self.assertEqual(field_f.name, "f")
        self.assertIsInstance(field_f.type_val, QFunType)
        self.assertEqual(field_f.type_val.params[0].type_val, field_a.type_val)
        self.assertEqual(field_f.type_val.result_type, INT_TYPE)

    def test_nested_existential_tuple_dependent_scoping(self) -> None:
        """Type formal introduced in outer tuple is in scope in inner tuple."""
        self.run_source("Let T = Tuple A::TYPE pair:Tuple x:A y:A end end;")

        sym = self.env.lookup_type("T")
        self.assertIsNotNone(sym)
        tup_type = sym.definition
        self.assertIsInstance(tup_type, QTupleType)

        formal_a = tup_type.fields[0]
        pair_field = tup_type.fields[1]
        self.assertIsInstance(pair_field.type_val, QTupleType)

        inner_tup = pair_field.type_val
        self.assertEqual(len(inner_tup.fields), 2)
        self.assertEqual(inner_tup.fields[0].type_val.symbol_id, formal_a.symbol_id)
        self.assertEqual(inner_tup.fields[1].type_val.symbol_id, formal_a.symbol_id)

    def test_manifest_type_in_tuple_signature(self) -> None:
        """Tuple signature with manifest type definition: Tuple Def A::TYPE = Int a:A end."""
        self.run_source("Let T = Tuple Def A::TYPE = Int a:A end;")

        sym = self.env.lookup_type("T")
        self.assertIsNotNone(sym)
        tup_type = sym.definition
        self.assertIsInstance(tup_type, QTupleType)
        self.assertEqual(len(tup_type.fields), 2)

        comp_0 = tup_type.fields[0]
        self.assertIsInstance(comp_0, QTupleTypeBinding)
        self.assertEqual(comp_0.name, "A")
        self.assertEqual(comp_0.type_val, INT_TYPE)

    def test_anonymous_type_formal_rejected(self) -> None:
        """Anonymous type formal (::TYPE) in tuple signature must be rejected."""
        ast_tuple = TypeTuple(
            fields=(
                TypeFormal(name="_", bound=KindType(offset=10), offset=10),
            ),
            offset=0,
        )
        with self.assertRaises(KindError) as cm:
            elaborate_type(ast_tuple, self.env)
        self.assertIn("must have an identifier", str(cm.exception))

    def test_tuple_type_substitute_shadowing(self) -> None:
        """Substitution must shadow type formal symbol IDs for subsequent components."""
        formal_id = self.env.fresh_symbol_id()
        formal = QTupleTypeFormal(name="A", symbol_id=formal_id, bound=TYPE_KIND)
        field = QTupleField(name="a", type_val=QTypeVar("A", symbol_id=formal_id, bound=TYPE_KIND))
        tup = QTupleType((formal, field))

        # Attempt to substitute formal_id with INT_TYPE from outer scope
        subst = {formal_id: INT_TYPE}
        res = tup.substitute(subst)
        self.assertIsInstance(res, QTupleType)
        # field.type_val must remain QTypeVar, NOT substituted by INT_TYPE
        self.assertIsInstance(res.fields[1].type_val, QTypeVar)
        self.assertEqual(res.fields[1].type_val.symbol_id, formal_id)


class TestExistentialTuplesPhase2(unittest.TestCase):
    """Verifies Phase 2: tuple subtyping & extended subsignatures."""

    def setUp(self) -> None:
        self.env = Environment()

    def test_prefix_subtyping_simple_tuples(self) -> None:
        """Cardelli §7.1: Vehicle <: Object (prefix subtyping)."""
        object_tup = elaborate_test_type("Tuple age: Int end", self.env)
        vehicle_tup = elaborate_test_type("Tuple age: Int speed: Int end", self.env)

        # Vehicle <: Object
        self.assertTrue(is_subtype(vehicle_tup, object_tup, self.env))
        # Object is NOT a subtype of Vehicle
        self.assertFalse(is_subtype(object_tup, vehicle_tup, self.env))

    def test_cardelli_abstract_tuple_subtyping(self) -> None:
        """Cardelli §7.1: ColorPoint <: Point."""
        point_type = elaborate_test_type(
            "Tuple A::TYPE new(x:Int y:Int):A x(p:A):Int end",
            self.env,
        )
        color_point_type = elaborate_test_type(
            "Tuple A::TYPE new(x:Int y:Int):A x(p:A):Int paint(p:A c:Int):Ok color(p:A):Int end",
            self.env,
        )

        # ColorPoint <: Point
        self.assertTrue(is_subtype(color_point_type, point_type, self.env))
        # Point is NOT a subtype of ColorPoint
        self.assertFalse(is_subtype(point_type, color_point_type, self.env))

    def test_component_name_mismatch_rejected(self) -> None:
        """Rule 4: Component names must match identically (no alpha-conversion)."""
        t1 = elaborate_test_type("Tuple A::TYPE a:A end", self.env)
        t2 = elaborate_test_type("Tuple B::TYPE a:B end", self.env)

        # Distinct type formal names A vs B: must NOT be subtypes
        self.assertFalse(is_subtype(t1, t2, self.env))
        self.assertFalse(is_subtype(t2, t1, self.env))

    def test_value_field_name_mismatch_rejected(self) -> None:
        """Value field names must match if present in supertype."""
        t1 = elaborate_test_type("Tuple x: Int end", self.env)
        t2 = elaborate_test_type("Tuple y: Int end", self.env)
        self.assertFalse(is_subtype(t1, t2, self.env))

    def test_type_formal_subkinding(self) -> None:
        """Type formal subkinding: POWER(Int) <:: TYPE."""
        sub_tup = elaborate_test_type("Tuple A::POWER(Int) a:A end", self.env)
        sup_tup = elaborate_test_type("Tuple A::TYPE a:A end", self.env)

        # A::POWER(Int) <: A::TYPE
        self.assertTrue(is_subtype(sub_tup, sup_tup, self.env))
        # A::TYPE is NOT subtype of A::POWER(Int)
        self.assertFalse(is_subtype(sup_tup, sub_tup, self.env))

    def test_manifest_type_binding_subtype_of_formal(self) -> None:
        """Manifest type binding Tuple Def A::TYPE = Int a:A end <: Tuple A::TYPE a:A end."""
        manifest_sub = elaborate_test_type("Tuple Def A::TYPE = Int a:A end", self.env)
        sup_tup = elaborate_test_type("Tuple A::TYPE a:A end", self.env)

        self.assertTrue(is_subtype(manifest_sub, sup_tup, self.env))


class TestExistentialTuplesPhase3(unittest.TestCase):
    """Verifies Phase 3: existential tuple packing, witness checking, and execution."""

    def setUp(self) -> None:
        self.env = Environment()
        self.runtime_env = RuntimeEnvironment.create_root_env()

    def run_source(self, source: str) -> CompilerContext:
        return assert_pipeline_success(source, env=self.env, runtime_env=self.runtime_env)

    def check_failure(self, source: str, expected_substr: str) -> None:
        assert_pipeline_failure(source, expected_substr, env=self.env, runtime_env=self.runtime_env)

    def test_cardelli_existential_tuple_packing_and_execution(self) -> None:
        """Cardelli §5.3: Packing existential tuple with witness and value fields."""
        source = """
        Let T = Tuple A::TYPE a:A f(x:A):Int end;
        let t1: T = tuple Let A::TYPE = Int let a:A = 0 let f(x:A):Int = x+1 end;
        """
        ctx = self.run_source(source)
        self.assertIn("t1", ctx.env.current_scope.values)
        t1_val = ctx.runtime_env.lookup("t1")
        self.assertIsInstance(t1_val, QTuple)
        self.assertEqual(len(t1_val.elements), 3)
        self.assertEqual(t1_val.labels, ("A", "a", "f"))
        self.assertEqual(t1_val.get_by_name("A"), QTypeValue(INT_TYPE, name="A"))
        self.assertEqual(t1_val.get_by_name("a"), QInt(0))
        self.assertIsInstance(t1_val.get_by_name("f"), QClosure)

    def test_unannotated_tuple_synthesis_and_coercion(self) -> None:
        """Unannotated tuple synthesizes transparent tuple type which coerces to existential."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t = tuple Let A::TYPE = Int let a:A = 42 end;
        let t1: T = t;
        """
        ctx = self.run_source(source)
        t_sym = ctx.env.current_scope.lookup_value("t")
        self.assertIsNotNone(t_sym)
        t_type = t_sym.type_val
        self.assertIsInstance(t_type, QTupleType)
        self.assertFalse(t_type.is_existential)
        self.assertEqual(len(t_type.fields), 2)
        self.assertIsInstance(t_type.fields[0], QTupleTypeBinding)
        self.assertEqual(t_type.fields[0].name, "A")
        self.assertEqual(t_type.fields[0].type_val, INT_TYPE)

        t1_sym = ctx.env.current_scope.lookup_value("t1")
        self.assertIsNotNone(t1_sym)
        t1_type = t1_sym.type_val
        self.assertIsInstance(t1_type, QTupleType)
        self.assertTrue(t1_type.is_existential)

    def test_type_mismatch_in_witness_substituted_field(self) -> None:
        """Field value violating witness-substituted type is rejected with TypeError."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple Let A::TYPE = Int let a = "hello" end;
        """
        self.check_failure(source, "is not a subtype of expected type 'Int'")

    def test_type_formal_name_mismatch_rejected(self) -> None:
        """Component name mismatch between witness and type formal is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple Let B::TYPE = Int let a = 0 end;
        """
        self.check_failure(source, "Tuple type formal name mismatch: expected 'A', got 'B'")

    def test_tuple_arity_mismatch_rejected(self) -> None:
        """Tuple packing with missing component is rejected with arity mismatch."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple Let A::TYPE = Int end;
        """
        self.check_failure(source, "Tuple arity mismatch: expected 2 components, got 1")

    def test_value_provided_for_type_formal_rejected(self) -> None:
        """Providing a value where a type witness is expected is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple let A = 0 let a = 0 end;
        """
        self.check_failure(source, "Expected type witness for type formal 'A', got value component")

    def test_type_binding_for_value_field_rejected(self) -> None:
        """Providing a type binding where a value field is expected is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple Let A::TYPE = Int Let a = Int end;
        """
        self.check_failure(source, "Unexpected type binding 'a' for value field 'a'")

    def test_witness_kind_bound_mismatch_rejected(self) -> None:
        """Providing a witness that does not satisfy the kind bound is rejected."""
        source = """
        Let T = Tuple A::POWER(Int) a:A end;
        let t1: T = tuple Let A::TYPE = String let a = "test" end;
        """
        self.check_failure(source, "Kind mismatch")


class TestExistentialTuplesPhase4(unittest.TestCase):
    """Unit tests for Phase 4: Path-Dependent Types, Member Projection & Escape Checking."""

    def setUp(self) -> None:
        self.pipeline = default_pipeline()
        self.env = Environment()
        self.runtime_env = RuntimeEnvironment.create_root_env()

    def run_source(self, source: str) -> tuple[CompilerContext, Any]:
        """Compiles and executes source, returning (ctx, final_val)."""
        ctx = CompilerContext.create(
            source,
            "<test>",
            env=self.env,
            runtime_env=self.runtime_env,
        )
        res = self.pipeline.execute(source, "<test>", ctx=ctx)
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        return ctx, res.final_artifact

    def check_failure(self, source: str, expected_substr: str) -> None:
        assert_pipeline_failure(source, expected_substr, env=self.env, runtime_env=self.runtime_env)

    def test_cardelli_section_5_3_end_to_end(self) -> None:
        """Cardelli §5.3: packing, dot-projection, path-type annotation, and application."""
        source = """
        Let T = Tuple A::TYPE a:A f(x:A):Int end;
        let t1: T = tuple Let A::TYPE = Int let a = 0 let f(x: A): Int = x + 1 end;
        let a1: t1.A = t1.a;
        let res: Int = t1.f(a1);
        """
        _, val = self.run_source(source)
        res_val = self.runtime_env.lookup("res")
        self.assertIsNotNone(res_val)
        self.assertIsInstance(res_val, QInt)
        self.assertEqual(res_val.value, 1)

    def test_distinct_package_abstraction_incompatibility(self) -> None:
        """Two packages with identical signatures have distinct abstract types t1.A != t2.A."""
        source = """
        Let T = Tuple A::TYPE a:A f(x:A):Int end;
        let t1: T = tuple Let A::TYPE = Int let a = 0 let f(x: A): Int = x + 1 end;
        let t2: T = tuple Let A::TYPE = Int let a = 0 let f(x: A): Int = x + 1 end;
        let bad = t1.f(t2.a);
        """
        self.check_failure(source, "synthesized type 't2.A' is not a subtype of expected type 't1.A'")

    def test_abstract_type_mismatch_with_concrete_type(self) -> None:
        """Abstract type t1.A cannot be treated as concrete witness Int without bound."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let t1: T = tuple Let A::TYPE = Int let a = 0 end;
        let bad = t1.a + 1;
        """
        self.check_failure(source, "synthesized type 't1.A' is not a subtype of expected type 'Int'")

    def test_bounded_path_dependent_subtyping(self) -> None:
        """Type formal with POWER bound allows subtyping: tb.A <: Int."""
        source = """
        Let TB = Tuple A::POWER(Int) a:A end;
        let tb: TB = tuple Let A::POWER(Int) = Int let a = 42 end;
        let res: Int = tb.a + 1;
        """
        self.run_source(source)
        res_val = self.runtime_env.lookup("res")
        self.assertIsNotNone(res_val)
        self.assertIsInstance(res_val, QInt)
        self.assertEqual(res_val.value, 43)

    def test_projection_from_anonymous_tuple_rejected(self) -> None:
        """Selecting dependent member from anonymous existential tuple is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let make(u: Ok): T = tuple Let A::TYPE = Int let a = 0 end;
        let bad = make(ok).a;
        """
        self.check_failure(
            source,
            "Cannot select type-dependent member 'a' from compound or anonymous existential tuple",
        )

    def test_projection_from_mutable_var_rejected(self) -> None:
        """Selecting type-dependent member from mutable var is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let var t: T = tuple Let A::TYPE = Int let a = 0 end;
        let bad = t.a;
        """
        self.check_failure(
            source,
            "Cannot select type-dependent member 'a' from mutable variable 't'",
        )

    def test_path_type_from_mutable_var_rejected(self) -> None:
        """Projecting type t.A from mutable variable t is rejected during kind elaboration."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let var t: T = tuple Let A::TYPE = Int let a = 0 end;
        let x: t.A = 0;
        """
        self.check_failure(source, "Cannot project type from mutable variable 't'")

    def test_escape_in_function_inferred_return_type_rejected(self) -> None:
        """Function body returning t.a where return type is inferred is rejected for escaping scope."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let geta(t: T) = t.a;
        """
        self.check_failure(source, "Abstract type 't.A' cannot escape function scope")

    def test_escape_in_function_annotated_return_type_rejected(self) -> None:
        """Function with explicit return type annotation t.A is rejected for escaping scope."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let geta(t: T): t.A = t.a;
        """
        self.check_failure(source, "Abstract type 't.A' cannot escape function scope")

    def test_escape_in_block_rejected(self) -> None:
        """Local variable abstract type escaping a block expression is rejected."""
        source = """
        Let T = Tuple A::TYPE a:A end;
        let res = begin
            let t: T = tuple Let A::TYPE = Int let a = 0 end;
            t.a
        end;
        """
        self.check_failure(source, "cannot escape its scope")

    def test_repl_formatting_cardelli_style(self) -> None:
        """Cardelli §5.3: existential tuples format as <Hidden>::TYPE and values as <hidden>."""
        from quest.interpreter import format_interactive_result

        source = """
        Let T = Tuple A::TYPE a:A f(x:A):Int end;
        let t1: T = tuple Let A::TYPE = Int let a = 0 let f(x: A): Int = x + 1 end;
        """
        ctx, _ = self.run_source(source)
        t1_val = self.runtime_env.lookup("t1")
        typed_ast = ctx.sink.diagnostics # or lookup from env
        # Find t1 symbol in env
        t1_sym = self.env.lookup_value("t1")
        self.assertIsNotNone(t1_sym)
        interp_phase = [p for p in self.pipeline.phases if p.name == "interpret"][0]
        out_let = format_interactive_result(
            interp_phase._last_phrase_results[1][0],
            t1_val,
        )
        self.assertIn("<Hidden>::TYPE", out_let)
        self.assertIn("a=<hidden>", out_let)
        self.assertIn("f=<fun>", out_let)

        # Evaluating t1.a directly
        source2 = "t1.a;"
        ctx2, val2 = self.run_source(source2)
        interp_phase2 = [p for p in self.pipeline.phases if p.name == "interpret"][0]
        out_expr = format_interactive_result(interp_phase2._last_phrase_results[0][0], val2)
        self.assertEqual(out_expr, "<hidden> : t1.A")


if __name__ == "__main__":
    unittest.main()
