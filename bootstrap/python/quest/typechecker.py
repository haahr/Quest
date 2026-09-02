"""Quest Term Elaboration and Bidirectional Typechecker (Phases 2 & 3)."""

from __future__ import annotations

from typing import Any, Optional, Union

import quest.ast as ast
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QAllType,
    QArrayType,
    QFunType,
    QKind,
    QOptionField,
    QOptionType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTupleType,
    QType,
    QTypeMeta,
    QVarType,
    QVariantField,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    is_subtype,
    is_type_equal,
)
from quest.env import (
    Environment,
    KindSymbol,
    Scope,
    TypeSymbol,
    ValueSymbol,
)
from quest.elaborate_types import (
    elaborate_kind,
    elaborate_kind_binding,
    elaborate_mutual_rec_type_group,
    elaborate_type,
    elaborate_type_binding,
)
from quest.typed_ast import (
    TypedApp,
    TypedAssign,
    TypedBinding,
    TypedBlock,
    TypedBool,
    TypedChar,
    TypedDefKind,
    TypedDerefCell,
    TypedExit,
    TypedExpr,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedInfix,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedOk,
    TypedParam,
    TypedReal,
    TypedString,
    TypedTypeApp,
    TypedVar,
    TypedVarCell,
    TypedWhile,
)


class TypeError(Exception):
    """Raised when a type error occurs during term elaboration and typechecking."""

    def __init__(self, message: str, offset: int = 0) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.message = message
        self.offset = offset


# ============================================================================
# Bidirectional Typechecking Core (check_expr & synth_expr)
# ============================================================================

def check_expr(
    expr: ast.Expr,
    expected_type: QType,
    env: Optional[Environment] = None,
    loop_depth: int = 0,
) -> TypedExpr:
    """Checks an AST expression against an expected QType (Gamma |- e <= T)."""
    if env is None:
        env = Environment()

    # 1. Conditionals with else branch: check both branches against expected_type
    if isinstance(expr, ast.ExprIf) and expr.else_branch is not None:
        return _check_if_expr(expr, expected_type, env, loop_depth)

    # 2. Block expression: check final result against expected_type
    if isinstance(expr, ast.ExprBlock):
        return _check_block_expr(expr, expected_type, env, loop_depth)

    # 3. Function abstraction: check against expected function type
    if isinstance(expr, ast.ExprFun):
        return _check_fun_expr(expr, expected_type, env, loop_depth)

    # 4. Subsumption: synthesize minimal type and check subtyping (S <= T)
    typed = synth_expr(expr, env, loop_depth)
    if not is_subtype(typed.type_val, expected_type, env):
        raise TypeError(
            f"Type mismatch: synthesized type '{typed.type_val}' is not a subtype "
            f"of expected type '{expected_type}'",
            offset=expr.offset,
        )
    return typed


