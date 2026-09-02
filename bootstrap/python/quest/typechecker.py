"""Quest Term Elaboration and Bidirectional Typechecker (Phases 2, 3, 4 & 5)."""

from __future__ import annotations

from typing import Any, Optional, Union

import quest.ast as ast
from quest.types import (
    BOOL_TYPE,
    BOTTOM_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QAllType,
    QArrayType,
    QBottomType,
    QExceptionType,
    QFunType,
    QKind,
    QOptionField,
    QOptionType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QType,
    QTypeMeta,
    QTypeVar,
    QVarType,
    QVariantField,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    is_subkind,
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
    TypedArray,
    TypedArrayRep,
    TypedAssign,
    TypedBinding,
    TypedBlock,
    TypedBool,
    TypedCase,
    TypedCaseBranch,
    TypedChar,
    TypedDefKind,
    TypedDerefCell,
    TypedException,
    TypedExit,
    TypedExpr,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedIndex,
    TypedIndexAssign,
    TypedInfix,
    TypedInspect,
    TypedInspectBranch,
    TypedInterface,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedModule,
    TypedOk,
    TypedOption,
    TypedParam,
    TypedProgram,
    TypedRaise,
    TypedReal,
    TypedRecord,
    TypedRecordField,
    TypedSelect,
    TypedString,
    TypedTry,
    TypedTryBranch,
    TypedTuple,
    TypedTypeApp,
    TypedVar,
    TypedVarCell,
    TypedVariant,
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

    # 4. Record expression: check fields against expected record type
    if isinstance(expr, ast.ExprRecord):
        return _check_record_expr(expr, expected_type, env, loop_depth)

    # 5. Tuple expression: check elements against expected tuple type
    if isinstance(expr, ast.ExprTuple):
        return _check_tuple_expr(expr, expected_type, env, loop_depth)

    # 6. Case expression: check all branches against expected_type
    if isinstance(expr, ast.ExprCase):
        return _check_case_expr(expr, expected_type, env, loop_depth)

    # 7. Array expressions: check elements against expected array element type
    if isinstance(expr, ast.ExprArray):
        return _check_array_expr(expr, expected_type, env, loop_depth)

    if isinstance(expr, ast.ExprArrayRep):
        return _check_array_rep_expr(expr, expected_type, env, loop_depth)

    # 8. Phase 5: Raise expression (divergent control flow checks against any expected type)
    if isinstance(expr, ast.ExprRaise):
        return _check_raise_expr(expr, expected_type, env, loop_depth)

    # 9. Phase 5: Try expression
    if isinstance(expr, ast.ExprTry):
        return _check_try_expr(expr, expected_type, env, loop_depth)

    # 10. Phase 5: Inspect expression
    if isinstance(expr, ast.ExprInspect):
        return _check_inspect_expr(expr, expected_type, env, loop_depth)

    # 11. Subsumption: synthesize minimal type and check subtyping (S <= T)
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

    # --- Aggregates (Records, Tuples, Options, Variants, Arrays) ---
    if isinstance(expr, ast.ExprRecord):
        return _synth_record_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprTuple):
        return _synth_tuple_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprSelect):
        return _synth_select_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprOption):
        return _synth_option_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprVariant):
        return _synth_variant_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprCase):
        return _synth_case_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprArray):
        return _synth_array_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprArrayRep):
        return _synth_array_rep_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprIndex):
        return _synth_index_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprIndexAssign):
        return _synth_index_assign_expr(expr, env, loop_depth)

    # --- Exceptions & Dynamic (Phase 5) ---
    if isinstance(expr, ast.ExprException):
        return _synth_exception_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprRaise):
        return _synth_raise_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprTry):
        return _synth_try_expr(expr, env, loop_depth)

    if isinstance(expr, ast.ExprInspect):
        return _synth_inspect_expr(expr, env, loop_depth)

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
            if not is_subtype(param_type, sym.type_val, env):
                raise TypeError(
                    f"Type mismatch on out parameter: parameter type '{param_type}' is not a subtype "
                    f"of destination variable type '{sym.type_val}'",
                    offset=arg.offset,
                )
        else:
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

    meta_map: dict[int, QTypeMeta] = {}
    for q in all_type.quantifiers:
        meta_map[q.symbol_id] = QTypeMeta(name=f"?{q.name}")

    instantiated_fn = fn_body.substitute(meta_map)
    assert isinstance(instantiated_fn, QFunType)

    typed_args: list[TypedExpr] = []
    for arg, param in zip(expr.args, instantiated_fn.params):
        if param.is_var or param.is_out:
            typed_arg = _check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=param.is_out)
        else:
            typed_arg = check_expr(arg, param.type_val, env, loop_depth)
        typed_args.append(typed_arg)

    resolved_targs: list[QType] = []
    for q in all_type.quantifiers:
        meta = meta_map[q.symbol_id]
        solved = meta.prune()
        if solved is meta:
            solved = INT_TYPE
        resolved_targs.append(solved)

    final_subst = {q.symbol_id: resolved_targs[i] for i, q in enumerate(all_type.quantifiers)}
    final_fn = instantiated_fn.substitute(final_subst)
    assert isinstance(final_fn, QFunType)

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
# Phase 4 & 5 Helpers: Aggregates, Options, Variants, Arrays, Exceptions & Dynamic
# ============================================================================

def _synth_record_expr(expr: ast.ExprRecord, env: Environment, loop_depth: int) -> TypedRecord:
    """Synthesizes a record constructor: record [var] x = e1 ... end."""
    field_typeds: list[TypedRecordField] = []
    q_fields: list[QRecordField] = []

    for b in expr.fields:
        val_typed = synth_expr(b.value, env, loop_depth)
        field_typeds.append(
            TypedRecordField(name=b.name, value=val_typed, is_var=b.is_var, offset=b.offset)
        )
        q_fields.append(QRecordField(name=b.name, type_val=val_typed.type_val, is_var=b.is_var))

    rec_type = QRecordType(fields=tuple(q_fields))
    return TypedRecord(fields=tuple(field_typeds), type_val=rec_type, offset=expr.offset)


