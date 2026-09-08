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
from quest.diagnostics import Diagnostic, DiagnosticSink, FatalDiagnosticError, Severity
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.interpreter import (
    QuestException,
    QuestRuntimeError,
    RuntimeEnvironment,
    eval_program,
    eval_program_phrases,
    format_interactive_result,
)
from quest.parser import ParserError
from quest.runtime import QOk, QValue, qvalue_to_str
from quest.tokenizer import Tokenizer, TokenizerError
from quest.tokens import SourceMap, Token, TokenKind
from quest.typechecker import elaborate_program, TypeError as QuestTypeError
from quest.typed_ast import TypedBinding, TypedExpr, TypedProgram
from quest.types import KindError


@dataclass
class CompilerOptions:
    """Compilation configuration options passed to compiler phases."""
    stop_after: Optional[str] = None
    dump_after: set[str] = field(default_factory=set)
    include_paths: list[Path] = field(default_factory=list)
    echo: bool = False
    show_offsets: bool = False
    show_values: bool = False


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
        except TokenizerError as error:
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

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[ast.Program]:
        tokens: list[Token] = input_data
        try:
            return parse_quest_program(tokens, ctx.source_map)
        except ParserError as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        tree: ast.Program = output_data
        return ast.ast_dump(tree, show_offsets=ctx.options.show_offsets)


class TypecheckPhase(Phase):
    """Semantic analysis phase: elaborates AST into typed AST."""
    name = "typecheck"
    description = "Elaborate AST terms and kinds into typed AST"
    artifact_name = "typed_ast"

    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[TypedProgram]:
        tree: ast.Program = input_data
        try:
            return elaborate_program(tree, ctx.env)
        except (QuestTypeError, KindError) as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        typed_prog: TypedProgram = output_data
        return typed_prog.dump()


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
        typed_prog: TypedProgram = input_data
        if typed_prog.phrases:
            self._last_final_phrase = typed_prog.phrases[-1]
        else:
            self._last_final_phrase = None
        try:
            self._last_phrase_results = eval_program_phrases(typed_prog, ctx.runtime_env)
            if ctx.options.echo:
                for phrase, val in self._last_phrase_results:
                    out_str = format_interactive_result(phrase, val)
                    if out_str:
                        sys.stdout.write(out_str + "\n")
            return self._last_phrase_results[-1][1] if self._last_phrase_results else OK_VALUE
        except (QuestException, QuestRuntimeError) as error:
            ctx.sink.emit(error.to_diagnostic())
            return None

    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        val: QValue = output_data
        return format_interactive_result(self._last_final_phrase, val)


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
    ) -> PipelineResult:
        """Executes the pipeline on source_text."""
        opts = options or CompilerOptions()
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