def synth_expr(
    expr: ast.Expr,
    env: Optional[Environment] = None,
    loop_depth: int = 0,
) -> TypedExpr:
    """Synthesizes the minimal QType and elaborated TypedExpr (Gamma |- e => T)."""
    if env is None:
        env = Environment()

    # --- Literals ---
    if isinstance(expr, ast.ExprInt):
        return TypedInt(value=expr.value, offset=expr.offset)

    if isinstance(expr, ast.ExprReal):
        return TypedReal(value=expr.value, offset=expr.offset)

    if isinstance(expr, ast.ExprBool):
        return TypedBool(value=expr.value, offset=expr.offset)

    if isinstance(expr, ast.ExprChar):
        return TypedChar(value=expr.value, offset=expr.offset)

    if isinstance(expr, ast.ExprString):
        return TypedString(value=expr.value, offset=expr.offset)

    if isinstance(expr, ast.ExprOk):
        return TypedOk(offset=expr.offset)

    if isinstance(expr, ast.ExprExit):
        if loop_depth <= 0:
            raise TypeError("Exit statement outside of any loop", offset=expr.offset)
        return TypedExit(offset=expr.offset)

    # --- Variables & Identifiers ---
    if isinstance(expr, ast.ExprId):
        sym = env.lookup_value(expr.name)
        if sym is None:
            raise TypeError(f"Undefined variable '{expr.name}'", offset=expr.offset)

        # Implicit dereferencing: mutable variables in value positions yield element type
        if sym.is_var:
            var_node = TypedVar(
                name=sym.name,
                symbol=sym,
                type_val=QVarType(sym.type_val),
                offset=expr.offset,
            )
            return TypedDerefCell(target=var_node, type_val=sym.type_val, offset=expr.offset)

        return TypedVar(name=sym.name, symbol=sym, type_val=sym.type_val, offset=expr.offset)

    # --- Explicit Dereference (@e or !e) ---
    if isinstance(expr, ast.ExprDerefCell):
        if isinstance(expr.target, ast.ExprId):
            sym = env.lookup_value(expr.target.name)
            if sym is None:
                raise TypeError(f"Undefined variable '{expr.target.name}'", offset=expr.target.offset)
            if not sym.is_var and not isinstance(sym.type_val, QVarType):
                raise TypeError(
                    f"Cannot dereference non-variable symbol '{expr.target.name}'",
                    offset=expr.target.offset,
                )
            var_type = QVarType(sym.type_val) if sym.is_var else sym.type_val
            elem_type = sym.type_val if sym.is_var else sym.type_val.element_type
            var_node = TypedVar(
                name=sym.name,
                symbol=sym,
                type_val=var_type,
                offset=expr.target.offset,
            )
            return TypedDerefCell(target=var_node, type_val=elem_type, offset=expr.offset)

        target_typed = synth_expr(expr.target, env, loop_depth)
        if not isinstance(target_typed.type_val, QVarType):
            raise TypeError(
                f"Cannot dereference non-variable type '{target_typed.type_val}'",
                offset=expr.offset,
            )
        return TypedDerefCell(
            target=target_typed,
            type_val=target_typed.type_val.element_type,
            offset=expr.offset,
        )

    # --- Reference Cell Allocation (var e) ---
    if isinstance(expr, ast.ExprVarCell):
        val_typed = synth_expr(expr.value, env, loop_depth)
        return TypedVarCell(
            value=val_typed,
            type_val=QVarType(val_typed.type_val),
            offset=expr.offset,
        )

    # --- Infix Operators ---
    if isinstance(expr, ast.ExprInfix):
        return _synth_infix_expr(expr, env, loop_depth)

    # --- Conditionals (if cond then e1 [elsif ...] [else e2] end) ---
    if isinstance(expr, ast.ExprIf):
        return _synth_if_expr(expr, env, loop_depth)

    # --- Loops & Control Flow ---
    if isinstance(expr, ast.ExprWhile):
        cond_typed = check_expr(expr.cond, BOOL_TYPE, env, loop_depth)
        body_typed = synth_expr(expr.body, env, loop_depth + 1)
        return TypedWhile(cond=cond_typed, body=body_typed, offset=expr.offset)

    if isinstance(expr, ast.ExprLoop):
        body_typed = synth_expr(expr.body, env, loop_depth + 1)
        return TypedLoop(body=body_typed, offset=expr.offset)

    if isinstance(expr, ast.ExprFor):
        return _synth_for_expr(expr, env, loop_depth)

    # --- Block Expressions ---
    if isinstance(expr, ast.ExprBlock):
        return _synth_block_expr(expr, env, loop_depth)

    # --- Functions and Applications ---
    if isinstance(expr, ast.ExprFun):
        return _synth_fun_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprApp):
        return _synth_app_expr(expr, env, loop_depth)

    raise TypeError(f"Unsupported AST expression '{expr}'", offset=getattr(expr, "offset", 0))


# ============================================================================
# Functions and Applications Helpers
# ============================================================================

