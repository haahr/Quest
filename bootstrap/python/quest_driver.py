#!/usr/bin/env python3
"""Quest Compiler Unified CLI Driver.

Executes compiler phases sequentially, supporting early exit (--stop-after),
intermediate inspection (--dump-after), inline execution (-e), and include paths (-I).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quest.builtins import BuiltinModuleRegistry
from quest.diagnostics import DiagnosticRenderer, Severity
from quest.interpreter import format_interactive_result
from quest.pipeline import (
    CompilerContext,
    CompilerOptions,
    compile_pipeline,
    default_pipeline,
    full_pipeline,
)
from quest.runtime import QOk, qvalue_to_str
from quest.tokens import SourceMap


def run_driver(args: list[str]) -> int:
    """Executes the compiler driver with given CLI argument list."""
    if args and args[0] == "compile":
        return run_compile(args[1:])

    all_phases = ["tokenize", "parse", "typecheck", "interpret", "codegen_c", "run_c_compiled"]

    if "--" in args:
        dash_idx = args.index("--")
        driver_args = args[:dash_idx]
        target_args = args[dash_idx + 1:]
    else:
        driver_args = args
        target_args = []

    arg_parser = argparse.ArgumentParser(
        prog="quest",
        description="Quest Compiler Driver — compile, check, interpret, and inspect Quest programs.",
    )
    arg_parser.add_argument(
        "files",
        nargs="*",
        default=[],
        help="Path to Quest source file (.quest), object files (.o, .a), or '-' for standard input.",
    )
    arg_parser.add_argument(
        "-o", "--output",
        dest="output",
        default=None,
        help="Output binary file path (or C file path if --emit-c).",
    )
    arg_parser.add_argument(
        "-c", "--compile-only",
        dest="compile_only",
        action="store_true",
        help="Compile only (do not link). For interfaces, generates .h and .qi.",
    )
    arg_parser.add_argument(
        "-e", "--eval", "--code", "--command",
        dest="code",
        help="Inline Quest code string to process.",
    )
    arg_parser.add_argument(
        "-i", "--interactive",
        dest="interactive",
        action="store_true",
        help="Run file, then enter interactive REPL (or enter REPL if no file).",
    )
    arg_parser.add_argument(
        "--echo",
        dest="echo",
        action="store_true",
        help="Echo Cardelli-format typescript for each top-level phrase in batch mode.",
    )
    arg_parser.add_argument(
        "--stop-after", "--stop_after",
        dest="stop_after",
        choices=all_phases,
        help="Stop pipeline execution after specified phase and dump its canonical output.",
    )
    arg_parser.add_argument(
        "--dump-after", "--dump_after",
        dest="dump_after",
        action="append",
        choices=all_phases,
        default=[],
        help="Dump canonical output of specified phase while continuing pipeline execution.",
    )
    arg_parser.add_argument(
        "--print-result", "--print_result",
        dest="print_result",
        action="store_true",
        help="Print Cardelli-format result of the final phrase when compiling C code.",
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
    arg_parser.add_argument(
        "--expected-exit", "--expected_exit",
        dest="expected_exit",
        type=int,
        default=0,
        help="Expected exit code of target program (for testing).",
    )

    parsed_args = arg_parser.parse_args(driver_args)

    # Determine input source and extra objects
    is_inline_code = parsed_args.code is not None
    source_file = None
    extra_objects: list[Path] = []
    for f_str in parsed_args.files:
        p = Path(f_str)
        if p.suffix in (".o", ".a", ".dylib", ".so"):
            extra_objects.append(p.resolve() if p.exists() else p)
        elif source_file is None:
            source_file = f_str
        else:
            sys.stderr.write(
                f"quest: error: multiple source files specified: '{source_file}' and '{f_str}'\n"
            )
            return 1

    if is_inline_code:
        source_text = parsed_args.code
        file_name = "<string>"
    elif source_file is None:
        if parsed_args.interactive or sys.stdin.isatty():
            from quest.repl import run_repl
            return run_repl()
        source_text = sys.stdin.read()
        file_name = "<stdin>"
    elif source_file == "-":
        source_text = sys.stdin.read()
        file_name = "<stdin>"
    else:
        file_path = Path(source_file)
        if not file_path.exists():
            sys.stderr.write(f"quest: error: file not found: '{file_path}'\n")
            return 1
        if file_path.name.endswith(".int.quest"):
            from quest.interface_compiler import compile_interface_file
            try:
                include_paths = [Path(p) for p in parsed_args.include_paths]
                compile_interface_file(file_path, include_paths=include_paths)
                return 0
            except Exception as err:
                sys.stderr.write(f"quest: error: {err}\n")
                return 1
        if file_path.name.endswith(".mod.quest"):
            from quest.module_compiler import compile_module_file
            try:
                include_paths = [Path(p) for p in parsed_args.include_paths]
                output_dir = Path(parsed_args.output).parent if parsed_args.output else None
                compile_module_file(file_path, output_dir=output_dir, include_paths=include_paths)
                return 0
            except Exception as err:
                sys.stderr.write(f"quest: error: {err}\n")
                return 1
        try:
            source_text = file_path.read_text(encoding="utf-8")
            file_name = str(file_path)
        except OSError as error:
            sys.stderr.write(f"quest: error reading '{file_path}': {error}\n")
            return 1

    # Configure pipeline and options
    has_output = parsed_args.output is not None
    has_objects = bool(extra_objects)
    needs_c_pipeline = (
        has_output
        or has_objects
        or parsed_args.stop_after in ("codegen_c", "run_c_compiled")
        or any(p in ("codegen_c", "run_c_compiled") for p in parsed_args.dump_after)
    )
    if has_output:
        pipeline = compile_pipeline()
    elif needs_c_pipeline:
        pipeline = full_pipeline()
    else:
        pipeline = default_pipeline()

    available_phases = pipeline.phase_names()
    stop_after = parsed_args.stop_after
    if has_objects and not has_output and stop_after is None and not parsed_args.dump_after:
        stop_after = "run_c_compiled"
    print_result = parsed_args.print_result or (stop_after == "run_c_compiled")

    options = CompilerOptions(
        stop_after=stop_after,
        dump_after=set(parsed_args.dump_after),
        include_paths=[Path(p) for p in parsed_args.include_paths],
        echo=parsed_args.echo,
        show_offsets=parsed_args.show_offsets,
        show_values=parsed_args.show_values,
        print_result=print_result,
        target_args=target_args,
        expected_exit=parsed_args.expected_exit,
        extra_objects=extra_objects,
    )

    sys.argv = [file_name] + target_args
    BuiltinModuleRegistry.set_system_args(sys.argv)

    # Execute pipeline
    try:
        ctx = CompilerContext.create(source_text, file_name, options=options)
        for obj in extra_objects:
            from quest.module_loader import canonicalize_module_path
            canon_mod = canonicalize_module_path(obj, options.include_paths)
            mod_name = obj.name.split(".")[0]
            ctx.env.precompiled_modules.add(canon_mod)
            ctx.env.precompiled_modules.add(mod_name)
            if obj not in ctx.env.linked_objects:
                ctx.env.linked_objects.append(obj)
        result = pipeline.execute(source_text, file_name, options=options, ctx=ctx)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        sys.stdout.flush()
        sys.stderr.flush()
        return code

    # Output any requested phase dumps
    for phase_name in available_phases:
        if phase_name in result.dump_outputs:
            out_str = result.dump_outputs[phase_name]
            if out_str:
                sys.stdout.write(out_str + "\n")

    # Print the final phrase result (unless it's ok or already printed via dump/echo)
    if result.success and "interpret" not in result.dump_outputs and not parsed_args.echo:
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

    if not result.success:
        return 1

    if has_output:
        c_code = result.artifacts.get("codegen_c")
        if c_code is None:
            return 1
        output_path = Path(parsed_args.output)
        from quest.codegen import compile_c_source
        try:
            extra_objs = list(options.extra_objects)
            for obj in ctx.env.linked_objects:
                if obj not in extra_objs:
                    extra_objs.append(obj)
            compile_c_source(
                c_code,
                output_path=output_path,
                nogc=False,
                extra_objects=extra_objs,
            )
            return 0
        except Exception as error:
            sys.stderr.write(f"quest: error: {error}\n")
            return 1

    # If -i / --interactive was requested with a file, enter REPL with populated context
    if parsed_args.interactive:
        from quest.repl import run_repl
        return run_repl(ctx=ctx)

    if parsed_args.expected_exit != 0 and parsed_args.stop_after == "run_c_compiled":
        return parsed_args.expected_exit

    return 0


def run_compile(args: list[str]) -> int:
    """Executes the compile subcommand: translates Quest to C and invokes host compiler."""
    pipeline = compile_pipeline()
    available_phases = pipeline.phase_names()

    arg_parser = argparse.ArgumentParser(
        prog="quest compile",
        description="Quest Compiler — compile Quest source into C or native machine binary.",
    )
    arg_parser.add_argument(
        "files",
        nargs="*",
        default=[],
        help="Path to Quest source file (.quest), object files (.o, .a), or '-' for standard input.",
    )
    arg_parser.add_argument(
        "-o", "--output",
        dest="output",
        default=None,
        help="Output binary file path (or C file path if --emit-c).",
    )
    arg_parser.add_argument(
        "--emit-c",
        dest="emit_c",
        action="store_true",
        help="Emit C source code instead of compiling to a binary executable.",
    )
    arg_parser.add_argument(
        "--nogc",
        dest="nogc",
        action="store_true",
        help="Compile without Boehm GC (uses standard libc malloc/free).",
    )
    arg_parser.add_argument(
        "-c", "--compile-only",
        dest="compile_only",
        action="store_true",
        help="Compile only (do not link). For interfaces, generates .h and .qi.",
    )
    arg_parser.add_argument(
        "-e", "--eval", "--code", "--command",
        dest="code",
        help="Inline Quest code string to compile.",
    )
    arg_parser.add_argument(
        "--echo",
        dest="echo",
        action="store_true",
        help="Echo Cardelli-format typescript for top-level phrases.",
    )
    arg_parser.add_argument(
        "-I", "--include",
        dest="include_paths",
        action="append",
        default=[],
        help="Add directory to interface/module search path.",
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
        "--print-result", "--print_result",
        dest="print_result",
        action="store_true",
        help="Print Cardelli-format result of the final phrase when compiling C code.",
    )

    parsed_args = arg_parser.parse_args(args)

    # Determine input source and extra objects
    is_inline_code = parsed_args.code is not None
    source_file = None
    extra_objects: list[Path] = []
    for f_str in parsed_args.files:
        p = Path(f_str)
        if p.suffix in (".o", ".a", ".dylib", ".so"):
            extra_objects.append(p.resolve() if p.exists() else p)
        elif source_file is None:
            source_file = f_str
        else:
            sys.stderr.write(
                f"quest compile: error: multiple source files specified: '{source_file}' and '{f_str}'\n"
            )
            return 1

    if is_inline_code:
        source_text = parsed_args.code
        file_name = "<string>"
        default_out = Path("a.out")
    elif source_file is None:
        if sys.stdin.isatty():
            arg_parser.print_help(sys.stderr)
            return 1
        source_text = sys.stdin.read()
        file_name = "<stdin>"
        default_out = Path("a.out")
    elif source_file == "-":
        source_text = sys.stdin.read()
        file_name = "<stdin>"
        default_out = Path("a.out")
    else:
        file_path = Path(source_file)
        if not file_path.exists():
            sys.stderr.write(f"quest compile: error: file not found: '{file_path}'\n")
            return 1
        if file_path.name.endswith(".int.quest"):
            from quest.interface_compiler import compile_interface_file
            try:
                include_paths = [Path(p) for p in parsed_args.include_paths]
                compile_interface_file(file_path, include_paths=include_paths)
                return 0
            except Exception as err:
                sys.stderr.write(f"quest compile: error: {err}\n")
                return 1
        if file_path.name.endswith(".mod.quest"):
            from quest.module_compiler import compile_module_file
            try:
                include_paths = [Path(p) for p in parsed_args.include_paths]
                output_dir = Path(parsed_args.output).parent if parsed_args.output else None
                compile_module_file(file_path, output_dir=output_dir, include_paths=include_paths)
                return 0
            except Exception as err:
                sys.stderr.write(f"quest compile: error: {err}\n")
                return 1
        try:
            source_text = file_path.read_text(encoding="utf-8")
            file_name = str(file_path)
            if file_path.suffix == ".quest":
                default_out = file_path.with_suffix("")
            else:
                default_out = file_path.with_name(file_path.name + ".bin")
        except OSError as error:
            sys.stderr.write(f"quest compile: error reading '{file_path}': {error}\n")
            return 1

    output_path = Path(parsed_args.output) if parsed_args.output else default_out

    options = CompilerOptions(
        stop_after=parsed_args.stop_after,
        dump_after=set(parsed_args.dump_after),
        include_paths=[Path(p) for p in parsed_args.include_paths],
        echo=parsed_args.echo,
        emit_c=parsed_args.emit_c,
        output_path=output_path,
        nogc=parsed_args.nogc,
        print_result=parsed_args.print_result,
        extra_objects=extra_objects,
    )

    ctx = CompilerContext.create(source_text, file_name, options=options)
    for obj in extra_objects:
        from quest.module_loader import canonicalize_module_path
        canon_mod = canonicalize_module_path(obj, options.include_paths)
        mod_name = obj.name.split(".")[0]
        ctx.env.precompiled_modules.add(canon_mod)
        ctx.env.precompiled_modules.add(mod_name)
        if obj not in ctx.env.linked_objects:
            ctx.env.linked_objects.append(obj)
    result = pipeline.execute(source_text, file_name, options=options, ctx=ctx)

    for phase_name in available_phases:
        if phase_name in result.dump_outputs:
            out_str = result.dump_outputs[phase_name]
            if out_str:
                sys.stdout.write(out_str + "\n")

    if result.diagnostics:
        source_map = SourceMap(source_text, file_name)
        for diag in result.diagnostics:
            rendered = DiagnosticRenderer.render_diagnostic(diag, source_map=source_map)
            sys.stderr.write(rendered + "\n")

    if any(d.severity == Severity.FATAL for d in result.diagnostics):
        return 70

    if not result.success:
        return 1

    if parsed_args.stop_after and parsed_args.stop_after != "codegen_c":
        return 0

    c_code = result.artifacts.get("codegen_c")
    if c_code is None:
        return 1

    if parsed_args.emit_c:
        if parsed_args.output:
            try:
                output_path.write_text(c_code, encoding="utf-8")
            except OSError as error:
                sys.stderr.write(f"quest compile: error writing '{output_path}': {error}\n")
                return 1
        else:
            sys.stdout.write(c_code)
        return 0

    from quest.codegen import compile_c_source
    try:
        extra_objs = list(options.extra_objects)
        for obj in ctx.env.linked_objects:
            if obj not in extra_objs:
                extra_objs.append(obj)
        compile_c_source(
            c_code,
            output_path=output_path,
            nogc=parsed_args.nogc,
            extra_objects=extra_objs,
        )
    except Exception as error:
        sys.stderr.write(f"quest compile: error: {error}\n")
        return 1

    return 0


def main() -> int:
    return run_driver(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
