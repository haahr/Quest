"""Shared helper utilities for Quest unit tests."""

from typing import Any, Optional, Union

from quest import ast
from quest.elaborate_types import elaborate_kind, elaborate_type
from quest.env import Environment
from quest.interpreter import RuntimeEnvironment, eval_program
from quest.parser import SyntaxTarget
from quest.pipeline import (
    CompilerContext,
    CompilerOptions,
    PipelineResult,
    default_pipeline,
)
from quest.typechecker import check_expr, synth_expr
from quest.types import QKind, QType

_parser_pipeline = default_pipeline()


def parse_phrase(
    source: str,
    target: Optional[Union[str, SyntaxTarget]] = None,
) -> Any:
    """Parse a source string through the compiler pipeline up to the parse phase.

    If target is provided (e.g. 'type', 'kind', 'expr', 'phrase', 'program', 'signature',
    or a SyntaxTarget), parses starting from that grammar target.
    Otherwise, parses as a standard program and returns the first phrase.
    """
    opts = CompilerOptions(stop_after="parse", target=target)
    res = _parser_pipeline.execute(source, "<test>", options=opts)
    if res.has_errors:
        errors = [d.message for d in res.diagnostics]
        raise ValueError(f"Failed to parse '{source}': {errors}")
    artifact = res.artifacts.get("parse")
    if artifact is None:
        raise ValueError(f"No parse artifact produced from '{source}'")
    if target is None and isinstance(artifact, ast.Program):
        if not artifact.phrases:
            raise ValueError(f"No phrases parsed from '{source}'")
        return artifact.phrases[0]
    return artifact


def parse_type(type_source: str) -> ast.Type:
    """Parse a type expression through the compiler pipeline."""
    return parse_phrase(type_source, target="type")


def parse_kind(kind_source: str) -> ast.Kind:
    """Parse a kind expression through the compiler pipeline."""
    return parse_phrase(kind_source, target="kind")


def parse_expr(expr_source: str) -> ast.Expr:
    """Parse a value expression through the compiler pipeline."""
    return parse_phrase(expr_source, target="expr")


def elaborate_test_type(source: str, env: Optional[Environment] = None) -> QType:
    """Parse and elaborate a type expression into a semantic QType."""
    if env is None:
        env = Environment()
    return elaborate_type(parse_type(source), env)


def elaborate_test_kind(source: str, env: Optional[Environment] = None) -> QKind:
    """Parse and elaborate a kind expression into a semantic QKind."""
    if env is None:
        env = Environment()
    return elaborate_kind(parse_kind(source), env)


def synth_test_expr(source: str, env: Optional[Environment] = None) -> Any:
    """Parse and type-synthesize an expression AST node."""
    if env is None:
        env = Environment()
    return synth_expr(parse_expr(source), env)


def check_test_expr(
    source: str,
    expected_type: QType,
    env: Optional[Environment] = None,
) -> Any:
    """Parse and type-check an expression AST node against an expected type."""
    if env is None:
        env = Environment()
    return check_expr(parse_expr(source), expected_type, env)


def eval_test_source(
    source: str,
    env: Optional[RuntimeEnvironment] = None,
) -> Any:
    """Parse, typecheck, and evaluate Quest source code, returning the resulting QValue.

    Raises RuntimeError if compilation fails.
    """
    pipeline = default_pipeline()
    opts = CompilerOptions(stop_after="typecheck")
    res = pipeline.execute(source, "<test>", options=opts)
    if not res.success or res.final_artifact is None:
        diags = "\n".join(d.message for d in res.diagnostics)
        raise RuntimeError(f"Compilation failed for '{source}':\n{diags}")
    return eval_program(res.final_artifact, env)



def run_pipeline(
    source: str,
    env: Optional[Environment] = None,
    runtime_env: Optional[RuntimeEnvironment] = None,
    options: Optional[CompilerOptions] = None,
    ctx: Optional[CompilerContext] = None,
) -> tuple[PipelineResult, CompilerContext]:
    """Run the standard compiler pipeline and return (result, ctx)."""
    opts = options or CompilerOptions()
    if ctx is None:
        ctx = CompilerContext.create(
            source_text=source,
            file_name="<test>",
            options=opts,
            env=env,
            runtime_env=runtime_env,
        )
    result = default_pipeline().execute(source, "<test>", options=opts, ctx=ctx)
    return result, ctx


def run_source(
    source: str,
    env: Optional[Environment] = None,
    runtime_env: Optional[RuntimeEnvironment] = None,
    options: Optional[CompilerOptions] = None,
    ctx: Optional[CompilerContext] = None,
) -> PipelineResult:
    """Run the standard compiler pipeline on a Quest source string."""
    result, _ = run_pipeline(
        source,
        env=env,
        runtime_env=runtime_env,
        options=options,
        ctx=ctx,
    )
    return result


def assert_pipeline_success(
    source: str,
    env: Optional[Environment] = None,
    runtime_env: Optional[RuntimeEnvironment] = None,
    options: Optional[CompilerOptions] = None,
    ctx: Optional[CompilerContext] = None,
) -> CompilerContext:
    """Execute source through the pipeline, asserting success and returning CompilerContext."""
    result, context = run_pipeline(
        source,
        env=env,
        runtime_env=runtime_env,
        options=options,
        ctx=ctx,
    )
    if not result.success:
        diags = "\n".join(d.message for d in result.diagnostics)
        raise AssertionError(
            f"Pipeline failed unexpectedly for source:\n{source}\nDiagnostics:\n{diags}"
        )
    return context


def assert_pipeline_failure(
    source: str,
    expected_substr: Optional[str] = None,
    env: Optional[Environment] = None,
    runtime_env: Optional[RuntimeEnvironment] = None,
    options: Optional[CompilerOptions] = None,
    ctx: Optional[CompilerContext] = None,
) -> list[str]:
    """Execute source through the pipeline, asserting failure and checking error messages."""
    result, _ = run_pipeline(
        source,
        env=env,
        runtime_env=runtime_env,
        options=options,
        ctx=ctx,
    )
    if result.success:
        raise AssertionError(f"Expected pipeline failure, but succeeded for source:\n{source}")
    messages = [d.message for d in result.diagnostics]
    if expected_substr is not None:
        combined = " ".join(messages)
        if expected_substr not in combined:
            raise AssertionError(
                f"Expected substring '{expected_substr}' not found in diagnostics: {messages}\n"
                f"Source:\n{source}"
            )
    return messages