def _synth_fun_expr(expr: ast.ExprFun, env: Environment, loop_depth: int) -> TypedFun:
    """Synthesizes a function abstraction: fun(params): RetType Body."""
    env.push_scope("fun")
    try:
        formal_params: list[TypedParam] = []
        q_params: list[QParam] = []

        for p in expr.params:
            if p.type_annot is None:
                raise TypeError(
                    f"Parameter '{p.name}' requires a type annotation in synthesis mode",
                    offset=p.offset,
                )
            p_type = elaborate_type(p.type_annot, env)
            is_var = p.mode == ast.ParamMode.VAR
            is_out = p.mode == ast.ParamMode.OUT
            p_sym = ValueSymbol(name=p.name, type_val=p_type, is_var=is_var, is_out=is_out)
            env.current_scope.declare_value(p_sym)
            formal_params.append(
                TypedParam(
                    name=p.name,
                    symbol=p_sym,
                    type_val=p_type,
                    is_var=is_var,
                    is_out=is_out,
                    offset=p.offset,
                )
            )
            q_params.append(QParam(name=p.name, type_val=p_type, is_var=is_var, is_out=is_out))

        if expr.return_type is not None:
            expected_ret = elaborate_type(expr.return_type, env)
            body_typed = check_expr(expr.body, expected_ret, env, loop_depth=0)
            ret_type = expected_ret
        else:
            body_typed = synth_expr(expr.body, env, loop_depth=0)
            ret_type = body_typed.type_val

        fun_type = QFunType(params=tuple(q_params), result_type=ret_type)
        return TypedFun(
            params=tuple(formal_params),
            body=body_typed,
            type_val=fun_type,
            offset=expr.offset,
        )
    finally:
        env.pop_scope()


def _check_fun_expr(
    expr: ast.ExprFun,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedFun:
    """Checks a function abstraction against an expected function type."""
    expected_lazy = expected_type.evaluate_lazily(env)
    if not isinstance(expected_lazy, QFunType):
        # Fall back to synthesis and subsumption
        typed_fun = _synth_fun_expr(expr, env, loop_depth)
        if not is_subtype(typed_fun.type_val, expected_type, env):
            raise TypeError(
                f"Function type '{typed_fun.type_val}' is not a subtype of expected type '{expected_type}'",
                offset=expr.offset,
            )
        return typed_fun

    if len(expr.params) != len(expected_lazy.params):
        raise TypeError(
            f"Function arity mismatch: expected {len(expected_lazy.params)} parameters, "
            f"got {len(expr.params)}",
            offset=expr.offset,
        )

    env.push_scope("fun")
    try:
        formal_params: list[TypedParam] = []
        q_params: list[QParam] = []

        for p, exp_p in zip(expr.params, expected_lazy.params):
            is_var = p.mode == ast.ParamMode.VAR
            is_out = p.mode == ast.ParamMode.OUT
            if p.type_annot is not None:
                p_type = elaborate_type(p.type_annot, env)
            else:
                p_type = exp_p.type_val

            p_sym = ValueSymbol(name=p.name, type_val=p_type, is_var=is_var, is_out=is_out)
            env.current_scope.declare_value(p_sym)
            formal_params.append(
                TypedParam(
                    name=p.name,
                    symbol=p_sym,
                    type_val=p_type,
                    is_var=is_var,
                    is_out=is_out,
                    offset=p.offset,
                )
            )
            q_params.append(QParam(name=p.name, type_val=p_type, is_var=is_var, is_out=is_out))

        body_typed = check_expr(expr.body, expected_lazy.result_type, env, loop_depth=0)
        fun_type = QFunType(params=tuple(q_params), result_type=expected_lazy.result_type)
        return TypedFun(
            params=tuple(formal_params),
            body=body_typed,
            type_val=fun_type,
            offset=expr.offset,
        )
    finally:
        env.pop_scope()


def _synth_app_expr(expr: ast.ExprApp, env: Environment, loop_depth: int) -> TypedExpr:
    """Synthesizes a function application, handling polymorphic type inference, var, and out params."""
    func_typed = synth_expr(expr.func, env, loop_depth)
    fn_type = func_typed.type_val.evaluate_lazily(env)

    # 1. Polymorphic function call (QAllType)
    if isinstance(fn_type, QAllType):
        return _synth_polymorphic_app(expr, func_typed, fn_type, env, loop_depth)

    # 2. Monomorphic function call (QFunType)
    if isinstance(fn_type, QFunType):
        return _synth_monomorphic_app(expr, func_typed, fn_type, env, loop_depth)

    raise TypeError(f"Cannot invoke non-function type '{fn_type}'", offset=expr.func.offset)


def _synth_monomorphic_app(
    expr: ast.ExprApp,
    func_typed: TypedExpr,
    fn_type: QFunType,
    env: Environment,
    loop_depth: int,
) -> TypedApp:
    """Synthesizes a monomorphic function application."""
    if len(expr.args) != len(fn_type.params):
        raise TypeError(
            f"Function expects {len(fn_type.params)} arguments, but got {len(expr.args)}",
            offset=expr.offset,
        )

    typed_args: list[TypedExpr] = []
    for arg, param in zip(expr.args, fn_type.params):
        if param.is_var:
            typed_arg = _check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=False)
            typed_args.append(typed_arg)
        elif param.is_out:
            typed_arg = _check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=True)
            typed_args.append(typed_arg)
        else:
            typed_arg = check_expr(arg, param.type_val, env, loop_depth)
            typed_args.append(typed_arg)

    return TypedApp(
        func=func_typed,
        args=tuple(typed_args),
        type_val=fn_type.result_type,
        offset=expr.offset,
    )


