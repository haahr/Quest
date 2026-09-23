"""C Code Generator for Quest AST (Emitting Standard ISO C99)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quest.builtins import BuiltinModuleRegistry
from quest.codegen.c_analysis import (
    CLambdaInfo,
    CProgramAnalysis,
    analyze_program_for_c,
    collect_fun_quantifiers,
    topological_sort_modules,
)
from quest.codegen.c_declarations import CDeclarationEmitter
from quest.codegen.c_types import (
    RecordNamingContext,
    c_char_literal,
    c_string_literal,
    closure_fn_ptr_type,
    is_record_subtype,
    is_tuple_subtype,
    is_variant_subtype,
    mangle_ident,
    mangle_module_ident,
    normalize_type,
    option_struct_name,
    qtype_to_c_type,
    qtype_to_name_str,
    qval_unwrap,
    qval_wrap,
    record_struct_name,
    tuple_struct_name,
    type_to_c_tag,
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
    TypedExternal,
    TypedExpr,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedImport,
    TypedIndex,
    TypedIndexAssign,
    TypedIndexRef,
    TypedInfix,
    TypedInspect,
    TypedInspectBranch,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedModule,
    TypedNativeBinding,
    TypedNode,
    TypedOk,
    TypedOption,
    TypedParam,
    TypedProgram,
    TypedRaise,
    TypedReal,
    TypedRecord,
    TypedRecordField,
    TypedSelect,
    TypedSelectRef,
    TypedTupleSelectRef,
    TypedString,
    TypedTuple,
    TypedTry,
    TypedTryBranch,
    TypedTypeApp,
    TypedTypeWitness,
    TypedVar,
    TypedVarCell,
    TypedVariant,
    TypedVariantAssert,
    TypedVariantCheck,
    TypedWhile,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    INFIX_OPERATORS,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QAbstractType,
    QAllType,
    QArrayType,
    QExceptionType,
    QExternalType,
    QFunType,
    QOptionType,
    QQuantifier,
    QRecordField,
    QRecordType,
    QPathType,
    QTupleField,
    QTupleType,
    QTupleTypeBinding,
    QTupleTypeFormal,
    QType,
    QTypeVar,
    QVarType,
    QOutType,
    QVariantType,
    resolve_record_bound,
    resolve_variant_bound,
    resolve_option_bound,
)


# Backward-compatibility alias
LambdaInfo = CLambdaInfo

# Aliases for functions moved to c_types
_c_string_literal = c_string_literal
_c_char_literal = c_char_literal
_qval_wrap = qval_wrap
_closure_fn_ptr_type = closure_fn_ptr_type


def _qval_unwrap(qval_expr: str, t: QType, emitter: Optional[Any] = None) -> str:
    ctx = emitter.record_ctx if emitter is not None else None
    return qval_unwrap(qval_expr, t, ctx)


def _indent(text: str, spaces: int = 4) -> str:
    """Indents non-empty lines of text by the given number of spaces."""
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


class CEmitter:
    """Translates typed Quest AST nodes into standard C99 source code."""

    def __init__(
        self,
        echo: bool = False,
        print_result: bool = False,
        module_prefix: Optional[str] = None,
    ):
        self.echo = echo
        self.print_result = print_result
        self.module_prefix = module_prefix
        self._tmp_id = 0
        self.top_fun_names: set[str] = set()
        self.top_var_names: set[str] = set()
        self.val_referenced_top_funs: set[str] = set()
        self.lambda_info_by_id: dict[int, LambdaInfo] = {}
        self.lifted_lambdas: list[LambdaInfo] = []
        self.current_env_vars: dict[str, str] = {}
        self.record_ctx = RecordNamingContext()
        self.needed_dicts: set[tuple[QRecordType, QRecordType]] = set()
        self.tuple_coercions: set[tuple[QTupleType, QTupleType]] = set()
        self.variant_coercions: set[tuple[QVariantType, QVariantType]] = set()
        self.param_dict_names: dict[str, str] = {}
        self.var_dict_names: dict[str, str] = {}
        self.top_funs_dict: dict[str, tuple[TypedFun, Any]] = {}
        self.in_scope_type_descriptors: dict[str, str] = {}
        self.specializations: dict[tuple[str, tuple[QType, ...]], tuple[str, TypedFun]] = {}
        self.all_modules: dict[str, TypedModule] = {}
        self.pointer_params: set[str] = set()
        self.adapter_defs: list[str] = []
        self.adapter_cache: dict[tuple[QType, QType], str] = {}

    def c_type(self, t: QType) -> str:
        return qtype_to_c_type(t, self.record_ctx)

    def c_type_descriptor(self, t: QType) -> str:
        """Returns the C expression evaluating to `const QTypeDescriptor *` for type `t`."""
        t = t.prune() if hasattr(t, "prune") else t
        t = normalize_type(t)
        if t == INT_TYPE:
            return "&quest_type_Int"
        if t == REAL_TYPE:
            return "&quest_type_Real"
        if t == BOOL_TYPE:
            return "&quest_type_Bool"
        if t == CHAR_TYPE:
            return "&quest_type_Char"
        if t == STRING_TYPE:
            return "&quest_type_String"
        if t == OK_TYPE:
            return "&quest_type_Ok"
        if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
            return "&quest_type_Dynamic"
        if isinstance(t, QTupleType) and not t.fields:
            return "&quest_type_EmptyTuple"
        if isinstance(t, QRecordType) or (rec_b := resolve_record_bound(t)) is not None:
            rec_t = t if isinstance(t, QRecordType) else rec_b
            tag = record_struct_name(rec_t, self.record_ctx)
            return f"(&quest_type_{tag})"
        if isinstance(t, QTupleType):
            tag = tuple_struct_name(t)
            return f"(&quest_type_{tag})"
        if isinstance(t, QVariantType) or (var_b := resolve_variant_bound(t)) is not None:
            var_t = t if isinstance(t, QVariantType) else var_b
            tag = type_to_c_tag(var_t)
            return f"(&quest_type_{tag})"
        if isinstance(t, QOptionType) or (opt_b := resolve_option_bound(t)) is not None:
            opt_t = t if isinstance(t, QOptionType) else opt_b
            tag = option_struct_name(opt_t)
            return f"(&quest_type_{tag})"
        if isinstance(t, QArrayType):
            elem_tag = type_to_c_tag(t.element_type)
            return f"(&quest_type_array_{elem_tag})"
        if isinstance(t, QExternalType):
            name = t.name or t.c_type
            tag = f"opaque_{mangle_ident(name)}"
            return f"(&quest_type_{tag})"
        if isinstance(t, QTypeVar):
            if t.name in self.in_scope_type_descriptors:
                return self.in_scope_type_descriptors[t.name]
            tag = f"opaque_{mangle_ident(t.name)}"
            return f"(&quest_type_{tag})"
        if isinstance(t, QAbstractType):
            if t.name in self.in_scope_type_descriptors:
                return self.in_scope_type_descriptors[t.name]
            tag = f"opaque_{mangle_ident(t.name)}"
            return f"(&quest_type_{tag})"
        if isinstance(t, (QFunType, QAllType)):
            tag = f"fun_{type_to_c_tag(t)}"
            return f"(&quest_type_{tag})"
        return "&quest_type_EmptyTuple"

    def record_struct_name(self, t: QRecordType) -> str:
        return record_struct_name(t, self.record_ctx)

    def _is_exact_record_literal(self, t: QType, val: TypedExpr) -> bool:
        if not isinstance(t, QRecordType) or not isinstance(val, TypedRecord):
            return False
        if len(t.fields) != len(val.fields):
            return False
        t_fields = {f.name: f.type_val for f in t.fields}
        for fld in val.fields:
            if fld.name not in t_fields or t_fields[fld.name] != fld.value.type_val:
                return False
        return True

    def mangle_ident(self, name: str) -> str:
        """Mangles an identifier using module_prefix if set."""
        if self.module_prefix:
            return mangle_module_ident(self.module_prefix, name)
        return mangle_ident(name)

    def _collect_fun_quantifiers(self, fun_type: QType) -> tuple[tuple[QQuantifier, ...], QType]:
        """Extracts any universal quantifiers wrapping a function type."""
        quants: tuple[QQuantifier, ...] = ()
        curr = fun_type
        while isinstance(curr, QAllType):
            quants = quants + curr.quantifiers
            curr = curr.body
        return quants, curr

    def _param_c_decl(self, p: TypedParam, ident: str) -> str:
        ptr = " *" if getattr(p, "is_out", False) or getattr(p, "is_var", False) else " "
        return f"{self.c_type(p.type_val)}{ptr}{ident}"

    def _param_signatures(
        self,
        params: list[TypedParam],
        quantifiers: tuple[QQuantifier, ...] = (),
    ) -> tuple[list[str], list[str]]:
        decls: list[str] = []
        forward_args: list[str] = []

        # 1. Preceding quantifier type descriptors
        for q in quantifiers:
            q_param = f"descriptor_{q.name}"
            decls.append(f"const QTypeDescriptor *{q_param}")
            forward_args.append(q_param)

        # 2. Value parameters
        for p in params:
            p_c = self.mangle_ident(p.name)
            decls.append(self._param_c_decl(p, p_c))
            forward_args.append(p_c)
        return decls, forward_args

    def fresh_tmp(self, prefix: str = "_tmp") -> str:
        """Generates a unique temporary C identifier."""
        self._tmp_id += 1
        return f"{prefix}_{self._tmp_id}"

    def _collect_fun_params(
        self, fun: TypedFun
    ) -> tuple[tuple[QQuantifier, ...], list[TypedParam], TypedExpr, QType]:
        """Extracts quantifiers, formal parameters, body, and return type of a function."""
        quants, inner_type = self._collect_fun_quantifiers(fun.type_val)
        ret_type = inner_type.result_type if isinstance(inner_type, QFunType) else inner_type
        return quants, list(fun.params), fun.body, ret_type

    def _collect_fun_type_params(
        self, fun_type: QType
    ) -> tuple[tuple[QQuantifier, ...], list[tuple[str, QType]], QType]:
        """Extracts quantifiers, parameters, and return type directly from a QFunType or QAllType."""
        quants, inner_type = self._collect_fun_quantifiers(fun_type)
        if isinstance(inner_type, QFunType):
            params = [(p.name, p.type_val) for p in inner_type.params]
            ret_type = inner_type.result_type
        else:
            params = []
            ret_type = inner_type
        return quants, params, ret_type

    def _collect_app_args(self, app: TypedApp) -> tuple[TypedExpr, list[TypedExpr]]:
        """Flattens nested curried TypedApp nodes into target function and argument list."""
        args = list(app.args)
        curr = app.func
        while isinstance(curr, TypedApp):
            args = list(curr.args) + args
            curr = curr.func
        return curr, args

    def _effective_record_type(self, expr: TypedExpr) -> QType:
        """Extracts the concrete QRecordType if expr is a TypedRecord, otherwise returns expr.type_val."""
        if isinstance(expr, TypedRecord):
            return QRecordType(
                fields=tuple(
                    QRecordField(name=f.name, type_val=f.value.type_val, is_var=f.is_var)
                    for f in expr.fields
                )
            )
        return expr.type_val

    def _coerce_record_val(self, c_expr: str, expr: TypedExpr, target_type: QRecordType) -> str:
        """Coerces a record expression to target_type by attaching an offset dictionary if subtyped."""
        actual_t = self._effective_record_type(expr)
        if isinstance(actual_t, QRecordType) and actual_t != target_type:
            d_name = self.record_ctx.offset_dict_instance_name(target_type, actual_t)
            return f"((QRecordVal){{ .val = {c_expr}.val, .dict = (const void *)&{d_name} }})"
        return c_expr

    def _emit_variant_upcast(
        self,
        c_val: str,
        source_t: QVariantType,
        target_t: QVariantType,
        lines: list[str],
        dest: Optional[str] = None,
    ) -> str:
        """Remaps tag and copies payload into an unboxed QVariantVal."""
        tmp_src = self.fresh_tmp("_vsrc")
        lines.append(f"QVariantVal {tmp_src} = {c_val};")
        tagmap_name = f"tagmap_{type_to_c_tag(target_t)}_{type_to_c_tag(source_t)}"
        tmp_v = dest if dest is not None else self.fresh_tmp("_vup")
        if dest is None:
            lines.append(
                f"QVariantVal {tmp_v} = (QVariantVal){{ "
                f".tag = {tagmap_name}[{tmp_src}.tag], "
                f".payload = {tmp_src}.payload }};"
            )
        else:
            lines.append(
                f"{tmp_v} = (QVariantVal){{ "
                f".tag = {tagmap_name}[{tmp_src}.tag], "
                f".payload = {tmp_src}.payload }};"
            )
        return tmp_v

    def _emit_closure_adaptation(
        self,
        c_closure: str,
        orig_t: QType,
        target_t: QType,
        lines: list[str],
    ) -> str:
        """Emits an adaptation thunk closure if orig_t and target_t closure signatures differ."""
        orig_fn_ptr = _closure_fn_ptr_type(orig_t, self.record_ctx)
        target_fn_ptr = _closure_fn_ptr_type(target_t, self.record_ctx)
        if orig_fn_ptr == target_fn_ptr:
            return c_closure

        cache_key = (orig_t, target_t)
        if cache_key in self.adapter_cache:
            adapt_fn_name = self.adapter_cache[cache_key]
        else:
            adapt_fn_name = self.fresh_tmp("qv_adapt")
            self.adapter_cache[cache_key] = adapt_fn_name

            _, inner_tgt = self._collect_fun_quantifiers(target_t)
            _, inner_orig = self._collect_fun_quantifiers(orig_t)

            tgt_params = inner_tgt.params if isinstance(inner_tgt, QFunType) else ()
            orig_params = inner_orig.params if isinstance(inner_orig, QFunType) else ()
            tgt_ret_t = inner_tgt.result_type if isinstance(inner_tgt, QFunType) else OK_TYPE
            orig_ret_t = inner_orig.result_type if isinstance(inner_orig, QFunType) else OK_TYPE

            ret_c = "void" if tgt_ret_t == OK_TYPE else self.c_type(tgt_ret_t)

            param_decls = ["void *_raw_env"]
            call_args = []
            for idx, tp in enumerate(tgt_params):
                op = orig_params[idx] if idx < len(orig_params) else tp
                arg_name = f"qv_arg_{idx}"
                tp_c = self.c_type(tp.type_val)
                param_decls.append(f"{tp_c} {arg_name}")

                tp_tag = qtype_to_c_type(tp.type_val, self.record_ctx)
                op_tag = qtype_to_c_type(op.type_val, self.record_ctx)
                if tp_tag == "QVal" and op_tag != "QVal":
                    call_args.append(_qval_unwrap(arg_name, op.type_val, self))
                elif tp_tag != "QVal" and op_tag == "QVal":
                    call_args.append(_qval_wrap(arg_name, tp.type_val))
                else:
                    call_args.append(arg_name)

            sig = ", ".join(param_decls)
            fn_body: list[str] = [
                f"static Q_UNUSED {ret_c} {adapt_fn_name}({sig}) {{",
                "    QClosure *orig = (QClosure *)_raw_env;",
            ]
            args_str = ", ".join(["orig->env"] + call_args)
            call_expr = f"(({orig_fn_ptr})(orig->fn))({args_str})"

            tgt_ret_tag = qtype_to_c_type(tgt_ret_t, self.record_ctx)
            orig_ret_tag = qtype_to_c_type(orig_ret_t, self.record_ctx)

            if tgt_ret_t == OK_TYPE:
                fn_body.append(f"    {call_expr};")
                fn_body.append("    return;")
            elif tgt_ret_tag == "QVal" and orig_ret_tag != "QVal":
                wrapped = _qval_wrap(call_expr, orig_ret_t)
                fn_body.append(f"    return {wrapped};")
            elif tgt_ret_tag != "QVal" and orig_ret_tag == "QVal":
                unwrapped = _qval_unwrap(call_expr, tgt_ret_t, self)
                fn_body.append(f"    return {unwrapped};")
            else:
                fn_body.append(f"    return {call_expr};")
            fn_body.append("}")
            fn_body.append("")
            self.adapter_defs.extend(fn_body)

        clo_tmp = self.fresh_tmp("_adapt_clo")
        lines.append(f"QClosure *{clo_tmp} = (QClosure *)quest_alloc(sizeof(QClosure));")
        lines.append(f"{clo_tmp}->fn = (void *){adapt_fn_name};")
        lines.append(f"{clo_tmp}->env = (void *)({c_closure});")
        return clo_tmp

    def _coerce_tuple_val(
        self,
        c_val: str,
        source_t: QTupleType,
        target_t: QTupleType,
        lines: list[str],
        dest: Optional[str] = None,
    ) -> str:
        """Coerces source_t tuple to target_t, copying and wrapping fields if representations differ."""
        target_struct = tuple_struct_name(target_t)
        source_struct = tuple_struct_name(source_t)

        def _field_can_direct_cast(sf: QType, tf: QType) -> bool:
            if qtype_to_c_type(sf, self.record_ctx) != qtype_to_c_type(tf, self.record_ctx):
                return False
            if isinstance(tf, QRecordType) and isinstance(sf, QRecordType) and sf != tf:
                return False
            if isinstance(tf, QVariantType) and isinstance(sf, QVariantType) and sf != tf:
                return False
            if isinstance(tf, (QFunType, QAllType)) and isinstance(sf, (QFunType, QAllType)):
                if _closure_fn_ptr_type(tf, self.record_ctx) != _closure_fn_ptr_type(sf, self.record_ctx):
                    return False
            return True

        fields_match = len(source_t.value_fields) >= len(target_t.value_fields) and all(
            _field_can_direct_cast(
                source_t.value_fields[i].type_val, target_t.value_fields[i].type_val
            )
            for i in range(len(target_t.value_fields))
        )
        if fields_match:
            cast_expr = f"(({target_struct} *){c_val})"
            if dest is not None:
                lines.append(f"{dest} = {cast_expr};")
                return dest
            return cast_expr

        res_tmp = dest if dest is not None else self.fresh_tmp("_tup_up")
        alloc_expr = f"({target_struct} *)quest_alloc(sizeof({target_struct}))"
        if dest is None:
            lines.append(f"{target_struct} *{res_tmp} = {alloc_expr};")
        else:
            lines.append(f"{res_tmp} = {alloc_expr};")

        tmp_src = self.fresh_tmp("_tsrc")
        lines.append(f"{source_struct} *{tmp_src} = {c_val};")

        for i, tgt_vf in enumerate(target_t.value_fields):
            src_vf = source_t.value_fields[i]
            src_field_access = f"{tmp_src}->_{i}"
            tgt_field_c_t = qtype_to_c_type(tgt_vf.type_val, self.record_ctx)
            src_field_c_t = qtype_to_c_type(src_vf.type_val, self.record_ctx)

            if tgt_field_c_t == "QVal" and src_field_c_t != "QVal":
                wrapped = _qval_wrap(src_field_access, src_vf.type_val)
                lines.append(f"{res_tmp}->_{i} = {wrapped};")
            elif tgt_field_c_t != "QVal" and src_field_c_t == "QVal":
                unwrapped = _qval_unwrap(src_field_access, tgt_vf.type_val, self)
                lines.append(f"{res_tmp}->_{i} = {unwrapped};")
            elif (
                isinstance(tgt_vf.type_val, (QFunType, QAllType))
                and isinstance(src_vf.type_val, (QFunType, QAllType))
                and _closure_fn_ptr_type(tgt_vf.type_val, self.record_ctx)
                != _closure_fn_ptr_type(src_vf.type_val, self.record_ctx)
            ):
                adapted = self._emit_closure_adaptation(
                    src_field_access, src_vf.type_val, tgt_vf.type_val, lines
                )
                lines.append(f"{res_tmp}->_{i} = {adapted};")
            elif (
                isinstance(tgt_vf.type_val, QTupleType)
                and isinstance(src_vf.type_val, QTupleType)
                and src_vf.type_val != tgt_vf.type_val
            ):
                coerced = self._coerce_tuple_val(
                    src_field_access, src_vf.type_val, tgt_vf.type_val, lines
                )
                lines.append(f"{res_tmp}->_{i} = {coerced};")
            elif (
                isinstance(tgt_vf.type_val, QRecordType)
                and isinstance(src_vf.type_val, QRecordType)
                and src_vf.type_val != tgt_vf.type_val
            ):
                d_name = self.record_ctx.offset_dict_instance_name(
                    tgt_vf.type_val, src_vf.type_val
                )
                lines.append(
                    f"{res_tmp}->_{i} = ((QRecordVal){{ .val = {src_field_access}.val, "
                    f".dict = (const void *)&{d_name} }});"
                )
            elif (
                isinstance(tgt_vf.type_val, QVariantType)
                and isinstance(src_vf.type_val, QVariantType)
                and src_vf.type_val != tgt_vf.type_val
            ):
                v_up = self._emit_variant_upcast(
                    src_field_access, src_vf.type_val, tgt_vf.type_val, lines
                )
                lines.append(f"{res_tmp}->_{i} = {v_up};")
            else:
                lines.append(f"{res_tmp}->_{i} = {src_field_access};")
        return res_tmp

    def _emit_fun_return(self, body: TypedExpr, ret_type: QType, fn_lines: list[str]) -> None:
        """Emits function return handling with appropriate subtyping coercions."""
        if ret_type == OK_TYPE:
            self.emit_to(body, None, fn_lines)
            fn_lines.append("return;")
        elif isinstance(ret_type, QRecordType):
            ret_val = self.emit_val(body, fn_lines)
            coerced = self._coerce_record_val(ret_val, body, ret_type)
            fn_lines.append(f"return {coerced};")
        elif (rec_bound := resolve_record_bound(ret_type)) is not None:
            ret_val = self.emit_val(body, fn_lines)
            coerced = self._coerce_record_val(ret_val, body, rec_bound)
            fn_lines.append(f"return {coerced};")
        elif (
            isinstance(ret_type, QTupleType)
            and isinstance(body.type_val, QTupleType)
            and body.type_val != ret_type
        ):
            ret_val = self.emit_val(body, fn_lines)
            coerced = self._coerce_tuple_val(ret_val, body.type_val, ret_type, fn_lines)
            fn_lines.append(f"return {coerced};")
        elif (
            isinstance(ret_type, QVariantType)
            and isinstance(body.type_val, QVariantType)
            and body.type_val != ret_type
        ):
            ret_val = self.emit_val(body, fn_lines)
            tmp_v = self._emit_variant_upcast(ret_val, body.type_val, ret_type, fn_lines)
            fn_lines.append(f"return {tmp_v};")
        elif (var_bound := resolve_variant_bound(ret_type)) is not None:
            ret_val = self.emit_val(body, fn_lines)
            if isinstance(body.type_val, QVariantType) and body.type_val != var_bound:
                tmp_v = self._emit_variant_upcast(ret_val, body.type_val, var_bound, fn_lines)
                fn_lines.append(f"return {tmp_v};")
            else:
                fn_lines.append(f"return {ret_val};")
        elif self.c_type(ret_type) == "QVal":
            ret_val = self.emit_val(body, fn_lines)
            fn_lines.append(f"return {_qval_wrap(ret_val, body.type_val)};")
        else:
            ret_val = self.emit_val(body, fn_lines)
            fn_lines.append(f"return {ret_val};")

    def _emit_call_arg(
        self,
        formal_t: QType,
        actual_a: TypedExpr,
        lines: list[str],
        is_ref: bool = False,
        is_out: bool = False,
        writebacks: Optional[list[str]] = None,
    ) -> str:
        """Emits and coerces an argument at a function or closure call site."""
        is_ref = (
            is_ref
            or isinstance(actual_a.type_val, (QVarType, QOutType))
            or isinstance(
                actual_a,
                (TypedIndexRef, TypedTupleSelectRef, TypedSelectRef, TypedVarCell),
            )
        )
        if is_ref:
            formal_c = qtype_to_c_type(formal_t, self.record_ctx)
            actual_elem_t = actual_a.type_val
            if isinstance(actual_elem_t, (QVarType, QOutType)):
                actual_elem_t = actual_elem_t.element_type
            actual_c = qtype_to_c_type(actual_elem_t, self.record_ctx)

            if formal_c == "QVal" and actual_c != "QVal" and writebacks is not None:
                if isinstance(actual_a, TypedVar):
                    c_name = self.current_env_vars.get(
                        actual_a.name, self.mangle_ident(actual_a.name)
                    )
                    loc_ptr = c_name if actual_a.name in self.pointer_params else f"(&{c_name})"
                elif isinstance(actual_a, TypedVarCell):
                    tmp = self.fresh_tmp("_var_cell")
                    c_t = self.c_type(actual_a.value.type_val)
                    c_v = self.emit_val(actual_a.value, lines)
                    lines.append(f"{c_t} {tmp} = {c_v};")
                    loc_ptr = f"(&{tmp})"
                elif isinstance(actual_a, (TypedIndexRef, TypedTupleSelectRef, TypedSelectRef)):
                    loc_ptr = self.emit_val(actual_a, lines)
                else:
                    loc_ptr = self.emit_val(actual_a, lines)

                ptr_tmp = self.fresh_tmp("_loc_ptr")
                lines.append(f"{actual_c} *{ptr_tmp} = {loc_ptr};")

                shadow_tmp = self.fresh_tmp("_shadow_cell")
                lines.append(f"QVal {shadow_tmp};")

                if not is_out:
                    wrapped = _qval_wrap(f"(*{ptr_tmp})", actual_elem_t)
                    lines.append(f"{shadow_tmp} = {wrapped};")

                unwrapped = _qval_unwrap(shadow_tmp, actual_elem_t, self)
                writebacks.append(f"(*{ptr_tmp}) = {unwrapped};")
                return f"(&{shadow_tmp})"

            if isinstance(actual_a, TypedVar):
                c_name = self.current_env_vars.get(
                    actual_a.name, self.mangle_ident(actual_a.name)
                )
                if actual_a.name in self.pointer_params:
                    return c_name
                return f"(&{c_name})"
            elif isinstance(actual_a, TypedVarCell):
                tmp = self.fresh_tmp("_var_cell")
                c_t = self.c_type(actual_a.value.type_val)
                c_v = self.emit_val(actual_a.value, lines)
                lines.append(f"{c_t} {tmp} = {c_v};")
                return f"(&{tmp})"
            elif isinstance(actual_a, (TypedIndexRef, TypedTupleSelectRef, TypedSelectRef)):
                return self.emit_val(actual_a, lines)

        c_a = self.emit_val(actual_a, lines)
        if isinstance(formal_t, QRecordType):
            return self._coerce_record_val(c_a, actual_a, formal_t)
        elif (rec_bound := resolve_record_bound(formal_t)) is not None:
            return self._coerce_record_val(c_a, actual_a, rec_bound)
        elif (
            isinstance(formal_t, QTupleType)
            and isinstance(actual_a.type_val, QTupleType)
            and actual_a.type_val != formal_t
        ):
            return self._coerce_tuple_val(c_a, actual_a.type_val, formal_t, lines)
        elif (
            isinstance(formal_t, QVariantType)
            and isinstance(actual_a.type_val, QVariantType)
            and actual_a.type_val != formal_t
        ):
            return self._emit_variant_upcast(c_a, actual_a.type_val, formal_t, lines)
        elif (var_bound := resolve_variant_bound(formal_t)) is not None:
            if isinstance(actual_a.type_val, QVariantType) and actual_a.type_val != var_bound:
                return self._emit_variant_upcast(c_a, actual_a.type_val, var_bound, lines)
            return c_a
        elif resolve_option_bound(formal_t) is not None:
            return c_a
        elif self.c_type(formal_t) == "QVal":
            return _qval_wrap(c_a, actual_a.type_val)
        else:
            return c_a

    def _emit_array_get(self, c_arr: str, c_idx: str, elem_t: QType) -> str:
        """Emits C expression to extract an element of type elem_t from a QArray slot."""
        if elem_t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
            return f"({c_arr}->data[{c_idx}].i)"
        elif elem_t == REAL_TYPE:
            return f"({c_arr}->data[{c_idx}].r)"
        elif isinstance(elem_t, QRecordType) or resolve_record_bound(elem_t) is not None:
            return f"({c_arr}->data[{c_idx}])"
        elif isinstance(elem_t, QVariantType) or resolve_variant_bound(elem_t) is not None:
            return f"({c_arr}->data[{c_idx}])"
        elif (
            elem_t == STRING_TYPE
            or elem_t == DYNAMIC_TYPE
            or (isinstance(elem_t, QTypeVar) and elem_t.name == "Dynamic.T")
            or isinstance(
                elem_t,
                (QTupleType, QFunType, QAllType, QArrayType, QOptionType, QExceptionType),
            )
            or resolve_option_bound(elem_t) is not None
        ):
            c_elem_t = self.c_type(elem_t)
            return f"(({c_elem_t})({c_arr}->data[{c_idx}].p))"
        else:
            return f"({c_arr}->data[{c_idx}])"

    def _tag_index(self, t: QType, tag: Optional[str]) -> int:
        """Returns the 0-based integer tag index for an Option or Variant tag."""
        if tag is None:
            return 0
        if isinstance(t, QOptionType) or (opt_bound := resolve_option_bound(t)) is not None:
            opt_t = t if isinstance(t, QOptionType) else opt_bound
            for i, opt in enumerate(opt_t.options):
                if opt.name == tag:
                    return i
        elif isinstance(t, QVariantType):
            for i, v in enumerate(t.variants):
                if v.name == tag:
                    return i
        return 0

    def _tuple_field_index(self, tuple_t: QTupleType, fld: str) -> int:
        """Resolves a tuple field name or index string to its 0-based value slot index."""
        for i, vf in enumerate(tuple_t.value_fields):
            if vf.name == fld:
                return i
        if fld.startswith("_") and fld[1:].isdigit():
            return int(fld[1:])
        if fld.isdigit():
            return int(fld)
        raise ValueError(f"Cannot resolve tuple field '{fld}' in {tuple_t}")

    def _emit_record_field_access(
        self,
        c_tgt: str,
        rec_t: QRecordType,
        fld: str,
        fld_t: QType,
        lines: list[str],
        as_ref: bool = False,
    ) -> str:
        """Emits field access on a QRecordVal using dynamic dictionary offsets."""
        if not c_tgt.isidentifier():
            tmp_r = self.fresh_tmp("_rec")
            lines.append(f"QRecordVal {tmp_r} = {c_tgt};")
            c_tgt = tmp_r
        c_fld_t = self.c_type(fld_t)
        dict_t = self.record_ctx.offset_dict_struct_name(rec_t)
        ptr_expr = f"(({c_fld_t} *)((char *){c_tgt}.val + ((const {dict_t} *){c_tgt}.dict)->offset_{fld}))"
        return ptr_expr if as_ref else f"(*{ptr_expr})"

    def _emit_qval_extract(self, qval_expr: str, elem_t: QType) -> str:
        """Extracts a scalar or pointer expression from a QVal union."""
        return _qval_unwrap(qval_expr, elem_t, self)

    def emit_program(
        self,
        prog: TypedProgram,
        loaded_modules: Optional[dict[str, TypedModule]] = None,
    ) -> str:
        """Translates a TypedProgram into a full standard C99 source file string."""
        analysis = analyze_program_for_c(prog, self.record_ctx, loaded_modules)

        self.needed_dicts = analysis.needed_dicts
        self.tuple_coercions = analysis.tuple_coercions
        self.variant_coercions = analysis.variant_coercions
        self.top_fun_names = analysis.top_fun_names
        self.top_var_names = analysis.top_var_names
        self.val_referenced_top_funs = analysis.val_referenced_top_funs
        self.lifted_lambdas = analysis.lifted_lambdas
        self.lambda_info_by_id = analysis.lambda_info_by_id
        self.top_funs_dict = analysis.top_funs_dict
        self.specializations = analysis.specializations

        decl_emitter = CDeclarationEmitter(
            record_ctx=self.record_ctx,
            c_type_fn=self.c_type,
            param_sigs_fn=self._param_signatures,
            collect_quants_fn=self._collect_fun_quantifiers,
            is_exact_record_literal_fn=self._is_exact_record_literal,
        )

        lines: list[str] = [
            "/* Emitted by Quest Bootstrap C Transpiler */",
            "#include \"quest_runtime.h\"",
            "",
        ]

        lines.extend(decl_emitter.emit_forward_typedefs(analysis.agg_types))
        lines.extend(decl_emitter.emit_module_declarations(analysis))
        lines.extend(decl_emitter.emit_aggregate_structs(analysis.agg_types))
        lines.extend(decl_emitter.emit_evidence_dictionaries(analysis.agg_types, self.needed_dicts))
        lines.extend(decl_emitter.emit_coercion_tables(self.tuple_coercions, self.variant_coercions))
        lines.extend(decl_emitter.emit_type_descriptors(
            analysis.agg_types,
            analysis.variant_types,
            self.c_type_descriptor,
            analysis.all_program_types,
        ))
        lines.extend(decl_emitter.emit_environment_structs(self.lifted_lambdas))
        lines.extend(decl_emitter.emit_top_vars_declarations(analysis.top_vars, self.var_dict_names))
        lines.extend(decl_emitter.emit_forward_declarations_and_trampolines(
            analysis.top_funs,
            self.lifted_lambdas,
            self.val_referenced_top_funs,
            self.top_funs_dict,
        ))
        lines.extend(decl_emitter.emit_precompiled_module_declarations(analysis))

        top_funs = analysis.top_funs
        top_vars = analysis.top_vars
        sorted_modules = analysis.sorted_modules

        all_module_map: dict[str, TypedModule] = {m.name: m for m in sorted_modules}
        if loaded_modules:
            for mod in loaded_modules.values():
                if isinstance(mod, TypedModule):
                    all_module_map[mod.name] = mod
        for phrase in prog.phrases:
            if isinstance(phrase, TypedModule):
                all_module_map[phrase.name] = phrase
        self.all_modules = all_module_map
        # 7. Function definitions for top-level functions
        if top_funs:
            lines.append("/* Function definitions */")
            for name, fun, _sym in top_funs:
                quants, params, body, ret_type = self._collect_fun_params(fun)
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                decls, _ = self._param_signatures(params, quants)
                param_sig = "void" if not decls else ", ".join(decls)
                lines.append(f"static Q_UNUSED {ret_c} {c_name}({param_sig}) {{")
                saved_descriptors = dict(self.in_scope_type_descriptors)
                saved_ptr_params = set(self.pointer_params)
                for p in params:
                    if getattr(p, "is_out", False) or getattr(p, "is_var", False):
                        self.pointer_params.add(p.name)
                for q in quants:
                    self.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                fn_lines: list[str] = []
                # Silence unused descriptor warnings
                for q in quants:
                    fn_lines.append(f"(void)descriptor_{q.name};")
                self._emit_fun_return(body, ret_type, fn_lines)
                self.in_scope_type_descriptors = saved_descriptors
                self.pointer_params = saved_ptr_params
                for f_line in fn_lines:
                    lines.append(f"    {f_line}" if f_line.strip() else f_line)
                lines.append("}")
                lines.append("")

        # 8. Function definitions for lifted lambdas
        if self.lifted_lambdas:
            lines.append("/* Lifted lambda definitions */")
            for l in self.lifted_lambdas:
                quants, inner_t = self._collect_fun_quantifiers(l.fun.type_val)
                ret_type = inner_t.result_type if isinstance(inner_t, QFunType) else inner_t
                ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                decls, _ = self._param_signatures(l.fun.params, quants)
                param_sigs = ["void *_raw_env"] + decls
                sig = ", ".join(param_sigs)
                lines.append(f"static Q_UNUSED {ret_c} {l.c_fn_name}({sig}) {{")
                fn_lines = []
                if l.free_vars:
                    fn_lines.append(f"{l.env_struct_name} *_env = ({l.env_struct_name} *)_raw_env;")
                    prev_env = self.current_env_vars
                    self.current_env_vars = {
                        vname: f"_env->{mangle_ident(vname)}" for vname, _ in l.free_vars
                    }
                else:
                    fn_lines.append("(void)_raw_env;")
                    prev_env = self.current_env_vars
                    self.current_env_vars = {}

                saved_descriptors = dict(self.in_scope_type_descriptors)
                saved_ptr_params = set(self.pointer_params)
                for p in l.fun.params:
                    if getattr(p, "is_out", False) or getattr(p, "is_var", False):
                        self.pointer_params.add(p.name)
                for q in quants:
                    self.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                    fn_lines.append(f"(void)descriptor_{q.name};")

                self._emit_fun_return(l.fun.body, ret_type, fn_lines)

                self.in_scope_type_descriptors = saved_descriptors
                self.pointer_params = saved_ptr_params
                self.current_env_vars = prev_env
                for f_line in fn_lines:
                    lines.append(f"    {f_line}" if f_line.strip() else f_line)
                lines.append("}")
                lines.append("")

        # 8b. Emit module functions and initializers
        if sorted_modules:
            lines.append("/* Compiled module definitions and initializers */")
            for mod in sorted_modules:
                if getattr(mod, "is_precompiled", False):
                    continue
                lines.extend(
                    self._emit_single_module_definition(
                        mod,
                        all_module_map,
                        standalone=False,
                        decl_emitter=decl_emitter,
                    )
                )

        # 9. Main entrypoint
        main_lines: list[str] = [
            "int main(int argc, char **argv) {",
            "    quest_gc_init();",
            "    quest_builtins_init(argc, argv);",
            "",
        ]

        if decl_emitter.emitted_descriptor_tags:
            main_lines.append("    /* Register static program type descriptors */")
            for tag in decl_emitter.emitted_descriptor_tags:
                main_lines.append(f"    quest_register_static_type_descriptor(&quest_type_{tag});")
            main_lines.append("")

        # Initialize all compiled modules topologically
        if sorted_modules:
            for mod in sorted_modules:
                clean_mod = mod.name.replace(".", "_")
                main_lines.append(f"    qv_mod_{clean_mod}_init();")
            main_lines.append("")

        total_phrases = len(prog.phrases)
        for i, phrase in enumerate(prog.phrases):
            is_last = (i == total_phrases - 1)
            self._emit_phrase(phrase, main_lines, is_last=is_last)

        main_lines.extend([
            "",
            "    return 0;",
            "}",
            "",
        ])

        if self.adapter_defs:
            lines.append("/* Closure adaptation thunks for existential packages */")
            lines.extend(self.adapter_defs)

        lines.extend(main_lines)
        return "\n".join(lines)

    def emit_module(
        self,
        mod: TypedModule,
        loaded_modules: Optional[dict[str, TypedModule]] = None,
        interface_header: Optional[str] = None,
        exported_funs: Optional[set[str]] = None,
    ) -> str:
        """Translates a standalone TypedModule into a C99 source string (no main function)."""
        prog = TypedProgram(phrases=(mod,))
        analysis = analyze_program_for_c(prog, self.record_ctx, loaded_modules)

        self.needed_dicts = analysis.needed_dicts
        self.tuple_coercions = analysis.tuple_coercions
        self.variant_coercions = analysis.variant_coercions
        self.top_fun_names = analysis.top_fun_names
        self.top_var_names = analysis.top_var_names
        self.val_referenced_top_funs = analysis.val_referenced_top_funs
        self.lifted_lambdas = analysis.lifted_lambdas
        self.lambda_info_by_id = analysis.lambda_info_by_id
        self.top_funs_dict = analysis.top_funs_dict
        self.specializations = analysis.specializations

        decl_emitter = CDeclarationEmitter(
            record_ctx=self.record_ctx,
            c_type_fn=self.c_type,
            param_sigs_fn=self._param_signatures,
            collect_quants_fn=self._collect_fun_quantifiers,
            is_exact_record_literal_fn=self._is_exact_record_literal,
        )

        lines: list[str] = [
            "/* Emitted by Quest Module Compiler */",
            "#include \"quest_runtime.h\"",
        ]
        if interface_header:
            lines.append(f'#include "{interface_header}"')
        lines.append("")

        lines.extend(decl_emitter.emit_forward_typedefs(analysis.agg_types))
        lines.extend(decl_emitter.emit_aggregate_structs(analysis.agg_types))
        lines.extend(decl_emitter.emit_evidence_dictionaries(analysis.agg_types, self.needed_dicts))
        lines.extend(decl_emitter.emit_coercion_tables(self.tuple_coercions, self.variant_coercions))
        lines.extend(decl_emitter.emit_type_descriptors(
            analysis.agg_types,
            analysis.variant_types,
            self.c_type_descriptor,
            analysis.all_program_types,
        ))
        lines.extend(decl_emitter.emit_environment_structs(self.lifted_lambdas))

        all_module_map: dict[str, TypedModule] = {m.name: m for m in analysis.sorted_modules}
        if loaded_modules:
            for m in loaded_modules.values():
                if isinstance(m, TypedModule):
                    all_module_map[m.name] = m
        all_module_map[mod.name] = mod
        self.all_modules = all_module_map

        lines.append("/* Compiled module definitions and initializers */")
        lines.extend(self._emit_single_module_definition(
            mod,
            all_module_map,
            standalone=True,
            exported_funs=exported_funs,
            decl_emitter=decl_emitter,
        ))

        if self.adapter_defs:
            lines.append("/* Closure adaptation thunks for existential packages */")
            lines.extend(self.adapter_defs)

        return "\n".join(lines)

    def _emit_single_module_definition(
        self,
        mod: TypedModule,
        all_module_map: dict[str, TypedModule],
        standalone: bool = False,
        exported_funs: Optional[set[str]] = None,
        decl_emitter: Optional[CDeclarationEmitter] = None,
    ) -> list[str]:
        lines: list[str] = []
        clean_mod = mod.name.replace(".", "_")
        mod_funs: list[tuple[str, TypedFun, Any]] = []
        mod_vars: list[tuple[str, TypedExpr, Any]] = []
        mod_native_funs: list[TypedNativeBinding] = []
        mod_native_vals: list[TypedNativeBinding] = []
        mod_imported_mods: list[str] = []
        for b in mod.bindings:
            match b:
                case TypedLetValue(name=b_name, value=b_val, symbol=b_sym):
                    if isinstance(b_val, TypedFun):
                        mod_funs.append((b_name, b_val, b_sym))
                    elif (
                        isinstance(b_val, TypedExternal)
                        and isinstance(b_sym.type_val, (QFunType, QAllType))
                    ):
                        mod_native_funs.append(
                            TypedNativeBinding(
                                name=b_name,
                                symbol=b_val.symbol,
                                inline_template=None,
                                c_val=None,
                                type_val=b_sym.type_val,
                            )
                        )
                    else:
                        mod_vars.append((b_name, b_val, b_sym))
                case TypedNativeBinding() as nb:
                    if nb.c_val is not None:
                        mod_native_vals.append(nb)
                    elif isinstance(nb.type_val, (QFunType, QAllType)):
                        mod_native_funs.append(nb)
                    else:
                        mod_native_vals.append(nb)
                case TypedImport(items=items):
                    for it in items:
                        for iname in it.names:
                            if standalone or iname in all_module_map:
                                mod_imported_mods.append(iname)
                case TypedException(name=b_name, type_val=b_t) as exc_n:
                    if b_name:
                        mod_vars.append(
                            (b_name, exc_n, type("Symbol", (), {"type_val": b_t})())
                        )
                case _:
                    pass

        if standalone and mod_imported_mods:
            lines.append("/* Forward declarations for imported dependency modules */")
            for dep in mod_imported_mods:
                dep_clean = dep.replace(".", "_")
                lines.append(f"extern void qv_mod_{dep_clean}_init(void);")
                lines.append(f"extern QRecordVal qv_{dep_clean};")
            lines.append("")

        for vname, vval, vsym in mod_vars:
            if vsym.type_val != OK_TYPE:
                m_ident = mangle_module_ident(clean_mod, vname)
                lines.append(f"static {self.c_type(vsym.type_val)} {m_ident};")

        fun_adapters: dict[
            str,
            tuple[str, str, QType, list[TypedParam], QType, list[Any], str, str, str],
        ] = {}
        for fname, ffun, fsym in mod_funs:
            m_ident = mangle_module_ident(clean_mod, fname)
            quants, params, _, ret_type = self._collect_fun_params(ffun)
            int_ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
            quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
            param_decls = quant_decls + [
                self._param_c_decl(p, mangle_module_ident(clean_mod, p.name))
                for p in params
            ]
            sig = "void" if not param_decls else ", ".join(param_decls)
            is_exported = standalone and (exported_funs is None or fname in exported_funs)
            linkage = "" if is_exported else "static "

            exp_sym = mod.scope.values.get(fname)
            needs_adapter = False
            if exp_sym is not None:
                exp_val_t = exp_sym.type_val
                if isinstance(exp_val_t, QAllType):
                    exp_quants = exp_val_t.quantifiers
                    exp_fun = exp_val_t.body
                else:
                    exp_quants = ()
                    exp_fun = exp_val_t
                if isinstance(exp_fun, QFunType):
                    exp_ret_t = exp_fun.result_type
                    exp_params = exp_fun.params
                    exp_ret_c = "void" if exp_ret_t == OK_TYPE else self.c_type(exp_ret_t)
                    if exp_ret_c != int_ret_c or len(exp_params) != len(params):
                        needs_adapter = True
                    else:
                        for ep, ip in zip(exp_params, params):
                            if self.c_type(ep.type_val) != self.c_type(ip.type_val):
                                needs_adapter = True
                                break

            if needs_adapter:
                impl_ident = f"_{m_ident}_impl"
                lines.append(f"static {int_ret_c} {impl_ident}({sig});")
                exp_quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in exp_quants]
                exp_param_decls = exp_quant_decls + [
                    (
                        f"{self.c_type(p.type_val)}"
                        f"{' *' if getattr(p, 'is_out', False) or getattr(p, 'is_var', False) else ' '}"
                        f"qv_p_{p.name}"
                    )
                    for p in exp_params
                ]
                exp_sig = "void" if not exp_param_decls else ", ".join(exp_param_decls)
                lines.append(f"{linkage}{exp_ret_c} {m_ident}({exp_sig});")
                tramp_name = f"{m_ident}_trampoline"
                tramp_param_sigs = ["void *env"] + exp_param_decls
                tramp_sig = ", ".join(tramp_param_sigs)
                tramp_call_args = [f"descriptor_{q.name}" for q in exp_quants] + [
                    f"qv_p_{p.name}" for p in exp_params
                ]
                tramp_args_str = ", ".join(tramp_call_args)
                lines.append(f"static {exp_ret_c} {tramp_name}({tramp_sig}) {{")
                lines.append("    (void)env;")
                if exp_ret_t == OK_TYPE:
                    lines.append(f"    {m_ident}({tramp_args_str});")
                else:
                    lines.append(f"    return {m_ident}({tramp_args_str});")
                lines.append("}")
                lines.append("")
                fun_adapters[fname] = (
                    impl_ident,
                    sig,
                    ret_type,
                    params,
                    exp_ret_t,
                    exp_params,
                    exp_sig,
                    exp_ret_c,
                    linkage,
                )
            else:
                lines.append(f"{linkage}{int_ret_c} {m_ident}({sig});")
                tramp_name = f"{m_ident}_trampoline"
                param_sigs = ["void *env"] + param_decls
                tramp_sig = ", ".join(param_sigs)
                f_args = [f"descriptor_{q.name}" for q in quants] + [
                    mangle_module_ident(clean_mod, p.name) for p in params
                ]
                args_str = ", ".join(f_args)
                lines.append(f"static {int_ret_c} {tramp_name}({tramp_sig}) {{")
                lines.append("    (void)env;")
                if ret_type == OK_TYPE:
                    lines.append(f"    {m_ident}({args_str});")
                else:
                    lines.append(f"    return {m_ident}({args_str});")
                lines.append("}")
                lines.append("")

        for nb in mod_native_funs:
            if nb.symbol or nb.inline_template:
                tramp_name = f"qv_{clean_mod}_{nb.name}_trampoline"
                if isinstance(nb.type_val, QAllType):
                    quants = nb.type_val.quantifiers
                    base_fun = nb.type_val.body
                else:
                    quants = ()
                    base_fun = nb.type_val
                params = base_fun.params if isinstance(base_fun, QFunType) else ()
                ret_type = base_fun.result_type if isinstance(base_fun, QFunType) else OK_TYPE
                ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                param_decls = quant_decls + [
                    f"{self.c_type(p.type_val)} qv_p_{p.name}" for p in params
                ]
                param_sigs = ["void *env"] + param_decls
                sig = ", ".join(param_sigs)
                call_args = (
                    [f"descriptor_{q.name}" for q in quants]
                    if getattr(nb, "pass_type_descriptors", False)
                    else []
                ) + [f"qv_p_{p.name}" for p in params]
                if nb.inline_template:
                    call_expr = nb.inline_template.format(*call_args)
                else:
                    call_expr = f"{nb.symbol}({', '.join(call_args)})"
                lines.append(f"static {ret_c} {tramp_name}({sig}) {{")
                lines.append("    (void)env;")
                for q in quants:
                    lines.append(f"    (void)descriptor_{q.name};")
                if ret_type == OK_TYPE:
                    lines.append(f"    {call_expr};")
                else:
                    lines.append(f"    return {call_expr};")
                lines.append("}")
                lines.append("")

        mod_emitter = CEmitter(echo=False, module_prefix=clean_mod)
        mod_emitter.top_fun_names = {fname for fname, _, _ in mod_funs}
        mod_emitter.top_funs_dict = {fname: (ffun, fsym) for fname, ffun, fsym in mod_funs}
        mod_emitter.record_ctx = self.record_ctx
        mod_emitter.all_modules = self.all_modules

        for fname, ffun, fsym in mod_funs:
            m_ident = mangle_module_ident(clean_mod, fname)
            quants, params, body, ret_type = self._collect_fun_params(ffun)
            if fname in fun_adapters:
                (
                    impl_ident,
                    int_sig,
                    int_ret_t,
                    int_params,
                    exp_ret_t,
                    exp_params,
                    exp_sig,
                    exp_ret_c,
                    linkage,
                ) = fun_adapters[fname]
                int_ret_c = "void" if int_ret_t == OK_TYPE else self.c_type(int_ret_t)
                lines.append(f"static {int_ret_c} {impl_ident}({int_sig}) {{")
                fn_lines: list[str] = []
                for q in quants:
                    mod_emitter.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                    fn_lines.append(f"(void)descriptor_{q.name};")
                prev_env = mod_emitter.current_env_vars
                mod_emitter.current_env_vars = {
                    p.name: mangle_module_ident(clean_mod, p.name) for p in params
                }
                for vname, _, _ in mod_vars:
                    mod_emitter.current_env_vars[vname] = mangle_module_ident(clean_mod, vname)
                for fn_k, (fn_impl, *_) in fun_adapters.items():
                    mod_emitter.current_env_vars[fn_k] = fn_impl
                mod_emitter.pointer_params = {
                    p.name for p in params if getattr(p, "is_out", False) or getattr(p, "is_var", False)
                }
                mod_emitter._emit_fun_return(body, int_ret_t, fn_lines)
                mod_emitter.pointer_params = set()
                mod_emitter.current_env_vars = prev_env
                for fl in fn_lines:
                    lines.append(f"    {fl}" if fl.strip() else fl)
                lines.append("}")
                lines.append("")

                lines.append(f"{linkage}{exp_ret_c} {m_ident}({exp_sig}) {{")
                adapter_args = [f"descriptor_{q.name}" for q in quants]
                for ep, ip in zip(exp_params, int_params):
                    ep_name = f"qv_p_{ep.name}"
                    if self.c_type(ep.type_val) != self.c_type(ip.type_val):
                        unwrapped = _qval_unwrap(ep_name, ip.type_val, self)
                        adapter_args.append(unwrapped)
                    else:
                        adapter_args.append(ep_name)
                args_str = ", ".join(adapter_args)
                if int_ret_t == OK_TYPE:
                    lines.append(f"    {impl_ident}({args_str});")
                    if exp_ret_t != OK_TYPE:
                        lines.append("    return ((QVal){ .p = NULL });")
                    else:
                        lines.append("    return;")
                else:
                    lines.append(f"    {int_ret_c} _res = {impl_ident}({args_str});")
                    if exp_ret_c != int_ret_c:
                        wrapped = _qval_wrap("_res", int_ret_t)
                        lines.append(f"    return {wrapped};")
                    else:
                        lines.append("    return _res;")
                lines.append("}")
                lines.append("")
            else:
                ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                param_decls = quant_decls + [
                    self._param_c_decl(p, mangle_module_ident(clean_mod, p.name))
                    for p in params
                ]
                sig = "void" if not param_decls else ", ".join(param_decls)
                is_exported = standalone and (exported_funs is None or fname in exported_funs)
                linkage = "" if is_exported else "static "
                lines.append(f"{linkage}{ret_c} {m_ident}({sig}) {{")
                fn_lines: list[str] = []
                for q in quants:
                    mod_emitter.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                    fn_lines.append(f"(void)descriptor_{q.name};")
                prev_env = mod_emitter.current_env_vars
                mod_emitter.current_env_vars = {
                    p.name: mangle_module_ident(clean_mod, p.name) for p in params
                }
                for vname, _, _ in mod_vars:
                    mod_emitter.current_env_vars[vname] = mangle_module_ident(clean_mod, vname)
                mod_emitter.pointer_params = {
                    p.name for p in params if getattr(p, "is_out", False) or getattr(p, "is_var", False)
                }
                mod_emitter._emit_fun_return(body, ret_type, fn_lines)
                mod_emitter.pointer_params = set()
                mod_emitter.current_env_vars = prev_env
                for fl in fn_lines:
                    lines.append(f"    {fl}" if fl.strip() else fl)
                lines.append("}")
                lines.append("")

        if standalone:
            lines.append(f"QRecordVal qv_{clean_mod};")
            lines.append(f"static bool qv_mod_{clean_mod}_initialized = false;")
            lines.append(f"void qv_mod_{clean_mod}_init(void) {{")
        else:
            lines.append(f"static void qv_mod_{clean_mod}_init(void) {{")
        lines.append(f"    if (qv_mod_{clean_mod}_initialized) return;")
        lines.append(f"    qv_mod_{clean_mod}_initialized = true;")
        if standalone and decl_emitter and decl_emitter.emitted_descriptor_tags:
            lines.append("    /* Register static program type descriptors */")
            for tag in decl_emitter.emitted_descriptor_tags:
                lines.append(f"    quest_register_static_type_descriptor(&quest_type_{tag});")
            lines.append("")
        for dep in mod_imported_mods:
            dep_clean = dep.replace(".", "_")
            lines.append(f"    qv_mod_{dep_clean}_init();")
        if mod.c_init:
            lines.append(f"    {mod.c_init};")

        init_lines: list[str] = []
        mod_emitter.current_env_vars = {
            vname: mangle_module_ident(clean_mod, vname) for vname, _, _ in mod_vars
        }
        for b in mod.bindings:
            match b:
                case TypedLetValue(name=vname, value=vval, symbol=vsym):
                    if any(vname == mv[0] for mv in mod_vars):
                        m_ident = mangle_module_ident(clean_mod, vname)
                        if vsym.type_val == OK_TYPE:
                            mod_emitter.emit_to(vval, None, init_lines)
                        else:
                            mod_emitter.emit_to(vval, m_ident, init_lines)
                case TypedException(name=ename) as exc_n:
                    if ename and any(ename == mv[0] for mv in mod_vars):
                        m_ident = mangle_module_ident(clean_mod, ename)
                        mod_emitter.emit_to(exc_n, m_ident, init_lines)
                case _:
                    pass
        for il in init_lines:
            lines.append(f"    {il}" if il.strip() else il)

        mod_rec_t = BuiltinModuleRegistry._build_record_type_from_scope(mod.scope)
        rec_struct = self.record_struct_name(mod_rec_t)
        payload_var = f"_{clean_mod}_payload"
        lines.append(
            f"    {rec_struct} *{payload_var} = "
            f"({rec_struct} *)quest_alloc(sizeof({rec_struct}));"
        )
        lines.append(f"    {payload_var}->header.descriptor = NULL;")
        for fld in sorted(mod_rec_t.fields, key=lambda f: f.name):
            if any(fn == fld.name for fn, _, _ in mod_funs):
                tramp_name = f"{mangle_module_ident(clean_mod, fld.name)}_trampoline"
                clos_tmp = self.fresh_tmp(f"_{clean_mod}_{fld.name}_clos")
                lines.append(
                    f"    QClosure *{clos_tmp} = "
                    f"(QClosure *)quest_alloc(sizeof(QClosure));"
                )
                lines.append(f"    {clos_tmp}->fn = (void *){tramp_name};")
                lines.append(f"    {clos_tmp}->env = NULL;")
                lines.append(f"    {payload_var}->qf_{fld.name} = {clos_tmp};")
            elif (nb := next((b for b in mod_native_funs if b.name == fld.name), None)) is not None:
                if nb.symbol or nb.inline_template:
                    tramp_name = f"qv_{clean_mod}_{fld.name}_trampoline"
                    clos_tmp = self.fresh_tmp(f"_{clean_mod}_{fld.name}_clos")
                    lines.append(
                        f"    QClosure *{clos_tmp} = "
                        f"(QClosure *)quest_alloc(sizeof(QClosure));"
                    )
                    lines.append(f"    {clos_tmp}->fn = (void *){tramp_name};")
                    lines.append(f"    {clos_tmp}->env = NULL;")
                    lines.append(f"    {payload_var}->qf_{fld.name} = {clos_tmp};")
                else:
                    lines.append(f"    {payload_var}->qf_{fld.name} = NULL;")
            elif (nb := next((b for b in mod_native_vals if b.name == fld.name), None)) is not None:
                val_str = nb.c_val
                if self.c_type(fld.type_val) == "QVal" and self.c_type(nb.type_val) != "QVal":
                    val_str = _qval_wrap(val_str, nb.type_val)
                lines.append(f"    {payload_var}->qf_{fld.name} = {val_str};")
            else:
                m_ident = mangle_module_ident(clean_mod, fld.name)
                val_b = next((b for b in mod.bindings if getattr(b, "name", None) == fld.name), None)
                val_t = getattr(getattr(val_b, "symbol", None), "type_val", None)
                if val_t is None:
                    val_t = getattr(val_b, "type_val", None)
                val_str = m_ident
                if val_t and self.c_type(fld.type_val) == "QVal" and self.c_type(val_t) != "QVal":
                    val_str = _qval_wrap(val_str, val_t)
                lines.append(f"    {payload_var}->qf_{fld.name} = {val_str};")
        d_name = self.record_ctx.offset_dict_instance_name(mod_rec_t, mod_rec_t)
        lines.append(
            f"    qv_{clean_mod} = (QRecordVal){{ .val = (void *){payload_var}, "
            f".dict = (const void *)&{d_name} }};"
        )
        lines.append("}")
        lines.append("")
        return lines

    def _format_existential_tuple_val(self, typ: QTupleType) -> str:
        """Formats the hidden representation of an existential tuple value for interactive output."""
        parts: list[str] = []
        for comp in typ.components:
            if isinstance(comp, QTupleTypeFormal):
                parts.append(f"<Hidden>::{comp.bound}")
            elif isinstance(comp, QTupleTypeBinding):
                parts.append(f"Let {comp.name} = {comp.type_val}")
            elif isinstance(comp, QTupleField):
                if isinstance(comp.type_val, (QPathType, QTypeVar)):
                    elem_str = "<hidden>"
                elif isinstance(comp.type_val, (QFunType, QAllType)):
                    elem_str = "<fun>"
                else:
                    elem_str = "<val>"
                if comp.name:
                    parts.append(f"{comp.name}={elem_str}")
                else:
                    parts.append(elem_str)
        return f"tuple {' '.join(parts)} end" if parts else "tuple end"

    def _emit_phrase(self, phrase: TypedNode, lines: list[str], is_last: bool = False) -> None:
        """Translates a top-level binding or expression phrase."""
        should_print_result = self.print_result and is_last
        match phrase:
            case TypedLetValue(name=name, value=val, symbol=symbol):
                if isinstance(val, TypedFun):
                    if self.echo:
                        type_str = _c_string_literal(qtype_to_name_str(symbol.type_val))
                        lines.append(f"    quest_print_val(((QVal){{ .u = 0 }}), {type_str});")
                    elif should_print_result:
                        var_str = "var " if symbol.is_var else ""
                        type_str = str(symbol.type_val)
                        msg = f"let {var_str}{name}:{type_str} = <fun>"
                        lines.append(f"    puts({_c_string_literal(msg)});")
                    return

                c_ident = mangle_ident(name)
                if symbol.type_val == OK_TYPE:
                    lines.append(f"    // inlined {name}")
                    phrase_lines: list[str] = []
                    self.emit_to(val, None, phrase_lines)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                elif isinstance(symbol.type_val, QRecordType):
                    phrase_lines = []
                    val_c = self.emit_val(val, phrase_lines)
                    coerced = self._coerce_record_val(val_c, val, symbol.type_val)
                    phrase_lines.append(f"{c_ident} = {coerced};")
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                elif (
                    isinstance(symbol.type_val, QTupleType)
                    and isinstance(val.type_val, QTupleType)
                    and val.type_val != symbol.type_val
                ):
                    phrase_lines = []
                    val_c = self.emit_val(val, phrase_lines)
                    self._coerce_tuple_val(
                        val_c, val.type_val, symbol.type_val, phrase_lines, dest=c_ident
                    )
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                elif (
                    isinstance(symbol.type_val, QVariantType)
                    and isinstance(val.type_val, QVariantType)
                    and val.type_val != symbol.type_val
                ):
                    phrase_lines = []
                    val_c = self.emit_val(val, phrase_lines)
                    self._emit_variant_upcast(val_c, val.type_val, symbol.type_val, phrase_lines, dest=c_ident)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                else:
                    phrase_lines = []
                    self.emit_to(val, c_ident, phrase_lines)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                if self.echo:
                    wrap = _qval_wrap(c_ident, symbol.type_val)
                    type_str = _c_string_literal(qtype_to_name_str(symbol.type_val))
                    lines.append(f"    quest_print_val({wrap}, {type_str});")
                elif should_print_result:
                    var_str = "var " if symbol.is_var else ""
                    if symbol.type_val == OK_TYPE:
                        msg = f"let {var_str}{name}:Ok = ok"
                        lines.append(f"    puts({_c_string_literal(msg)});")
                    elif isinstance(symbol.type_val, (QFunType, QAllType)):
                        type_str = str(symbol.type_val)
                        msg = f"let {var_str}{name}:{type_str} = <fun>"
                        lines.append(f"    puts({_c_string_literal(msg)});")
                    elif symbol.type_val == INT_TYPE:
                        lines.append(
                            f'    printf("let {var_str}{name}:Int = %lld\\n", (long long){c_ident});'
                        )
                    elif symbol.type_val == REAL_TYPE:
                        lines.append(
                            f'    if ({c_ident} == (double)(int64_t){c_ident}) '
                            f'printf("let {var_str}{name}:Real = %.1f\\n", {c_ident}); '
                            f'else printf("let {var_str}{name}:Real = %g\\n", {c_ident});'
                        )
                    elif symbol.type_val == BOOL_TYPE:
                        lines.append(
                            f'    printf("let {var_str}{name}:Bool = %s\\n", {c_ident} ? "true" : "false");'
                        )
                    elif symbol.type_val == CHAR_TYPE:
                        lines.append(
                            f'    printf("let {var_str}{name}:Char = \'%c\'\\n", (char){c_ident});'
                        )
                    elif symbol.type_val == STRING_TYPE:
                        lines.append(
                            f'    printf("let {var_str}{name}:String = \\"%s\\"\\n", '
                            f'{c_ident} ? {c_ident}->data : "");'
                        )
                    elif isinstance(symbol.type_val, QTupleType) and symbol.type_val.is_existential:
                        type_str = str(symbol.type_val)
                        val_str = self._format_existential_tuple_val(symbol.type_val)
                        msg = f"let {var_str}{name}:{type_str} = {val_str}"
                        lines.append(f"    puts({_c_string_literal(msg)});")
                    else:
                        type_str = str(symbol.type_val)
                        msg = f"let {var_str}{name}:{type_str} = <val>"
                        lines.append(f"    puts({_c_string_literal(msg)});")

            case TypedLetType(name=name, symbol=symbol):
                if should_print_result:
                    kind_str = str(symbol.kind)
                    if symbol.definition is not None:
                        msg = f"Let {name}::{kind_str} = {symbol.definition}"
                    else:
                        msg = f"Let {name}::{kind_str}"
                    lines.append(f"    puts({_c_string_literal(msg)});")

            case TypedDefKind(name=name, symbol=symbol):
                if should_print_result:
                    kind_str = str(symbol.kind)
                    msg = f"DEF {name} = {kind_str}"
                    lines.append(f"    puts({_c_string_literal(msg)});")

            case TypedException(name=name) as exc_node:
                if name:
                    c_ident = mangle_ident(name)
                    phrase_lines = []
                    self.emit_to(exc_node, c_ident, phrase_lines)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                    if self.echo:
                        wrap = _qval_wrap(c_ident, exc_node.type_val)
                        type_str = _c_string_literal(qtype_to_name_str(exc_node.type_val))
                        lines.append(f"    quest_print_val({wrap}, {type_str});")
                    elif should_print_result:
                        lines.append(f"    puts({_c_string_literal(f'exception {name}')});")
                else:
                    self._emit_expr_phrase(phrase, lines, is_last=is_last)

            case TypedExprStmt(expr=inner):
                if isinstance(inner, TypedException) and inner.name:
                    self._emit_phrase(inner, lines, is_last=is_last)
                else:
                    self._emit_expr_phrase(inner, lines, is_last=is_last)

            case TypedExpr():
                self._emit_expr_phrase(phrase, lines, is_last=is_last)

            case _:
                # Type / Kind declarations are erased at runtime
                pass

    def _emit_expr_phrase(self, expr: TypedExpr, lines: list[str], is_last: bool = False) -> None:
        expr_type = expr.type_val
        phrase_lines: list[str] = []
        if expr_type == OK_TYPE:
            self.emit_to(expr, None, phrase_lines)
            for s in phrase_lines:
                lines.append(f"    {s}" if s.strip() else s)
            return

        c_type = self.c_type(expr_type)
        tmp = self.fresh_tmp("_res")
        phrase_lines.append(f"{c_type} {tmp};")
        self.emit_to(expr, tmp, phrase_lines)
        for s in phrase_lines:
            lines.append(f"    {s}" if s.strip() else s)
        if self.echo or is_last:
            wrap = _qval_wrap(tmp, expr_type)
            type_str = _c_string_literal(qtype_to_name_str(expr_type))
            lines.append(f"    quest_print_val({wrap}, {type_str});")

    def emit_val(self, expr: TypedExpr, lines: list[str]) -> str:
        """Emits any preparatory statements into lines and returns a C99 expression value."""
        match expr:
            case TypedInt(value=val):
                return f"{val}LL" if val >= 0 else f"({val}LL)"

            case TypedReal(value=val):
                s = repr(val)
                if "e" not in s and "." not in s:
                    s += ".0"
                return s

            case TypedBool(value=val):
                return "true" if val else "false"

            case TypedChar(value=val):
                return _c_char_literal(val)

            case TypedString(value=val):
                lit = _c_string_literal(val)
                return f"quest_string_new({lit}, {len(val)}LL)"

            case TypedOk():
                return "((void)0)"

            case TypedVar(name=name):
                if name == "DivideByZero":
                    return "(&quest_exc_DivideByZero)"
                if name in INFIX_OPERATORS and name not in self.current_env_vars:
                    return f"(&{mangle_ident(name)}_closure)"
                if name in self.top_fun_names:
                    return f"(&{self.mangle_ident(name)}_closure)"
                if name in self.current_env_vars:
                    return self.current_env_vars[name]
                return mangle_ident(name)

            case TypedFun():
                linfo = self.lambda_info_by_id[id(expr)]
                if not linfo.free_vars:
                    return f"(&{linfo.closure_var_name})"
                clos_tmp = self.fresh_tmp("_clos")
                lines.append(f"QClosure *{clos_tmp};")
                self.emit_to(expr, clos_tmp, lines)
                return clos_tmp

            case TypedDerefCell(target=tgt):
                if isinstance(tgt, TypedVar) and tgt.name in self.pointer_params:
                    c_name = self.current_env_vars.get(tgt.name, self.mangle_ident(tgt.name))
                    return f"(*{c_name})"
                return self.emit_val(tgt, lines)

            case TypedVarCell(value=val):
                return self.emit_val(val, lines)

            case TypedAssign(target=tgt, value=val):
                target_t = tgt.type_val
                if isinstance(target_t, (QVarType, QOutType)):
                    target_t = target_t.element_type
                if isinstance(tgt, TypedVar) and tgt.name in self.pointer_params:
                    c_name = self.current_env_vars.get(tgt.name, self.mangle_ident(tgt.name))
                    c_tgt = f"(*{c_name})"
                else:
                    c_tgt = self.emit_val(tgt, lines)
                if isinstance(target_t, QRecordType):
                    c_val = self.emit_val(val, lines)
                    coerced = self._coerce_record_val(c_val, val, target_t)
                    lines.append(f"{c_tgt} = {coerced};")
                elif (
                    isinstance(target_t, QVariantType)
                    and isinstance(val.type_val, QVariantType)
                    and val.type_val != target_t
                ):
                    c_val = self.emit_val(val, lines)
                    self._emit_variant_upcast(c_val, val.type_val, target_t, lines, dest=c_tgt)
                else:
                    self.emit_to(val, c_tgt, lines)
                return "((void)0)"

            case TypedRecord(fields=flds):
                concrete_t = self._effective_record_type(expr)
                tmp = self.fresh_tmp("_alloc")
                c_type = self.c_type(concrete_t)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedTuple() | TypedVariant() | TypedOption():
                tmp = self.fresh_tmp("_alloc")
                c_type = self.c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedVariantCheck(target=tgt, tag=tag):
                c_tgt = self.emit_val(tgt, lines)
                target_t = tgt.type_val
                if (var_bound := resolve_variant_bound(target_t)) is not None:
                    target_t = var_bound
                elif (opt_bound := resolve_option_bound(target_t)) is not None:
                    target_t = opt_bound
                tag_idx = self._tag_index(target_t, tag)
                if isinstance(target_t, QVariantType):
                    return f"({c_tgt}.tag == {tag_idx}LL)"
                return f"({c_tgt}->tag == {tag_idx}LL)"

            case TypedVariantAssert(target=tgt, tag=tag):
                c_tgt = self.emit_val(tgt, lines)
                target_t = tgt.type_val
                if (var_bound := resolve_variant_bound(target_t)) is not None:
                    target_t = var_bound
                elif (opt_bound := resolve_option_bound(target_t)) is not None:
                    target_t = opt_bound
                tag_idx = self._tag_index(target_t, tag)
                if isinstance(target_t, QOptionType):
                    opt_field = target_t.get_option(tag) if tag is not None else None
                    lines.append(f"if ({c_tgt}->tag != {tag_idx}LL) quest_raise_variant_error();")
                    tup_type = expr.type_val
                    tup_struct = tuple_struct_name(tup_type)
                    res_tmp = self.fresh_tmp("_unpacked_opt")
                    lines.append(f"{tup_struct} *{res_tmp} = ({tup_struct} *)quest_alloc(sizeof({tup_struct}));")
                    lines.append(f"{res_tmp}->_0 = {c_tgt}->tag;")
                    if opt_field and opt_field.payload_type:
                        pt = opt_field.payload_type
                        if isinstance(pt, QTupleType):
                            for i, f in enumerate(pt.value_fields):
                                lines.append(f"{res_tmp}->_{i + 1} = {c_tgt}->u.{tag}._{i};")
                        elif isinstance(pt, QRecordType):
                            for i, f in enumerate(sorted(pt.fields, key=lambda fld: fld.name)):
                                lines.append(f"{res_tmp}->_{i + 1} = {c_tgt}->u.{tag}.qf_{f.name};")
                        else:
                            lines.append(f"{res_tmp}->_1 = {c_tgt}->u.{tag}.val;")
                    return res_tmp
                elif isinstance(target_t, QVariantType):
                    if not c_tgt.isidentifier():
                        tmp_v = self.fresh_tmp("_vtgt")
                        lines.append(f"QVariantVal {tmp_v} = {c_tgt};")
                        c_tgt = tmp_v
                    lines.append(f"if ({c_tgt}.tag != {tag_idx}LL) quest_raise_variant_error();")
                    return self._emit_qval_extract(f"{c_tgt}.payload", expr.type_val)
                else:
                    lines.append("quest_raise_variant_error();")
                    return "((void)0)"

            case TypedCase() | TypedInspect():
                if expr.type_val == OK_TYPE:
                    self.emit_to(expr, None, lines)
                    return "((void)0)"
                tmp = self.fresh_tmp("_case_res")
                c_type = self.c_type(expr.type_val)
                lines.append(f"{c_type} {tmp} = ({c_type}){{0}};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedSelect(target=tgt, field=fld):
                if isinstance(tgt, TypedVar) and tgt.name in self.all_modules:
                    mod = self.all_modules[tgt.name]
                    nb = next(
                        (b for b in mod.bindings if isinstance(b, TypedNativeBinding) and b.name == fld),
                        None,
                    )
                    if nb is not None and nb.c_val is not None:
                        return nb.c_val
                c_tgt = self.emit_val(tgt, lines)
                tgt_t = normalize_type(tgt.type_val)
                if isinstance(tgt_t, QTupleType):
                    val_idx = self._tuple_field_index(tgt_t, fld)
                    return f"{c_tgt}->_{val_idx}"
                elif isinstance(tgt_t, QRecordType):
                    return self._emit_record_field_access(
                        c_tgt, tgt_t, fld, expr.type_val, lines, as_ref=False
                    )
                elif (rec_bound := resolve_record_bound(tgt_t)) is not None:
                    return self._emit_record_field_access(
                        c_tgt, rec_bound, fld, expr.type_val, lines, as_ref=False
                    )
                else:
                    return f"{c_tgt}->qf_{fld}"

            case TypedSelectRef(target=tgt, field=fld):
                c_tgt = self.emit_val(tgt, lines)
                elem_t = expr.type_val
                if isinstance(elem_t, (QVarType, QOutType)):
                    elem_t = elem_t.element_type
                tgt_t = normalize_type(tgt.type_val)
                if isinstance(tgt_t, QTupleType):
                    val_idx = self._tuple_field_index(tgt_t, fld)
                    return f"(&({c_tgt}->_{val_idx}))"
                elif isinstance(tgt_t, QRecordType):
                    return self._emit_record_field_access(
                        c_tgt, tgt_t, fld, elem_t, lines, as_ref=True
                    )
                elif (rec_bound := resolve_record_bound(tgt_t)) is not None:
                    return self._emit_record_field_access(
                        c_tgt, rec_bound, fld, elem_t, lines, as_ref=True
                    )
                else:
                    return f"(&({c_tgt}->qf_{fld}))"

            case TypedIndexRef(target=tgt, index=idx):
                c_arr = self.emit_val(tgt, lines)
                c_idx = self.emit_val(idx, lines)
                elem_t = expr.type_val
                if isinstance(elem_t, (QVarType, QOutType)):
                    elem_t = elem_t.element_type
                if elem_t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
                    return f"(&({c_arr}->data[{c_idx}].i))"
                elif elem_t == REAL_TYPE:
                    return f"(&({c_arr}->data[{c_idx}].r))"
                elif isinstance(elem_t, QRecordType) or resolve_record_bound(elem_t) is not None:
                    return f"(&({c_arr}->data[{c_idx}]))"
                elif isinstance(elem_t, QVariantType) or resolve_variant_bound(elem_t) is not None:
                    return f"(&({c_arr}->data[{c_idx}]))"
                else:
                    c_elem_t = self.c_type(elem_t)
                    return f"(({c_elem_t} *)(&({c_arr}->data[{c_idx}].p)))"

            case TypedTupleSelectRef(target=tgt, index=idx):
                c_tgt = self.emit_val(tgt, lines)
                return f"(&({c_tgt}->_{idx}))"

            case TypedInfix(left=left, op=op, right=right):
                c_left = self.emit_val(left, lines)
                c_right = self.emit_val(right, lines)
                return self._emit_infix(c_left, op, c_right)

            case TypedApp(func=f, args=args):
                # Check for unwrapped type applications and collect type arguments
                effective_func = f
                type_args: list[QType] = []
                while isinstance(effective_func, TypedTypeApp):
                    type_args = list(effective_func.type_args) + type_args
                    effective_func = effective_func.func

                # Direct inline lowering for Cardelli prefix monadic operators
                if isinstance(effective_func, TypedVar) and len(args) == 1:
                    if effective_func.name == "not":
                        c_arg = self.emit_val(args[0], lines)
                        return f"(!({c_arg}))"
                    elif effective_func.name == "extent":
                        c_arg = self.emit_val(args[0], lines)
                        return f"(({c_arg})->length)"
                    elif effective_func.name == "ordinal":
                        c_arg = self.emit_val(args[0], lines)
                        if self.c_type(args[0].type_val) == "QVal":
                            return f"(((const int64_t *)({c_arg}.p))[0])"
                        return f"(({c_arg})->tag)"

                # Direct inline lowering for Cardelli prefix built-in binary operators
                if (
                    isinstance(effective_func, TypedVar)
                    and effective_func.name in INFIX_OPERATORS
                    and effective_func.name not in self.current_env_vars
                    and len(args) == 2
                ):
                    c_l = self.emit_val(args[0], lines)
                    c_r = self.emit_val(args[1], lines)
                    return self._emit_infix(c_l, effective_func.name, c_r)

                # Direct lowering for built-in arrayOp calls
                if isinstance(effective_func, TypedSelect) and isinstance(effective_func.target, TypedVar):
                    mod_name = effective_func.target.name
                    fld = effective_func.field
                    if mod_name == "arrayOp":
                        if fld == "new" and len(args) == 2:
                            c_sz = self.emit_val(args[0], lines)
                            c_init = self.emit_val(args[1], lines)
                            target_elem_t = (
                                expr.type_val.element_type
                                if isinstance(expr.type_val, QArrayType)
                                else args[1].type_val
                            )
                            if (
                                isinstance(target_elem_t, QRecordType)
                                or resolve_record_bound(target_elem_t) is not None
                            ):
                                c_init = self._coerce_record_val(c_init, args[1], target_elem_t)
                                return f"quest_array_new_wide_record({c_sz}, {c_init})"
                            elif (
                                isinstance(target_elem_t, QVariantType)
                                or resolve_variant_bound(target_elem_t) is not None
                            ):
                                if (
                                    isinstance(args[1].type_val, QVariantType)
                                    and args[1].type_val != target_elem_t
                                ):
                                    c_init = self._emit_variant_upcast(
                                        c_init, args[1].type_val, target_elem_t, lines
                                    )
                                return f"quest_array_new_wide_variant({c_sz}, {c_init})"
                            else:
                                wrap = _qval_wrap(c_init, target_elem_t)
                                return f"quest_array_new({c_sz}, {wrap})"
                        elif fld == "size" and len(args) == 1:
                            c_arr = self.emit_val(args[0], lines)
                            return f"({c_arr}->length)"
                        elif fld == "get" and len(args) == 2:
                            c_arr = self.emit_val(args[0], lines)
                            c_idx = self.emit_val(args[1], lines)
                            lines.append(f"quest_check_array_bounds({c_arr}, {c_idx});")
                            return self._emit_array_get(c_arr, c_idx, expr.type_val)
                        elif fld == "set" and len(args) == 3:
                            c_arr = self.emit_val(args[0], lines)
                            c_idx = self.emit_val(args[1], lines)
                            c_item = self.emit_val(args[2], lines)
                            lines.append(f"quest_check_array_bounds({c_arr}, {c_idx});")
                            target_elem_t = (
                                args[0].type_val.element_type
                                if isinstance(args[0].type_val, QArrayType)
                                else args[2].type_val
                            )
                            if (
                                isinstance(target_elem_t, QRecordType)
                                or resolve_record_bound(target_elem_t) is not None
                            ):
                                c_item = self._coerce_record_val(c_item, args[2], target_elem_t)
                                lines.append(f"{c_arr}->data[{c_idx}] = {c_item};")
                            elif (
                                isinstance(target_elem_t, QVariantType)
                                or resolve_variant_bound(target_elem_t) is not None
                            ):
                                if (
                                    isinstance(args[2].type_val, QVariantType)
                                    and args[2].type_val != target_elem_t
                                ):
                                    c_item = self._emit_variant_upcast(
                                        c_item, args[2].type_val, target_elem_t, lines
                                    )
                                lines.append(f"{c_arr}->data[{c_idx}] = {c_item};")
                            else:
                                wrap = _qval_wrap(c_item, target_elem_t)
                                lines.append(f"{c_arr}->data[{c_idx}] = {wrap};")
                            return "((void)0)"
                    elif mod_name in self.all_modules:
                        mod = self.all_modules[mod_name]
                        clean_mod = mod_name.replace(".", "_")
                        binding = next(
                            (b for b in mod.bindings if getattr(b, "name", None) == fld),
                            None,
                        )
                        if isinstance(binding, TypedNativeBinding):
                            quants, inner_t = self._collect_fun_quantifiers(binding.type_val)
                            c_args = []
                            if type_args and quants and getattr(binding, "pass_type_descriptors", False):
                                for targ in type_args:
                                    c_args.append(self.c_type_descriptor(targ))
                            if isinstance(inner_t, QFunType):
                                formal_params = inner_t.params
                                for i, a in enumerate(args):
                                    formal_t = (
                                        formal_params[i].type_val
                                        if i < len(formal_params)
                                        else a.type_val
                                    )
                                    is_r = (
                                        getattr(formal_params[i], "is_out", False)
                                        or getattr(formal_params[i], "is_var", False)
                                    ) if i < len(formal_params) else False
                                    is_o = (
                                        getattr(formal_params[i], "is_out", False)
                                        if i < len(formal_params)
                                        else False
                                    )
                                    c_args.append(
                                        self._emit_call_arg(
                                            formal_t, a, lines, is_ref=is_r, is_out=is_o
                                        )
                                    )
                            else:
                                c_args.extend([self.emit_val(a, lines) for a in args])

                            if binding.inline_template:
                                return binding.inline_template.format(*c_args)
                            elif binding.symbol:
                                call_str = f"{binding.symbol}({', '.join(c_args)})"
                                if expr.type_val == OK_TYPE:
                                    lines.append(f"{call_str};")
                                    return "((void)0)"
                                if (
                                    isinstance(inner_t, QFunType)
                                    and self.c_type(inner_t.result_type) == "QVal"
                                    and self.c_type(expr.type_val) != "QVal"
                                ):
                                    return _qval_unwrap(call_str, expr.type_val, self)
                                return call_str
                        elif (
                            isinstance(binding, TypedLetValue)
                            and isinstance(binding.value, TypedExternal)
                            and isinstance(getattr(binding.symbol, "type_val", None), (QFunType, QAllType))
                        ):
                            c_args = [self.emit_val(a, lines) for a in args]
                            call_str = f"{binding.value.symbol}({', '.join(c_args)})"
                            if expr.type_val == OK_TYPE:
                                lines.append(f"{call_str};")
                                return "((void)0)"
                            return call_str

                # Preceding descriptor arguments from type_args
                descriptor_args = [self.c_type_descriptor(targ) for targ in type_args]

                spec_fname = (
                    effective_func.name
                    if isinstance(effective_func, TypedVar)
                    else (
                        f"{effective_func.target.name}.{effective_func.field}"
                        if (
                            isinstance(effective_func, TypedSelect)
                            and isinstance(effective_func.target, TypedVar)
                        )
                        else None
                    )
                )
                spec_entry = (
                    self.specializations.get((spec_fname, tuple(type_args)))
                    if spec_fname and type_args
                    else None
                )

                if spec_entry is not None:
                    spec_ident, spec_fun = spec_entry
                    c_func = mangle_ident(spec_ident)
                    spec_quants, formal_params, _, ret_type = self._collect_fun_params(spec_fun)
                    c_args = [self.c_type_descriptor(q) for q in spec_quants]
                    for formal_p, actual_a in zip(formal_params, args):
                        is_r = getattr(formal_p, "is_out", False) or getattr(formal_p, "is_var", False)
                        is_o = getattr(formal_p, "is_out", False)
                        c_args.append(
                            self._emit_call_arg(
                                formal_p.type_val, actual_a, lines, is_ref=is_r, is_out=is_o
                            )
                        )
                    args_str = ", ".join(c_args)
                    call_str = f"{c_func}({args_str})"
                    if ret_type == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    return call_str
                elif isinstance(effective_func, TypedVar) and effective_func.name in self.top_fun_names:
                    c_func = self.current_env_vars.get(
                        effective_func.name, self.mangle_ident(effective_func.name)
                    )
                    c_args = list(descriptor_args)
                    fun, _ = self.top_funs_dict[effective_func.name]
                    _, formal_params, _, ret_type = self._collect_fun_params(fun)
                    writebacks: list[str] = []
                    for formal_p, actual_a in zip(formal_params, args):
                        is_r = getattr(formal_p, "is_out", False) or getattr(formal_p, "is_var", False)
                        is_o = getattr(formal_p, "is_out", False)
                        c_args.append(
                            self._emit_call_arg(
                                formal_p.type_val,
                                actual_a,
                                lines,
                                is_ref=is_r,
                                is_out=is_o,
                                writebacks=writebacks,
                            )
                        )
                    args_str = ", ".join(c_args)
                    call_str = f"{c_func}({args_str})"
                    if (
                        self.c_type(ret_type) == "QVal"
                        and self.c_type(expr.type_val) != "QVal"
                    ):
                        if (rec_bound := resolve_record_bound(ret_type)) is not None:
                            if isinstance(expr.type_val, QRecordType):
                                tmp_ret = self.fresh_tmp("_call_ret")
                                lines.append(f"QRecordVal {tmp_ret} = {call_str};")
                                d_name = self.record_ctx.offset_dict_instance_name(
                                    expr.type_val, expr.type_val
                                )
                                call_str = (
                                    f"((QRecordVal){{ .val = {tmp_ret}.val, "
                                    f".dict = (const void *)&{d_name} }})"
                                )
                        elif resolve_variant_bound(ret_type) is not None:
                            pass
                        else:
                            call_str = _qval_unwrap(call_str, expr.type_val, self)
                    elif (
                        isinstance(ret_type, QTupleType)
                        and isinstance(expr.type_val, QTupleType)
                        and ret_type != expr.type_val
                    ):
                        call_str = self._coerce_tuple_val(call_str, ret_type, expr.type_val, lines)
                    if writebacks:
                        if expr.type_val == OK_TYPE:
                            lines.append(f"{call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return "((void)0)"
                        else:
                            ret_c = self.c_type(expr.type_val)
                            ret_tmp = self.fresh_tmp("_call_res")
                            lines.append(f"{ret_c} {ret_tmp} = {call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return ret_tmp
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    return call_str
                elif (
                    isinstance(effective_func, TypedSelect)
                    and isinstance(effective_func.target, TypedVar)
                    and effective_func.target.name in self.all_modules
                    and (
                        (mod := self.all_modules[effective_func.target.name]) is not None
                        and getattr(mod, "is_precompiled", False)
                        and effective_func.field in mod.scope.values
                        and isinstance(mod.scope.values[effective_func.field].type_val, (QFunType, QAllType))
                    )
                ):
                    mod_name = effective_func.target.name
                    fld = effective_func.field
                    mod = self.all_modules[mod_name]
                    clean_mod = mod_name.replace(".", "_")
                    fld_sym = mod.scope.values[fld]
                    c_func = mangle_module_ident(clean_mod, fld)
                    c_args = list(descriptor_args)
                    if isinstance(fld_sym.type_val, QAllType):
                        mod_fun_t = fld_sym.type_val.body
                    else:
                        mod_fun_t = fld_sym.type_val
                    formal_params = mod_fun_t.params if isinstance(mod_fun_t, QFunType) else ()
                    ret_type = mod_fun_t.result_type if isinstance(mod_fun_t, QFunType) else OK_TYPE
                    writebacks: list[str] = []
                    for formal_p, actual_a in zip(formal_params, args):
                        is_r = getattr(formal_p, "is_out", False) or getattr(formal_p, "is_var", False)
                        is_o = getattr(formal_p, "is_out", False)
                        c_args.append(
                            self._emit_call_arg(
                                formal_p.type_val,
                                actual_a,
                                lines,
                                is_ref=is_r,
                                is_out=is_o,
                                writebacks=writebacks,
                            )
                        )
                    args_str = ", ".join(c_args)
                    call_str = f"{c_func}({args_str})"
                    if (
                        self.c_type(ret_type) == "QVal"
                        and self.c_type(expr.type_val) != "QVal"
                    ):
                        if (rec_bound := resolve_record_bound(ret_type)) is not None:
                            if isinstance(expr.type_val, QRecordType):
                                tmp_ret = self.fresh_tmp("_call_ret")
                                lines.append(f"QRecordVal {tmp_ret} = {call_str};")
                                d_name = self.record_ctx.offset_dict_instance_name(
                                    expr.type_val, expr.type_val
                                )
                                call_str = (
                                    f"((QRecordVal){{ .val = {tmp_ret}.val, "
                                    f".dict = (const void *)&{d_name} }})"
                                )
                        elif resolve_variant_bound(ret_type) is not None:
                            pass
                        else:
                            call_str = _qval_unwrap(call_str, expr.type_val, self)
                    elif (
                        isinstance(ret_type, QTupleType)
                        and isinstance(expr.type_val, QTupleType)
                        and ret_type != expr.type_val
                    ):
                        call_str = self._coerce_tuple_val(call_str, ret_type, expr.type_val, lines)
                    if writebacks:
                        if expr.type_val == OK_TYPE:
                            lines.append(f"{call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return "((void)0)"
                        else:
                            ret_c = self.c_type(expr.type_val)
                            ret_tmp = self.fresh_tmp("_call_res")
                            lines.append(f"{ret_c} {ret_tmp} = {call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return ret_tmp
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    return call_str
                else:
                    fn_ptr_t = _closure_fn_ptr_type(effective_func.type_val, self.record_ctx)
                    clos_val = self.emit_val(effective_func, lines)
                    _, inner_formal = self._collect_fun_quantifiers(effective_func.type_val)
                    formal_params = inner_formal.params if isinstance(inner_formal, QFunType) else None
                    c_args = list(descriptor_args)
                    writebacks = []
                    for i, actual_a in enumerate(args):
                        if formal_params and i < len(formal_params):
                            fp = formal_params[i]
                            is_r = getattr(fp, "is_out", False) or getattr(fp, "is_var", False)
                            is_o = getattr(fp, "is_out", False)
                            c_args.append(
                                self._emit_call_arg(
                                    fp.type_val,
                                    actual_a,
                                    lines,
                                    is_ref=is_r,
                                    is_out=is_o,
                                    writebacks=writebacks,
                                )
                            )
                        else:
                            c_args.append(self._emit_call_arg(actual_a.type_val, actual_a, lines))
                    all_c_args = [f"{clos_val}->env"] + c_args
                    args_str = ", ".join(all_c_args)
                    call_str = f"(({fn_ptr_t})({clos_val}->fn))({args_str})"
                    formal_ret = inner_formal.result_type if isinstance(inner_formal, QFunType) else None
                    if (
                        formal_ret is not None
                        and self.c_type(formal_ret) == "QVal"
                        and self.c_type(expr.type_val) != "QVal"
                    ):
                        if (rec_bound := resolve_record_bound(formal_ret)) is not None:
                            if isinstance(expr.type_val, QRecordType):
                                tmp_ret = self.fresh_tmp("_call_ret")
                                lines.append(f"QRecordVal {tmp_ret} = {call_str};")
                                d_name = self.record_ctx.offset_dict_instance_name(
                                    expr.type_val, expr.type_val
                                )
                                call_str = (
                                    f"((QRecordVal){{ .val = {tmp_ret}.val, "
                                    f".dict = (const void *)&{d_name} }})"
                                )
                        elif resolve_variant_bound(formal_ret) is not None:
                            pass
                        else:
                            call_str = _qval_unwrap(call_str, expr.type_val, self)
                    elif (
                        formal_ret is not None
                        and isinstance(formal_ret, QTupleType)
                        and isinstance(expr.type_val, QTupleType)
                        and formal_ret != expr.type_val
                    ):
                        call_str = self._coerce_tuple_val(call_str, formal_ret, expr.type_val, lines)
                    if writebacks:
                        if expr.type_val == OK_TYPE:
                            lines.append(f"{call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return "((void)0)"
                        else:
                            ret_c = self.c_type(expr.type_val)
                            ret_tmp = self.fresh_tmp("_call_res")
                            lines.append(f"{ret_c} {ret_tmp} = {call_str};")
                            for wb in writebacks:
                                lines.append(wb)
                            return ret_tmp
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    return call_str

            case TypedArray() | TypedArrayRep():
                tmp = self.fresh_tmp("_arr")
                c_type = self.c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedIndex(target=tgt, index=idx):
                c_tgt = self.emit_val(tgt, lines)
                c_idx = self.emit_val(idx, lines)
                lines.append(f"quest_check_array_bounds({c_tgt}, {c_idx});")
                return self._emit_array_get(c_tgt, c_idx, expr.type_val)

            case TypedIndexAssign(target=tgt, index=idx, value=val):
                c_tgt = self.emit_val(tgt, lines)
                c_idx = self.emit_val(idx, lines)
                lines.append(f"quest_check_array_bounds({c_tgt}, {c_idx});")
                c_val = self.emit_val(val, lines)
                target_elem_t = tgt.type_val.element_type if isinstance(tgt.type_val, QArrayType) else val.type_val
                if isinstance(target_elem_t, QRecordType) or resolve_record_bound(target_elem_t) is not None:
                    c_val = self._coerce_record_val(c_val, val, target_elem_t)
                    lines.append(f"{c_tgt}->data[{c_idx}] = {c_val};")
                elif (
                    isinstance(target_elem_t, QVariantType)
                    or resolve_variant_bound(target_elem_t) is not None
                ):
                    if (
                        isinstance(val.type_val, QVariantType)
                        and val.type_val != target_elem_t
                    ):
                        c_val = self._emit_variant_upcast(
                            c_val, val.type_val, target_elem_t, lines
                        )
                    lines.append(f"{c_tgt}->data[{c_idx}] = {c_val};")
                else:
                    wrap = _qval_wrap(c_val, target_elem_t)
                    lines.append(f"{c_tgt}->data[{c_idx}] = {wrap};")
                return "((void)0)"

            case TypedExit():
                lines.append("break;")
                return "((void)0)"

            case TypedException(name=name):
                c_name = _c_string_literal(name) if name else '""'
                return f"quest_alloc_exception({c_name})"

            case TypedRaise():
                self.emit_to(expr, None, lines)
                return "((void)0)"

            case TypedIf() | TypedBlock() | TypedWhile() | TypedLoop() | TypedFor() | TypedTry():
                if expr.type_val == OK_TYPE:
                    self.emit_to(expr, None, lines)
                    return "((void)0)"
                tmp = self.fresh_tmp("_val")
                c_type = self.c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedTypeApp(func=func, type_args=type_args):
                _, inner_t = self._collect_fun_quantifiers(expr.type_val)
                if isinstance(inner_t, QFunType):
                    return self.emit_val(func, lines)
                descriptor_args = [self.c_type_descriptor(targ) for targ in type_args]
                if isinstance(func, TypedVar) and func.name in self.top_fun_names:
                    c_func = self.mangle_ident(func.name)
                    call_str = f"{c_func}({', '.join(descriptor_args)})"
                    return call_str
                else:
                    fn_ptr_t = _closure_fn_ptr_type(func.type_val, self.record_ctx)
                    clos_val = self.emit_val(func, lines)
                    all_c_args = [f"{clos_val}->env"] + descriptor_args
                    call_str = f"(({fn_ptr_t})({clos_val}->fn))({', '.join(all_c_args)})"
                    return call_str

            case TypedExternal(symbol=symbol):
                return symbol

            case _:
                raise NotImplementedError(
                    f"C code generation for {expr.__class__.__name__} not implemented in Phase 4.3"
                )

    def emit_to(self, expr: TypedExpr, dest: Optional[str], lines: list[str]) -> None:
        """Lowers expr into lines, storing the result into dest (if dest is not None)."""
        match expr:
            case TypedIf(cond=cond, then_branch=then_b, else_branch=else_b, type_val=t):
                c_cond = self.emit_val(cond, lines)
                lines.append(f"if ({c_cond}) {{")
                then_lines: list[str] = []
                self.emit_to(then_b, dest, then_lines)
                for line in then_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                if else_b is not None:
                    lines.append("} else {")
                    else_lines: list[str] = []
                    self.emit_to(else_b, dest, else_lines)
                    for line in else_lines:
                        lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedBlock(bindings=bindings, result=result):
                lines.append("{")
                block_lines: list[str] = []
                for b in bindings:
                    match b:
                        case TypedLetValue(name=name, value=val, symbol=symbol):
                            c_ident = mangle_ident(name)
                            if symbol.type_val == OK_TYPE:
                                self.emit_to(val, None, block_lines)
                            elif isinstance(symbol.type_val, QRecordType):
                                block_lines.append(f"QRecordVal {c_ident};")
                                val_c = self.emit_val(val, block_lines)
                                coerced = self._coerce_record_val(val_c, val, symbol.type_val)
                                block_lines.append(f"{c_ident} = {coerced};")
                            elif (
                                isinstance(symbol.type_val, QTupleType)
                                and isinstance(val.type_val, QTupleType)
                                and val.type_val != symbol.type_val
                            ):
                                c_type = self.c_type(symbol.type_val)
                                block_lines.append(f"{c_type} {c_ident};")
                                val_c = self.emit_val(val, block_lines)
                                self._coerce_tuple_val(
                                    val_c, val.type_val, symbol.type_val, block_lines, dest=c_ident
                                )
                            elif (
                                isinstance(symbol.type_val, QVariantType)
                                and isinstance(val.type_val, QVariantType)
                                and val.type_val != symbol.type_val
                            ):
                                block_lines.append(f"QVariantVal {c_ident};")
                                val_c = self.emit_val(val, block_lines)
                                self._emit_variant_upcast(
                                    val_c, val.type_val, symbol.type_val, block_lines, dest=c_ident
                                )
                            else:
                                c_type = self.c_type(symbol.type_val)
                                block_lines.append(f"{c_type} {c_ident};")
                                self.emit_to(val, c_ident, block_lines)
                        case TypedExprStmt(expr=TypedException(name=name) as exc_node):
                            if name:
                                c_ident = mangle_ident(name)
                                block_lines.append(f"const QException *{c_ident};")
                                self.emit_to(exc_node, c_ident, block_lines)
                            else:
                                self.emit_to(exc_node, None, block_lines)
                        case TypedException(name=name) as exc_node:
                            if name:
                                c_ident = mangle_ident(name)
                                block_lines.append(f"const QException *{c_ident};")
                                self.emit_to(exc_node, c_ident, block_lines)
                            else:
                                self.emit_to(exc_node, None, block_lines)
                        case TypedExprStmt(expr=inner):
                            self.emit_to(inner, None, block_lines)
                        case _:
                            pass
                self.emit_to(result, dest, block_lines)
                for line in block_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedWhile(cond=cond, body=body):
                lines.append("while (1) {")
                loop_lines: list[str] = []
                c_cond = self.emit_val(cond, loop_lines)
                loop_lines.append(f"if (!({c_cond})) break;")
                self.emit_to(body, None, loop_lines)
                for line in loop_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedLoop(body=body):
                lines.append("while (1) {")
                loop_lines = []
                self.emit_to(body, None, loop_lines)
                for line in loop_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedFor(start=start, stop=stop, body=body, is_downto=is_downto, var_name=var_name):
                c_start = self.emit_val(start, lines)
                c_stop = self.emit_val(stop, lines)
                v = mangle_ident(var_name)
                stop_tmp = self.fresh_tmp("_stop")
                cmp_op = ">=" if is_downto else "<="
                step_op = "--" if is_downto else "++"
                lines.append(f"QInt {stop_tmp} = {c_stop};")
                lines.append(f"for (QInt {v} = {c_start}; {v} {cmp_op} {stop_tmp}; {v}{step_op}) {{")
                for_lines: list[str] = []
                self.emit_to(body, None, for_lines)
                for line in for_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedExit():
                lines.append("break;")

            case TypedTuple(elements=elems, type_val=t):
                struct_name = tuple_struct_name(t)
                alloc_expr = f"({struct_name} *)quest_alloc(sizeof({struct_name}))"
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_tuple")
                    lines.append(f"{struct_name} *{target_dest} = {alloc_expr};")
                else:
                    lines.append(f"{target_dest} = {alloc_expr};")
                val_idx = 0
                for elem in elems:
                    if isinstance(elem, TypedTypeWitness):
                        continue
                    expected_fld_t = t.value_fields[val_idx].type_val
                    expected_fld_c = qtype_to_c_type(expected_fld_t, self.record_ctx)
                    elem_c_t = qtype_to_c_type(elem.type_val, self.record_ctx)
                    if expected_fld_c == "QVal" and elem_c_t != "QVal":
                        val_c = self.emit_val(elem, lines)
                        wrapped = _qval_wrap(val_c, elem.type_val)
                        lines.append(f"{target_dest}->_{val_idx} = {wrapped};")
                    elif (
                        isinstance(expected_fld_t, (QFunType, QAllType))
                        and isinstance(elem.type_val, (QFunType, QAllType))
                        and _closure_fn_ptr_type(expected_fld_t, self.record_ctx)
                        != _closure_fn_ptr_type(elem.type_val, self.record_ctx)
                    ):
                        val_c = self.emit_val(elem, lines)
                        adapted = self._emit_closure_adaptation(
                            val_c, elem.type_val, expected_fld_t, lines
                        )
                        lines.append(f"{target_dest}->_{val_idx} = {adapted};")
                    elif (
                        isinstance(expected_fld_t, QTupleType)
                        and isinstance(elem.type_val, QTupleType)
                        and elem.type_val != expected_fld_t
                    ):
                        val_c = self.emit_val(elem, lines)
                        coerced = self._coerce_tuple_val(
                            val_c, elem.type_val, expected_fld_t, lines
                        )
                        lines.append(f"{target_dest}->_{val_idx} = {coerced};")
                    elif isinstance(expected_fld_t, QRecordType):
                        val_c = self.emit_val(elem, lines)
                        coerced = self._coerce_record_val(val_c, elem, expected_fld_t)
                        lines.append(f"{target_dest}->_{val_idx} = {coerced};")
                    elif (
                        isinstance(expected_fld_t, QVariantType)
                        and isinstance(elem.type_val, QVariantType)
                        and elem.type_val != expected_fld_t
                    ):
                        val_c = self.emit_val(elem, lines)
                        tmp_v = self._emit_variant_upcast(
                            val_c, elem.type_val, expected_fld_t, lines
                        )
                        lines.append(f"{target_dest}->_{val_idx} = {tmp_v};")
                    else:
                        self.emit_to(elem, f"{target_dest}->_{val_idx}", lines)
                    val_idx += 1

            case TypedRecord(fields=flds, type_val=t):
                concrete_t = self._effective_record_type(expr)
                struct_name = self.record_struct_name(concrete_t)
                alloc_expr = f"({struct_name} *)quest_alloc(sizeof({struct_name}))"
                payload_tmp = self.fresh_tmp("_rec_payload")
                lines.append(f"{struct_name} *{payload_tmp} = {alloc_expr};")
                lines.append(f"{payload_tmp}->header.descriptor = NULL;")
                for fld in flds:
                    self.emit_to(fld.value, f"{payload_tmp}->qf_{fld.name}", lines)
                if dest is not None:
                    target_t = t if isinstance(t, QRecordType) else concrete_t
                    d_name = self.record_ctx.offset_dict_instance_name(target_t, concrete_t)
                    lines.append(
                        f"{dest} = (QRecordVal){{ .val = (void *){payload_tmp}, "
                        f".dict = (const void *)&{d_name} }};"
                    )

            case TypedFun():
                linfo = self.lambda_info_by_id[id(expr)]
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_clos")
                    lines.append(f"QClosure *{target_dest};")

                if not linfo.free_vars:
                    lines.append(f"{target_dest} = &{linfo.closure_var_name};")
                else:
                    env_tmp = self.fresh_tmp("_env")
                    lines.append(
                        f"{linfo.env_struct_name} *{env_tmp} = "
                        f"({linfo.env_struct_name} *)quest_alloc(sizeof({linfo.env_struct_name}));"
                    )
                    for vname, _ in linfo.free_vars:
                        src_val = (
                            self.current_env_vars[vname]
                            if vname in self.current_env_vars
                            else mangle_ident(vname)
                        )
                        lines.append(f"{env_tmp}->{mangle_ident(vname)} = {src_val};")
                    lines.append(f"{target_dest} = (QClosure *)quest_alloc(sizeof(QClosure));")
                    lines.append(f"{target_dest}->fn = (void *){linfo.c_fn_name};")
                    lines.append(f"{target_dest}->env = (void *){env_tmp};")

            case TypedArray(elements=elems, type_val=t):
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_arr")
                    c_type = self.c_type(t)
                    lines.append(f"{c_type} {target_dest};")
                n = len(elems)
                elem_t = t.element_type
                if isinstance(elem_t, QRecordType) or resolve_record_bound(elem_t) is not None:
                    lines.append(
                        f"{target_dest} = (QArrayWideRecord *)quest_alloc("
                        f"sizeof(QArrayWideRecord) + (size_t)({n}LL) * sizeof(QRecordVal));"
                    )
                    lines.append(f"{target_dest}->length = {n}LL;")
                    for i, elem in enumerate(elems):
                        c_elem = self.emit_val(elem, lines)
                        c_elem = self._coerce_record_val(c_elem, elem, elem_t)
                        lines.append(f"{target_dest}->data[{i}LL] = {c_elem};")
                elif isinstance(elem_t, QVariantType) or resolve_variant_bound(elem_t) is not None:
                    lines.append(
                        f"{target_dest} = (QArrayWideVariant *)quest_alloc("
                        f"sizeof(QArrayWideVariant) + (size_t)({n}LL) * sizeof(QVariantVal));"
                    )
                    lines.append(f"{target_dest}->length = {n}LL;")
                    for i, elem in enumerate(elems):
                        c_elem = self.emit_val(elem, lines)
                        if (
                            isinstance(elem.type_val, QVariantType)
                            and elem.type_val != elem_t
                        ):
                            c_elem = self._emit_variant_upcast(
                                c_elem, elem.type_val, elem_t, lines
                            )
                        lines.append(f"{target_dest}->data[{i}LL] = {c_elem};")
                else:
                    lines.append(
                        f"{target_dest} = (QArray *)quest_alloc("
                        f"sizeof(QArray) + (size_t)({n}LL) * sizeof(QVal));"
                    )
                    lines.append(f"{target_dest}->length = {n}LL;")
                    for i, elem in enumerate(elems):
                        c_elem = self.emit_val(elem, lines)
                        wrap = _qval_wrap(c_elem, elem_t)
                        lines.append(f"{target_dest}->data[{i}LL] = {wrap};")

            case TypedArrayRep(count=cnt, init_val=init_v, type_val=t):
                c_cnt = self.emit_val(cnt, lines)
                c_init = self.emit_val(init_v, lines)
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_arr")
                    c_type = self.c_type(t)
                    lines.append(f"{c_type} {target_dest};")
                elem_t = t.element_type
                if isinstance(elem_t, QRecordType) or resolve_record_bound(elem_t) is not None:
                    c_init = self._coerce_record_val(c_init, init_v, elem_t)
                    lines.append(f"{target_dest} = quest_array_new_wide_record({c_cnt}, {c_init});")
                elif isinstance(elem_t, QVariantType) or resolve_variant_bound(elem_t) is not None:
                    if (
                        isinstance(init_v.type_val, QVariantType)
                        and init_v.type_val != elem_t
                    ):
                        c_init = self._emit_variant_upcast(
                            c_init, init_v.type_val, elem_t, lines
                        )
                    lines.append(f"{target_dest} = quest_array_new_wide_variant({c_cnt}, {c_init});")
                else:
                    wrap = _qval_wrap(c_init, elem_t)
                    lines.append(f"{target_dest} = quest_array_new({c_cnt}, {wrap});")

            case TypedVariant(tag=tag, payload=payload, type_val=t):
                tag_idx = self._tag_index(t, tag)
                if payload is not None:
                    c_payload = self.emit_val(payload, lines)
                    v_field = t.get_variant(tag) if isinstance(t, QVariantType) else None
                    payload_expected_t = (
                        v_field.type_val if v_field and v_field.type_val else payload.type_val
                    )
                    if isinstance(payload_expected_t, QRecordType):
                        c_payload = self._coerce_record_val(c_payload, payload, payload_expected_t)
                    elif (
                        isinstance(payload_expected_t, QVariantType)
                        and isinstance(payload.type_val, QVariantType)
                        and payload.type_val != payload_expected_t
                    ):
                        c_payload = self._emit_variant_upcast(
                            c_payload, payload.type_val, payload_expected_t, lines
                        )
                    wrap = _qval_wrap(c_payload, payload_expected_t)
                else:
                    wrap = "Q_OK_VAL"

                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_var")
                    lines.append(
                        f"QVariantVal {target_dest} = (QVariantVal){{ "
                        f".tag = {tag_idx}LL, .payload = {wrap} }};"
                    )
                else:
                    lines.append(
                        f"{target_dest} = (QVariantVal){{ "
                        f".tag = {tag_idx}LL, .payload = {wrap} }};"
                    )

            case TypedOption(tag=tag, payload=payload, ordinal=ordinal, ordinal_expr=ordinal_expr, type_val=t):
                target_dest = dest
                opt_t = t if isinstance(t, QOptionType) else (resolve_option_bound(t) or t)
                s_name = option_struct_name(opt_t)
                if target_dest is None:
                    target_dest = self.fresh_tmp("_opt")
                    lines.append(f"{s_name} *{target_dest};")
                lines.append(f"{target_dest} = ({s_name} *)quest_alloc(sizeof({s_name}));")
                if ordinal_expr is not None:
                    c_ord = self.emit_val(ordinal_expr, lines)
                    lines.append(f"{target_dest}->tag = {c_ord};")
                    if tag is None and hasattr(opt_t, "options") and opt_t.options:
                        if isinstance(ordinal_expr, TypedInt) and 0 <= ordinal_expr.value < len(opt_t.options):
                            tag = opt_t.options[ordinal_expr.value].name
                        else:
                            tag = opt_t.options[0].name
                else:
                    tag_idx = self._tag_index(opt_t, tag) if tag is not None else ordinal
                    lines.append(f"{target_dest}->tag = {tag_idx}LL;")

                if payload is not None and tag is not None:
                    opt_field = opt_t.get_option(tag) if hasattr(opt_t, "get_option") else None
                    if opt_field and opt_field.payload_type:
                        pt = opt_field.payload_type
                        if isinstance(pt, QTupleType) and isinstance(payload, TypedTuple):
                            for i, elem in enumerate(payload.elements):
                                c_elem = self.emit_val(elem, lines)
                                f_type = (
                                    pt.value_fields[i].type_val
                                    if i < len(pt.value_fields)
                                    else elem.type_val
                                )
                                if self.c_type(f_type) == "QVal" and self.c_type(elem.type_val) != "QVal":
                                    c_elem = _qval_wrap(c_elem, elem.type_val)
                                lines.append(f"{target_dest}->u.{tag}._{i} = {c_elem};")
                        elif isinstance(pt, QRecordType) and isinstance(payload, TypedRecord):
                            for f in payload.fields:
                                c_f = self.emit_val(f.value, lines)
                                lines.append(f"{target_dest}->u.{tag}.qf_{f.name} = {c_f};")
                        else:
                            c_p = self.emit_val(payload, lines)
                            lines.append(f"{target_dest}->u.{tag}.val = {c_p};")

            case TypedCase(target=tgt, branches=branches, else_branch=else_b, type_val=t):
                c_tgt = self.emit_val(tgt, lines)
                target_type = tgt.type_val
                if (var_bound := resolve_variant_bound(target_type)) is not None:
                    target_type = var_bound
                elif (opt_bound := resolve_option_bound(target_type)) is not None:
                    target_type = opt_bound
                if isinstance(target_type, QVariantType):
                    if not c_tgt.isidentifier():
                        tmp_tgt = self.fresh_tmp("_case_tgt")
                        lines.append(f"QVariantVal {tmp_tgt} = {c_tgt};")
                        c_tgt = tmp_tgt
                    tag_expr = f"{c_tgt}.tag"
                else:
                    tag_expr = f"{c_tgt}->tag"
                lines.append(f"switch ({tag_expr}) {{")
                for branch in branches:
                    for tag in branch.tags:
                        tag_idx = self._tag_index(target_type, tag)
                        lines.append(f"    case {tag_idx}LL:")
                    lines.append("    {")
                    branch_lines: list[str] = []
                    if branch.binder is not None:
                        b_name = mangle_ident(branch.binder.name)
                        b_type = branch.binder.type_val
                        c_b_type = self.c_type(b_type)
                        branch_lines.append(f"{c_b_type} {b_name};")
                        if isinstance(target_type, QOptionType):
                            if isinstance(b_type, QTupleType):
                                s_tup = tuple_struct_name(b_type)
                                branch_lines.append(f"{b_name} = ({s_tup} *)quest_alloc(sizeof({s_tup}));")
                                opt_branch = target_type.get_option(branch.tags[0]) if branch.tags else None
                                opt_pt = opt_branch.payload_type if opt_branch else None
                                for i, f in enumerate(b_type.value_fields):
                                    field_src = f"{c_tgt}->u.{branch.tags[0]}._{i}"
                                    opt_f_t = (
                                        opt_pt.value_fields[i].type_val
                                        if isinstance(opt_pt, QTupleType) and i < len(opt_pt.value_fields)
                                        else None
                                    )
                                    if (
                                        opt_f_t is not None
                                        and self.c_type(opt_f_t) == "QVal"
                                        and self.c_type(f.type_val) != "QVal"
                                    ):
                                        field_src = _qval_unwrap(field_src, f.type_val, self)
                                    branch_lines.append(f"{b_name}->_{i} = {field_src};")
                            elif isinstance(b_type, QRecordType):
                                s_rec = self.record_struct_name(b_type)
                                branch_lines.append(f"{b_name} = ({s_rec} *)quest_alloc(sizeof({s_rec}));")
                                branch_lines.append(f"{b_name}->header.descriptor = NULL;")
                                for f in sorted(b_type.fields, key=lambda fld: fld.name):
                                    branch_lines.append(
                                        f"{b_name}->qf_{f.name} = {c_tgt}->u.{branch.tags[0]}.qf_{f.name};"
                                    )
                            else:
                                branch_lines.append(f"{b_name} = {c_tgt}->u.{branch.tags[0]}.val;")
                        elif isinstance(target_type, QVariantType):
                            extracted = self._emit_qval_extract(f"{c_tgt}.payload", b_type)
                            branch_lines.append(f"{b_name} = {extracted};")

                    self.emit_to(branch.body, dest, branch_lines)
                    for bline in branch_lines:
                        lines.append(f"        {bline}" if bline.strip() else bline)
                    lines.append("        break;")
                    lines.append("    }")

                lines.append("    default: {")
                default_lines: list[str] = []
                if else_b is not None:
                    self.emit_to(else_b, dest, default_lines)
                else:
                    default_lines.append("quest_raise_variant_error();")
                for dline in default_lines:
                    lines.append(f"        {dline}" if dline.strip() else dline)
                lines.append("        break;")
                lines.append("    }")
                lines.append("}")

            case TypedException(name=name):
                c_name = _c_string_literal(name) if name else '""'
                if dest is not None:
                    lines.append(f"{dest} = quest_alloc_exception({c_name});")
                else:
                    lines.append(f"quest_alloc_exception({c_name});")

            case TypedRaise(exc=exc, payload=payload):
                c_exc = self.emit_val(exc, lines)
                if payload is not None:
                    c_payload_val = self.emit_val(payload, lines)
                    c_payload = _qval_wrap(c_payload_val, payload.type_val)
                else:
                    c_payload = "Q_OK_VAL"
                lines.append(f"quest_raise({c_exc}, {c_payload});")

            case TypedTry(body=body, branches=branches, else_branch=else_b, type_val=t):
                h_name = self.fresh_tmp("_qh")
                caught_name = self.fresh_tmp("_caught")
                lines.append("{")
                lines.append(f"    QExceptionHandler {h_name};")
                lines.append(f"    {h_name}.prev = quest_current_exception_handler;")
                lines.append(f"    quest_current_exception_handler = &{h_name};")
                lines.append(f"    if (setjmp({h_name}.env_jmp) == 0) {{")
                body_lines: list[str] = []
                self.emit_to(body, dest, body_lines)
                for bl in body_lines:
                    lines.append(f"        {bl}" if bl.strip() else bl)
                lines.append(f"        quest_current_exception_handler = {h_name}.prev;")
                lines.append("    } else {")
                lines.append(f"        quest_current_exception_handler = {h_name}.prev;")
                lines.append(f"        QExceptionState {caught_name} = quest_current_exception;")
                first_branch = True
                for branch in branches:
                    cond_prefix = "if" if first_branch else "else if"
                    first_branch = False
                    br_eval_lines: list[str] = []
                    pat_val = self.emit_val(branch.exc_pattern, br_eval_lines)
                    for el in br_eval_lines:
                        lines.append(f"        {el}" if el.strip() else el)
                    lines.append(f"        {cond_prefix} ({caught_name}.exc == {pat_val}) {{")
                    branch_lines: list[str] = []
                    if branch.binder is not None:
                        b_name = mangle_ident(branch.binder.name)
                        b_type = branch.binder.type_val
                        c_b_type = self.c_type(b_type)
                        branch_lines.append(f"{c_b_type} {b_name};")
                        extracted = self._emit_qval_extract(f"{caught_name}.payload", b_type)
                        branch_lines.append(f"{b_name} = ({c_b_type})({extracted});")
                    self.emit_to(branch.body, dest, branch_lines)
                    for bl in branch_lines:
                        lines.append(f"            {bl}" if bl.strip() else bl)
                    lines.append("        }")
                lines.append("        else {")
                default_lines: list[str] = []
                if else_b is not None:
                    self.emit_to(else_b, dest, default_lines)
                else:
                    default_lines.append(f"quest_raise({caught_name}.exc, {caught_name}.payload);")
                for dl in default_lines:
                    lines.append(f"            {dl}" if dl.strip() else dl)
                lines.append("        }")
                lines.append("    }")
                lines.append("}")

            case TypedInspect(target=tgt, branches=branches, else_branch=else_b, type_val=t):
                c_tgt = self.emit_val(tgt, lines)
                if not c_tgt.isidentifier():
                    tmp_tgt = self.fresh_tmp("_insp_tgt")
                    lines.append(f"const QDynamic *{tmp_tgt} = {c_tgt};")
                    c_tgt = tmp_tgt
                if not branches:
                    if else_b is not None:
                        self.emit_to(else_b, dest, lines)
                    else:
                        lines.append("quest_raise_dynamic_error();")
                else:
                    for i, branch in enumerate(branches):
                        match_desc = self.c_type_descriptor(branch.match_type)
                        cond = f"quest_is_subtype({c_tgt}->type_desc, {match_desc})"
                        prefix = "if" if i == 0 else "} else if"
                        lines.append(f"{prefix} ({cond}) {{")
                        branch_lines: list[str] = []
                        if branch.binders:
                            call_str = f"quest_dynamic_be({match_desc}, {c_tgt})"
                            val_expr = _qval_unwrap(call_str, branch.match_type, self)
                            first_sym = branch.binders[0]
                            c_b_type = self.c_type(first_sym.type_val)
                            tmp_bind = self.fresh_tmp("_insp_val")
                            branch_lines.append(f"{c_b_type} {tmp_bind} = {val_expr};")
                            for b_sym in branch.binders:
                                b_name = mangle_ident(b_sym.name)
                                branch_lines.append(f"{c_b_type} {b_name} = {tmp_bind};")
                        self.emit_to(branch.body, dest, branch_lines)
                        for bl in branch_lines:
                            lines.append(f"    {bl}" if bl.strip() else bl)
                    lines.append("} else {")
                    default_lines: list[str] = []
                    if else_b is not None:
                        self.emit_to(else_b, dest, default_lines)
                    else:
                        default_lines.append("quest_raise_dynamic_error();")
                    for dl in default_lines:
                        lines.append(f"    {dl}" if dl.strip() else dl)
                    lines.append("}")

            case _:
                val = self.emit_val(expr, lines)
                if dest is not None and expr.type_val != OK_TYPE:
                    lines.append(f"{dest} = {val};")
                elif val != "((void)0)":
                    lines.append(f"{val};")

    def _emit_infix(self, c_left: str, op: str, c_right: str) -> str:
        # 1. Integer division and modulo via C99 inline runtime functions
        if op == "/":
            return f"quest_int_div({c_left}, {c_right})"
        if op in ("%", "mod"):
            return f"quest_int_mod({c_left}, {c_right})"

        # 2. Real exponentiation
        if op == "^^":
            return f"quest_real_pow({c_left}, {c_right})"

        # 3. String concatenation
        if op == "<>":
            return f"quest_string_concat({c_left}, {c_right})"

        # 4. Standard arithmetic & relations mapping directly
        op_map = {
            "+": "+", "-": "-", "*": "*",
            "++": "+", "--": "-", "**": "*", "//": "/",
            "<": "<", "<=": "<=", ">": ">", ">=": ">=",
            "<<": "<", "<<=": "<=", ">>": ">", ">>=": ">=",
            "/\\": "&&", "\\/": "||",
            "is": "==", "isnot": "!=", "==": "==",
        }
        if op in op_map:
            c_op = op_map[op]
            return f"(({c_left}) {c_op} ({c_right}))"

        raise NotImplementedError(f"Unsupported infix operator '{op}' in C codegen")
