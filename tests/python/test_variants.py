"""Unit tests for Cardelli unordered Variant types, injections, subtyping, and ?/! operators."""

import unittest

from quest.env import Environment
from quest.interpreter import RuntimeEnvironment
from quest.pipeline import CompilerContext
from quest.runtime import QBool, QInt, QOk, QTuple, QVariant, qvalue_to_str
from quest.types import (
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    QVariantField,
    QVariantType,
    is_subtype,
)
from tests.python.helpers import assert_pipeline_failure, assert_pipeline_success


class TestVariants(unittest.TestCase):
    """Verifies Variant types from Cardelli's Typeful Programming §6.3."""

    def setUp(self) -> None:
        self.env = Environment()
        self.runtime_env = RuntimeEnvironment.create_root_env()

    def run_source(self, source: str) -> CompilerContext:
        return assert_pipeline_success(source, env=self.env, runtime_env=self.runtime_env)

    def check_failure(self, source: str, expected_substr: str) -> None:
        assert_pipeline_failure(source, expected_substr, env=self.env, runtime_env=self.runtime_env)

    def test_variant_type_elaboration(self) -> None:
        """Cardelli §6.3 Day variant signature elaborates correctly."""
        ctx = self.run_source("Let Day = Variant mon, tue, wed, thu, fri:Ok end;")
        day_sym = ctx.env.lookup_type("Day")
        self.assertIsNotNone(day_sym)
        self.assertIsInstance(day_sym.definition, QVariantType)
        var_type: QVariantType = day_sym.definition
        self.assertEqual(len(var_type.variants), 5)
        self.assertEqual(
            [v.name for v in var_type.variants],
            ["mon", "tue", "wed", "thu", "fri"],
        )
        for v in var_type.variants:
            self.assertEqual(v.type_val, OK_TYPE)

    def test_duplicate_variant_tag_rejected(self) -> None:
        """Duplicate variant tags are rejected with KindError."""
        self.check_failure(
            "Let Bad = Variant a: Int a: Real end;",
            "Duplicate variant tag 'a'",
        )

    def test_variant_subtyping_cardelli(self) -> None:
        """Cardelli §6.3 variant width subtyping: WeekDay <: Day."""
        self.run_source(
            """
            Let Day = Variant mon, tue, wed, thu, fri, sat, sun:Ok end;
            Let WeekDay = Variant mon, tue, wed, thu, fri:Ok end;
            Let WeekendDay = Variant sat, sun:Ok end;
            """
        )
        day_type = self.env.lookup_type("Day").definition
        weekday_type = self.env.lookup_type("WeekDay").definition
        weekend_type = self.env.lookup_type("WeekendDay").definition

        self.assertTrue(is_subtype(weekday_type, day_type, self.env))
        self.assertTrue(is_subtype(weekend_type, day_type, self.env))
        self.assertFalse(is_subtype(day_type, weekday_type, self.env))
        self.assertFalse(is_subtype(weekday_type, weekend_type, self.env))

    def test_variant_injection_and_case_discrimination(self) -> None:
        """Variant injection and case pattern matching."""
        self.run_source(
            """
            Let Day = Variant mon, tue, wed, thu, fri:Ok end;
            let d = variant mon of Day with ok end;
            let dayNum(x: Day): Int =
                case x
                    when mon then 1
                    when tue then 2
                    else 0
                end;
            let res: Int = dayNum(d);
            """
        )
        self.assertEqual(self.runtime_env.lookup("res"), QInt(1))

    def test_variant_query_operator(self) -> None:
        """Testing variant tag query operator '?'."""
        self.run_source(
            """
            Let Day = Variant mon, tue, wed, thu, fri:Ok end;
            let d = variant mon of Day with ok end;
            let isMon: Bool = d?mon;
            let isTue: Bool = d?tue;
            """
        )
        self.assertEqual(self.runtime_env.lookup("isMon"), QBool(True))
        self.assertEqual(self.runtime_env.lookup("isTue"), QBool(False))

    def test_variant_query_invalid_tag_rejected(self) -> None:
        """Querying non-existent variant tag is rejected at typecheck time."""
        self.check_failure(
            """
            Let Day = Variant mon, tue, wed:Ok end;
            let d = variant mon of Day with ok end;
            let bad = d?sun;
            """,
            "Tag 'sun' is not a valid variant",
        )

    def test_variant_assert_operator(self) -> None:
        """Testing variant tag assertion and extraction operator '!'."""
        self.run_source(
            """
            Let Number = Variant int: Int real: Real end;
            let n = variant int of Number with 42 end;
            let isInt: Bool = n?int;
            let isReal: Bool = n?real;
            let val: Int = n!int;
            """
        )
        self.assertEqual(self.runtime_env.lookup("isInt"), QBool(True))
        self.assertEqual(self.runtime_env.lookup("isReal"), QBool(False))
        self.assertEqual(self.runtime_env.lookup("val"), QInt(42))

    def test_variant_assert_tag_mismatch_fails_at_runtime(self) -> None:
        """Asserting wrong tag with '!' fails at runtime."""
        self.check_failure(
            """
            Let Number = Variant int: Int real: Real end;
            let n = variant int of Number with 42 end;
            let fail = n!real;
            """,
            "Variant tag mismatch in '!': expected 'real', got 'int'",
        )

    def test_option_query_and_assert_operators(self) -> None:
        """Option types also support '?' and '!' operators."""
        self.run_source(
            """
            Let Color = Option red green blue with val: Int end end;
            let cRed = option red of Color end;
            let cBlue = option blue of Color with tuple 100 end end;

            let isRed: Bool = cRed?red;
            let isGreen: Bool = cRed?green;
            let isBlue: Bool = cBlue?blue;

            let redPayload = cRed!red;
            let bluePayload = cBlue!blue;
            let blueVal: Int = bluePayload.val;
            """
        )
        self.assertEqual(self.runtime_env.lookup("isRed"), QBool(True))
        self.assertEqual(self.runtime_env.lookup("isGreen"), QBool(False))
        self.assertEqual(self.runtime_env.lookup("isBlue"), QBool(True))
        self.assertEqual(qvalue_to_str(self.runtime_env.lookup("redPayload")), "tuple 0 end")
        self.assertEqual(qvalue_to_str(self.runtime_env.lookup("bluePayload")), "tuple 2 val=100 end")
        self.assertEqual(self.runtime_env.lookup("blueVal"), QInt(100))


if __name__ == "__main__":
    unittest.main()