def _check_lvalue_arg(
    arg: ast.Expr,
    param_type: QType,
    env: Environment,
    loop_depth: int,
    is_out: bool,
) -> TypedExpr:
    """Validates that arg is a mutable lvalue location for var or out parameters."""
    if isinstance(arg, ast.ExprId):
        sym = env.lookup_value(arg.name)
        if sym is None:
            raise TypeError(f"Undefined variable '{arg.name}'", offset=arg.offset)
        if not sym.is_var:
            mode_name = "out" if is_out else "var"
            raise TypeError(
                f"Argument to '{mode_name}' parameter '{arg.name}' must be a mutable variable",
                offset=arg.offset,
            )

        if is_out:
            # Covariance: param_type <= sym.type_val
            if not is_subtype(param_type, sym.type_val, env):
                raise TypeError(
                    f"Type mismatch on out parameter: parameter type '{param_type}' is not a subtype "
                    f"of destination variable type '{sym.type_val}'",
                    offset=arg.offset,
                )
        else:
            # Invariance: param_type == sym.type_val
            if not (
                is_subtype(param_type, sym.type_val, env)
                and is_subtype(sym.type_val, param_type, env)
            ):
                raise TypeError(
                    f"Type mismatch on var parameter: expected exactly '{param_type}', but got "
                    f"variable of type '{sym.type_val}' (var parameters are invariant)",
                    offset=arg.offset,
                )

        return TypedVar(
            name=sym.name,
            symbol=sym,
            type_val=QVarType(sym.type_val),
            offset=arg.offset,
        )

    mode_name = "out" if is_out else "var"
    raise TypeError(
        f"Argument to '{mode_name}' parameter must be a mutable variable identifier",
        offset=arg.offset,
    )


def _synth_polymorphic_app(
    expr: ast.ExprApp,
    func_typed: TypedExpr,
    all_type: QAllType,
    env: Environment,
    loop_depth: int,
) -> TypedApp:
    """Instantiates a polymorphic function using metavariable inference and emits TypedTypeApp."""
    fn_body = all_type.body.evaluate_lazily(env)
    if not isinstance(fn_body, QFunType):
        raise TypeError(
            f"Polymorphic body is '{fn_body}', not a function type",
            offset=expr.offset,
        )

    if len(expr.args) != len(fn_body.params):
        raise TypeError(
            f"Function expects {len(fn_body.params)} arguments, but got {len(expr.args)}",
            offset=expr.offset,
        )

    # 1. Create fresh QTypeMeta metavariables for each quantifier
    meta_map: dict[int, QTypeMeta] = {}
    for q in all_type.quantifiers:
        meta_map[q.symbol_id] = QTypeMeta(name=f"?{q.name}")

    # 2. Substitute metavariables into the function signature
    instantiated_fn = fn_body.substitute(meta_map)
    assert isinstance(instantiated_fn, QFunType)

    # 3. Check arguments against instantiated parameter types
    typed_args: list[TypedExpr] = []
    for arg, param in zip(expr.args, instantiated_fn.params):
        if param.is_var or param.is_out:
            typed_arg = _check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=param.is_out)
        else:
            typed_arg = check_expr(arg, param.type_val, env, loop_depth)
        typed_args.append(typed_arg)

    # 4. Extract solved type arguments
    resolved_targs: list[QType] = []
    for q in all_type.quantifiers:
        meta = meta_map[q.symbol_id]
        solved = meta.prune()
        if solved is meta:
            solved = INT_TYPE
        resolved_targs.append(solved)

    # 5. Substitute solved types into instantiated function
    final_subst = {q.symbol_id: resolved_targs[i] for i, q in enumerate(all_type.quantifiers)}
    final_fn = instantiated_fn.substitute(final_subst)
    assert isinstance(final_fn, QFunType)

    # 6. Wrap func in TypedTypeApp
    typed_type_app = TypedTypeApp(
        func=func_typed,
        type_args=tuple(resolved_targs),
        type_val=final_fn,
        offset=expr.offset,
    )

    return TypedApp(
        func=typed_type_app,
        args=tuple(typed_args),
        type_val=final_fn.result_type,
        offset=expr.offset,
    )


