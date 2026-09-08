"""Quest Interactive REPL (Read-Eval-Print Loop).

Implements Phase 3.6 of the Quest bootstrap compiler:
- Persistent CompilerContext (Environment and RuntimeEnvironment).
- Semicolon-optional multi-line input buffering with unexpected-EOF continuation detection.
- 4-column visual alignment: '>>  ' (main), '    ' (continuation), '==  ' (response).
- History persistence to ~/.quest_history with terminal escape sequence safety (dumb/emacs detection).
- Clean rollback of environment state on typecheck error or runtime exception.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from quest.diagnostics import DiagnosticRenderer
from quest.grammar import parse_quest_program
from quest.interpreter import format_interactive_result
from quest.parser import ParserError
from quest.pipeline import CompilerContext, CompilerOptions, default_pipeline
from quest.runtime import QOk, QValue
from quest.tokenizer import Tokenizer, TokenizerError
from quest.tokens import SourceMap, TokenKind
from quest.typed_ast import TypedBinding, TypedExpr

PROMPT_MAIN = ">>  "
PROMPT_CONT = "    "
PREFIX_RESP = "==  "
HISTORY_FILE_NAME = ".quest_history"


def _is_terminal_dumb_or_emacs() -> bool:
    """Checks whether TERM indicates a dumb or emacs terminal where escape sequences fail."""
    term = os.environ.get("TERM", "").strip().lower()
    return term in ("dumb", "emacs", "")


def _setup_readline(history_path: Path) -> None:
    """Configures readline for line editing and persistent history if the terminal supports it."""
    if not sys.stdin.isatty() or _is_terminal_dumb_or_emacs():
        return

    try:
        import readline

        try:
            if history_path.exists():
                readline.read_history_file(str(history_path))
        except (OSError, UnicodeDecodeError):
            pass

        def save_history() -> None:
            try:
                readline.set_history_length(1000)
                readline.write_history_file(str(history_path))
            except OSError:
                pass

        atexit.register(save_history)
    except ImportError:
        pass


def check_input_completeness(buffer: str) -> tuple[bool, Optional[str]]:
    """Analyzes buffer to check whether more lines are needed to complete a phrase.

    Returns:
        (is_incomplete, error_message):
        - (True, None) if the input reached EOF while expecting more tokens or unclosed delimiters.
        - (False, None) if the input is a syntactically valid complete phrase (or empty).
        - (False, err_msg) if the input has a definite syntax error on a non-EOF token.
    """
    stripped = buffer.strip()
    if not stripped:
        return (False, None)

    # 1. Lexical check
    tokenizer = Tokenizer(buffer, "<repl>")
    try:
        tokens = tokenizer.tokenize_all()
    except TokenizerError as tok_err:
        err_msg = str(tok_err)
        # If unclosed comment or string literal at EOF, more lines can close it
        if "Unclosed comment" in err_msg or "Unterminated string" in err_msg:
            return (True, None)
        return (False, err_msg)

    # 2. Parse check
    source_map = SourceMap(buffer, "<repl>")
    try:
        parse_quest_program(tokens, source_map)
        return (False, None)
    except ParserError as parse_err:
        if parse_err.token.kind == TokenKind.EOF:
            # Reached EOF while expecting closing delimiters or operands
            return (True, None)
        # Definite syntax error on a concrete non-EOF token
        return (False, str(parse_err))


class QuestREPL:
    """Interactive Read-Eval-Print Loop for the Quest language."""

    def __init__(
        self,
        ctx: Optional[CompilerContext] = None,
        input_fn: Optional[Callable[[str], str]] = None,
        stdout_write: Optional[Callable[[str], Any]] = None,
        stderr_write: Optional[Callable[[str], Any]] = None,
    ):
        self.context = ctx or CompilerContext.create("", "<repl>", options=CompilerOptions())
        self.pipeline = default_pipeline()
        self.input_fn = input_fn or input
        self.stdout_write = stdout_write or sys.stdout.write
        self.stderr_write = stderr_write or sys.stderr.write

    def format_phrase_output(self, phrase: TypedBinding | TypedExpr, val: QValue) -> Optional[str]:
        """Formats an evaluated phrase with '==  ' prefix and 4-space aligned continuations."""
        raw = format_interactive_result(phrase, val)
        if not raw:
            return None

        lines = raw.split("\n")
        first_line = f"{PREFIX_RESP}{lines[0]}"
        cont_lines = [f"{PROMPT_CONT}{line}" for line in lines[1:]]
        return "\n".join([first_line] + cont_lines)

    def run(self) -> int:
        """Executes the main interactive REPL loop until EOF (Ctrl-D) or exit."""
        history_path = Path.home() / HISTORY_FILE_NAME
        _setup_readline(history_path)

        buffer_lines: list[str] = []

        while True:
            prompt = PROMPT_CONT if buffer_lines else PROMPT_MAIN
            try:
                line = self.input_fn(prompt)
            except EOFError:
                self.stdout_write("\n")
                break
            except KeyboardInterrupt:
                self.stdout_write("\n")
                buffer_lines.clear()
                continue

            buffer_lines.append(line)
            current_buffer = "\n".join(buffer_lines)

            # Check if input is complete or needs continuation
            is_incomplete, err_msg = check_input_completeness(current_buffer)
            if is_incomplete:
                continue

            # Clear accumulator for next cycle
            buffer_lines.clear()

            # Empty input (user just hit enter)
            if not current_buffer.strip():
                continue

            # Snapshot environment state before evaluation for transactional rollback on failure
            env_snap = self.context.env.snapshot()
            runtime_snap = self.context.runtime_env.snapshot()

            result = self.pipeline.compile_phrase(current_buffer, ctx=self.context)

            if result.has_errors or not result.success:
                # Rollback environment mutations from failing phrase
                self.context.env.restore(env_snap)
                self.context.runtime_env.restore(runtime_snap)

                # Render error diagnostics
                source_map = SourceMap(current_buffer, "<repl>")
                for diag in result.diagnostics:
                    rendered = DiagnosticRenderer.render_diagnostic(diag, source_map=source_map)
                    self.stderr_write(rendered + "\n")
                continue

            # Output evaluated results for all non-ok phrases on this input
            interpret_phase = self.pipeline.get_phase("interpret")
            phrase_results = getattr(interpret_phase, "last_phrase_results", [])

            if phrase_results:
                for phrase, val in phrase_results:
                    out = self.format_phrase_output(phrase, val)
                    if out:
                        self.stdout_write(out + "\n")
            else:
                # Fallback to final artifact if phrase_results not available
                final_val = result.final_artifact
                typed_prog = result.artifacts.get("typecheck")
                if final_val is not None and typed_prog and typed_prog.phrases:
                    out = self.format_phrase_output(typed_prog.phrases[-1], final_val)
                    if out:
                        self.stdout_write(out + "\n")

        return 0


def run_repl(ctx: Optional[CompilerContext] = None) -> int:
    """Convenience entry point to start the interactive Quest REPL."""
    repl = QuestREPL(ctx=ctx)
    return repl.run()
