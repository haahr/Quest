"""Target-agnostic free-variable and closure analysis for Quest AST."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quest.typed_ast import (
    TypedBlock,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedLetValue,
    TypedTry,
    TypedVar,
)
from quest.types import QType


@dataclass(frozen=True)
class CapturedVar:
    """Represents a variable captured by an inner closure."""
    name: str
    type_val: QType


@dataclass
class LambdaAnalysis:
    """Target-agnostic summary of a lambda function and its captured free variables."""
    id: str
    fun: TypedFun
    free_vars: list[CapturedVar]


def find_free_vars(fun: TypedFun, global_names: set[str]) -> list[CapturedVar]:
    """Finds all free variables captured by a function from enclosing non-global scopes."""
    free_vars: list[CapturedVar] = []
    seen: set[str] = set()

    def walk(node: Any, bound: set[str]) -> None:
        if node is None:
            return
        match node:
            case TypedVar(name=name, type_val=t):
                if name not in bound and name not in global_names and name not in seen:
                    seen.add(name)
                    free_vars.append(CapturedVar(name=name, type_val=t))
            case TypedLetValue(name=name, value=v):
                walk(v, bound)
                bound.add(name)
            case TypedFor(var_name=name, start=st, stop=sp, body=b):
                walk(st, bound)
                walk(sp, bound)
                walk(b, bound | {name})
            case TypedBlock(bindings=bindings, result=res):
                b_bound = set(bound)
                for b in bindings:
                    match b:
                        case TypedLetValue(name=name, value=v):
                            walk(v, b_bound)
                            b_bound.add(name)
                        case TypedExprStmt(expr=e):
                            walk(e, b_bound)
                        case _:
                            pass
                walk(res, b_bound)
            case TypedFun(params=params, body=b):
                inner_bound = bound | {p.name for p in params}
                walk(b, inner_bound)
            case TypedTry(body=b, branches=branches, else_branch=else_b):
                walk(b, bound)
                for br in branches:
                    walk(br.exc_pattern, bound)
                    br_bound = bound | ({br.binder.name} if br.binder else set())
                    walk(br.body, br_bound)
                if else_b:
                    walk(else_b, bound)
            case _:
                if isinstance(node, (list, tuple)):
                    for item in node:
                        walk(item, bound)
                elif hasattr(node, "__dataclass_fields__"):
                    for field_name in node.__dataclass_fields__:
                        walk(getattr(node, field_name), bound)

    init_bound = {p.name for p in fun.params}
    walk(fun.body, init_bound)
    return free_vars


def analyze_closures(
    prog: Any,
    top_fun_objs: set[int],
    global_names: set[str],
) -> list[LambdaAnalysis]:
    """Scans AST to find all lambdas needing lifting and collects their free variables."""
    lambdas: list[LambdaAnalysis] = []
    lambda_counter = 0

    def scan(node: Any) -> None:
        nonlocal lambda_counter
        if node is None:
            return
        if isinstance(node, TypedFun):
            if id(node) not in top_fun_objs:
                lambda_counter += 1
                lid = f"lambda_{lambda_counter}"
                fvars = find_free_vars(node, global_names)
                lambdas.append(
                    LambdaAnalysis(
                        id=lid,
                        fun=node,
                        free_vars=fvars,
                    )
                )
            # Continue scanning body for nested lambdas
            scan(node.body)
            return

        if isinstance(node, (list, tuple)):
            for item in node:
                scan(item)
            return

        if hasattr(node, "__dataclass_fields__"):
            for field_name in node.__dataclass_fields__:
                scan(getattr(node, field_name))

    scan(prog)
    return lambdas