# ============================================================================
# Helpers for Infix, Conditionals, Loops, and Blocks
# ============================================================================

def _synth_infix_expr(expr: ast.ExprInfix, env: Environment, loop_depth: int) -> TypedExpr:
    """Synthesizes an infix expression (assignment, logic, arithmetic, comparison)."""
    # 1. Assignment (lhs := rhs)
    if expr.op == ":=":
        return _synth_assignment(expr, env, loop_depth)

    # 2. Short-Circuit Logic (andif, orif) -> desugar to TypedIf
    if expr.op in ("andif", "orif"):
        left_typed = check_expr(expr.left, BOOL_TYPE, env, loop_depth)
        right_typed = check_expr(expr.right, BOOL_TYPE, env, loop_depth)
        if expr.op == "andif":
            return TypedIf(
                cond=left_typed,
                then_branch=right_typed,
                else_branch=TypedBool(value=False, offset=expr.offset),
                type_val=BOOL_TYPE,
                offset=expr.offset,
            )
        else:
            return TypedIf(
                cond=left_typed,
                then_branch=TypedBool(value=True, offset=expr.offset),
                else_branch=right_typed,
                type_val=BOOL_TYPE,
                offset=expr.offset,
            )

    # 3. Arithmetic Operators (+, -, *, /, mod)
    left_typed = synth_expr(expr.left, env, loop_depth)
    right_typed = synth_expr(expr.right, env, loop_depth)

    if expr.op in ("+", "-", "*", "/", "mod"):
        if left_typed.type_val == INT_TYPE:
            if right_typed.type_val != INT_TYPE:
                raise TypeError(
                    f"Operator '{expr.op}' requires both operands to be Int, but got "
                    f"'{left_typed.type_val}' and '{right_typed.type_val}' (no numeric coercion)",
                    offset=expr.offset,
                )
            return TypedInfix(
                left=left_typed,
                op=expr.op,
                right=right_typed,
                type_val=INT_TYPE,
                offset=expr.offset,
            )

        if left_typed.type_val == REAL_TYPE:
            if expr.op == "mod":
                raise TypeError("Operator 'mod' is not defined for Real", offset=expr.offset)
            if right_typed.type_val != REAL_TYPE:
                raise TypeError(
                    f"Operator '{expr.op}' requires both operands to be Real, but got "
                    f"'{left_typed.type_val}' and '{right_typed.type_val}' (no numeric coercion)",
                    offset=expr.offset,
                )
            return TypedInfix(
                left=left_typed,
                op=expr.op,
                right=right_typed,
                type_val=REAL_TYPE,
                offset=expr.offset,
            )

        raise TypeError(
            f"Arithmetic operator '{expr.op}' requires Int or Real operands, got '{left_typed.type_val}'",
            offset=expr.offset,
        )

    # 4. Relational Operators (<, <=, >, >=)
    if expr.op in ("<", "<=", ">", ">="):
        if (
            (left_typed.type_val == INT_TYPE and right_typed.type_val == INT_TYPE)
            or (left_typed.type_val == REAL_TYPE and right_typed.type_val == REAL_TYPE)
            or (left_typed.type_val == CHAR_TYPE and right_typed.type_val == CHAR_TYPE)
            or (left_typed.type_val == STRING_TYPE and right_typed.type_val == STRING_TYPE)
        ):
            return TypedInfix(
                left=left_typed,
                op=expr.op,
                right=right_typed,
                type_val=BOOL_TYPE,
                offset=expr.offset,
            )

        raise TypeError(
            f"Relational operator '{expr.op}' requires operands of the same comparable type "
            f"(Int, Real, Char, or String), got '{left_typed.type_val}' and '{right_typed.type_val}'",
            offset=expr.offset,
        )

    # 5. Equality Operators (==, <>, is, isnot)
    if expr.op in ("==", "<>", "is", "isnot"):
        if (
            is_subtype(left_typed.type_val, right_typed.type_val, env)
            or is_subtype(right_typed.type_val, left_typed.type_val, env)
        ):
            return TypedInfix(
                left=left_typed,
                op=expr.op,
                right=right_typed,
                type_val=BOOL_TYPE,
                offset=expr.offset,
            )

        raise TypeError(
            f"Equality operator '{expr.op}' requires operands of compatible types, got "
            f"'{left_typed.type_val}' and '{right_typed.type_val}'",
            offset=expr.offset,
        )

    raise TypeError(f"Unsupported infix operator '{expr.op}'", offset=expr.offset)