def _check_record_expr(
    expr: ast.ExprRecord,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedRecord:
    """Checks a record constructor against an expected record type."""
    expected_lazy = expected_type.evaluate_lazily(env)
    if not isinstance(expected_lazy, QRecordType):
        typed_rec = _synth_record_expr(expr, env, loop_depth)
        if not is_subtype(typed_rec.type_val, expected_type, env):
            raise TypeError(
                f"Record type '{typed_rec.type_val}' is not a subtype of expected '{expected_type}'",
                offset=expr.offset,
            )
        return typed_rec

    field_map = {b.name: b for b in expr.fields}
    field_typeds: list[TypedRecordField] = []

    for exp_f in expected_lazy.fields:
        if exp_f.name not in field_map:
            raise TypeError(
                f"Record constructor missing required field '{exp_f.name}' of type '{exp_f.type_val}'",
                offset=expr.offset,
            )
        b = field_map[exp_f.name]
        if exp_f.is_var:
            if not b.is_var:
                raise TypeError(
                    f"Field '{exp_f.name}' in record must be declared mutable (var)",
                    offset=b.offset,
                )
            val_typed = check_expr(b.value, exp_f.type_val, env, loop_depth)
            if not is_type_equal(val_typed.type_val, exp_f.type_val, env):
                raise TypeError(
                    f"Mutable record field '{exp_f.name}' is invariant; expected '{exp_f.type_val}', "
                    f"got '{val_typed.type_val}'",
                    offset=b.offset,
                )
        else:
            val_typed = check_expr(b.value, exp_f.type_val, env, loop_depth)

        field_typeds.append(
            TypedRecordField(name=b.name, value=val_typed, is_var=b.is_var, offset=b.offset)
        )

    for b in expr.fields:
        if expected_lazy.get_field(b.name) is None:
            extra_val = synth_expr(b.value, env, loop_depth)
            field_typeds.append(
                TypedRecordField(name=b.name, value=extra_val, is_var=b.is_var, offset=b.offset)
            )

    return TypedRecord(fields=tuple(field_typeds), type_val=expected_lazy, offset=expr.offset)


def _synth_tuple_expr(expr: ast.ExprTuple, env: Environment, loop_depth: int) -> TypedTuple:
    """Synthesizes a tuple constructor: tuple [name =] e1 ... end."""
    elem_typeds: list[TypedExpr] = []
    q_fields: list[QTupleField] = []

    for b in expr.fields:
        val_typed = synth_expr(b.value, env, loop_depth)
        elem_typeds.append(val_typed)
        q_fields.append(QTupleField(name=b.name, type_val=val_typed.type_val))

    tuple_type = QTupleType(tuple(q_fields))
    return TypedTuple(elements=tuple(elem_typeds), type_val=tuple_type, offset=expr.offset)


def _check_tuple_expr(
    expr: ast.ExprTuple,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedTuple:
    """Checks a tuple constructor against an expected tuple type."""
    expected_lazy = expected_type.evaluate_lazily(env)
    if not isinstance(expected_lazy, QTupleType):
        typed_tup = _synth_tuple_expr(expr, env, loop_depth)
        if not is_subtype(typed_tup.type_val, expected_type, env):
            raise TypeError(
                f"Tuple type '{typed_tup.type_val}' is not a subtype of expected '{expected_type}'",
                offset=expr.offset,
            )
        return typed_tup

    if len(expr.fields) != len(expected_lazy.fields):
        raise TypeError(
            f"Tuple arity mismatch: expected {len(expected_lazy.fields)} components, got {len(expr.fields)}",
            offset=expr.offset,
        )

    elem_typeds: list[TypedExpr] = []
    for b, exp_f in zip(expr.fields, expected_lazy.fields):
        if exp_f.name is not None and b.name is not None and b.name != exp_f.name:
            raise TypeError(
                f"Tuple field name mismatch: expected '{exp_f.name}', got '{b.name}'",
                offset=b.offset,
            )
        val_typed = check_expr(b.value, exp_f.type_val, env, loop_depth)
        elem_typeds.append(val_typed)

    return TypedTuple(elements=tuple(elem_typeds), type_val=expected_lazy, offset=expr.offset)


def _synth_select_expr(expr: ast.ExprSelect, env: Environment, loop_depth: int) -> TypedSelect:
    """Synthesizes a field selection on a record, tuple, or module: target.field."""
    if isinstance(expr.target, ast.ExprId):
        module_scope = env.lookup_module(expr.target.name)
        if module_scope is not None:
            val_sym = module_scope.lookup_value_local(expr.field)
            if val_sym is None:
                raise TypeError(
                    f"Module '{expr.target.name}' has no exported member '{expr.field}'",
                    offset=expr.offset,
                )
            target_typed = TypedVar(
                name=expr.target.name,
                symbol=env.lookup_value(expr.target.name) or ValueSymbol(name=expr.target.name, type_val=OK_TYPE),
                type_val=OK_TYPE,
                offset=expr.target.offset,
            )
            return TypedSelect(
                target=target_typed,
                field=expr.field,
                type_val=val_sym.type_val,
                offset=expr.offset,
            )

    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)

    if isinstance(target_type, QRecordType):
        rec_f = target_type.get_field(expr.field)
        if rec_f is None:
            raise TypeError(
                f"Record type '{target_type}' has no field named '{expr.field}'",
                offset=expr.offset,
            )
        return TypedSelect(target=target_typed, field=expr.field, type_val=rec_f.type_val, offset=expr.offset)

    if isinstance(target_type, QTupleType):
        tup_f = target_type.get_field(expr.field)
        if tup_f is None:
            raise TypeError(
                f"Tuple type '{target_type}' has no field named '{expr.field}'",
                offset=expr.offset,
            )
        return TypedSelect(target=target_typed, field=expr.field, type_val=tup_f.type_val, offset=expr.offset)

    raise TypeError(
        f"Cannot select field '{expr.field}' from non-record/tuple type '{target_type}'",
        offset=expr.offset,
    )


def _synth_option_expr(expr: ast.ExprOption, env: Environment, loop_depth: int) -> TypedOption:
    """Synthesizes an option injection: option tag [with payload] of OptionType end."""
    opt_type = elaborate_type(expr.option_type, env)
    opt_lazy = opt_type.evaluate_lazily(env)
    if not isinstance(opt_lazy, QOptionType):
        raise TypeError(f"Expected option type in 'of' clause, got '{opt_type}'", offset=expr.offset)

    opt_field = opt_lazy.get_option(expr.tag)
    if opt_field is None:
        raise TypeError(
            f"Option type '{opt_type}' has no variant tag '{expr.tag}'",
            offset=expr.offset,
        )

    if opt_field.payload_type is not None:
        if expr.payload is None:
            raise TypeError(
                f"Option variant '{expr.tag}' requires a payload of type '{opt_field.payload_type}'",
                offset=expr.offset,
            )
        payload_typed = check_expr(expr.payload, opt_field.payload_type, env, loop_depth)
    else:
        if expr.payload is not None:
            raise TypeError(f"Option variant '{expr.tag}' does not accept a payload", offset=expr.offset)
        payload_typed = None

    return TypedOption(tag=expr.tag, type_val=opt_type, payload=payload_typed, offset=expr.offset)


def _synth_variant_expr(expr: ast.ExprVariant, env: Environment, loop_depth: int) -> TypedVariant:
    """Synthesizes a variant injection: variant tag [with payload] of VariantType end."""
    var_type = elaborate_type(expr.variant_type, env)
    var_lazy = var_type.evaluate_lazily(env)
    if not isinstance(var_lazy, QVariantType):
        raise TypeError(f"Expected variant type in 'of' clause, got '{var_type}'", offset=expr.offset)

    var_field = var_lazy.get_variant(expr.tag)
    if var_field is None:
        raise TypeError(
            f"Variant type '{var_type}' has no tag '{expr.tag}'",
            offset=expr.offset,
        )

    if var_field.type_val is not None:
        if expr.payload is None:
            raise TypeError(
                f"Variant tag '{expr.tag}' requires a payload of type '{var_field.type_val}'",
                offset=expr.offset,
            )
        payload_typed = check_expr(expr.payload, var_field.type_val, env, loop_depth)
    else:
        if expr.payload is not None:
            raise TypeError(f"Variant tag '{expr.tag}' does not accept a payload", offset=expr.offset)
        payload_typed = None

    return TypedVariant(tag=expr.tag, type_val=var_type, payload=payload_typed, offset=expr.offset)


def _synth_case_expr(expr: ast.ExprCase, env: Environment, loop_depth: int) -> TypedCase:
    """Synthesizes a case expression over an option or variant target."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)

    available_tags, typed_branches = _elaborate_case_branches(
        expr, target_type, expected_type=None, env=env, loop_depth=loop_depth
    )

    if expr.else_branch is not None:
        else_typed: Optional[TypedExpr] = synth_expr(expr.else_branch, env, loop_depth)
    else:
        else_typed = None

    branch_types = [b.body.type_val for b in typed_branches]
    if else_typed is not None:
        branch_types.append(else_typed.type_val)

    if not branch_types:
        return TypedCase(
            target=target_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=OK_TYPE,
            offset=expr.offset,
        )

    join_type = branch_types[0]
    for bt in branch_types[1:]:
        if is_subtype(join_type, bt, env):
            join_type = bt
        elif is_subtype(bt, join_type, env):
            pass
        else:
            raise TypeError(
                f"Cannot find common supertype join for case branch types '{join_type}' and '{bt}'",
                offset=expr.offset,
            )

    return TypedCase(
        target=target_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=join_type,
        offset=expr.offset,
    )


def _check_case_expr(
    expr: ast.ExprCase,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedCase:
    """Checks a case expression against an expected QType."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)

    available_tags, typed_branches = _elaborate_case_branches(
        expr, target_type, expected_type=expected_type, env=env, loop_depth=loop_depth
    )

    if expr.else_branch is not None:
        else_typed: Optional[TypedExpr] = check_expr(expr.else_branch, expected_type, env, loop_depth)
    else:
        else_typed = None

    return TypedCase(
        target=target_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=expected_type,
        offset=expr.offset,
    )


def _elaborate_case_branches(
    expr: ast.ExprCase,
    target_type: QType,
    expected_type: Optional[QType],
    env: Environment,
    loop_depth: int,
) -> tuple[dict[str, Optional[QType]], list[TypedCaseBranch]]:
    """Validates tags, binders, exhaustiveness, and elaborates typed case branches."""
    if isinstance(target_type, QOptionType):
        available_tags = {opt.name: opt.payload_type for opt in target_type.options}
    elif isinstance(target_type, QVariantType):
        available_tags = {var.name: var.type_val for var in target_type.variants}
    else:
        raise TypeError(
            f"Case target must have Option or Variant type, got '{target_type}'",
            offset=expr.target.offset,
        )

    covered_tags: set[str] = set()
    typed_branches: list[TypedCaseBranch] = []

    for branch in expr.branches:
        for tag in branch.tags:
            if tag not in available_tags:
                raise TypeError(
                    f"Tag '{tag}' is not a valid variant of type '{target_type}'",
                    offset=branch.offset,
                )
            covered_tags.add(tag)

        if branch.binder is not None:
            first_payload = available_tags[branch.tags[0]]
            if first_payload is None:
                raise TypeError(
                    f"Tag '{branch.tags[0]}' has no payload to bind to '{branch.binder}'",
                    offset=branch.offset,
                )

            if branch.binder_type is not None:
                binder_t = elaborate_type(branch.binder_type, env)
                if not is_subtype(first_payload, binder_t, env):
                    raise TypeError(
                        f"Binder '{branch.binder}' type '{binder_t}' is not compatible with payload '{first_payload}'",
                        offset=branch.offset,
                    )
            else:
                binder_t = first_payload

            env.push_scope(f"case_{branch.binder}")
            try:
                binder_sym = ValueSymbol(name=branch.binder, type_val=binder_t, is_var=False)
                env.current_scope.declare_value(binder_sym)
                if expected_type is not None:
                    body_typed = check_expr(branch.body, expected_type, env, loop_depth)
                else:
                    body_typed = synth_expr(branch.body, env, loop_depth)
            finally:
                env.pop_scope()
        else:
            binder_sym = None
            if expected_type is not None:
                body_typed = check_expr(branch.body, expected_type, env, loop_depth)
            else:
                body_typed = synth_expr(branch.body, env, loop_depth)

        typed_branches.append(
            TypedCaseBranch(
                tags=branch.tags,
                body=body_typed,
                binder=binder_sym,
                offset=branch.offset,
            )
        )

    if expr.else_branch is None:
        missing = set(available_tags.keys()) - covered_tags
        if missing:
            missing_str = ", ".join(sorted(missing))
            raise TypeError(
                f"Non-exhaustive case expression missing tags: {missing_str}",
                offset=expr.offset,
            )

    return available_tags, typed_branches


def _synth_array_expr(expr: ast.ExprArray, env: Environment, loop_depth: int) -> TypedArray:
    """Synthesizes an explicit array literal: array of e1 e2 ... end."""
    if not expr.elements:
        raise TypeError(
            "Cannot infer element type of empty array; type annotation required",
            offset=expr.offset,
        )

    elem_typeds = [synth_expr(e, env, loop_depth) for e in expr.elements]
    join_type = elem_typeds[0].type_val
    for et in elem_typeds[1:]:
        if is_subtype(join_type, et.type_val, env):
            join_type = et.type_val
        elif is_subtype(et.type_val, join_type, env):
            pass
        else:
            raise TypeError(
                f"Incompatible array element types '{join_type}' and '{et.type_val}'",
                offset=expr.offset,
            )

    return TypedArray(
        elements=tuple(elem_typeds),
        type_val=QArrayType(element_type=join_type),
        offset=expr.offset,
    )


def _check_array_expr(
    expr: ast.ExprArray,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedArray:
    """Checks an array literal against an expected array type."""
    expected_lazy = expected_type.evaluate_lazily(env)
    if not isinstance(expected_lazy, QArrayType):
        typed_arr = _synth_array_expr(expr, env, loop_depth)
        if not is_subtype(typed_arr.type_val, expected_type, env):
            raise TypeError(
                f"Array type '{typed_arr.type_val}' is not a subtype of expected '{expected_type}'",
                offset=expr.offset,
            )
        return typed_arr

    elem_typeds = [
        check_expr(e, expected_lazy.element_type, env, loop_depth) for e in expr.elements
    ]
    return TypedArray(elements=tuple(elem_typeds), type_val=expected_lazy, offset=expr.offset)


def _synth_array_rep_expr(expr: ast.ExprArrayRep, env: Environment, loop_depth: int) -> TypedArrayRep:
    """Synthesizes an array repetition: array of (count init) end."""
    count_typed = check_expr(expr.count, INT_TYPE, env, loop_depth)
    init_typed = synth_expr(expr.init_val, env, loop_depth)
    return TypedArrayRep(
        count=count_typed,
        init_val=init_typed,
        type_val=QArrayType(element_type=init_typed.type_val),
        offset=expr.offset,
    )


def _check_array_rep_expr(
    expr: ast.ExprArrayRep,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedArrayRep:
    """Checks an array repetition against an expected array type."""
    expected_lazy = expected_type.evaluate_lazily(env)
    if not isinstance(expected_lazy, QArrayType):
        typed_rep = _synth_array_rep_expr(expr, env, loop_depth)
        if not is_subtype(typed_rep.type_val, expected_type, env):
            raise TypeError(
                f"Array type '{typed_rep.type_val}' is not a subtype of expected '{expected_type}'",
                offset=expr.offset,
            )
        return typed_rep

    count_typed = check_expr(expr.count, INT_TYPE, env, loop_depth)
    init_typed = check_expr(expr.init_val, expected_lazy.element_type, env, loop_depth)
    return TypedArrayRep(
        count=count_typed,
        init_val=init_typed,
        type_val=expected_lazy,
        offset=expr.offset,
    )


def _synth_index_expr(expr: ast.ExprIndex, env: Environment, loop_depth: int) -> TypedIndex:
    """Synthesizes an array indexing expression: arr[i]."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)
    if not isinstance(target_type, QArrayType):
        raise TypeError(f"Cannot index non-array type '{target_type}'", offset=expr.offset)

    idx_typed = check_expr(expr.index, INT_TYPE, env, loop_depth)
    return TypedIndex(
        target=target_typed,
        index=idx_typed,
        type_val=target_type.element_type,
        offset=expr.offset,
    )


def _synth_index_assign_expr(
    expr: ast.ExprIndexAssign,
    env: Environment,
    loop_depth: int,
) -> TypedIndexAssign:
    """Synthesizes an array element assignment: arr[i] := val."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)
    if not isinstance(target_type, QArrayType):
        raise TypeError(
            f"Cannot assign to index of non-array type '{target_type}'",
            offset=expr.offset,
        )

    idx_typed = check_expr(expr.index, INT_TYPE, env, loop_depth)
    val_typed = check_expr(expr.value, target_type.element_type, env, loop_depth)
    return TypedIndexAssign(
        target=target_typed,
        index=idx_typed,
        value=val_typed,
        type_val=OK_TYPE,
        offset=expr.offset,
    )


# ============================================================================
# Phase 5: Exceptions, Dynamic Types, and Type Inspection Helpers
# ============================================================================

def _synth_exception_expr(expr: ast.ExprException, env: Environment, loop_depth: int) -> TypedException:
    """Synthesizes an exception constructor: exception Name [: PayloadType] end."""
    payload_type = elaborate_type(expr.type_annot, env) if expr.type_annot else OK_TYPE
    exc_type = QExceptionType(payload_type=payload_type)
    sym = ValueSymbol(name=expr.name, type_val=exc_type, is_var=False)
    env.current_scope.declare_value(sym)
    return TypedException(
        name=expr.name,
        payload_type=payload_type,
        type_val=exc_type,
        offset=expr.offset,
    )


def _check_raise_expr(
    expr: ast.ExprRaise,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedRaise:
    """Checks a raise expression against any expected type (divergent control flow)."""
    exc_typed = synth_expr(expr.exc, env, loop_depth)
    exc_type = exc_typed.type_val.evaluate_lazily(env)
    if not isinstance(exc_type, QExceptionType):
        raise TypeError(f"Cannot raise non-exception type '{exc_type}'", offset=expr.exc.offset)

    if expr.payload is not None:
        payload_typed = check_expr(expr.payload, exc_type.payload_type, env, loop_depth)
    else:
        if exc_type.payload_type != OK_TYPE:
            raise TypeError(
                f"Exception '{exc_type}' requires a payload of type '{exc_type.payload_type}'",
                offset=expr.offset,
            )
        payload_typed = None

    return TypedRaise(
        exc=exc_typed,
        payload=payload_typed,
        type_val=expected_type,
        offset=expr.offset,
    )


def _synth_raise_expr(expr: ast.ExprRaise, env: Environment, loop_depth: int) -> TypedRaise:
    """Synthesizes a raise expression. Defaults to Ok if no declared type is present."""
    exc_typed = synth_expr(expr.exc, env, loop_depth)
    exc_type = exc_typed.type_val.evaluate_lazily(env)
    if not isinstance(exc_type, QExceptionType):
        raise TypeError(f"Cannot raise non-exception type '{exc_type}'", offset=expr.exc.offset)

    if expr.payload is not None:
        payload_typed = check_expr(expr.payload, exc_type.payload_type, env, loop_depth)
    else:
        if exc_type.payload_type != OK_TYPE:
            raise TypeError(
                f"Exception '{exc_type}' requires a payload of type '{exc_type.payload_type}'",
                offset=expr.offset,
            )
        payload_typed = None

    if expr.as_type is not None:
        res_type = elaborate_type(expr.as_type, env)
    else:
        res_type = OK_TYPE

    return TypedRaise(
        exc=exc_typed,
        payload=payload_typed,
        type_val=res_type,
        offset=expr.offset,
    )


def _check_try_expr(
    expr: ast.ExprTry,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedTry:
    """Checks a try expression against an expected QType."""
    body_typed = check_expr(expr.body, expected_type, env, loop_depth)
    typed_branches: list[TypedTryBranch] = []

    for branch in expr.branches:
        exc_typed = synth_expr(branch.exc_pattern, env, loop_depth)
        exc_type = exc_typed.type_val.evaluate_lazily(env)
        if not isinstance(exc_type, QExceptionType):
            raise TypeError(
                f"Pattern in when branch must be an exception, got '{exc_type}'",
                offset=branch.offset,
            )

        if branch.binder is not None:
            env.push_scope(f"try_{branch.binder}")
            try:
                binder_sym = ValueSymbol(name=branch.binder, type_val=exc_type.payload_type, is_var=False)
                env.current_scope.declare_value(binder_sym)
                h_body = check_expr(branch.body, expected_type, env, loop_depth)
            finally:
                env.pop_scope()
        else:
            binder_sym = None
            h_body = check_expr(branch.body, expected_type, env, loop_depth)

        typed_branches.append(
            TypedTryBranch(
                exc_pattern=exc_typed,
                body=h_body,
                binder=binder_sym,
                offset=branch.offset,
            )
        )

    if expr.else_branch is not None:
        else_typed = check_expr(expr.else_branch, expected_type, env, loop_depth)
    else:
        else_typed = None

    return TypedTry(
        body=body_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=expected_type,
        offset=expr.offset,
    )


def _synth_try_expr(expr: ast.ExprTry, env: Environment, loop_depth: int) -> TypedTry:
    """Synthesizes a try expression by joining body and branch result types."""
    body_typed = synth_expr(expr.body, env, loop_depth)
    typed_branches: list[TypedTryBranch] = []

    for branch in expr.branches:
        exc_typed = synth_expr(branch.exc_pattern, env, loop_depth)
        exc_type = exc_typed.type_val.evaluate_lazily(env)
        if not isinstance(exc_type, QExceptionType):
            raise TypeError(
                f"Pattern in when branch must be an exception, got '{exc_type}'",
                offset=branch.offset,
            )

        if branch.binder is not None:
            env.push_scope(f"try_{branch.binder}")
            try:
                binder_sym = ValueSymbol(name=branch.binder, type_val=exc_type.payload_type, is_var=False)
                env.current_scope.declare_value(binder_sym)
                h_body = synth_expr(branch.body, env, loop_depth)
            finally:
                env.pop_scope()
        else:
            binder_sym = None
            h_body = synth_expr(branch.body, env, loop_depth)

        typed_branches.append(
            TypedTryBranch(
                exc_pattern=exc_typed,
                body=h_body,
                binder=binder_sym,
                offset=branch.offset,
            )
        )

    if expr.else_branch is not None:
        else_typed = synth_expr(expr.else_branch, env, loop_depth)
    else:
        else_typed = None

    # Collect result types across body, branches, and else
    all_types = [body_typed.type_val] + [b.body.type_val for b in typed_branches]
    if else_typed is not None:
        all_types.append(else_typed.type_val)

    join_type = all_types[0]
    for bt in all_types[1:]:
        if is_subtype(join_type, bt, env):
            join_type = bt
        elif is_subtype(bt, join_type, env):
            pass
        else:
            raise TypeError(
                f"Cannot find common supertype join for try expression branch types '{join_type}' and '{bt}'",
                offset=expr.offset,
            )

    return TypedTry(
        body=body_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=join_type,
        offset=expr.offset,
    )


def _check_inspect_expr(
    expr: ast.ExprInspect,
    expected_type: QType,
    env: Environment,
    loop_depth: int,
) -> TypedInspect:
    """Checks an inspect expression against an expected QType."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)
    if not is_subtype(target_type, DYNAMIC_TYPE, env):
        raise TypeError(f"Target of inspect must be Dynamic, got '{target_type}'", offset=expr.target.offset)

    typed_branches: list[TypedInspectBranch] = []
    for branch in expr.branches:
        match_t = elaborate_type(branch.match_type, env)
        if branch.binders:
            env.push_scope("inspect_branch")
            try:
                b_syms: list[ValueSymbol] = []
                for name, _ in branch.binders:
                    b_sym = ValueSymbol(name=name, type_val=match_t, is_var=False)
                    env.current_scope.declare_value(b_sym)
                    b_syms.append(b_sym)
                h_body = check_expr(branch.body, expected_type, env, loop_depth)
            finally:
                env.pop_scope()
        else:
            b_syms = []
            h_body = check_expr(branch.body, expected_type, env, loop_depth)

        typed_branches.append(
            TypedInspectBranch(
                match_type=match_t,
                binders=tuple(b_syms),
                body=h_body,
                offset=branch.offset,
            )
        )

    if expr.else_branch is not None:
        else_typed = check_expr(expr.else_branch, expected_type, env, loop_depth)
    else:
        else_typed = None

    return TypedInspect(
        target=target_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=expected_type,
        offset=expr.offset,
    )


def _synth_inspect_expr(expr: ast.ExprInspect, env: Environment, loop_depth: int) -> TypedInspect:
    """Synthesizes an inspect expression by joining branch result types."""
    target_typed = synth_expr(expr.target, env, loop_depth)
    target_type = target_typed.type_val.evaluate_lazily(env)
    if not is_subtype(target_type, DYNAMIC_TYPE, env):
        raise TypeError(f"Target of inspect must be Dynamic, got '{target_type}'", offset=expr.target.offset)

    typed_branches: list[TypedInspectBranch] = []
    for branch in expr.branches:
        match_t = elaborate_type(branch.match_type, env)
        if branch.binders:
            env.push_scope("inspect_branch")
            try:
                b_syms: list[ValueSymbol] = []
                for name, _ in branch.binders:
                    b_sym = ValueSymbol(name=name, type_val=match_t, is_var=False)
                    env.current_scope.declare_value(b_sym)
                    b_syms.append(b_sym)
                h_body = synth_expr(branch.body, env, loop_depth)
            finally:
                env.pop_scope()
        else:
            b_syms = []
            h_body = synth_expr(branch.body, env, loop_depth)

        typed_branches.append(
            TypedInspectBranch(
                match_type=match_t,
                binders=tuple(b_syms),
                body=h_body,
                offset=branch.offset,
            )
        )

    if expr.else_branch is not None:
        else_typed = synth_expr(expr.else_branch, env, loop_depth)
    else:
        else_typed = None

    branch_types = [b.body.type_val for b in typed_branches]
    if else_typed is not None:
        branch_types.append(else_typed.type_val)

    if not branch_types:
        return TypedInspect(
            target=target_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=OK_TYPE,
            offset=expr.offset,
        )

    join_type = branch_types[0]
    for bt in branch_types[1:]:
        if is_subtype(join_type, bt, env):
            join_type = bt
        elif is_subtype(bt, join_type, env):
            pass
        else:
            raise TypeError(
                f"Cannot find common supertype join for inspect branch types '{join_type}' and '{bt}'",
                offset=expr.offset,
            )

    return TypedInspect(
        target=target_typed,
        branches=tuple(typed_branches),
        else_branch=else_typed,
        type_val=join_type,
        offset=expr.offset,
    )


# ============================================================================
# Phase 6: Interfaces, Modules, and Program Elaboration Helpers
# ============================================================================

def elaborate_interface(decl: ast.InterfaceDecl, env: Environment) -> TypedInterface:
    """Elaborates an interface declaration into a specification scope and TypedInterface."""
    interface_scope = Scope(name=f"interface_{decl.name}", parent=env.current_scope)

    # 1. Resolve imports into interface_scope
    for imp in decl.imports:
        source_interface_scope = env.lookup_interface(imp.interface_name)
        if source_interface_scope is None:
            raise TypeError(
                f"Undefined interface '{imp.interface_name}' in import of interface '{decl.name}'",
                offset=decl.offset,
            )
        for name in imp.names:
            type_symbol = source_interface_scope.lookup_type_local(name)
            if type_symbol is not None:
                interface_scope.declare_type(type_symbol)
                continue
            value_symbol = source_interface_scope.lookup_value_local(name)
            if value_symbol is not None:
                interface_scope.declare_value(value_symbol)
                continue
            kind_symbol = source_interface_scope.lookup_kind_local(name)
            if kind_symbol is not None:
                interface_scope.declare_kind(kind_symbol)
                continue
            raise TypeError(
                f"Symbol '{name}' not found in imported interface '{imp.interface_name}'",
                offset=decl.offset,
            )

    # 2. Elaborate signatures in a child scope of the interface
    saved_scope = env.current_scope
    env.current_scope = interface_scope
    try:
        for sig in decl.signatures:
            if isinstance(sig, ast.TypeFormal):
                bound_kind = elaborate_kind(sig.bound, env) if sig.bound else TYPE_KIND
                symbol_id = env.fresh_symbol_id()
                type_symbol = TypeSymbol(name=sig.name, symbol_id=symbol_id, kind=bound_kind, definition=None)
                interface_scope.declare_type(type_symbol)

            elif isinstance(sig, ast.LetTypeBinding):
                bound_kind = elaborate_kind(sig.bound, env) if sig.bound is not None else None
                concrete_def = elaborate_type(sig.type_val, env)
                symbol_id = env.fresh_symbol_id()
                type_symbol = TypeSymbol(
                    name=sig.name,
                    symbol_id=symbol_id,
                    kind=bound_kind,
                    definition=concrete_def,
                )
                interface_scope.declare_type(type_symbol)

            elif isinstance(sig, ast.FieldSig):
                val_type = elaborate_type(sig.type_sig, env)
                val_symbol = ValueSymbol(
                    name=sig.name,
                    type_val=val_type,
                    is_var=(sig.mode == ast.ParamMode.VAR),
                    is_out=(sig.mode == ast.ParamMode.OUT),
                )
                interface_scope.declare_value(val_symbol)

            elif isinstance(sig, ast.DefKindBinding):
                kind_symbol = elaborate_kind_binding(sig, env)
                interface_scope.declare_kind(kind_symbol)
    finally:
        env.current_scope = saved_scope

    env.register_interface(decl.name, interface_scope)
    return TypedInterface(name=decl.name, signatures=(), scope=interface_scope, offset=decl.offset)


def elaborate_module(decl: ast.ModuleDecl, env: Environment) -> TypedModule:
    """Elaborates and typechecks a module against its interface, enforcing information hiding."""
    target_interface_scope = env.lookup_interface(decl.interface_name)
    if target_interface_scope is None:
        raise TypeError(
            f"Undefined interface '{decl.interface_name}' for module '{decl.name}'",
            offset=decl.offset,
        )

    module_internal_scope = Scope(name=f"module_internal_{decl.name}", parent=env.current_scope)

    # 1. Resolve imports into module_internal_scope
    for imp in decl.imports:
        source_interface_scope = env.lookup_interface(imp.interface_name)
        if source_interface_scope is None:
            raise TypeError(
                f"Undefined interface '{imp.interface_name}' in import of module '{decl.name}'",
                offset=decl.offset,
            )
        for name in imp.names:
            type_symbol = source_interface_scope.lookup_type_local(name)
            if type_symbol is not None:
                module_internal_scope.declare_type(type_symbol)
                continue
            value_symbol = source_interface_scope.lookup_value_local(name)
            if value_symbol is not None:
                module_internal_scope.declare_value(value_symbol)
                continue
            kind_symbol = source_interface_scope.lookup_kind_local(name)
            if kind_symbol is not None:
                module_internal_scope.declare_kind(kind_symbol)
                continue
            raise TypeError(
                f"Symbol '{name}' not found in imported interface '{imp.interface_name}'",
                offset=decl.offset,
            )

    # 2. Elaborate module internal bindings
    saved_scope = env.current_scope
    env.current_scope = module_internal_scope
    typed_bindings: list[TypedBinding] = []
    try:
        for b in decl.bindings:
            typed_b = _elaborate_binding(b, env, loop_depth=0)
            typed_bindings.append(typed_b)

        # 3. Conformance checking against interface
        type_subst: dict[int, QType] = {}
        for type_name, interface_type_symbol in target_interface_scope.types.items():
            mod_type_symbol = module_internal_scope.lookup_type_local(type_name)
            if mod_type_symbol is None:
                raise TypeError(
                    f"Module '{decl.name}' does not implement required type '{type_name}' "
                    f"from interface '{decl.interface_name}'",
                    offset=decl.offset,
                )
            if interface_type_symbol.definition is not None:
                mod_def = (
                    mod_type_symbol.definition
                    if mod_type_symbol.definition is not None
                    else mod_type_symbol.type_val
                )
                if not is_type_equal(mod_def, interface_type_symbol.definition, env):
                    raise TypeError(
                        f"Module '{decl.name}' defines manifest type '{type_name}' "
                        f"incompatibly with interface '{decl.interface_name}'",
                        offset=decl.offset,
                    )
            if interface_type_symbol.kind is not None and mod_type_symbol.kind is not None:
                if not is_subkind(mod_type_symbol.kind, interface_type_symbol.kind, env):
                    raise TypeError(
                        f"Type '{type_name}' in module '{decl.name}' does not satisfy "
                        f"kind bound from interface '{decl.interface_name}'",
                        offset=decl.offset,
                    )
            if interface_type_symbol.definition is None:
                concrete_def = (
                    mod_type_symbol.definition
                    if mod_type_symbol.definition is not None
                    else mod_type_symbol.type_val
                )
                type_subst[interface_type_symbol.symbol_id] = concrete_def

        for val_name, interface_val_symbol in target_interface_scope.values.items():
            mod_val_symbol = module_internal_scope.lookup_value_local(val_name)
            if mod_val_symbol is None:
                raise TypeError(
                    f"Module '{decl.name}' does not implement required value '{val_name}' "
                    f"from interface '{decl.interface_name}'",
                    offset=decl.offset,
                )
            expected_type = interface_val_symbol.type_val.substitute(type_subst)
            if not is_subtype(mod_val_symbol.type_val, expected_type, env):
                raise TypeError(
                    f"Value '{val_name}' in module '{decl.name}' has type '{mod_val_symbol.type_val}', "
                    f"which is not a subtype of interface signature '{expected_type}'",
                    offset=decl.offset,
                )
    finally:
        env.current_scope = saved_scope

    # 4. Create exported module scope (strictly opaque for abstract interface types)
    module_export_scope = Scope(name=f"module_export_{decl.name}")
    export_type_subst: dict[int, QType] = {}

    for type_name, interface_type_symbol in target_interface_scope.types.items():
        if interface_type_symbol.definition is None:
            export_sym_id = env.fresh_symbol_id()
            opaque_type_symbol = TypeSymbol(
                name=type_name,
                symbol_id=export_sym_id,
                kind=interface_type_symbol.kind,
                definition=None,
            )
            module_export_scope.declare_type(opaque_type_symbol)
            export_type_subst[interface_type_symbol.symbol_id] = QTypeVar(
                name=f"{decl.name}.{type_name}",
                symbol_id=export_sym_id,
                bound=interface_type_symbol.kind,
            )
        else:
            manifest_type_symbol = TypeSymbol(
                name=type_name,
                symbol_id=env.fresh_symbol_id(),
                kind=interface_type_symbol.kind,
                definition=interface_type_symbol.definition,
            )
            module_export_scope.declare_type(manifest_type_symbol)

    for val_name, interface_val_symbol in target_interface_scope.values.items():
        exported_val_type = interface_val_symbol.type_val.substitute(export_type_subst)
        module_export_scope.declare_value(
            ValueSymbol(
                name=val_name,
                type_val=exported_val_type,
                is_var=interface_val_symbol.is_var,
                is_out=interface_val_symbol.is_out,
            )
        )

    env.register_module(decl.name, module_export_scope)

    rec_fields = tuple(
        QRecordField(name=v.name, type_val=v.type_val, is_var=v.is_var)
        for v in module_export_scope.values.values()
    )
    env.current_scope.declare_value(
        ValueSymbol(name=decl.name, type_val=QRecordType(fields=rec_fields))
    )

    return TypedModule(
        name=decl.name,
        interface_name=decl.interface_name,
        bindings=tuple(typed_bindings),
        scope=module_export_scope,
        offset=decl.offset,
    )


def elaborate_program(
    program: ast.Program,
    env: Optional[Environment] = None,
) -> TypedProgram:
    """Elaborates a top-level Quest program unit (interfaces, modules, declarations, statements)."""
    if env is None:
        env = Environment()

    typed_phrases: list[Union[TypedBinding, TypedExpr]] = []
    for phrase in program.phrases:
        if isinstance(phrase, ast.InterfaceDecl):
            typed_interface = elaborate_interface(phrase, env)
            typed_phrases.append(typed_interface)
        elif isinstance(phrase, ast.ModuleDecl):
            typed_module = elaborate_module(phrase, env)
            typed_phrases.append(typed_module)
        elif isinstance(phrase, ast.BindingNode):
            typed_binding = _elaborate_binding(phrase, env, loop_depth=0)
            typed_phrases.append(typed_binding)
        elif isinstance(phrase, ast.Expr):
            typed_expr = synth_expr(phrase, env, loop_depth=0)
            typed_phrases.append(typed_expr)
        else:
            raise TypeError(
                f"Unsupported top-level phrase '{phrase}'",
                offset=getattr(phrase, "offset", 0),
            )

    return TypedProgram(phrases=tuple(typed_phrases), offset=program.offset)


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
    # Target 1: Variable identifier
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

    # Target 2: Record field selection (r.field := rhs)
    if isinstance(expr.left, ast.ExprSelect):
        target_typed = synth_expr(expr.left.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if not isinstance(target_type, QRecordType):
            raise TypeError(
                f"Cannot mutate field of non-record type '{target_type}'",
                offset=expr.left.offset,
            )
        rec_f = target_type.get_field(expr.left.field)
        if rec_f is None:
            raise TypeError(
                f"Record has no field '{expr.left.field}'",
                offset=expr.left.offset,
            )
        if not rec_f.is_var:
            raise TypeError(
                f"Cannot assign to immutable record field '{expr.left.field}'",
                offset=expr.left.offset,
            )
        rhs_typed = check_expr(expr.right, rec_f.type_val, env, loop_depth)
        target_select = TypedSelect(
            target=target_typed,
            field=expr.left.field,
            type_val=rec_f.type_val,
            offset=expr.left.offset,
        )
        return TypedAssign(target=target_select, value=rhs_typed, offset=expr.offset)

    raise TypeError("Assignment target must be a mutable variable or field", offset=expr.left.offset)


def _synth_if_expr(expr: ast.ExprIf, env: Environment, loop_depth: int) -> TypedIf:
    """Synthesizes an if expression."""
    cond_typed = check_expr(expr.cond, BOOL_TYPE, env, loop_depth)

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
    if isinstance(binding, ast.InterfaceDecl):
        return elaborate_interface(binding, env)

    if isinstance(binding, ast.ModuleDecl):
        return elaborate_module(binding, env)

    if isinstance(binding, ast.ExprException):
        typed_exc = _synth_exception_expr(binding, env, loop_depth)
        return TypedExprStmt(expr=typed_exc, offset=binding.offset)

    if isinstance(binding, ast.ExprStmt):
        if isinstance(binding.expr, ast.ExprException):
            typed_exc = _synth_exception_expr(binding.expr, env, loop_depth)
            return TypedExprStmt(expr=typed_exc, offset=binding.offset)
        typed_e = synth_expr(binding.expr, env, loop_depth)
        return TypedExprStmt(expr=typed_e, offset=binding.offset)

    if isinstance(binding, ast.LetValueBinding):
        if binding.params:
            fn_expr = ast.ExprFun(
                params=binding.params,
                return_type=binding.type_annot,
                body=binding.value,
                offset=binding.offset,
            )
            if binding.is_rec:
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
