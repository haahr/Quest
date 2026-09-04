#!/usr/bin/env python3
"""Quest Compiler Unified CLI Driver.

Executes compiler phases sequentially, supporting early exit (--stop-after),
intermediate inspection (--dump-after), inline execution (-c), and include paths (-I).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quest.diagnostics import DiagnosticRenderer, Severity
from quest.interpreter import format_interactive_result
from quest.pipeline import CompilerOptions, default_pipeline
from quest.runtime import QOk, qvalue_to_str
from quest.tokens import SourceMap


def run_driver(args: list[str]) -> int:
    """Executes the compiler driver with given CLI argument list."""
    pipeline = default_pipeline()
    available_phases = pipeline.phase_names()

    arg_parser = argparse.ArgumentParser(
        prog="quest",
        description="Quest Compiler Driver — compile, check, and inspect Quest programs.",
    )
    arg_parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to Quest source file (.quest), or '-' for standard input.",
    )
    arg_parser.add_argument(
        "-c", "--code", "--command",
        dest="code",
        help="Inline Quest code string to process.",
    )
    arg_parser.add_argument(
        "--stop-after", "--stop_after",
        dest="stop_after",
        choices=available_phases,
        help="Stop pipeline execution after specified phase and dump its canonical output.",
    )
    arg_parser.add_argument(
        "--dump-after", "--dump_after",
        dest="dump_after",
        action="append",
        choices=available_phases,
        default=[],
        help="Dump canonical output of specified phase while continuing pipeline execution.",
    )
    arg_parser.add_argument(
        "-I", "--include",
        dest="include_paths",
        action="append",
        default=[],
        help="Add directory to interface/module search path.",
    )
    arg_parser.add_argument(
        "--show-offsets",
        dest="show_offsets",
        action="store_true",
        help="Include character offsets in AST and typed AST dumps.",
    )
    arg_parser.add_argument(
        "--show-values",
        dest="show_values",
        action="store_true",
        help="Include parsed literal values in token dumps.",
    )

    parsed_args = arg_parser.parse_args(args)

    # Determine input source
    is_inline_code = parsed_args.code is not None
    if is_inline_code:
        source_text = parsed_args.code
        file_name = "<string>"
    elif parsed_args.file is None or parsed_args.file == "-":
        source_text = sys.stdin.read()
        file_name = "<stdin>"
    else:
        file_path = Path(parsed_args.file)
        if not file_path.exists():
            sys.stderr.write(f"quest: error: file not found: '{file_path}'\n")
            return 1
        try:
            source_text = file_path.read_text(encoding="utf-8")
            file_name = str(file_path)
        except OSError as error:
            sys.stderr.write(f"quest: error reading '{file_path}': {error}\n")
            return 1

    # Configure options
    options = CompilerOptions(
        stop_after=parsed_args.stop_after,
        dump_after=set(parsed_args.dump_after),
        include_paths=[Path(p) for p in parsed_args.include_paths],
        show_offsets=parsed_args.show_offsets,
        show_values=parsed_args.show_values,
    )

    # Execute pipeline
    result = pipeline.execute(source_text, file_name, options=options)

    # Output any requested phase dumps
    for phase_name in available_phases:
        if phase_name in result.dump_outputs:
            out_str = result.dump_outputs[phase_name]
            if out_str:
                sys.stdout.write(out_str + "\n")

    # If evaluated inline code via -c, print the final phrase result (unless it's ok)
    if is_inline_code and result.success and "interpret" not in result.dump_outputs:
        typed_prog = result.artifacts.get("typecheck")
        final_phrase = typed_prog.phrases[-1] if typed_prog and typed_prog.phrases else None
        val = result.artifacts.get("interpret")
        if val is not None:
            out_str = format_interactive_result(final_phrase, val)
            if out_str:
                sys.stdout.write(out_str + "\n")

    # Render diagnostics if any occurred
    if result.diagnostics:
        source_map = SourceMap(source_text, file_name)
        for diag in result.diagnostics:
            rendered = DiagnosticRenderer.render_diagnostic(diag, source_map=source_map)
            sys.stderr.write(rendered + "\n")

    # Exit code determination
    if any(d.severity == Severity.FATAL for d in result.diagnostics):
        return 70  # EX_SOFTWARE

    return 0 if result.success else 1


def main() -> int:
    return run_driver(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
