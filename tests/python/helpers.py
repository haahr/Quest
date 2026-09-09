"""Shared helper utilities for Quest unit tests."""

from typing import Any, Optional, Union

from quest import ast
from quest.env import Environment
from quest.interpreter import RuntimeEnvironment
from quest.parser import SyntaxTarget
from quest.pipeline import (
    CompilerContext,
    CompilerOptions,
    PipelineResult,
    default_pipeline,
)

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


def parse_fragment(
    source: str,
    target: Union[str, SyntaxTarget] = "phrase",
) -> Any:
    """Parse a source fragment through the compiler pipeline."""
    return parse_phrase(source, target=target)


def run_source(
    source: str,
    env: Optional[Environment] = None,
    runtime_env: Optional[RuntimeEnvironment] = None,
    options: Optional[CompilerOptions] = None,
    ctx: Optional[CompilerContext] = None,
) -> PipelineResult:
    """Run the standard compiler pipeline on a Quest source string."""
    pipeline = default_pipeline()
    opts = options or CompilerOptions()
    if ctx is None:
        ctx = CompilerContext.create(
            source_text=source,
            file_name="<test>",
            options=opts,
            env=env,
            runtime_env=runtime_env,
        )
    return pipeline.execute(source, "<test>", options=opts, ctx=ctx)
