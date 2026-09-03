"""Comprehensive Unit Tests for Quest Diagnostic Architecture."""

import os
import sys
import unittest

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.tokens import SourceMap
from quest.tokenizer import TokenizerError
from quest.parser import ParserError
from quest.typechecker import TypeError as QuestTypeError
from quest.types import KindError
from quest.diagnostics import (
    CodeSuggestion,
    Diagnostic,
    DiagnosticLabel,
    DiagnosticRenderer,
    DiagnosticSink,
    FatalDiagnosticError,
    Severity,
)


class TestDiagnosticDataStructures(unittest.TestCase):
    """Tests for core diagnostic data structures and factories."""

    def test_severity_enum(self):
        self.assertEqual(Severity.FATAL.value, "fatal")
        self.assertEqual(Severity.ERROR.value, "error")
        self.assertEqual(Severity.WARNING.value, "warning")
        self.assertEqual(Severity.INFO.value, "info")

    def test_diagnostic_label_and_suggestion(self):
        label = DiagnosticLabel(offset=10, length=4, message="expected type defined here", is_primary=False)
        self.assertEqual(label.offset, 10)
        self.assertEqual(label.length, 4)
        self.assertEqual(label.message, "expected type defined here")
        self.assertFalse(label.is_primary)

        sugg = CodeSuggestion(offset=5, length=3, replacement="andif", description="use Quest boolean conjunction")
        self.assertEqual(sugg.offset, 5)
        self.assertEqual(sugg.length, 3)
        self.assertEqual(sugg.replacement, "andif")
        self.assertEqual(sugg.description, "use Quest boolean conjunction")

    def test_diagnostic_factory_methods(self):
        err = Diagnostic.make_error(
            message="Type mismatch",
            offset=12,
            length=5,
            help_text="convert to Int",
            notes=["expected Int, got String"],
            error_code="E0101",
        )
        self.assertEqual(err.severity, Severity.ERROR)
        self.assertEqual(err.message, "Type mismatch")
        self.assertIsNotNone(err.primary_label)
        self.assertEqual(err.primary_label.offset, 12)
        self.assertEqual(err.primary_label.length, 5)
        self.assertEqual(err.help_text, "convert to Int")
        self.assertEqual(err.notes, ["expected Int, got String"])
        self.assertEqual(err.error_code, "E0101")

        warn = Diagnostic.make_warning("Unused variable 'x'", offset=0, length=1)
        self.assertEqual(warn.severity, Severity.WARNING)

        fatal = Diagnostic.make_fatal("Internal compiler error", offset=None)
        self.assertEqual(fatal.severity, Severity.FATAL)
        self.assertIsNone(fatal.primary_label)


class TestDiagnosticSink(unittest.TestCase):
    """Tests for DiagnosticSink collection, severity counts, and fatal aborts."""

    def test_accumulation_and_counts(self):
        sink = DiagnosticSink()
        self.assertFalse(sink.has_errors)
        self.assertEqual(sink.error_count, 0)
        self.assertEqual(sink.warning_count, 0)

        sink.add_warning("Unused binding", offset=5)
        self.assertFalse(sink.has_errors)
        self.assertEqual(sink.warning_count, 1)

        sink.add_error("Type mismatch", offset=10)
        self.assertTrue(sink.has_errors)
        self.assertEqual(sink.error_count, 1)
        self.assertEqual(sink.warning_count, 1)

    def test_warnings_as_errors(self):
        sink = DiagnosticSink(warnings_as_errors=True)
        sink.add_warning("Shadowed variable", offset=2)
        self.assertTrue(sink.has_errors)

    def test_fatal_error_aborts_immediately(self):
        sink = DiagnosticSink()
        sink.add_warning("Note 1", offset=0)
        sink.add_error("Error 1", offset=5)

        with self.assertRaises(FatalDiagnosticError) as ctx:
            sink.add_fatal("Internal Compiler Error: unhandled AST node", offset=20)

        self.assertIn("Internal Compiler Error", str(ctx.exception))
        # Prior diagnostics are preserved in the sink
        self.assertEqual(len(sink.diagnostics), 3)
        self.assertEqual(sink.diagnostics[0].message, "Note 1")
        self.assertEqual(sink.diagnostics[1].message, "Error 1")
        self.assertEqual(sink.diagnostics[2].message, "Internal Compiler Error: unhandled AST node")

    def test_fail_fast_mode(self):
        sink = DiagnosticSink(fail_fast=True)
        with self.assertRaises(FatalDiagnosticError):
            sink.add_error("Syntax error", offset=4)


