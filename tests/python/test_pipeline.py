"""Unit tests for the Quest Compiler Phase Pipeline Framework."""

import tempfile
import unittest
from pathlib import Path

from quest.env import Environment
from quest.pipeline import (
    CompilerContext,
    CompilerOptions,
    PhasePipeline,
    default_pipeline,
)


class TestPipeline(unittest.TestCase):
    """Tests for PhasePipeline registration, execution, and artifact dumping."""

    def setUp(self):
        self.pipeline = default_pipeline()

    def test_pipeline_phases_and_precursors(self):
        """Verifies phase registration and automatic precursor computation."""
        self.assertEqual(
            self.pipeline.phase_names(),
            ["tokenize", "parse", "typecheck", "interpret"],
        )
        self.assertEqual(self.pipeline.precursors_of("tokenize"), [])
        self.assertEqual(self.pipeline.precursors_of("parse"), ["tokenize"])
        self.assertEqual(self.pipeline.precursors_of("typecheck"), ["tokenize", "parse"])
        self.assertEqual(
            self.pipeline.precursors_of("interpret"),
            ["tokenize", "parse", "typecheck"],
        )

        with self.assertRaises(ValueError):
            self.pipeline.precursors_of("nonexistent")

    def test_execute_success(self):
        """Verifies full execution through interpret."""
        res = self.pipeline.execute("let x: Int = 10;", "<test>")
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "interpret")
        self.assertIn("tokenize", res.artifacts)
        self.assertIn("parse", res.artifacts)
        self.assertIn("typecheck", res.artifacts)
        self.assertIn("interpret", res.artifacts)
        self.assertFalse(res.has_errors)

    def test_stop_after_and_dump(self):
        """Verifies --stop-after halts early and populates dump_outputs."""
        opts = CompilerOptions(stop_after="parse")
        res = self.pipeline.execute("let x: Int = 10;", "<test>", options=opts)
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "parse")
        self.assertIn("parse", res.dump_outputs)
        self.assertNotIn("typecheck", res.artifacts)
        self.assertIn("(LetValueBinding", res.dump_outputs["parse"])

    def test_dump_after_intermediate(self):
        """Verifies --dump-after captures intermediate output while pipeline continues."""
        opts = CompilerOptions(dump_after={"parse"}, stop_after="typecheck")
        res = self.pipeline.execute("let x: Int = 10;", "<test>", options=opts)
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "typecheck")
        self.assertIn("parse", res.dump_outputs)
        self.assertIn("typecheck", res.dump_outputs)

    def test_target_option(self):
        """Verifies target option allows parsing types, kinds, or expressions directly."""
        opts_type = CompilerOptions(stop_after="parse", target="type")
        res_type = self.pipeline.execute("Record x: Int end", "<test>", options=opts_type)
        self.assertTrue(res_type.success)
        self.assertIn("parse", res_type.artifacts)

        opts_kind = CompilerOptions(stop_after="parse", target="kind")
        res_kind = self.pipeline.execute("POWER(Int)", "<test>", options=opts_kind)
        self.assertTrue(res_kind.success)
        self.assertIn("parse", res_kind.artifacts)

        opts_expr = CompilerOptions(stop_after="parse", target="expr")
        res_expr = self.pipeline.execute("1 + 2", "<test>", options=opts_expr)
        self.assertTrue(res_expr.success)
        self.assertIn("parse", res_expr.artifacts)

    def test_target_polymorphism_full_pipeline(self):
        """Verifies full pipeline execution with expression, type, kind, and phrase targets."""
        # 1. Expression target executed through interpret
        res_expr = self.pipeline.execute("1 + 2", "<test>", target="expr")
        self.assertTrue(res_expr.success)
        self.assertEqual(res_expr.final_phase, "interpret")
        from quest.typed_ast import TypedExpr
        from quest.runtime import QInt
        self.assertIsInstance(res_expr.artifacts["typecheck"], TypedExpr)
        self.assertEqual(res_expr.artifacts["interpret"], QInt(3))

        # 2. Type target executed through typecheck
        opts_type = CompilerOptions(stop_after="typecheck", target="type")
        res_type = self.pipeline.execute("Record x: Int end", "<test>", options=opts_type)
        self.assertTrue(res_type.success)
        from quest.types import QRecordType
        self.assertIsInstance(res_type.artifacts["typecheck"], QRecordType)

        # 3. Kind target executed through typecheck
        opts_kind = CompilerOptions(stop_after="typecheck", target="kind")
        res_kind = self.pipeline.execute("POWER(Int)", "<test>", options=opts_kind)
        self.assertTrue(res_kind.success)
        from quest.types import QPowerKind
        self.assertIsInstance(res_kind.artifacts["typecheck"], QPowerKind)

        # 4. Phrase target executed through interpret
        res_phrase = self.pipeline.execute("let a: Int = 42", "<test>", target="phrase")
        self.assertTrue(res_phrase.success)
        self.assertEqual(res_phrase.artifacts["interpret"], QInt(42))

        # 5. Dump output on expression target
        opts_dump = CompilerOptions(target="expr", dump_after={"typecheck", "interpret"})
        res_dump = self.pipeline.execute("10 * 5", "<test>", options=opts_dump)
        self.assertTrue(res_dump.success)
        self.assertIn("typecheck", res_dump.dump_outputs)
        self.assertIn("interpret", res_dump.dump_outputs)
        self.assertIn("50", res_dump.dump_outputs["interpret"])

    def test_compile_file(self):
        """Verifies compile_file loads and compiles from disk."""
        with tempfile.NamedTemporaryFile("w", suffix=".quest", delete=False) as f:
            f.write("let y: Bool = true;\n")
            temp_path = Path(f.name)

        try:
            res = self.pipeline.compile_file(temp_path)
            self.assertTrue(res.success)
            self.assertEqual(res.final_phase, "interpret")
        finally:
            temp_path.unlink()

    def test_compile_phrase_stateful_context(self):
        """Verifies compile_phrase preserves environment bindings across interactive phrases."""
        env = Environment()
        ctx = CompilerContext.create("", "<repl>", env=env)

        # Phrase 1: declare x
        res1 = self.pipeline.compile_phrase("let x: Int = 42;", ctx=ctx)
        self.assertTrue(res1.success)

        # Phrase 2: use x in expression
        res2 = self.pipeline.compile_phrase("let y: Int = x + 1;", ctx=ctx)
        self.assertTrue(res2.success)

    def test_syntax_error_halts_before_typecheck(self):
        """Verifies parse error halts execution and records diagnostic."""
        res = self.pipeline.execute("let x = 1 +;", "<test>")
        self.assertFalse(res.success)
        self.assertEqual(res.final_phase, "parse")
        self.assertTrue(res.has_errors)
        self.assertNotIn("typecheck", res.artifacts)
        self.assertTrue(any("Unexpected token" in d.message for d in res.diagnostics))

    def test_interpret_dump(self):
        """Verifies --dump-after interpret emits formatted value for expressions."""
        opts = CompilerOptions(dump_after={"interpret"})
        res = self.pipeline.execute("40 + 2;", "<test>", options=opts)
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "interpret")
        self.assertIn("interpret", res.dump_outputs)
        self.assertEqual(res.dump_outputs["interpret"], "42 : Int")

    def test_interpret_dump_ok_silent(self):
        """Verifies --dump-after interpret produces empty output for ok / statements."""
        opts = CompilerOptions(dump_after={"interpret"})
        res = self.pipeline.execute("ok;", "<test>", options=opts)
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "interpret")
        self.assertIn("interpret", res.dump_outputs)
        self.assertEqual(res.dump_outputs["interpret"], "")

    def test_interpret_dump_declaration(self):
        """Verifies --dump-after interpret produces signature for declarations."""
        opts = CompilerOptions(dump_after={"interpret"})
        res = self.pipeline.execute("let x: Int = 10;", "<test>", options=opts)
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "interpret")
        self.assertIn("interpret", res.dump_outputs)
        self.assertEqual(res.dump_outputs["interpret"], "let x:Int = 10")

    def test_interpret_dump_import(self):
        """Verifies --dump-after interpret produces empty output for imports and evaluates imported calls."""
        opts = CompilerOptions(dump_after={"interpret"})
        res = self.pipeline.execute(
            'import conv: Conv; conv.int(0 - 5);',
            "<test>",
            options=opts,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.final_phase, "interpret")
        self.assertIn("interpret", res.dump_outputs)
        self.assertEqual(res.dump_outputs["interpret"], '"~5" : String')


if __name__ == "__main__":
    unittest.main()
