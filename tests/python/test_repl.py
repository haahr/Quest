"""Unit tests for the Quest interactive REPL subsystem (Phase 3.6)."""

import os
import unittest

from quest.repl import (
    QuestREPL,
    check_input_completeness,
    _is_terminal_dumb_or_emacs,
)


class TestQuestREPL(unittest.TestCase):
    """Tests interactive REPL evaluation, multi-line buffering, and rollback."""

    def _run_repl_session(self, inputs: list[str]) -> tuple[list[str], list[str]]:
        """Helper to run a QuestREPL session with mocked I/O and return stdout and stderr lines."""
        input_queue = list(inputs)
        stdout_records: list[str] = []
        stderr_records: list[str] = []

        def mock_input(prompt: str) -> str:
            if not input_queue:
                raise EOFError()
            val = input_queue.pop(0)
            stdout_records.append(prompt + val + "\n")
            return val

        repl = QuestREPL(
            input_fn=mock_input,
            stdout_write=stdout_records.append,
            stderr_write=stderr_records.append,
        )
        repl.run()
        return stdout_records, stderr_records

    def test_single_line_evaluation_without_semicolon(self) -> None:
        """Evaluates single-line expressions and bindings without requiring semicolons."""
        stdout, stderr = self._run_repl_session(["let a = 10", "let b = 20", "a + b"])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn(">>  let a = 10\n", output_text)
        self.assertIn("==  let a:Int = 10\n", output_text)
        self.assertIn(">>  let b = 20\n", output_text)
        self.assertIn("==  let b:Int = 20\n", output_text)
        self.assertIn(">>  a + b\n", output_text)
        self.assertIn("==  30 : Int\n", output_text)

    def test_single_line_evaluation_with_semicolon(self) -> None:
        """Evaluates single-line expressions and bindings when semicolons are explicitly given."""
        stdout, stderr = self._run_repl_session(["let a = 10;", "a + 5;"])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn(">>  let a = 10;\n", output_text)
        self.assertIn("==  let a:Int = 10\n", output_text)
        self.assertIn(">>  a + 5;\n", output_text)
        self.assertIn("==  15 : Int\n", output_text)

    def test_multiple_phrases_on_one_line(self) -> None:
        """Outputs a response prefixed with '==  ' for each non-ok phrase on a single line."""
        stdout, stderr = self._run_repl_session(["let x = 1; let y = 2; x + y;"])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn("==  let x:Int = 1\n", output_text)
        self.assertIn("==  let y:Int = 2\n", output_text)
        self.assertIn("==  3 : Int\n", output_text)

    def test_multi_line_function_buffering(self) -> None:
        """Prompts with continuation '    ' when phrase is incomplete and evaluates when closed."""
        stdout, stderr = self._run_repl_session([
            "let add(x: Int y: Int): Int =",
            "    x + y",
            "add(4 6)",
        ])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn(">>  let add(x: Int y: Int): Int =\n", output_text)
        self.assertIn("        x + y\n", output_text)
        self.assertIn("==  let add:Fun(x: Int y: Int): Int = <fun>\n", output_text)
        self.assertIn(">>  add(4 6)\n", output_text)
        self.assertIn("==  10 : Int\n", output_text)

    def test_multi_line_conditional_buffering(self) -> None:
        """Buffers multiline if-then-else until end keyword."""
        stdout, stderr = self._run_repl_session([
            "if true then",
            "    100",
            "else",
            "    200",
            "end",
        ])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn("==  100 : Int\n", output_text)

    def test_silent_ok_evaluation(self) -> None:
        """Suppresses response output when phrase evaluates to ok."""
        stdout, stderr = self._run_repl_session(["let var count = 0", "count := 5", "count"])
        self.assertEqual(stderr, [])
        output_text = "".join(stdout)
        self.assertIn("==  let var count:Int = 0\n", output_text)
        # Verify no response line was produced between count := 5 and next prompt
        self.assertNotIn("count := 5\n== ", output_text)
        self.assertIn("==  5 : Int\n", output_text)

    def test_rollback_on_typecheck_error(self) -> None:
        """Rolls back environment state if any phrase on an input line fails typechecking."""
        stdout, stderr = self._run_repl_session([
            "let a = 10",
            "let a = 99; let b: Int = \"type error\"",
            "a",
        ])
        self.assertTrue(len(stderr) > 0)
        self.assertIn("error: Type mismatch", "".join(stderr))
        output_text = "".join(stdout)
        # a should still be 10, not 99
        self.assertIn(">>  a\n==  10 : Int\n", output_text)

    def test_rollback_on_runtime_exception(self) -> None:
        """Rolls back environment state if a phrase raises an uncaught runtime exception."""
        stdout, stderr = self._run_repl_session([
            "let a = 10",
            "let a = 99; 1 / 0",
            "a",
        ])
        self.assertTrue(len(stderr) > 0)
        self.assertIn("error: Exception: DivideByZero", "".join(stderr))
        output_text = "".join(stdout)
        # a should still be 10, not 99
        self.assertIn(">>  a\n==  10 : Int\n", output_text)

    def test_syntax_error_recovery_without_hanging(self) -> None:
        """Reports non-EOF syntax error immediately and clears buffer without hanging."""
        stdout, stderr = self._run_repl_session(["let 123 = 4", "1 + 1"])
        self.assertTrue(len(stderr) > 0)
        output_text = "".join(stdout)
        self.assertIn("==  2 : Int\n", output_text)

    def test_check_input_completeness(self) -> None:
        """Verifies EOF-continuation heuristics."""
        self.assertEqual(check_input_completeness(""), (False, None))
        self.assertEqual(check_input_completeness("   \n  "), (False, None))
        self.assertEqual(check_input_completeness("1 + 2"), (False, None))
        self.assertEqual(check_input_completeness("let x = 1"), (False, None))
        self.assertEqual(check_input_completeness("let x = 1;"), (False, None))

        # Incomplete (expecting more tokens)
        is_inc, _ = check_input_completeness("let f(x: Int): Int =")
        self.assertTrue(is_inc)

        is_inc, _ = check_input_completeness("if true then 1")
        self.assertTrue(is_inc)

        is_inc, _ = check_input_completeness("(* unclosed comment")
        self.assertTrue(is_inc)

        is_inc, _ = check_input_completeness('"unclosed string')
        self.assertTrue(is_inc)

        # Definite syntax error on non-EOF token
        is_inc, err = check_input_completeness("let 123 = 4")
        self.assertFalse(is_inc)
        self.assertIsNotNone(err)

    def test_terminal_dumb_emacs_detection(self) -> None:
        """Verifies dumb or emacs TERM values are recognized."""
        orig_term = os.environ.get("TERM")
        try:
            os.environ["TERM"] = "dumb"
            self.assertTrue(_is_terminal_dumb_or_emacs())
            os.environ["TERM"] = "emacs"
            self.assertTrue(_is_terminal_dumb_or_emacs())
            os.environ["TERM"] = ""
            self.assertTrue(_is_terminal_dumb_or_emacs())
            os.environ["TERM"] = "xterm-256color"
            self.assertFalse(_is_terminal_dumb_or_emacs())
        finally:
            if orig_term is not None:
                os.environ["TERM"] = orig_term
            else:
                os.environ.pop("TERM", None)


if __name__ == "__main__":
    unittest.main()
