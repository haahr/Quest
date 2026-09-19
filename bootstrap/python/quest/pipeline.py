"""Quest Compiler Phase Pipeline Framework.

Provides uniform lifecycle management, execution, and artifact inspection
across compiler phases (tokenize, parse, typecheck, interpret, codegen).
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import quest.ast as ast
from quest.diagnostics import (
    Diagnostic,
    DiagnosticSink,
    FatalDiagnosticError,
    QuestCompilerError,
    Severity,
)
from quest.elaborate_types import elaborate_kind, elaborate_type
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.interpreter import (
    QuestException,
    QuestRuntimeError,
    RuntimeEnvironment,
    eval_binding,
    eval_expr,
    eval_program,
    eval_program_phrases,
    format_interactive_result,
)
from quest.parser import ParserError
from quest.runtime import OK_VALUE, QOk, QValue, qvalue_to_str
from quest.tokenizer import Tokenizer, TokenizerError
from quest.tokens import SourceMap, Token, TokenKind
from quest.typechecker import (
    elaborate_phrase,
    elaborate_program,
    synth_expr,
)
from quest.typed_ast import TypedBinding, TypedExpr, TypedProgram
from quest.types import KindError, QKind, QType


@dataclass
class CompilerOptions:
    """Compilation configuration options passed to compiler phases."""
    stop_after: Optional[str] = None
    dump_after: set[str] = field(default_factory=set)
    include_paths: list[Path] = field(default_factory=list)
    echo: bool = False
    show_offsets: bool = False
    show_values: bool = False
    target: Optional[Any] = None
    emit_c: bool = False
    output_path: Optional[Path] = None
    nogc: bool = False
    print_result: bool = False


@dataclass
class CompilerContext:
    """Shared state passed through all stages of a compilation session."""
    source_text: str
    file_name: str
    source_map: SourceMap
    sink: DiagnosticSink = field(default_factory=DiagnosticSink)
    env: Environment = field(default_factory=Environment)
    options: CompilerOptions = field(default_factory=CompilerOptions)
    runtime_env: RuntimeEnvironment = field(default_factory=RuntimeEnvironment.create_root_env)

    @classmethod
    def create(
        cls,
        source_text: str,
        file_name: str = "<stdin>",
        options: Optional[CompilerOptions] = None,
        env: Optional[Environment] = None,
        runtime_env: Optional[RuntimeEnvironment] = None,
    ) -> CompilerContext:
        """Constructs a fresh CompilerContext with initialized SourceMap."""
        opts = options or CompilerOptions()
        environment = env if env is not None else Environment()
        r_env = runtime_env if runtime_env is not None else RuntimeEnvironment.create_root_env()

        # Wire include_paths and current_dir
        environment.include_paths = list(opts.include_paths)
        r_env.include_paths = list(opts.include_paths)
        r_env.loaded_modules_ast = environment.loaded_modules_ast

        if file_name and not file_name.startswith("<"):
            try:
                p = Path(file_name).resolve()
                current_dir = p.parent
                environment.current_dir = current_dir
                r_env.current_dir = current_dir
            except Exception:
                pass
        elif environment.current_dir is None:
            cwd = Path.cwd()
            environment.current_dir = cwd
            r_env.current_dir = cwd

        source_map = SourceMap(source_text, file_name)
        return cls(
            source_text=source_text,
            file_name=file_name,
            source_map=source_map,
            sink=DiagnosticSink(),
            env=environment,
            options=opts,
            runtime_env=r_env,
        )


@dataclass
class PipelineResult:
    """Summary of a pipeline execution session."""
    success: bool
    final_phase: Optional[str]
    artifacts: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    dump_outputs: dict[str, str] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(d.severity in (Severity.ERROR, Severity.FATAL) for d in self.diagnostics)

    @property
    def final_artifact(self) -> Optional[Any]:
        if self.final_phase and self.final_phase in self.artifacts:
            return self.artifacts[self.final_phase]
        return None


class Phase(ABC):
    """Abstract base class for a discrete compiler transformation pass."""
    name: str
    description: str
    artifact_name: str

    @abstractmethod
    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[Any]:
        """Executes the phase on input_data. Returns output artifact or None on failure."""
        pass

    @abstractmethod
    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        """Renders the output artifact as canonical human-readable or golden-test text."""
        pass


class TokenizePhase(Phase):
    """Lexical analysis phase: converts source text into token stream."""
    name = "tokenize"
    description = "Tokenize source text into lexical tokens"
    artifact_name = "tokens"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[list[Token]]:
        source_text = str(input_data)
        tokenizer = Tokenizer(source_text, ctx.file_name)
        try:
            return tokenizer.tokenize_all()
        except QuestCompilerError as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        tokens: list[Token] = output_data
        lines: list[str] = []
        for token in tokens:
            loc = ctx.source_map.locate(token.offset)
            pos_str = f"{loc.line}:{loc.column}"
            if token.kind == TokenKind.EOF:
                lines.append(f"{pos_str}\t{token.kind.name}")
                break
            if ctx.options.show_values and token.value is not None:
                lines.append(f"{pos_str}\t{token.kind.name}\t{token.lexeme}\t(value={token.value!r})")
            else:
                lines.append(f"{pos_str}\t{token.kind.name}\t{token.lexeme}")
        return "\n".join(lines)


class ParsePhase(Phase):
    """Syntactic analysis phase: parses token stream into untyped AST."""
    name = "parse"
    description = "Parse token stream into untyped S-expression AST"
    artifact_name = "ast"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[Any]:
        tokens: list[Token] = input_data
        try:
            return parse_quest_program(tokens, ctx.source_map, target=ctx.options.target)
        except QuestCompilerError as error:
            ctx.sink.emit(error.to_diagnostic())
            return None
        except (ValueError, TypeError) as error:
            ctx.sink.emit(Diagnostic.make_error(str(error), 0))
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        if isinstance(output_data, ast.ASTNode):
            return ast.ast_dump(output_data, show_offsets=ctx.options.show_offsets)
        return str(output_data)


class TypecheckPhase(Phase):
    """Semantic analysis phase: elaborates AST into typed AST."""
    name = "typecheck"
    description = "Elaborate AST terms and kinds into typed AST"
    artifact_name = "typed_ast"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[Any]:
        try:
            match input_data:
                case ast.Program():
                    return elaborate_program(input_data, ctx.env)
                case ast.Expr():
                    return synth_expr(input_data, ctx.env)
                case ast.Type():
                    return elaborate_type(input_data, ctx.env)
                case ast.Kind():
                    return elaborate_kind(input_data, ctx.env)
                case ast.ASTNode():
                    return elaborate_phrase(input_data, ctx.env)
                case _:
                    return input_data
        except QuestCompilerError as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        if hasattr(output_data, "dump"):
            return output_data.dump()
        return str(output_data)


class InterpretPhase(Phase):
    """Interpretation phase: evaluates typed AST in tree-walking interpreter."""
    name = "interpret"
    description = "Evaluate typed AST in tree-walking interpreter"
    artifact_name = "value"

    def __init__(self) -> None:
        self._last_final_phrase: Optional[TypedBinding | TypedExpr] = None
        self._last_phrase_results: list[tuple[TypedBinding | TypedExpr, QValue]] = []

    @property
    def last_phrase_results(self) -> list[tuple[TypedBinding | TypedExpr, QValue]]:
        return self._last_phrase_results

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[QValue]:
        try:
            match input_data:
                case TypedProgram():
                    if input_data.phrases:
                        self._last_final_phrase = input_data.phrases[-1]
                    else:
                        self._last_final_phrase = None
                    self._last_phrase_results = eval_program_phrases(input_data, ctx.runtime_env)
                    if ctx.options.echo:
                        for phrase, val in self._last_phrase_results:
                            out_str = format_interactive_result(phrase, val)
                            if out_str:
                                sys.stdout.write(out_str + "\n")
                    return self._last_phrase_results[-1][1] if self._last_phrase_results else OK_VALUE

                case TypedExpr():
                    self._last_final_phrase = input_data
                    val = eval_expr(input_data, ctx.runtime_env)
                    self._last_phrase_results = [(input_data, val)]
                    if ctx.options.echo:
                        out_str = format_interactive_result(input_data, val)
                        if out_str:
                            sys.stdout.write(out_str + "\n")
                    return val

                case TypedBinding():
                    self._last_final_phrase = input_data
                    val = eval_binding(input_data, ctx.runtime_env)
                    self._last_phrase_results = [(input_data, val)]
                    if ctx.options.echo:
                        out_str = format_interactive_result(input_data, val)
                        if out_str:
                            sys.stdout.write(out_str + "\n")
                    return val

                case QType() | QKind():
                    self._last_final_phrase = None
                    self._last_phrase_results = []
                    return OK_VALUE

                case _:
                    self._last_final_phrase = None
                    self._last_phrase_results = []
                    return OK_VALUE
        except QuestCompilerError as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        val: QValue = output_data
        if self._last_final_phrase is not None:
            return format_interactive_result(self._last_final_phrase, val)
        return qvalue_to_str(val)


class CodegenCPhase(Phase):
    """C code generation phase: translates typed AST into C99 source code."""
    name = "codegen_c"
    description = "Translate typed AST into C99 source code"
    artifact_name = "c_source"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[str]:
        from quest.codegen.c_emitter import CEmitter

        try:
            emitter = CEmitter(
                echo=ctx.options.echo,
                print_result=getattr(ctx.options, "print_result", False),
            )
            loaded_mods = ctx.env.loaded_modules_ast if ctx.env else None
            match input_data:
                case TypedProgram():
                    return emitter.emit_program(input_data, loaded_modules=loaded_mods)
                case TypedExpr() | TypedBinding():
                    prog = TypedProgram(phrases=(input_data,))
                    return emitter.emit_program(prog, loaded_modules=loaded_mods)
                case _:
                    return None
        except Exception as error:
            ctx.sink.emit(Diagnostic.make_error(str(error), 0))
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        return str(output_data) if output_data is not None else ""


class RunCCompiledPhase(Phase):
    """Native binary execution phase: compiles C code and runs the resulting binary."""
    name = "run_c_compiled"
    description = "Compile C code to native binary and execute it"
    artifact_name = "stdout"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[str]:
        import tempfile
        from quest.codegen.compiler_runner import compile_c_source, run_binary

        if not isinstance(input_data, str):
            return None

        c_code: str = input_data
        with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp_file:
            bin_path = Path(tmp_file.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=ctx.options.nogc)
            proc = run_binary(bin_path)
            if proc.returncode != 0:
                msg = proc.stderr.strip() if proc.stderr else f"Binary exited with code {proc.returncode}"
                ctx.sink.emit(Diagnostic.make_error(msg, 0))
            return proc.stdout
        except Exception as error:
            ctx.sink.emit(Diagnostic.make_error(str(error), 0))
            return None
        finally:
            if bin_path.exists():
                try:
                    bin_path.unlink()
                except OSError:
                    pass

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        if output_data is None:
            return ""
        s = str(output_data)
        return s[:-1] if s.endswith("\n") else s


class PhasePipeline:
    """Manages sequential execution of registered compiler phases."""

    def __init__(self, phases: Optional[list[Phase]] = None) -> None:
        self.phases: list[Phase] = phases or []

    def register(self, phase: Phase) -> None:
        """Appends a phase to the pipeline."""
        self.phases.append(phase)

    def phase_names(self) -> list[str]:
        """Returns the ordered list of registered phase names."""
        return [p.name for p in self.phases]

    def get_phase(self, name: str) -> Optional[Phase]:
        """Looks up a registered phase by name."""
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def precursors_of(self, target_name: str) -> list[str]:
        """Returns the names of all phases strictly preceding target_name."""
        names = self.phase_names()
        if target_name not in names:
            raise ValueError(f"Unknown phase '{target_name}'. Available: {names}")
        idx = names.index(target_name)
        return names[:idx]

    def execute(
        self,
        source_text: str,
        file_name: str = "<stdin>",
        options: Optional[CompilerOptions] = None,
        ctx: Optional[CompilerContext] = None,
        target: Optional[Any] = None,
    ) -> PipelineResult:
        """Executes the pipeline on source_text."""
        opts = options or CompilerOptions()
        if target is not None:
            opts.target = target
        context = ctx or CompilerContext.create(source_text, file_name, opts)
        context.options = opts

        current_data: Any = source_text
        artifacts: dict[str, Any] = {}
        dump_outputs: dict[str, str] = {}
        final_phase: Optional[str] = None

        try:
            for phase in self.phases:
                final_phase = phase.name

                # Run phase
                current_data = phase.run(current_data, context)
                if current_data is not None:
                    artifacts[phase.name] = current_data

                # Check if dump requested via --dump-after or --stop-after
                should_dump = (phase.name in opts.dump_after) or (opts.stop_after == phase.name)
                if should_dump and current_data is not None:
                    dump_outputs[phase.name] = phase.dump(current_data, context)

                # Halt if phase encountered errors or reached --stop-after
                if context.sink.has_errors:
                    break
                if opts.stop_after == phase.name:
                    break

        except FatalDiagnosticError as fatal_err:
            # Fatal diagnostic already recorded in sink
            pass

        return PipelineResult(
            success=not context.sink.has_errors,
            final_phase=final_phase,
            artifacts=artifacts,
            diagnostics=list(context.sink.diagnostics),
            dump_outputs=dump_outputs,
        )

    def compile_file(
        self,
        path: Path,
        options: Optional[CompilerOptions] = None,
        ctx: Optional[CompilerContext] = None,
    ) -> PipelineResult:
        """Executes the pipeline on a file from disk."""
        source_text = path.read_text(encoding="utf-8")
        return self.execute(source_text, str(path), options=options, ctx=ctx)

    def compile_phrase(
        self,
        phrase_text: str,
        options: Optional[CompilerOptions] = None,
        ctx: Optional[CompilerContext] = None,
    ) -> PipelineResult:
        """Executes the pipeline on an interactive REPL phrase, preserving context."""
        context = ctx or CompilerContext.create(phrase_text, "<repl>", options=options)
        context.sink = DiagnosticSink()
        # Update source_text and source_map for this specific phrase
        context.source_text = phrase_text
        context.source_map = SourceMap(phrase_text, context.file_name)
        return self.execute(phrase_text, context.file_name, options=options, ctx=context)


def default_pipeline() -> PhasePipeline:
    """Returns the standard compiler pipeline containing all active phases."""
    pipeline = PhasePipeline()
    pipeline.register(TokenizePhase())
    pipeline.register(ParsePhase())
    pipeline.register(TypecheckPhase())
    pipeline.register(InterpretPhase())
    return pipeline


def compile_pipeline() -> PhasePipeline:
    """Returns the C compilation pipeline (Tokenize -> Parse -> Typecheck -> CodegenC)."""
    pipeline = PhasePipeline()
    pipeline.register(TokenizePhase())
    pipeline.register(ParsePhase())
    pipeline.register(TypecheckPhase())
    pipeline.register(CodegenCPhase())
    return pipeline


def full_pipeline() -> PhasePipeline:
    """Returns the full C compilation and execution pipeline."""
    pipeline = PhasePipeline()
    pipeline.register(TokenizePhase())
    pipeline.register(ParsePhase())
    pipeline.register(TypecheckPhase())
    pipeline.register(CodegenCPhase())
    pipeline.register(RunCCompiledPhase())
    return pipeline