class TestDiagnosticRenderer(unittest.TestCase):
    """Tests for formatting single and multi-label diagnostics."""

    def setUp(self):
        self.source = "let x: Int = \"hello\";\nlet y = x + 10;\n"
        self.source_map = SourceMap(self.source, "test.quest")

    def test_render_single_error(self):
        diag = Diagnostic.make_error("Type mismatch: expected Int, got String", offset=13, length=7)
        rendered = DiagnosticRenderer.render_diagnostic(diag, self.source_map)
        self.assertIn("test.quest:1:14: error: Type mismatch", rendered)
        self.assertIn("let x: Int = \"hello\";", rendered)
        self.assertIn("^^^^^^^", rendered)

    def test_render_with_secondary_labels_and_help(self):
        primary = DiagnosticLabel(offset=13, length=7, message="found 'String'")
        secondary = DiagnosticLabel(offset=7, length=3, message="expected 'Int'")
        diag = Diagnostic(
            severity=Severity.ERROR,
            message="mismatched types",
            primary_label=primary,
            secondary_labels=[secondary],
            notes=["String cannot be coerced to Int"],
            help_text="use String.toInt(s) to parse",
            error_code="E0042",
        )
        rendered = DiagnosticRenderer.render_diagnostic(diag, self.source_map)
        self.assertIn("test.quest:1:14: error[E0042]: mismatched types", rendered)
        self.assertIn("^^^^^^^ found 'String'", rendered)
        self.assertIn("note: expected 'Int'", rendered)
        self.assertIn("= note: String cannot be coerced to Int", rendered)
        self.assertIn("= help: use String.toInt(s) to parse", rendered)

    def test_render_all_from_sink(self):
        sink = DiagnosticSink()
        sink.add_warning("unused variable 'y'", offset=26, length=1)
        sink.add_error("type mismatch", offset=13, length=7)
        rendered = DiagnosticRenderer.render_all(sink, self.source_map)
        self.assertIn("warning: unused variable 'y'", rendered)
        self.assertIn("error: type mismatch", rendered)


class TestCompilerExceptionIntegration(unittest.TestCase):
    """Tests that existing compiler exceptions convert cleanly to diagnostics."""

    def setUp(self):
        self.source = "let x = 10;\nlet y = 20;\n"
        self.source_map = SourceMap(self.source, "test.quest")

    def test_tokenizer_error_diagnostic(self):
        err = TokenizerError("Unterminated string literal", offset=4, length=6)
        diag = err.to_diagnostic()
        self.assertEqual(diag.severity, Severity.ERROR)
        self.assertEqual(diag.message, "Unterminated string literal")
        formatted = err.format_with_source(self.source_map)
        self.assertIn("test.quest:1:5: error: Unterminated string literal", formatted)

    def test_parser_error_diagnostic(self):
        err = ParserError("Expected semicolon", offset=10, length=1)
        diag = err.to_diagnostic()
        self.assertEqual(diag.severity, Severity.ERROR)
        formatted = err.format_with_source(self.source_map)
        self.assertIn("test.quest:1:11: error: Expected semicolon", formatted)

    def test_type_error_diagnostic(self):
        err = QuestTypeError("Cannot assign to immutable variable 'x'", offset=4, help_text="declare with 'let var x'")
        diag = err.to_diagnostic()
        self.assertEqual(diag.severity, Severity.ERROR)
        self.assertEqual(diag.help_text, "declare with 'let var x'")
        formatted = err.format_with_source(self.source_map)
        self.assertIn("test.quest:1:5: error: Cannot assign to immutable variable 'x'", formatted)
        self.assertIn("= help: declare with 'let var x'", formatted)

    def test_kind_error_diagnostic(self):
        err = KindError("Kind mismatch: expected TYPE", offset=0, help_text="check kind bounds")
        diag = err.to_diagnostic()
        self.assertEqual(diag.severity, Severity.ERROR)
        self.assertEqual(diag.help_text, "check kind bounds")
        formatted = err.format_with_source(self.source_map)
        self.assertIn("test.quest:1:1: error: Kind mismatch: expected TYPE", formatted)
        self.assertIn("= help: check kind bounds", formatted)


if __name__ == "__main__":
    unittest.main()
