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


if __name__ == "__main__":
    unittest.main()