def _synth_assignment(expr: ast.ExprInfix, env: Environment, loop_depth: int) -> TypedAssign:
    """Synthesizes an assignment expression: lhs := rhs."""
    if isinstance(expr.left, ast.ExprId):
        sym = env.lookup_value(expr.left.name)
        if sym is None:
            raise TypeError(f"Undefined variable '{expr.left.name}'", offset=expr.left.offset)
        if not sym.is_var:
            raise TypeError(f"Cannot assign to immutable variable '{expr.left.name}'", offset=expr.left.offset)

        target_node = TypedVar(
            name=sym.name,
            symbol=sym,
            type_val=QVarType(sym.type_val),
            offset=expr.left.offset,
        )
        rhs_typed = check_expr(expr.right, sym.type_val, env, loop_depth)
        return TypedAssign(target=target_node, value=rhs_typed, offset=expr.offset)

    raise TypeError("Assignment target must be a mutable variable or field", offset=expr.left.offset)


def _synth_if_expr(expr: ast.ExprIf, env: Environment, loop_depth: int) -> TypedIf:
    """Synthesizes an if expression."""
    cond_typed = check_expr(expr.cond, BOOL_TYPE, env, loop_depth)

    # If without else branch: ignores return value of then branch and returns Ok
    if expr.else_branch is None and not expr.elsifs:
        then_typed = synth_expr(expr.then_branch, env, loop_depth)
        then_body = TypedBlock(
            bindings=(TypedExprStmt(expr=then_typed, offset=then_typed.offset),),
            result=TypedOk(offset=then_typed.offset),
            type_val=OK_TYPE,
            offset=then_typed.offset,
        )
        return TypedIf(
            cond=cond_typed,
            then_branch=then_body,
            else_branch=TypedOk(offset=expr.offset),
            type_val=OK_TYPE,
            offset=expr.offset,
        )

    # Desugar elsif branches right-to-left into nested if expressions
    desugared_else: ast.Expr = expr.else_branch if expr.else_branch else ast.ExprOk(offset=expr.offset)
    for elsif_cond, elsif_then in reversed(expr.elsifs):
        desugared_else = ast.ExprIf(
            cond=elsif_cond,
            then_branch=elsif_then,
            elsifs=(),
            else_branch=desugared_else,
            offset=elsif_cond.offset,
        )

    then_typed = synth_expr(expr.then_branch, env, loop_depth)
    else_typed = synth_expr(desugared_else, env, loop_depth)

    # Find common supertype join
    if is_subtype(then_typed.type_val, else_typed.type_val, env):
        join_type = else_typed.type_val
    elif is_subtype(else_typed.type_val, then_typed.type_val, env):
        join_type = then_typed.type_val
    else:
        raise TypeError(
            f"Cannot find common supertype for conditional branches '{then_typed.type_val}' "
            f"and '{else_typed.type_val}'",
            offset=expr.offset,
        )

    return TypedIf(
        cond=cond_typed,
        then_branch=then_typed,
        else_branch=else_typed,
        type_val=join_type,
        offset=expr.offset,
    )


