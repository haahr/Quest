"""Quest Term Elaboration and Bidirectional Typechecker (Phases 2, 3, 4 & 5)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
    QTupleComponent,
    QTupleField,
    QTupleType,
    QTupleTypeBinding,
    QTupleTypeFormal,
    QPathType,
    find_path_types,
    type_mentions_symbol_ids,
    QType,
    QTypeMeta,
    QTypeVar,
    QVarType,
    QVariantField,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    check_kind,
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
from quest.diagnostics import (
    Diagnostic,
    DiagnosticRenderer,
    QuestCompilerError,
    QuestTypeError,
)
from quest.modules import (
    elaborate_import,
    elaborate_interface,
    elaborate_module,
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
    TypedImport,
    TypedImportItem,
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
    TypedTypeWitness,
    TypedVar,
    TypedVarCell,
    TypedVariant,
    TypedVariantAssert,
    TypedVariantCheck,
    TypedWhile,
)


# Internal convenience alias for typechecking error raises
TypeError = QuestTypeError


def check_no_escaping_path_types(
    typ: QType,
    local_symbol_ids: set[int],
    context_desc: str,
    offset: int = 0,
) -> None:
    """Ensures that no abstract path-dependent types rooted at local variables escape."""
    for p in find_path_types(typ):
        if p.root_symbol_id in local_symbol_ids:
            raise TypeError(
                f"Abstract type '{p.root_name}.{p.field_name}' cannot escape {context_desc} "
                f"in type '{typ}'",
                offset=offset,
            )




# ============================================================================
# Bidirectional Typechecker & Elaboration Engine
# ============================================================================

class TypeElaborator:
    """Stateful term elaboration and bidirectional typechecker for Quest AST expressions and bindings."""

    def __init__(self, env: Optional[Environment] = None, loop_depth: int = 0) -> None:
        self.env: Environment = env if env is not None else Environment()
        self.loop_depth: int = loop_depth

    @contextmanager
    def scope(self, name: str = "local") -> Iterator[Scope]:
        """RAII scope context manager pushing and popping an environment scope."""
        with self.env.scoped(name) as s:
            yield s

    @contextmanager
    def in_loop(self) -> Iterator[None]:
        """RAII loop depth tracking context manager for while/loop/for constructs."""
        self.loop_depth += 1
        try:
            yield
        finally:
            self.loop_depth -= 1

    @contextmanager
    def in_function(self) -> Iterator[None]:
        """RAII scope isolation for function bodies (loops inside cannot exit outer loops)."""
        saved_depth = self.loop_depth
        self.loop_depth = 0
        try:
            yield
        finally:
            self.loop_depth = saved_depth

    def _join_types(
        self,
        types: list[QType] | tuple[QType, ...],
        env: Environment,
        offset: int,
        error_msg: Optional[str] = None,
    ) -> QType:
        """Computes the least common supertype of a collection of types under subtyping."""
        if not types:
            return OK_TYPE
        join_type = types[0]
        for bt in types[1:]:
            if is_subtype(join_type, bt, env):
                join_type = bt
            elif is_subtype(bt, join_type, env):
                pass
            else:
                msg = error_msg or f"Cannot find common supertype join for branch types '{join_type}' and '{bt}'"
                if "{t1}" in msg:
                    msg = msg.format(t1=join_type, t2=bt)
                raise TypeError(msg, offset=offset)
        return join_type

    def check_no_escaping_path_types(
        self,
        typ: QType,
        local_symbol_ids: set[int],
        context_desc: str,
        offset: int = 0,
    ) -> None:
        """Ensures that a type does not mention local path types that cannot escape."""
        check_no_escaping_path_types(typ, local_symbol_ids, context_desc, offset)

    def check(
        self,
        expr: ast.Expr,
        expected_type: QType,
        env: Optional[Environment] = None,
        loop_depth: Optional[int] = None,
    ) -> TypedExpr:
        """Checks an AST expression against an expected QType (Gamma |- e <= T)."""
        return self.check_expr(
            expr,
            expected_type,
            env=env or self.env,
            loop_depth=self.loop_depth if loop_depth is None else loop_depth,
        )

    def synth(
        self,
        expr: ast.Expr,
        env: Optional[Environment] = None,
        loop_depth: Optional[int] = None,
    ) -> TypedExpr:
        """Synthesizes the minimal QType and elaborated TypedExpr (Gamma |- e => T)."""
        return self.synth_expr(
            expr,
            env=env or self.env,
            loop_depth=self.loop_depth if loop_depth is None else loop_depth,
        )

    def elaborate_binding(
        self,
        binding: ast.BindingNode,
        env: Optional[Environment] = None,
        loop_depth: Optional[int] = None,
    ) -> TypedBinding:
        """Elaborates a single binding or statement inside a block or module."""
        return self._elaborate_binding(
            binding,
            env=env or self.env,
            loop_depth=self.loop_depth if loop_depth is None else loop_depth,
        )



    def check_expr(
        self,
        expr: ast.Expr,
        expected_type: QType,
        env: Optional[Environment] = None,
        loop_depth: int = 0,
    ) -> TypedExpr:
        """Checks an AST expression against an expected QType (Gamma |- e <= T)."""
        if env is None:
            env = self.env

        match expr:
            # 1. Conditionals with else branch: check both branches against expected_type
            case ast.ExprIf(else_branch=else_br) if else_br is not None:
                return self._check_if_expr(expr, expected_type, env, loop_depth)

            # 2. Block expression: check final result against expected_type
            case ast.ExprBlock():
                return self._check_block_expr(expr, expected_type, env, loop_depth)

            # 3. Function abstraction: check against expected function type
            case ast.ExprFun():
                return self._check_fun_expr(expr, expected_type, env, loop_depth)

            # 4. Record expression: check fields against expected record type
            case ast.ExprRecord():
                return self._check_record_expr(expr, expected_type, env, loop_depth)

            # 5. Tuple expression: check elements against expected tuple type
            case ast.ExprTuple():
                return self._check_tuple_expr(expr, expected_type, env, loop_depth)

            # 6. Case expression: check all branches against expected_type
            case ast.ExprCase():
                return self._check_case_expr(expr, expected_type, env, loop_depth)

            # 7. Array expressions: check elements against expected array element type
            case ast.ExprArray():
                return self._check_array_expr(expr, expected_type, env, loop_depth)

            case ast.ExprArrayRep():
                return self._check_array_rep_expr(expr, expected_type, env, loop_depth)

            # 8. Phase 5: Raise expression (divergent control flow checks against any expected type)
            case ast.ExprRaise():
                return self._check_raise_expr(expr, expected_type, env, loop_depth)

            # 9. Phase 5: Try expression
            case ast.ExprTry():
                return self._check_try_expr(expr, expected_type, env, loop_depth)

            # 10. Phase 5: Inspect expression
            case ast.ExprInspect():
                return self._check_inspect_expr(expr, expected_type, env, loop_depth)

            # 11. Statement unwrap (for phrase/statement bodies)
            case ast.ExprStmt(expr=inner):
                return self.check_expr(inner, expected_type, env, loop_depth)

            # 12. Subsumption: synthesize minimal type and check subtyping (S <= T)
            case _:
                typed = self.synth_expr(expr, env, loop_depth)
                if not is_subtype(typed.type_val, expected_type, env):
                    raise TypeError(
                        f"Type mismatch: synthesized type '{typed.type_val}' is not a subtype "
                        f"of expected type '{expected_type}'",
                        offset=expr.offset,
                    )
                return typed


    def synth_expr(
        self,
        expr: ast.Expr,
        env: Optional[Environment] = None,
        loop_depth: int = 0,
    ) -> TypedExpr:
        """Synthesizes the minimal QType and elaborated TypedExpr (Gamma |- e => T)."""
        if env is None:
            env = self.env

        match expr:
            # --- Literals ---
            case ast.ExprInt(value=val, offset=off):
                return TypedInt(value=val, offset=off)

            case ast.ExprReal(value=val, offset=off):
                return TypedReal(value=val, offset=off)

            case ast.ExprBool(value=val, offset=off):
                return TypedBool(value=val, offset=off)

            case ast.ExprChar(value=val, offset=off):
                return TypedChar(value=val, offset=off)

            case ast.ExprString(value=val, offset=off):
                return TypedString(value=val, offset=off)

            case ast.ExprOk(offset=off):
                return TypedOk(offset=off)

            case ast.ExprExit(offset=off):
                if loop_depth <= 0:
                    raise TypeError("Exit statement outside of any loop", offset=off)
                return TypedExit(offset=off)

            # --- Variables & Identifiers ---
            case ast.ExprId(name=name, offset=off):
                sym = env.lookup_value(name)
                if sym is None:
                    raise TypeError(f"Undefined variable '{name}'", offset=off)

                # Implicit dereferencing: mutable variables in value positions yield element type
                if sym.is_var:
                    var_node = TypedVar(
                        name=sym.name,
                        symbol=sym,
                        type_val=QVarType(sym.type_val),
                        offset=off,
                    )
                    return TypedDerefCell(target=var_node, type_val=sym.type_val, offset=off)

                return TypedVar(name=sym.name, symbol=sym, type_val=sym.type_val, offset=off)

            # --- Explicit Dereference (@e or !e) ---
            case ast.ExprDerefCell(target=target, offset=off):
                if isinstance(target, ast.ExprId):
                    sym = env.lookup_value(target.name)
                    if sym is None:
                        raise TypeError(f"Undefined variable '{target.name}'", offset=target.offset)
                    if not sym.is_var and not isinstance(sym.type_val, QVarType):
                        raise TypeError(
                            f"Cannot dereference non-variable symbol '{target.name}'",
                            offset=target.offset,
                        )
                    var_type = QVarType(sym.type_val) if sym.is_var else sym.type_val
                    elem_type = sym.type_val if sym.is_var else sym.type_val.element_type
                    var_node = TypedVar(
                        name=sym.name,
                        symbol=sym,
                        type_val=var_type,
                        offset=target.offset,
                    )
                    return TypedDerefCell(target=var_node, type_val=elem_type, offset=off)

                target_typed = self.synth_expr(target, env, loop_depth)
                if not isinstance(target_typed.type_val, QVarType):
                    raise TypeError(
                        f"Cannot dereference non-variable type '{target_typed.type_val}'",
                        offset=off,
                    )
                return TypedDerefCell(
                    target=target_typed,
                    type_val=target_typed.type_val.element_type,
                    offset=off,
                )

            # --- Reference Cell Allocation (var e) ---
            case ast.ExprVarCell(value=val, offset=off):
                val_typed = self.synth_expr(val, env, loop_depth)
                return TypedVarCell(
                    value=val_typed,
                    type_val=QVarType(val_typed.type_val),
                    offset=off,
                )

            # --- Infix Operators ---
            case ast.ExprInfix():
                return self._synth_infix_expr(expr, env, loop_depth)

            # --- Conditionals ---
            case ast.ExprIf():
                return self._synth_if_expr(expr, env, loop_depth)

            # --- Loops & Control Flow ---
            case ast.ExprWhile(cond=cond, body=body, offset=off):
                cond_typed = self.check_expr(cond, BOOL_TYPE, env, loop_depth)
                self.loop_depth = loop_depth
                with self.in_loop():
                    body_typed = self.synth_expr(body, env, self.loop_depth)
                return TypedWhile(cond=cond_typed, body=body_typed, offset=off)

            case ast.ExprLoop(body=body, offset=off):
                self.loop_depth = loop_depth
                with self.in_loop():
                    body_typed = self.synth_expr(body, env, self.loop_depth)
                return TypedLoop(body=body_typed, offset=off)

            case ast.ExprFor():
                return self._synth_for_expr(expr, env, loop_depth)

            # --- Block Expressions ---
            case ast.ExprBlock():
                return self._synth_block_expr(expr, env, loop_depth)

            # --- Functions and Applications ---
            case ast.ExprFun():
                return self._synth_fun_expr(expr, env, loop_depth)

            case ast.ExprApp():
                return self._synth_app_expr(expr, env, loop_depth)

            # --- Aggregates (Records, Tuples, Options, Variants, Arrays) ---
            case ast.ExprRecord():
                return self._synth_record_expr(expr, env, loop_depth)

            case ast.ExprTuple():
                return self._synth_tuple_expr(expr, env, loop_depth)

            case ast.ExprSelect():
                return self._synth_select_expr(expr, env, loop_depth)

            case ast.ExprOption():
                return self._synth_option_expr(expr, env, loop_depth)

            case ast.ExprVariant():
                return self._synth_variant_expr(expr, env, loop_depth)

            case ast.ExprVariantCheck():
                return self._synth_variant_check_expr(expr, env, loop_depth)

            case ast.ExprVariantAssert():
                return self._synth_variant_assert_expr(expr, env, loop_depth)

            case ast.ExprCase():
                return self._synth_case_expr(expr, env, loop_depth)

            case ast.ExprArray():
                return self._synth_array_expr(expr, env, loop_depth)

            case ast.ExprArrayRep():
                return self._synth_array_rep_expr(expr, env, loop_depth)

            case ast.ExprIndex():
                return self._synth_index_expr(expr, env, loop_depth)

            case ast.ExprIndexAssign():
                return self._synth_index_assign_expr(expr, env, loop_depth)

            # --- Exceptions & Dynamic (Phase 5) ---
            case ast.ExprException():
                return self._synth_exception_expr(expr, env, loop_depth)

            case ast.ExprRaise():
                return self._synth_raise_expr(expr, env, loop_depth)

            case ast.ExprTry():
                return self._synth_try_expr(expr, env, loop_depth)

            case ast.ExprInspect():
                return self._synth_inspect_expr(expr, env, loop_depth)

            # --- Statement Unwrap ---
            case ast.ExprStmt(expr=inner):
                return self.synth_expr(inner, env, loop_depth)

            case _:
                raise TypeError(f"Unsupported AST expression '{expr}'", offset=getattr(expr, "offset", 0))



    # ============================================================================
    # Functions and Applications Helpers
    # ============================================================================

    def _synth_fun_expr(self, expr: ast.ExprFun, env: Environment, loop_depth: int) -> TypedFun:
        """Synthesizes a function abstraction: fun(params): RetType Body."""
        with env.scoped("fun"):
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

            with self.in_function():
                if expr.return_type is not None:
                    expected_ret = elaborate_type(expr.return_type, env)
                    body_typed = self.check_expr(expr.body, expected_ret, env, loop_depth=self.loop_depth)
                    ret_type = expected_ret
                else:
                    body_typed = self.synth_expr(expr.body, env, loop_depth=self.loop_depth)
                    ret_type = body_typed.type_val

            local_symbol_ids = {sym.symbol_id for sym in env.current_scope.values.values()}
            check_no_escaping_path_types(ret_type, local_symbol_ids, "function scope", expr.offset)

            fun_type = QFunType(params=tuple(q_params), result_type=ret_type)
            return TypedFun(
                params=tuple(formal_params),
                body=body_typed,
                type_val=fun_type,
                offset=expr.offset,
            )


    def _check_fun_expr(
        self,
        expr: ast.ExprFun,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedFun:
        """Checks a function abstraction against an expected function type."""
        expected_lazy = expected_type.evaluate_lazily(env)
        if not isinstance(expected_lazy, QFunType):
            typed_fun = self._synth_fun_expr(expr, env, loop_depth)
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

        with env.scoped("fun"):
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

            with self.in_function():
                body_typed = self.check_expr(
                    expr.body,
                    expected_lazy.result_type,
                    env,
                    loop_depth=self.loop_depth,
                )
            fun_type = QFunType(params=tuple(q_params), result_type=expected_lazy.result_type)
            return TypedFun(
                params=tuple(formal_params),
                body=body_typed,
                type_val=fun_type,
                offset=expr.offset,
            )


    def _synth_app_expr(self, expr: ast.ExprApp, env: Environment, loop_depth: int) -> TypedExpr:
        """Synthesizes a function application, handling polymorphic type inference, var, and out params."""
        func_typed = self.synth_expr(expr.func, env, loop_depth)
        fn_type = func_typed.type_val.evaluate_lazily(env)

        # 1. Polymorphic function call (QAllType)
        if isinstance(fn_type, QAllType):
            return self._synth_polymorphic_app(expr, func_typed, fn_type, env, loop_depth)

        # 2. Monomorphic function call (QFunType)
        if isinstance(fn_type, QFunType):
            return self._synth_monomorphic_app(expr, func_typed, fn_type, env, loop_depth)

        raise TypeError(f"Cannot invoke non-function type '{fn_type}'", offset=expr.func.offset)


    def _synth_monomorphic_app(
        self,
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
                typed_arg = self._check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=False)
                typed_args.append(typed_arg)
            elif param.is_out:
                typed_arg = self._check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=True)
                typed_args.append(typed_arg)
            else:
                typed_arg = self.check_expr(arg, param.type_val, env, loop_depth)
                typed_args.append(typed_arg)

        return TypedApp(
            func=func_typed,
            args=tuple(typed_args),
            type_val=fn_type.result_type,
            offset=expr.offset,
        )


    def _check_lvalue_arg(
        self,
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
        self,
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
                typed_arg = self._check_lvalue_arg(arg, param.type_val, env, loop_depth, is_out=param.is_out)
            else:
                typed_arg = self.check_expr(arg, param.type_val, env, loop_depth)
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

    def _synth_record_expr(self, expr: ast.ExprRecord, env: Environment, loop_depth: int) -> TypedRecord:
        """Synthesizes a record constructor: record [var] x = e1 ... end."""
        field_typeds: list[TypedRecordField] = []
        q_fields: list[QRecordField] = []

        for b in expr.fields:
            val_typed = self.synth_expr(b.value, env, loop_depth)
            field_typeds.append(
                TypedRecordField(name=b.name, value=val_typed, is_var=b.is_var, offset=b.offset)
            )
            q_fields.append(QRecordField(name=b.name, type_val=val_typed.type_val, is_var=b.is_var))

        rec_type = QRecordType(fields=tuple(q_fields))
        return TypedRecord(fields=tuple(field_typeds), type_val=rec_type, offset=expr.offset)


    def _check_record_expr(
        self,
        expr: ast.ExprRecord,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedRecord:
        """Checks a record constructor against an expected record type."""
        expected_lazy = expected_type.evaluate_lazily(env)
        if not isinstance(expected_lazy, QRecordType):
            typed_rec = self._synth_record_expr(expr, env, loop_depth)
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
                val_typed = self.check_expr(b.value, exp_f.type_val, env, loop_depth)
                if not is_type_equal(val_typed.type_val, exp_f.type_val, env):
                    raise TypeError(
                        f"Mutable record field '{exp_f.name}' is invariant; expected '{exp_f.type_val}', "
                        f"got '{val_typed.type_val}'",
                        offset=b.offset,
                    )
            else:
                val_typed = self.check_expr(b.value, exp_f.type_val, env, loop_depth)

            field_typeds.append(
                TypedRecordField(name=b.name, value=val_typed, is_var=b.is_var, offset=b.offset)
            )

        for b in expr.fields:
            if expected_lazy.get_field(b.name) is None:
                extra_val = self.synth_expr(b.value, env, loop_depth)
                field_typeds.append(
                    TypedRecordField(name=b.name, value=extra_val, is_var=b.is_var, offset=b.offset)
                )
        return TypedRecord(fields=tuple(field_typeds), type_val=expected_lazy, offset=expr.offset)


    def _synth_tuple_expr(self, expr: ast.ExprTuple, env: Environment, loop_depth: int) -> TypedTuple:
        """Synthesizes a tuple constructor: tuple ... end."""
        with env.scoped("tuple_synth"):
            elem_typeds: list[TypedExpr] = []
            q_fields: list[QTupleComponent] = []

            for b in expr.fields:
                if isinstance(b, (ast.LetTypeBinding, ast.DefTypeBinding)):
                    witness_type = elaborate_type(b.type_val, env)
                    if b.bound is not None:
                        k_bound = elaborate_kind(b.bound, env)
                    else:
                        k_bound = TYPE_KIND
                    check_kind(witness_type, k_bound, env)
                    sym_id = env.fresh_symbol_id()
                    env.current_scope.declare_type(
                        TypeSymbol(
                            name=b.name,
                            symbol_id=sym_id,
                            kind=k_bound,
                            definition=witness_type,
                        )
                    )
                    elem_typeds.append(
                        TypedTypeWitness(
                            name=b.name,
                            witness_type=witness_type,
                            bound=k_bound,
                            offset=b.offset,
                        )
                    )
                    q_fields.append(QTupleTypeBinding(name=b.name, type_val=witness_type, bound=k_bound))
                elif isinstance(b, ast.TupleBinding):
                    if b.type_annot is not None:
                        annot_type = elaborate_type(b.type_annot, env)
                        val_typed = self.check_expr(b.value, annot_type, env, loop_depth)
                    else:
                        val_typed = self.synth_expr(b.value, env, loop_depth)
                    elem_typeds.append(val_typed)
                    q_fields.append(QTupleField(name=b.name, type_val=val_typed.type_val))
                    if b.name is not None:
                        env.current_scope.declare_value(
                            ValueSymbol(name=b.name, type_val=val_typed.type_val)
                        )
                else:
                    raise TypeError(
                        f"Unsupported tuple component '{b}'",
                        offset=getattr(b, "offset", expr.offset),
                    )

            tuple_type = QTupleType(tuple(q_fields))
            return TypedTuple(elements=tuple(elem_typeds), type_val=tuple_type, offset=expr.offset)


    def _check_tuple_expr(
        self,
        expr: ast.ExprTuple,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedTuple:
        """Checks a tuple constructor against an expected tuple type."""
        expected_lazy = expected_type.evaluate_lazily(env)
        if not isinstance(expected_lazy, QTupleType):
            typed_tup = self._synth_tuple_expr(expr, env, loop_depth)
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

        with env.scoped("tuple_check"):
            witness_subst: dict[int, QType] = {}
            elem_typeds: list[TypedExpr] = []
            for b, exp_f in zip(expr.fields, expected_lazy.fields):
                match exp_f:
                    case QTupleTypeFormal(name=formal_name, symbol_id=formal_sym_id, bound=formal_bound):
                        if not isinstance(b, (ast.LetTypeBinding, ast.DefTypeBinding)):
                            raise TypeError(
                                f"Expected type witness for type formal '{formal_name}', got value component",
                                offset=getattr(b, "offset", expr.offset),
                            )
                        if b.name != formal_name:
                            raise TypeError(
                                f"Tuple type formal name mismatch: expected '{formal_name}', got '{b.name}'",
                                offset=b.offset,
                            )
                        witness_type = elaborate_type(b.type_val, env)
                        expected_bound = formal_bound.substitute(witness_subst)
                        check_kind(witness_type, expected_bound, env)
                        witness_subst[formal_sym_id] = witness_type
                        env.current_scope.declare_type(
                            TypeSymbol(
                                name=formal_name,
                                symbol_id=formal_sym_id,
                                kind=expected_bound,
                                definition=witness_type,
                            )
                        )
                        elem_typeds.append(
                            TypedTypeWitness(
                                name=formal_name,
                                witness_type=witness_type,
                                bound=expected_bound,
                                offset=b.offset,
                            )
                        )

                    case QTupleTypeBinding(name=bind_name, type_val=bind_type, bound=bind_bound):
                        if not isinstance(b, (ast.LetTypeBinding, ast.DefTypeBinding)):
                            raise TypeError(
                                f"Expected type binding for '{bind_name}', got value component",
                                offset=getattr(b, "offset", expr.offset),
                            )
                        if b.name != bind_name:
                            raise TypeError(
                                f"Tuple type binding name mismatch: expected '{bind_name}', got '{b.name}'",
                                offset=b.offset,
                            )
                        witness_type = elaborate_type(b.type_val, env)
                        expected_type_val = bind_type.substitute(witness_subst)
                        if not is_type_equal(witness_type, expected_type_val, env):
                            raise TypeError(
                                f"Type binding '{bind_name}' must match manifest type '{expected_type_val}', "
                                f"got '{witness_type}'",
                                offset=b.offset,
                            )
                        elem_typeds.append(
                            TypedTypeWitness(
                                name=bind_name,
                                witness_type=witness_type,
                                bound=bind_bound,
                                offset=b.offset,
                            )
                        )

                    case QTupleField(name=field_name, type_val=field_type):
                        if isinstance(b, (ast.LetTypeBinding, ast.DefTypeBinding)):
                            raise TypeError(
                                f"Unexpected type binding '{b.name}' for value field '{field_name}'",
                                offset=b.offset,
                            )
                        if field_name is not None and b.name is not None and b.name != field_name:
                            raise TypeError(
                                f"Tuple field name mismatch: expected '{field_name}', got '{b.name}'",
                                offset=b.offset,
                            )
                        expected_field_type = field_type.substitute(witness_subst)
                        if getattr(b, "type_annot", None) is not None:
                            annot_type = elaborate_type(b.type_annot, env)
                            if not is_subtype(annot_type, expected_field_type, env):
                                raise TypeError(
                                    f"Tuple field '{b.name}' declared type '{annot_type}' is not a subtype "
                                    f"of expected field type '{expected_field_type}'",
                                    offset=b.offset,
                                )
                            val_typed = self.check_expr(b.value, annot_type, env, loop_depth)
                        else:
                            val_typed = self.check_expr(b.value, expected_field_type, env, loop_depth)
                        elem_typeds.append(val_typed)
                        if field_name is not None:
                            env.current_scope.declare_value(
                                ValueSymbol(name=field_name, type_val=expected_field_type)
                            )

            return TypedTuple(elements=tuple(elem_typeds), type_val=expected_lazy, offset=expr.offset)


    def _synth_select_expr(self, expr: ast.ExprSelect, env: Environment, loop_depth: int) -> TypedSelect:
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

        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)

        match target_type:
            case QRecordType():
                rec_f = target_type.get_field(expr.field)
                if rec_f is None:
                    raise TypeError(
                        f"Record type '{target_type}' has no field named '{expr.field}'",
                        offset=expr.offset,
                    )
                return TypedSelect(target=target_typed, field=expr.field, type_val=rec_f.type_val, offset=expr.offset)

            case QTupleType():
                tup_f = target_type.get_field(expr.field)
                if tup_f is None:
                    raise TypeError(
                        f"Tuple type '{target_type}' has no field named '{expr.field}'",
                        offset=expr.offset,
                    )
                if isinstance(tup_f, (QTupleTypeFormal, QTupleTypeBinding)):
                    raise TypeError(
                        f"Cannot select type component '{expr.field}' as a value expression",
                        offset=expr.offset,
                    )

                formal_sym_ids = {f.symbol_id for f in target_type.type_formals}
                is_dependent = type_mentions_symbol_ids(tup_f.type_val, formal_sym_ids)

                if is_dependent:
                    if not isinstance(expr.target, ast.ExprId):
                        raise TypeError(
                            f"Cannot select type-dependent member '{expr.field}' from compound or anonymous "
                            f"existential tuple; bind to an immutable variable first",
                            offset=expr.offset,
                        )
                    val_sym = env.lookup_value(expr.target.name)
                    if val_sym is not None and val_sym.is_var:
                        raise TypeError(
                            f"Cannot select type-dependent member '{expr.field}' from mutable variable "
                            f"'{expr.target.name}'; bind to an immutable variable first",
                            offset=expr.offset,
                        )
                    root_sym_id = val_sym.symbol_id if val_sym else 0
                    subst = {
                        f.symbol_id: QPathType(
                            root_name=expr.target.name,
                            root_symbol_id=root_sym_id,
                            field_name=f.name,
                            bound=f.bound,
                        )
                        for f in target_type.type_formals
                    }
                    field_type = tup_f.type_val.substitute(subst)
                else:
                    field_type = tup_f.type_val

                return TypedSelect(
                    target=target_typed,
                    field=expr.field,
                    type_val=field_type,
                    offset=expr.offset,
                )

            case _:
                raise TypeError(
                    f"Cannot select field '{expr.field}' from non-record/tuple type '{target_type}'",
                    offset=expr.offset,
                )


    def _synth_option_expr(self, expr: ast.ExprOption, env: Environment, loop_depth: int) -> TypedOption:
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
            payload_typed = self.check_expr(expr.payload, opt_field.payload_type, env, loop_depth)
        else:
            if expr.payload is not None:
                raise TypeError(f"Option variant '{expr.tag}' does not accept a payload", offset=expr.offset)
            payload_typed = None

        return TypedOption(tag=expr.tag, type_val=opt_type, payload=payload_typed, offset=expr.offset)


    def _synth_variant_expr(self, expr: ast.ExprVariant, env: Environment, loop_depth: int) -> TypedVariant:
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
            payload_typed = self.check_expr(expr.payload, var_field.type_val, env, loop_depth)
        else:
            if expr.payload is not None:
                raise TypeError(f"Variant tag '{expr.tag}' does not accept a payload", offset=expr.offset)
            payload_typed = None

        return TypedVariant(tag=expr.tag, type_val=var_type, payload=payload_typed, offset=expr.offset)


    def _synth_variant_check_expr(
        self,
        expr: ast.ExprVariantCheck, env: Environment, loop_depth: int
    ) -> TypedVariantCheck:
        """Synthesizes a variant/option tag query: target?tag."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if isinstance(target_type, QVariantType):
            field = target_type.get_variant(expr.tag)
            if field is None:
                raise TypeError(
                    f"Tag '{expr.tag}' is not a valid variant of type '{target_type}'",
                    offset=expr.offset,
                )
        elif isinstance(target_type, QOptionType):
            opt = target_type.get_option(expr.tag)
            if opt is None:
                raise TypeError(
                    f"Tag '{expr.tag}' is not a valid option of type '{target_type}'",
                    offset=expr.offset,
                )
        else:
            raise TypeError(
                f"Variant query '?' requires Variant or Option target, got '{target_type}'",
                offset=expr.offset,
            )
        return TypedVariantCheck(target=target_typed, tag=expr.tag, type_val=BOOL_TYPE, offset=expr.offset)


    def _synth_variant_assert_expr(
        self,
        expr: ast.ExprVariantAssert, env: Environment, loop_depth: int
    ) -> TypedVariantAssert:
        """Synthesizes a variant/option payload extraction: target!tag."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if isinstance(target_type, QVariantType):
            field = target_type.get_variant(expr.tag)
            if field is None:
                raise TypeError(
                    f"Tag '{expr.tag}' is not a valid variant of type '{target_type}'",
                    offset=expr.offset,
                )
            result_type = field.type_val if field.type_val is not None else OK_TYPE
        elif isinstance(target_type, QOptionType):
            opt = target_type.get_option(expr.tag)
            if opt is None:
                raise TypeError(
                    f"Tag '{expr.tag}' is not a valid option of type '{target_type}'",
                    offset=expr.offset,
                )
            result_type = opt.payload_type if opt.payload_type is not None else OK_TYPE
        else:
            raise TypeError(
                f"Variant assertion '!' requires Variant or Option target, got '{target_type}'",
                offset=expr.offset,
            )
        return TypedVariantAssert(target=target_typed, tag=expr.tag, type_val=result_type, offset=expr.offset)


    def _synth_case_expr(self, expr: ast.ExprCase, env: Environment, loop_depth: int) -> TypedCase:
        """Synthesizes a case expression over an option or variant target."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)

        available_tags, typed_branches = self._elaborate_case_branches(
            expr, target_type, expected_type=None, env=env, loop_depth=loop_depth
        )

        if expr.else_branch is not None:
            else_typed: Optional[TypedExpr] = self.synth_expr(expr.else_branch, env, loop_depth)
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

        join_type = self._join_types(
            branch_types,
            env,
            expr.offset,
            error_msg="Cannot find common supertype join for case branch types '{t1}' and '{t2}'",
        )

        return TypedCase(
            target=target_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=join_type,
            offset=expr.offset,
        )


    def _check_case_expr(
        self,
        expr: ast.ExprCase,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedCase:
        """Checks a case expression against an expected QType."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)

        available_tags, typed_branches = self._elaborate_case_branches(
            expr, target_type, expected_type=expected_type, env=env, loop_depth=loop_depth
        )

        if expr.else_branch is not None:
            else_typed: Optional[TypedExpr] = self.check_expr(expr.else_branch, expected_type, env, loop_depth)
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
        self,
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
                            f"Binder '{branch.binder}' type '{binder_t}' is not "
                            f"compatible with payload '{first_payload}'",
                            offset=branch.offset,
                        )
                else:
                    binder_t = first_payload

                with env.scoped(f"case_{branch.binder}"):
                    binder_sym = ValueSymbol(name=branch.binder, type_val=binder_t, is_var=False)
                    env.current_scope.declare_value(binder_sym)
                    if expected_type is not None:
                        body_typed = self.check_expr(branch.body, expected_type, env, loop_depth)
                    else:
                        body_typed = self.synth_expr(branch.body, env, loop_depth)
                        check_no_escaping_path_types(
                            body_typed.type_val,
                            {binder_sym.symbol_id},
                            "case branch scope",
                            branch.body.offset,
                        )
            else:
                binder_sym = None
                if expected_type is not None:
                    body_typed = self.check_expr(branch.body, expected_type, env, loop_depth)
                else:
                    body_typed = self.synth_expr(branch.body, env, loop_depth)

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


    def _synth_array_expr(self, expr: ast.ExprArray, env: Environment, loop_depth: int) -> TypedArray:
        """Synthesizes an explicit array literal: array of e1 e2 ... end."""
        if not expr.elements:
            raise TypeError(
                "Cannot infer element type of empty array; type annotation required",
                offset=expr.offset,
            )

        elem_typeds = [self.synth_expr(e, env, loop_depth) for e in expr.elements]
        join_type = self._join_types(
            [e.type_val for e in elem_typeds],
            env,
            expr.offset,
            error_msg="Incompatible array element types '{t1}' and '{t2}'",
        )

        return TypedArray(
            elements=tuple(elem_typeds),
            type_val=QArrayType(element_type=join_type),
            offset=expr.offset,
        )


    def _check_array_expr(
        self,
        expr: ast.ExprArray,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedArray:
        """Checks an array literal against an expected array type."""
        expected_lazy = expected_type.evaluate_lazily(env)
        if not isinstance(expected_lazy, QArrayType):
            typed_arr = self._synth_array_expr(expr, env, loop_depth)
            if not is_subtype(typed_arr.type_val, expected_type, env):
                raise TypeError(
                    f"Array type '{typed_arr.type_val}' is not a subtype of expected '{expected_type}'",
                    offset=expr.offset,
                )
            return typed_arr

        elem_typeds = [
            self.check_expr(e, expected_lazy.element_type, env, loop_depth) for e in expr.elements
        ]
        return TypedArray(elements=tuple(elem_typeds), type_val=expected_lazy, offset=expr.offset)


    def _synth_array_rep_expr(self, expr: ast.ExprArrayRep, env: Environment, loop_depth: int) -> TypedArrayRep:
        """Synthesizes an array repetition: array of (count init) end."""
        count_typed = self.check_expr(expr.count, INT_TYPE, env, loop_depth)
        init_typed = self.synth_expr(expr.init_val, env, loop_depth)
        return TypedArrayRep(
            count=count_typed,
            init_val=init_typed,
            type_val=QArrayType(element_type=init_typed.type_val),
            offset=expr.offset,
        )


    def _check_array_rep_expr(
        self,
        expr: ast.ExprArrayRep,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedArrayRep:
        """Checks an array repetition against an expected array type."""
        expected_lazy = expected_type.evaluate_lazily(env)
        if not isinstance(expected_lazy, QArrayType):
            typed_rep = self._synth_array_rep_expr(expr, env, loop_depth)
            if not is_subtype(typed_rep.type_val, expected_type, env):
                raise TypeError(
                    f"Array type '{typed_rep.type_val}' is not a subtype of expected '{expected_type}'",
                    offset=expr.offset,
                )
            return typed_rep

        count_typed = self.check_expr(expr.count, INT_TYPE, env, loop_depth)
        init_typed = self.check_expr(expr.init_val, expected_lazy.element_type, env, loop_depth)
        return TypedArrayRep(
            count=count_typed,
            init_val=init_typed,
            type_val=expected_lazy,
            offset=expr.offset,
        )


    def _synth_index_expr(self, expr: ast.ExprIndex, env: Environment, loop_depth: int) -> TypedIndex:
        """Synthesizes an array indexing expression: arr[i]."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if not isinstance(target_type, QArrayType):
            raise TypeError(f"Cannot index non-array type '{target_type}'", offset=expr.offset)

        idx_typed = self.check_expr(expr.index, INT_TYPE, env, loop_depth)
        return TypedIndex(
            target=target_typed,
            index=idx_typed,
            type_val=target_type.element_type,
            offset=expr.offset,
        )


    def _synth_index_assign_expr(
        self,
        expr: ast.ExprIndexAssign,
        env: Environment,
        loop_depth: int,
    ) -> TypedIndexAssign:
        """Synthesizes an array element assignment: arr[i] := val."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if not isinstance(target_type, QArrayType):
            raise TypeError(
                f"Cannot assign to index of non-array type '{target_type}'",
                offset=expr.offset,
            )

        idx_typed = self.check_expr(expr.index, INT_TYPE, env, loop_depth)
        val_typed = self.check_expr(expr.value, target_type.element_type, env, loop_depth)
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

    def _synth_exception_expr(self, expr: ast.ExprException, env: Environment, loop_depth: int) -> TypedException:
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


    def _elaborate_raise(
        self,
        expr: ast.ExprRaise,
        res_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedRaise:
        """Shared elaboration core for raise expressions."""
        exc_typed = self.synth_expr(expr.exc, env, loop_depth)
        exc_type = exc_typed.type_val.evaluate_lazily(env)
        if not isinstance(exc_type, QExceptionType):
            raise TypeError(f"Cannot raise non-exception type '{exc_type}'", offset=expr.exc.offset)

        if expr.payload is not None:
            payload_typed = self.check_expr(expr.payload, exc_type.payload_type, env, loop_depth)
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
            type_val=res_type,
            offset=expr.offset,
        )

    def _check_raise_expr(
        self,
        expr: ast.ExprRaise,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedRaise:
        """Checks a raise expression against any expected type (divergent control flow)."""
        return self._elaborate_raise(expr, expected_type, env, loop_depth)


    def _synth_raise_expr(self, expr: ast.ExprRaise, env: Environment, loop_depth: int) -> TypedRaise:
        """Synthesizes a raise expression. Defaults to Ok if no declared type is present."""
        res_type = elaborate_type(expr.as_type, env) if expr.as_type is not None else OK_TYPE
        return self._elaborate_raise(expr, res_type, env, loop_depth)


    def _elaborate_try_branches(
        self,
        expr: ast.ExprTry,
        expected_type: Optional[QType],
        env: Environment,
        loop_depth: int,
    ) -> tuple[TypedExpr, list[TypedTryBranch], Optional[TypedExpr]]:
        """Elaborates body, handler branches, and optional else branch for a try expression."""
        if expected_type is not None:
            body_typed = self.check_expr(expr.body, expected_type, env, loop_depth)
        else:
            body_typed = self.synth_expr(expr.body, env, loop_depth)

        typed_branches: list[TypedTryBranch] = []
        for branch in expr.branches:
            exc_typed = self.synth_expr(branch.exc_pattern, env, loop_depth)
            exc_type = exc_typed.type_val.evaluate_lazily(env)
            if not isinstance(exc_type, QExceptionType):
                raise TypeError(
                    f"Pattern in when branch must be an exception, got '{exc_type}'",
                    offset=branch.offset,
                )

            if branch.binder is not None:
                with env.scoped(f"try_{branch.binder}"):
                    binder_sym = ValueSymbol(name=branch.binder, type_val=exc_type.payload_type, is_var=False)
                    env.current_scope.declare_value(binder_sym)
                    if expected_type is not None:
                        h_body = self.check_expr(branch.body, expected_type, env, loop_depth)
                    else:
                        h_body = self.synth_expr(branch.body, env, loop_depth)
            else:
                binder_sym = None
                if expected_type is not None:
                    h_body = self.check_expr(branch.body, expected_type, env, loop_depth)
                else:
                    h_body = self.synth_expr(branch.body, env, loop_depth)

            typed_branches.append(
                TypedTryBranch(
                    exc_pattern=exc_typed,
                    body=h_body,
                    binder=binder_sym,
                    offset=branch.offset,
                )
            )

        if expr.else_branch is not None:
            if expected_type is not None:
                else_typed: Optional[TypedExpr] = self.check_expr(expr.else_branch, expected_type, env, loop_depth)
            else:
                else_typed = self.synth_expr(expr.else_branch, env, loop_depth)
        else:
            else_typed = None

        return body_typed, typed_branches, else_typed


    def _check_try_expr(
        self,
        expr: ast.ExprTry,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedTry:
        """Checks a try expression against an expected QType."""
        body_typed, typed_branches, else_typed = self._elaborate_try_branches(
            expr, expected_type, env, loop_depth
        )
        return TypedTry(
            body=body_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=expected_type,
            offset=expr.offset,
        )


    def _synth_try_expr(self, expr: ast.ExprTry, env: Environment, loop_depth: int) -> TypedTry:
        """Synthesizes a try expression by joining body and branch result types."""
        body_typed, typed_branches, else_typed = self._elaborate_try_branches(
            expr, None, env, loop_depth
        )
        all_types = [body_typed.type_val] + [b.body.type_val for b in typed_branches]
        if else_typed is not None:
            all_types.append(else_typed.type_val)

        join_type = self._join_types(
            all_types,
            env,
            expr.offset,
            error_msg="Cannot find common supertype join for try expression branch types '{t1}' and '{t2}'",
        )
        return TypedTry(
            body=body_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=join_type,
            offset=expr.offset,
        )


    def _elaborate_inspect_branches(
        self,
        expr: ast.ExprInspect,
        expected_type: Optional[QType],
        env: Environment,
        loop_depth: int,
    ) -> tuple[TypedExpr, list[TypedInspectBranch], Optional[TypedExpr]]:
        """Elaborates target, inspect branches, and optional else branch for an inspect expression."""
        target_typed = self.synth_expr(expr.target, env, loop_depth)
        target_type = target_typed.type_val.evaluate_lazily(env)
        if not is_subtype(target_type, DYNAMIC_TYPE, env):
            raise TypeError(f"Target of inspect must be Dynamic, got '{target_type}'", offset=expr.target.offset)

        typed_branches: list[TypedInspectBranch] = []
        for branch in expr.branches:
            match_t = elaborate_type(branch.match_type, env)
            if branch.binders:
                with env.scoped("inspect_branch"):
                    b_syms: list[ValueSymbol] = []
                    for name, _ in branch.binders:
                        b_sym = ValueSymbol(name=name, type_val=match_t, is_var=False)
                        env.current_scope.declare_value(b_sym)
                        b_syms.append(b_sym)
                    if expected_type is not None:
                        h_body = self.check_expr(branch.body, expected_type, env, loop_depth)
                    else:
                        h_body = self.synth_expr(branch.body, env, loop_depth)
                        b_ids = {s.symbol_id for s in b_syms}
                        check_no_escaping_path_types(
                            h_body.type_val,
                            b_ids,
                            "inspect branch scope",
                            branch.body.offset,
                        )
            else:
                b_syms = []
                if expected_type is not None:
                    h_body = self.check_expr(branch.body, expected_type, env, loop_depth)
                else:
                    h_body = self.synth_expr(branch.body, env, loop_depth)

            typed_branches.append(
                TypedInspectBranch(
                    match_type=match_t,
                    binders=tuple(b_syms),
                    body=h_body,
                    offset=branch.offset,
                )
            )

        if expr.else_branch is not None:
            if expected_type is not None:
                else_typed: Optional[TypedExpr] = self.check_expr(expr.else_branch, expected_type, env, loop_depth)
            else:
                else_typed = self.synth_expr(expr.else_branch, env, loop_depth)
        else:
            else_typed = None

        return target_typed, typed_branches, else_typed


    def _check_inspect_expr(
        self,
        expr: ast.ExprInspect,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedInspect:
        """Checks an inspect expression against an expected QType."""
        target_typed, typed_branches, else_typed = self._elaborate_inspect_branches(
            expr, expected_type, env, loop_depth
        )
        return TypedInspect(
            target=target_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=expected_type,
            offset=expr.offset,
        )


    def _synth_inspect_expr(self, expr: ast.ExprInspect, env: Environment, loop_depth: int) -> TypedInspect:
        """Synthesizes an inspect expression by joining branch result types."""
        target_typed, typed_branches, else_typed = self._elaborate_inspect_branches(
            expr, None, env, loop_depth
        )
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

        join_type = self._join_types(
            branch_types,
            env,
            expr.offset,
            error_msg="Cannot find common supertype join for inspect branch types '{t1}' and '{t2}'",
        )
        return TypedInspect(
            target=target_typed,
            branches=tuple(typed_branches),
            else_branch=else_typed,
            type_val=join_type,
            offset=expr.offset,
        )


    # ============================================================================
    # Phase 6: Phrase and Program Elaboration
    # ============================================================================


    def elaborate_phrase(
        self,
        phrase: ast.ASTNode,
        env: Optional[Environment] = None,
    ) -> TypedBinding | TypedExpr:
        """Elaborates a single top-level phrase (interface, module, import, binding, or expr)."""
        if env is None:
            env = self.env
        match phrase:
            case ast.InterfaceDecl():
                return elaborate_interface(phrase, env)
            case ast.ModuleDecl():
                return elaborate_module(phrase, env, self._elaborate_binding)
            case ast.ImportPhrase():
                return elaborate_import(phrase, env)
            case ast.BindingNode():
                return self._elaborate_binding(phrase, env, loop_depth=0)
            case ast.Expr():
                return self.synth_expr(phrase, env, loop_depth=0)
            case _:
                raise TypeError(
                    f"Unsupported top-level phrase '{phrase}'",
                    offset=getattr(phrase, "offset", 0),
                )


    def elaborate_program(
        self,
        program: ast.Program,
        env: Optional[Environment] = None,
    ) -> TypedProgram:
        """Elaborates a top-level Quest program unit (interfaces, modules, declarations, statements)."""
        if env is None:
            env = self.env

        typed_phrases = tuple(self.elaborate_phrase(phrase, env) for phrase in program.phrases)
        return TypedProgram(phrases=typed_phrases, offset=program.offset)


    # ============================================================================
    # Helpers for Infix, Conditionals, Loops, and Blocks
    # ============================================================================

    def _synth_infix_expr(self, expr: ast.ExprInfix, env: Environment, loop_depth: int) -> TypedExpr:
        """Synthesizes an infix expression (assignment, logic, arithmetic, comparison)."""
        # 1. Assignment (lhs := rhs)
        if expr.op == ":=":
            return self._synth_assignment(expr, env, loop_depth)

        # 2. Short-Circuit Logic (andif, orif) -> desugar to TypedIf
        if expr.op in ("andif", "orif"):
            left_typed = self.check_expr(expr.left, BOOL_TYPE, env, loop_depth)
            right_typed = self.check_expr(expr.right, BOOL_TYPE, env, loop_depth)
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
        left_typed = self.synth_expr(expr.left, env, loop_depth)
        right_typed = self.synth_expr(expr.right, env, loop_depth)

        if expr.op in ("+", "-", "*", "/", "mod", "%"):
            if is_subtype(left_typed.type_val, INT_TYPE, env):
                if not is_subtype(right_typed.type_val, INT_TYPE, env):
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

            if is_subtype(left_typed.type_val, REAL_TYPE, env):
                if expr.op in ("mod", "%"):
                    raise TypeError(f"Operator '{expr.op}' is not defined for Real", offset=expr.offset)
                if not is_subtype(right_typed.type_val, REAL_TYPE, env):
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
            l_t, r_t = left_typed.type_val, right_typed.type_val
            if (
                (is_subtype(l_t, INT_TYPE, env) and is_subtype(r_t, INT_TYPE, env))
                or (is_subtype(l_t, REAL_TYPE, env) and is_subtype(r_t, REAL_TYPE, env))
                or (is_subtype(l_t, CHAR_TYPE, env) and is_subtype(r_t, CHAR_TYPE, env))
                or (is_subtype(l_t, STRING_TYPE, env) and is_subtype(r_t, STRING_TYPE, env))
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


    def _synth_assignment(self, expr: ast.ExprInfix, env: Environment, loop_depth: int) -> TypedAssign:
        """Synthesizes an assignment expression: lhs := rhs."""
        match expr.left:
            # Target 1: Variable identifier
            case ast.ExprId(name=name, offset=id_off):
                sym = env.lookup_value(name)
                if sym is None:
                    raise TypeError(f"Undefined variable '{name}'", offset=id_off)
                if not sym.is_var:
                    raise TypeError(f"Cannot assign to immutable variable '{name}'", offset=id_off)

                target_node = TypedVar(
                    name=sym.name,
                    symbol=sym,
                    type_val=QVarType(sym.type_val),
                    offset=id_off,
                )
                rhs_typed = self.check_expr(expr.right, sym.type_val, env, loop_depth)
                return TypedAssign(target=target_node, value=rhs_typed, offset=expr.offset)

            # Target 2: Record field selection (r.field := rhs)
            case ast.ExprSelect(target=target, field=field, offset=sel_off):
                target_typed = self.synth_expr(target, env, loop_depth)
                target_type = target_typed.type_val.evaluate_lazily(env)
                if not isinstance(target_type, QRecordType):
                    raise TypeError(
                        f"Cannot mutate field of non-record type '{target_type}'",
                        offset=sel_off,
                    )
                rec_f = target_type.get_field(field)
                if rec_f is None:
                    raise TypeError(
                        f"Record has no field '{field}'",
                        offset=sel_off,
                    )
                if not rec_f.is_var:
                    raise TypeError(
                        f"Cannot assign to immutable record field '{field}'",
                        offset=sel_off,
                    )
                rhs_typed = self.check_expr(expr.right, rec_f.type_val, env, loop_depth)
                target_select = TypedSelect(
                    target=target_typed,
                    field=field,
                    type_val=rec_f.type_val,
                    offset=sel_off,
                )
                return TypedAssign(target=target_select, value=rhs_typed, offset=expr.offset)

            # Target 3: Array indexing (a[idx] := rhs)
            case ast.ExprIndex(target=target, index=index):
                return self._synth_index_assign_expr(
                    ast.ExprIndexAssign(target=target, index=index, value=expr.right, offset=expr.offset),
                    env,
                    loop_depth,
                )

            case _:
                raise TypeError("Assignment target must be a mutable variable or field", offset=expr.left.offset)


    def _desugar_if_else(self, expr: ast.ExprIf) -> ast.Expr:
        """Desugars elsif chains and optional else branch into a nested else AST expression."""
        desugared_else: ast.Expr = expr.else_branch if expr.else_branch else ast.ExprOk(offset=expr.offset)
        for elsif_cond, elsif_then in reversed(expr.elsifs):
            desugared_else = ast.ExprIf(
                cond=elsif_cond,
                then_branch=elsif_then,
                elsifs=(),
                else_branch=desugared_else,
                offset=elsif_cond.offset,
            )
        return desugared_else

    def _synth_if_expr(self, expr: ast.ExprIf, env: Environment, loop_depth: int) -> TypedIf:
        """Synthesizes an if expression."""
        cond_typed = self.check_expr(expr.cond, BOOL_TYPE, env, loop_depth)

        if expr.else_branch is None and not expr.elsifs:
            then_typed = self.synth_expr(expr.then_branch, env, loop_depth)
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

        desugared_else = self._desugar_if_else(expr)
        then_typed = self.synth_expr(expr.then_branch, env, loop_depth)
        else_typed = self.synth_expr(desugared_else, env, loop_depth)

        join_type = self._join_types(
            [then_typed.type_val, else_typed.type_val],
            env,
            expr.offset,
            error_msg="Cannot find common supertype for conditional branches '{t1}' and '{t2}'",
        )
        return TypedIf(
            cond=cond_typed,
            then_branch=then_typed,
            else_branch=else_typed,
            type_val=join_type,
            offset=expr.offset,
        )


    def _check_if_expr(
        self,
        expr: ast.ExprIf,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedIf:
        """Checks an if expression against an expected QType."""
        cond_typed = self.check_expr(expr.cond, BOOL_TYPE, env, loop_depth)
        desugared_else = self._desugar_if_else(expr)
        then_typed = self.check_expr(expr.then_branch, expected_type, env, loop_depth)
        else_typed = self.check_expr(desugared_else, expected_type, env, loop_depth)

        return TypedIf(
            cond=cond_typed,
            then_branch=then_typed,
            else_branch=else_typed,
            type_val=expected_type,
            offset=expr.offset,
        )


    def _synth_for_expr(self, expr: ast.ExprFor, env: Environment, loop_depth: int) -> TypedFor:
        """Synthesizes a for loop expression: for i = start upto/downto stop do body end."""
        start_typed = self.check_expr(expr.start, INT_TYPE, env, loop_depth)
        stop_typed = self.check_expr(expr.stop, INT_TYPE, env, loop_depth)

        with env.scoped(f"for_{expr.var_name}"):
            loop_var_sym = ValueSymbol(name=expr.var_name, type_val=INT_TYPE, is_var=False)
            env.current_scope.declare_value(loop_var_sym)
            self.loop_depth = loop_depth
            with self.in_loop():
                body_typed = self.synth_expr(expr.body, env, self.loop_depth)

        return TypedFor(
            var_name=expr.var_name,
            symbol=loop_var_sym,
            start=start_typed,
            is_downto=expr.is_downto,
            stop=stop_typed,
            body=body_typed,
            offset=expr.offset,
        )


    def _synth_block_expr(self, expr: ast.ExprBlock, env: Environment, loop_depth: int) -> TypedBlock:
        """Synthesizes a scoped block expression: begin bindings... result end."""
        with env.scoped("block") as block_scope:
            typed_bindings: list[TypedBinding] = []
            for binding in expr.bindings:
                typed_b = self._elaborate_binding(binding, env, loop_depth)
                typed_bindings.append(typed_b)

            if typed_bindings and isinstance(typed_bindings[-1], TypedExprStmt):
                last_stmt = typed_bindings.pop()
                assert isinstance(last_stmt, TypedExprStmt)
                result_expr = last_stmt.expr
                result_type = result_expr.type_val
            else:
                result_expr = TypedOk(offset=expr.offset)
                result_type = OK_TYPE

            local_symbol_ids = {sym.symbol_id for sym in block_scope.values.values()}
            check_no_escaping_path_types(result_type, local_symbol_ids, "its scope", result_expr.offset)

            return TypedBlock(
                bindings=tuple(typed_bindings),
                result=result_expr,
                type_val=result_type,
                offset=expr.offset,
            )


    def _check_block_expr(
        self,
        expr: ast.ExprBlock,
        expected_type: QType,
        env: Environment,
        loop_depth: int,
    ) -> TypedBlock:
        """Checks a scoped block expression against an expected QType."""
        with env.scoped("block"):
            typed_bindings: list[TypedBinding] = []
            for binding in expr.bindings[:-1]:
                typed_b = self._elaborate_binding(binding, env, loop_depth)
                typed_bindings.append(typed_b)

            if expr.bindings:
                last_binding = expr.bindings[-1]
                if isinstance(last_binding, ast.ExprStmt):
                    result_expr = self.check_expr(last_binding.expr, expected_type, env, loop_depth)
                else:
                    typed_b = self._elaborate_binding(last_binding, env, loop_depth)
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


    def _elaborate_binding(self, binding: ast.BindingNode, env: Environment, loop_depth: int) -> TypedBinding:
        """Elaborates a single binding or statement inside a block or module."""
        match binding:
            case ast.InterfaceDecl():
                return elaborate_interface(binding, env)

            case ast.ModuleDecl():
                return elaborate_module(binding, env, self._elaborate_binding)

            case ast.ExprException():
                typed_exc = self._synth_exception_expr(binding, env, loop_depth)
                return TypedExprStmt(expr=typed_exc, offset=binding.offset)

            case ast.ExprStmt(expr=ast.ExprException() as exc):
                typed_exc = self._synth_exception_expr(exc, env, loop_depth)
                return TypedExprStmt(expr=typed_exc, offset=binding.offset)

            case ast.ExprStmt(expr=expr):
                typed_e = self.synth_expr(expr, env, loop_depth)
                return TypedExprStmt(expr=typed_e, offset=binding.offset)

            case ast.LetValueBinding(params=params, is_rec=is_rec) if params:
                fn_expr = ast.ExprFun(
                    params=params,
                    return_type=binding.type_annot,
                    body=binding.value,
                    offset=binding.offset,
                )
                if is_rec:
                    if binding.type_annot is None:
                        raise TypeError(
                            f"Recursive function '{binding.name}' requires an explicit return type annotation",
                            offset=binding.offset,
                        )
                    for p in params:
                        if p.type_annot is None:
                            raise TypeError(
                                f"Parameter '{p.name}' in recursive function '{binding.name}' "
                                f"requires an explicit type annotation",
                                offset=p.offset,
                            )
                    param_types = tuple(
                        elaborate_type(p.type_annot, env)
                        for p in params
                    )
                    ret_type = elaborate_type(binding.type_annot, env)
                    q_params = tuple(
                        QParam(
                            name=p.name,
                            type_val=param_types[i],
                            is_var=(p.mode == ast.ParamMode.VAR),
                            is_out=(p.mode == ast.ParamMode.OUT),
                        )
                        for i, p in enumerate(params)
                    )
                    rec_fn_type = QFunType(params=q_params, result_type=ret_type)
                    rec_sym = ValueSymbol(name=binding.name, type_val=rec_fn_type)
                    env.current_scope.declare_value(rec_sym)

                    typed_val = self.check_expr(fn_expr, rec_fn_type, env, loop_depth=0)
                    return TypedLetValue(
                        name=binding.name,
                        value=typed_val,
                        symbol=rec_sym,
                        is_rec=True,
                        offset=binding.offset,
                    )
                else:
                    typed_val = self.synth_expr(fn_expr, env, loop_depth)
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

            case ast.LetValueBinding(is_rec=True):
                if binding.type_annot is None:
                    raise TypeError(
                        f"Recursive definition '{binding.name}' requires an explicit type annotation",
                        offset=binding.offset,
                    )
                expected = elaborate_type(binding.type_annot, env)
                sym = ValueSymbol(name=binding.name, type_val=expected, is_var=binding.is_var)
                env.current_scope.declare_value(sym)
                typed_val = self.check_expr(binding.value, expected, env, loop_depth)
                return TypedLetValue(
                    name=binding.name,
                    value=typed_val,
                    symbol=sym,
                    is_rec=True,
                    offset=binding.offset,
                )

            case ast.LetValueBinding():
                if binding.type_annot is not None:
                    expected = elaborate_type(binding.type_annot, env)
                    typed_val = self.check_expr(binding.value, expected, env, loop_depth)
                    val_type = expected
                else:
                    typed_val = self.synth_expr(binding.value, env, loop_depth)
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

            case ast.LetTypeBinding() | ast.DefTypeBinding():
                sym = elaborate_type_binding(binding, env)
                return TypedLetType(name=binding.name, symbol=sym, offset=binding.offset)

            case ast.DefKindBinding():
                k_sym = elaborate_kind_binding(binding, env)
                return TypedDefKind(name=binding.name, symbol=k_sym, offset=binding.offset)

            case _:
                raise TypeError(f"Unsupported binding '{binding}'", offset=getattr(binding, "offset", 0))


# ============================================================================
# Public Module-Level Facade Functions
# ============================================================================

def check_expr(
    expr: ast.Expr,
    expected_type: QType,
    env: Optional[Environment] = None,
    loop_depth: int = 0,
) -> TypedExpr:
    """Checks an AST expression against an expected QType (Gamma |- e <= T)."""
    return TypeElaborator(env=env, loop_depth=loop_depth).check_expr(
        expr, expected_type, env=env, loop_depth=loop_depth
    )


def synth_expr(
    expr: ast.Expr,
    env: Optional[Environment] = None,
    loop_depth: int = 0,
) -> TypedExpr:
    """Synthesizes the minimal QType and elaborated TypedExpr (Gamma |- e => T)."""
    return TypeElaborator(env=env, loop_depth=loop_depth).synth_expr(
        expr, env=env, loop_depth=loop_depth
    )


def elaborate_phrase(
    phrase: ast.ASTNode,
    env: Optional[Environment] = None,
) -> TypedBinding | TypedExpr:
    """Elaborates a single top-level phrase (interface, module, import, binding, or expr)."""
    return TypeElaborator(env=env).elaborate_phrase(phrase, env=env)


def elaborate_program(
    program: ast.Program,
    env: Optional[Environment] = None,
) -> TypedProgram:
    """Elaborates a top-level Quest program unit (interfaces, modules, declarations, statements)."""
    return TypeElaborator(env=env).elaborate_program(program, env=env)


def _elaborate_binding(
    binding: ast.BindingNode,
    env: Optional[Environment] = None,
    loop_depth: int = 0,
) -> TypedBinding:
    """Elaborates a single binding or statement inside a block or module."""
    return TypeElaborator(env=env, loop_depth=loop_depth)._elaborate_binding(
        binding, env=env, loop_depth=loop_depth
    )