def _check_if_expr(
    expr: ast.ExprIf,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedIf:
    """Checks an if expression against an expected QType."""
    cond_typed = check_expr(expr.cond, BOOL_TYPE, env, loop_depth)

    # Desugar elsif branches into nested if expressions
    desugared_else: ast.Expr = expr.else_branch if expr.else_branch else ast.ExprOk(offset=expr.offset)
    for elsif_cond, elsif_then in reversed(expr.elsifs):
        desugared_else = ast.ExprIf(
            cond=elsif_cond,
            then_branch=elsif_then,
            elsifs=(),
            else_branch=desugared_else,
            offset=elsif_cond.offset,
        )

    then_typed = check_expr(expr.then_branch, expected_type, env, loop_depth)
    else_typed = check_expr(desugared_else, expected_type, env, loop_depth)

    return TypedIf(
        cond=cond_typed,
        then_branch=then_typed,
        else_branch=else_typed,
        type_val=expected_type,
        offset=expr.offset,
    )


def _synth_for_expr(expr: ast.ExprFor, env: Environment, loop_depth: int) -> TypedFor:
    """Synthesizes a for loop expression: for i = start upto/downto stop do body end."""
    start_typed = check_expr(expr.start, INT_TYPE, env, loop_depth)
    stop_typed = check_expr(expr.stop, INT_TYPE, env, loop_depth)

    env.push_scope(f"for_{expr.var_name}")
    try:
        loop_var_sym = ValueSymbol(name=expr.var_name, type_val=INT_TYPE, is_var=False)
        env.current_scope.declare_value(loop_var_sym)
        body_typed = synth_expr(expr.body, env, loop_depth + 1)
    finally:
        env.pop_scope()

    return TypedFor(
        var_name=expr.var_name,
        symbol=loop_var_sym,
        start=start_typed,
        is_downto=expr.is_downto,
        stop=stop_typed,
        body=body_typed,
        offset=expr.offset,
    )


def _synth_block_expr(expr: ast.ExprBlock, env: Environment, loop_depth: int) -> TypedBlock:
    """Synthesizes a scoped block expression: begin bindings... result end."""
    env.push_scope("block")
    try:
        typed_bindings: list[TypedBinding] = []
        for binding in expr.bindings:
            typed_b = _elaborate_binding(binding, env, loop_depth)
            typed_bindings.append(typed_b)

        # In Quest, if the final statement in a block is an expression statement, its value is the block result
        if typed_bindings and isinstance(typed_bindings[-1], TypedExprStmt):
            last_stmt = typed_bindings.pop()
            assert isinstance(last_stmt, TypedExprStmt)
            result_expr = last_stmt.expr
            result_type = result_expr.type_val
        else:
            result_expr = TypedOk(offset=expr.offset)
            result_type = OK_TYPE

        return TypedBlock(
            bindings=tuple(typed_bindings),
            result=result_expr,
            type_val=result_type,
            offset=expr.offset,
        )
    finally:
        env.pop_scope()


def _check_block_expr(
    expr: ast.ExprBlock,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedBlock:
    """Checks a scoped block expression against an expected QType."""
    env.push_scope("block")
    try:
        typed_bindings: list[TypedBinding] = []
        for binding in expr.bindings[:-1]:
            typed_b = _elaborate_binding(binding, env, loop_depth)
            typed_bindings.append(typed_b)

        if expr.bindings:
            last_binding = expr.bindings[-1]
            if isinstance(last_binding, ast.ExprStmt):
                result_expr = check_expr(last_binding.expr, expected_type, env, loop_depth)
            else:
                typed_b = _elaborate_binding(last_binding, env, loop_depth)
                typed_bindings.append(typed_b)
                if not is_subtype(OK_TYPE, expected_type, env):
                    raise TypeError(
                        f"Block ending with declaration has type Ok, not expected type '{expected_type}'",
                        offset=expr.offset,
                    )
                result_expr = TypedOk(offset=expr.offset)
        else:
            if not is_subtype(OK_TYPE, expected_type, env):
                raise TypeError(
                    f"Empty block has type Ok, not expected type '{expected_type}'",
                    offset=expr.offset,
                )
            result_expr = TypedOk(offset=expr.offset)

        return TypedBlock(
            bindings=tuple(typed_bindings),
            result=result_expr,
            type_val=expected_type,
            offset=expr.offset,
        )
    finally:
        env.pop_scope()


def _elaborate_binding(binding: ast.BindingNode, env: Environment, loop_depth: int) -> TypedBinding:
    """Elaborates a single binding or statement inside a block or module."""
    if isinstance(binding, ast.ExprStmt):
        typed_e = synth_expr(binding.expr, env, loop_depth)
        return TypedExprStmt(expr=typed_e, offset=binding.offset)

    if isinstance(binding, ast.LetValueBinding):
        # Desugar parameter shorthand let f(x: Int): Int = body into ExprFun
        if binding.params:
            fn_expr = ast.ExprFun(
                params=binding.params,
                return_type=binding.type_annot,
                body=binding.value,
                offset=binding.offset,
            )
            if binding.is_rec:
                # Pre-declare recursive function signature in scope
                param_types = tuple(
                    elaborate_type(p.type_annot, env) if p.type_annot else DYNAMIC_TYPE
                    for p in binding.params
                )
                ret_type = elaborate_type(binding.type_annot, env) if binding.type_annot else DYNAMIC_TYPE
                q_params = tuple(
                    QParam(
                        name=p.name,
                        type_val=param_types[i],
                        is_var=(p.mode == ast.ParamMode.VAR),
                        is_out=(p.mode == ast.ParamMode.OUT),
                    )
                    for i, p in enumerate(binding.params)
                )
                rec_fn_type = QFunType(params=q_params, result_type=ret_type)
                rec_sym = ValueSymbol(name=binding.name, type_val=rec_fn_type)
                env.current_scope.declare_value(rec_sym)

                typed_val = check_expr(fn_expr, rec_fn_type, env, loop_depth=0)
                return TypedLetValue(
                    name=binding.name,
                    value=typed_val,
                    symbol=rec_sym,
                    is_rec=True,
                    offset=binding.offset,
                )
            else:
                if binding.type_annot is not None:
                    expected = elaborate_type(binding.type_annot, env)
                    typed_val = check_expr(fn_expr, expected, env, loop_depth)
                    val_type = expected
                else:
                    typed_val = synth_expr(fn_expr, env, loop_depth)
                    val_type = typed_val.type_val

                sym = ValueSymbol(name=binding.name, type_val=val_type, is_var=binding.is_var)
                env.current_scope.declare_value(sym)
                return TypedLetValue(
                    name=binding.name,
                    value=typed_val,
                    symbol=sym,
                    is_rec=False,
                    offset=binding.offset,
                )

        if binding.type_annot is not None:
            expected = elaborate_type(binding.type_annot, env)
            typed_val = check_expr(binding.value, expected, env, loop_depth)
            val_type = expected
        else:
            typed_val = synth_expr(binding.value, env, loop_depth)
            val_type = typed_val.type_val

        sym = ValueSymbol(name=binding.name, type_val=val_type, is_var=binding.is_var)
        env.current_scope.declare_value(sym)
        return TypedLetValue(
            name=binding.name,
            value=typed_val,
            symbol=sym,
            is_rec=binding.is_rec,
            offset=binding.offset,
        )

    if isinstance(binding, (ast.LetTypeBinding, ast.DefTypeBinding)):
        sym = elaborate_type_binding(binding, env)
        return TypedLetType(name=binding.name, symbol=sym, offset=binding.offset)

    if isinstance(binding, ast.DefKindBinding):
        k_sym = elaborate_kind_binding(binding, env)
        return TypedDefKind(name=binding.name, symbol=k_sym, offset=binding.offset)

    raise TypeError(f"Unsupported binding '{binding}'", offset=getattr(binding, "offset", 0))
