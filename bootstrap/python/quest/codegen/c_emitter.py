"""C Code Generator for Quest AST (Emitting Standard ISO C99)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quest.builtins import BuiltinModuleRegistry
from quest.codegen.c_analysis import (
    CLambdaInfo,
    CProgramAnalysis,
    analyze_program_for_c,
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
    TypedDerefCell,
    TypedException,
    TypedExit,
    TypedExpr,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedImport,
    TypedIndex,
    TypedIndexAssign,
    TypedInfix,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedModule,
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
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QAbstractType,
    QAllType,
    QArrayType,
    QExceptionType,
    QFunType,
    QOptionType,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QType,
    QTypeVar,
    QVariantType,
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

    def __init__(self, echo: bool = False, module_prefix: Optional[str] = None):
        self.echo = echo
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

    def c_type(self, t: QType) -> str:
        return qtype_to_c_type(t, self.record_ctx)

    def c_type_descriptor(self, t: QType) -> str:
        """Returns the C expression evaluating to `const QTypeDescriptor *` for type `t`."""
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
        if isinstance(t, QTypeVar):
            return self.in_scope_type_descriptors.get(t.name, f"descriptor_{t.name}")
        if isinstance(t, QAbstractType):
            if t.name in self.in_scope_type_descriptors:
                return self.in_scope_type_descriptors[t.name]
            return f"qv_qt_{t.name}"
        if isinstance(t, QArrayType):
            elem_desc = self.c_type_descriptor(t.element_type)
            return f"quest_make_array_descriptor({elem_desc})"
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
            decls.append(f"{self.c_type(p.type_val)} {p_c}")
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

    def _emit_fun_return(self, body: TypedExpr, ret_type: QType, fn_lines: list[str]) -> None:
        """Emits function return handling with appropriate subtyping coercions."""
        if ret_type == OK_TYPE:
            self.emit_to(body, None, fn_lines)
            fn_lines.append("return;")
        elif isinstance(ret_type, QRecordType):
            ret_val = self.emit_val(body, fn_lines)
            coerced = self._coerce_record_val(ret_val, body, ret_type)
            fn_lines.append(f"return {coerced};")
        elif (
            isinstance(ret_type, QTupleType)
            and isinstance(body.type_val, QTupleType)
            and body.type_val != ret_type
        ):
            ret_val = self.emit_val(body, fn_lines)
            cast_t = self.c_type(ret_type)
            fn_lines.append(f"return ({cast_t}){ret_val};")
        elif (
            isinstance(ret_type, QVariantType)
            and isinstance(body.type_val, QVariantType)
            and body.type_val != ret_type
        ):
            ret_val = self.emit_val(body, fn_lines)
            tmp_v = self._emit_variant_upcast(ret_val, body.type_val, ret_type, fn_lines)
            fn_lines.append(f"return {tmp_v};")
        else:
            ret_val = self.emit_val(body, fn_lines)
            fn_lines.append(f"return {ret_val};")

    def _emit_call_arg(self, formal_t: QType, actual_a: TypedExpr, lines: list[str]) -> str:
        """Emits and coerces an argument at a function or closure call site."""
        c_a = self.emit_val(actual_a, lines)
        if isinstance(formal_t, QRecordType):
            return self._coerce_record_val(c_a, actual_a, formal_t)
        elif (
            isinstance(formal_t, QTupleType)
            and isinstance(actual_a.type_val, QTupleType)
            and actual_a.type_val != formal_t
        ):
            cast_t = self.c_type(formal_t)
            return f"(({cast_t}){c_a})"
        elif (
            isinstance(formal_t, QVariantType)
            and isinstance(actual_a.type_val, QVariantType)
            and actual_a.type_val != formal_t
        ):
            return self._emit_variant_upcast(c_a, actual_a.type_val, formal_t, lines)
        elif isinstance(formal_t, QTypeVar):
            return _qval_wrap(c_a, actual_a.type_val)
        else:
            return c_a

    def _emit_array_get(self, c_arr: str, c_idx: str, elem_t: QType) -> str:
        """Emits C expression to extract an element of type elem_t from a QArray slot."""
        if elem_t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
            return f"({c_arr}->data[{c_idx}].i)"
        elif elem_t == REAL_TYPE:
            return f"({c_arr}->data[{c_idx}].r)"
        elif isinstance(elem_t, QRecordType):
            return f"(*((QRecordVal *)({c_arr}->data[{c_idx}].p)))"
        elif isinstance(elem_t, QVariantType):
            return f"(*((QVariantVal *)({c_arr}->data[{c_idx}].p)))"
        elif (
            elem_t == STRING_TYPE
            or elem_t == DYNAMIC_TYPE
            or (isinstance(elem_t, QTypeVar) and elem_t.name == "Dynamic.T")
            or isinstance(
                elem_t,
                (QTupleType, QFunType, QAllType, QArrayType, QOptionType, QExceptionType),
            )
        ):
            c_elem_t = self.c_type(elem_t)
            return f"(({c_elem_t})({c_arr}->data[{c_idx}].p))"
        else:
            return f"({c_arr}->data[{c_idx}])"

    def _tag_index(self, t: QType, tag: Optional[str]) -> int:
        """Returns the 0-based integer tag index for an Option or Variant tag."""
        if tag is None:
            return 0
        if isinstance(t, QOptionType):
            for i, opt in enumerate(t.options):
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
        lines.extend(decl_emitter.emit_environment_structs(self.lifted_lambdas))
        lines.extend(decl_emitter.emit_top_vars_declarations(analysis.top_vars, self.var_dict_names))
        lines.extend(decl_emitter.emit_forward_declarations_and_trampolines(
            analysis.top_funs,
            self.lifted_lambdas,
            self.val_referenced_top_funs,
            self.top_funs_dict,
        ))

        top_funs = analysis.top_funs
        top_vars = analysis.top_vars
        sorted_modules = analysis.sorted_modules

        all_module_map: dict[str, TypedModule] = {}
        if loaded_modules:
            for mod in loaded_modules.values():
                if isinstance(mod, TypedModule):
                    all_module_map[mod.name] = mod
        for phrase in prog.phrases:
            if isinstance(phrase, TypedModule):
                all_module_map[phrase.name] = phrase
        # 7. Function definitions for top-level functions
        if top_funs:
            lines.append("/* Function definitions */")
            for name, fun, _sym in top_funs:
                quants, params, body, ret_type = self._collect_fun_params(fun)
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                decls, _ = self._param_signatures(params, quants)
                param_sig = "void" if not decls else ", ".join(decls)
                lines.append(f"static {ret_c} {c_name}({param_sig}) {{")
                saved_descriptors = dict(self.in_scope_type_descriptors)
                for q in quants:
                    self.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                fn_lines: list[str] = []
                # Silence unused descriptor warnings
                for q in quants:
                    fn_lines.append(f"(void)descriptor_{q.name};")
                self._emit_fun_return(body, ret_type, fn_lines)
                self.in_scope_type_descriptors = saved_descriptors
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
                lines.append(f"static {ret_c} {l.c_fn_name}({sig}) {{")
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
                for q in quants:
                    self.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                    fn_lines.append(f"(void)descriptor_{q.name};")

                self._emit_fun_return(l.fun.body, ret_type, fn_lines)

                self.in_scope_type_descriptors = saved_descriptors
                self.current_env_vars = prev_env
                for f_line in fn_lines:
                    lines.append(f"    {f_line}" if f_line.strip() else f_line)
                lines.append("}")
                lines.append("")

        # 8b. Emit module functions and initializers
        if sorted_modules:
            lines.append("/* Compiled module definitions and initializers */")
            for mod in sorted_modules:
                clean_mod = mod.name.replace(".", "_")
                # Collect top-level functions and variables in this module
                mod_funs: list[tuple[str, TypedFun, Any]] = []
                mod_vars: list[tuple[str, TypedExpr, Any]] = []
                mod_imported_mods: list[str] = []
                for b in mod.bindings:
                    match b:
                        case TypedLetValue(name=b_name, value=b_val, symbol=b_sym):
                            if isinstance(b_val, TypedFun):
                                mod_funs.append((b_name, b_val, b_sym))
                            else:
                                mod_vars.append((b_name, b_val, b_sym))
                        case TypedImport(items=items):
                            for it in items:
                                for iname in it.names:
                                    if iname in all_module_map:
                                        mod_imported_mods.append(iname)
                        case TypedException(name=b_name, type_val=b_t) as exc_n:
                            if b_name:
                                mod_vars.append((b_name, exc_n, type("Symbol", (), {"type_val": b_t})()))
                        case _:
                            pass

                # Static variables for module internal let values
                for vname, vval, vsym in mod_vars:
                    if vsym.type_val != OK_TYPE:
                        m_ident = mangle_module_ident(clean_mod, vname)
                        lines.append(f"static {self.c_type(vsym.type_val)} {m_ident};")

                # Forward declarations and definitions for module functions
                for fname, ffun, fsym in mod_funs:
                    m_ident = mangle_module_ident(clean_mod, fname)
                    quants, params, _, ret_type = self._collect_fun_params(ffun)
                    ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                    quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                    param_decls = quant_decls + [
                        f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}"
                        for p in params
                    ]
                    sig = "void" if not param_decls else ", ".join(param_decls)
                    lines.append(f"static {ret_c} {m_ident}({sig});")

                # Trampolines for module functions so they can be wrapped in QClosure for exported record
                for fname, ffun, fsym in mod_funs:
                    m_ident = mangle_module_ident(clean_mod, fname)
                    tramp_name = f"{m_ident}_trampoline"
                    quants, params, _, ret_type = self._collect_fun_params(ffun)
                    ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                    quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                    param_decls = quant_decls + [
                        f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}"
                        for p in params
                    ]
                    param_sigs = ["void *env"] + param_decls
                    sig = ", ".join(param_sigs)
                    f_args = [f"descriptor_{q.name}" for q in quants] + [
                        mangle_module_ident(clean_mod, p.name) for p in params
                    ]
                    args_str = ", ".join(f_args)
                    lines.append(f"static {ret_c} {tramp_name}({sig}) {{")
                    lines.append("    (void)env;")
                    if ret_type == OK_TYPE:
                        lines.append(f"    {m_ident}({args_str});")
                        lines.append("    return;")
                    else:
                        lines.append(f"    return {m_ident}({args_str});")
                    lines.append("}")

                # Function definitions for module functions using module-scoped emitter
                mod_emitter = CEmitter(echo=False, module_prefix=clean_mod)
                mod_emitter.top_fun_names = {fname for fname, _, _ in mod_funs}
                mod_emitter.top_funs_dict = {fname: (ffun, fsym) for fname, ffun, fsym in mod_funs}
                mod_emitter.record_ctx = self.record_ctx

                for fname, ffun, fsym in mod_funs:
                    m_ident = mangle_module_ident(clean_mod, fname)
                    quants, params, body, ret_type = self._collect_fun_params(ffun)
                    ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                    quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                    param_decls = quant_decls + [
                        f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}"
                        for p in params
                    ]
                    sig = "void" if not param_decls else ", ".join(param_decls)
                    lines.append(f"static {ret_c} {m_ident}({sig}) {{")
                    fn_lines: list[str] = []
                    for q in quants:
                        mod_emitter.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                        fn_lines.append(f"(void)descriptor_{q.name};")
                    # Map param names in current_env_vars so they resolve to mangled names
                    prev_env = mod_emitter.current_env_vars
                    mod_emitter.current_env_vars = {p.name: mangle_module_ident(clean_mod, p.name) for p in params}
                    for vname, _, _ in mod_vars:
                        mod_emitter.current_env_vars[vname] = mangle_module_ident(clean_mod, vname)
                    mod_emitter._emit_fun_return(body, ret_type, fn_lines)
                    mod_emitter.current_env_vars = prev_env
                    for fl in fn_lines:
                        lines.append(f"    {fl}" if fl.strip() else fl)
                    lines.append("}")
                    lines.append("")

                # Module initializer function
                lines.append(f"static void qv_mod_{clean_mod}_init(void) {{")
                lines.append(f"    if (qv_mod_{clean_mod}_initialized) return;")
                lines.append(f"    qv_mod_{clean_mod}_initialized = true;")
                # Initialize dependencies first
                for dep in mod_imported_mods:
                    dep_clean = dep.replace(".", "_")
                    lines.append(f"    qv_mod_{dep_clean}_init();")
                # Evaluate module let values
                init_lines: list[str] = []
                mod_emitter.current_env_vars = {
                    vname: mangle_module_ident(clean_mod, vname) for vname, _, _ in mod_vars
                }
                for b in mod.bindings:
                    match b:
                        case TypedLetValue(name=vname, value=vval, symbol=vsym):
                            if not isinstance(vval, TypedFun):
                                m_ident = mangle_module_ident(clean_mod, vname)
                                if vsym.type_val == OK_TYPE:
                                    mod_emitter.emit_to(vval, None, init_lines)
                                else:
                                    mod_emitter.emit_to(vval, m_ident, init_lines)
                        case TypedException(name=ename) as exc_n:
                            if ename:
                                m_ident = mangle_module_ident(clean_mod, ename)
                                mod_emitter.emit_to(exc_n, m_ident, init_lines)
                        case _:
                            pass
                for il in init_lines:
                    lines.append(f"    {il}" if il.strip() else il)

                # Allocate and populate module record
                mod_rec_t = BuiltinModuleRegistry._build_record_type_from_scope(mod.scope)
                rec_struct = self.record_struct_name(mod_rec_t)
                payload_var = f"_{clean_mod}_payload"
                lines.append(f"    {rec_struct} *{payload_var} = ({rec_struct} *)quest_alloc(sizeof({rec_struct}));")
                lines.append(f"    {payload_var}->header.descriptor = NULL;")
                for fld in sorted(mod_rec_t.fields, key=lambda f: f.name):
                    # Check if exported field is a function
                    matching_fun = next((ff for fn, ff, _ in mod_funs if fn == fld.name), None)
                    if matching_fun is not None:
                        tramp_name = f"{mangle_module_ident(clean_mod, fld.name)}_trampoline"
                        clos_tmp = self.fresh_tmp(f"_{clean_mod}_{fld.name}_clos")
                        lines.append(f"    QClosure *{clos_tmp} = (QClosure *)quest_alloc(sizeof(QClosure));")
                        lines.append(f"    {clos_tmp}->fn = (void *){tramp_name};")
                        lines.append(f"    {clos_tmp}->env = NULL;")
                        lines.append(f"    {payload_var}->qf_{fld.name} = {clos_tmp};")
                    else:
                        m_ident = mangle_module_ident(clean_mod, fld.name)
                        lines.append(f"    {payload_var}->qf_{fld.name} = {m_ident};")
                d_name = self.record_ctx.offset_dict_instance_name(mod_rec_t, mod_rec_t)
                lines.append(
                    f"    qv_{clean_mod} = (QRecordVal){{ .val = (void *){payload_var}, "
                    f".dict = (const void *)&{d_name} }};"
                )
                lines.append("}")
                lines.append("")

        # 9. Main entrypoint
        lines.extend([
            "int main(int argc, char **argv) {",
            "    (void)argc; (void)argv;",
            "    quest_gc_init();",
            "",
        ])

        # Initialize all compiled modules topologically
        if sorted_modules:
            for mod in sorted_modules:
                clean_mod = mod.name.replace(".", "_")
                lines.append(f"    qv_mod_{clean_mod}_init();")
            lines.append("")

        total_phrases = len(prog.phrases)
        for i, phrase in enumerate(prog.phrases):
            is_last = (i == total_phrases - 1)
            self._emit_phrase(phrase, lines, is_last=is_last)

        lines.extend([
            "",
            "    return 0;",
            "}",
            "",
        ])
        return "\n".join(lines)

    def _emit_phrase(self, phrase: TypedNode, lines: list[str], is_last: bool = False) -> None:
        """Translates a top-level binding or expression phrase."""
        match phrase:
            case TypedLetValue(name=name, value=val, symbol=symbol):
                if isinstance(val, TypedFun):
                    if self.echo:
                        type_str = _c_string_literal(qtype_to_name_str(symbol.type_val))
                        lines.append(f"    quest_print_val(((QVal){{ .u = 0 }}), {type_str});")
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
                    cast_t = self.c_type(symbol.type_val)
                    phrase_lines.append(f"{c_ident} = ({cast_t}){val_c};")
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
                if name in self.top_fun_names:
                    return f"(&{mangle_ident(name)}_closure)"
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
                return self.emit_val(tgt, lines)

            case TypedVarCell(value=val):
                return self.emit_val(val, lines)

            case TypedAssign(target=tgt, value=val):
                c_tgt = self.emit_val(tgt, lines)
                target_t = tgt.type_val
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
                tag_idx = self._tag_index(tgt.type_val, tag)
                if isinstance(tgt.type_val, QVariantType):
                    return f"({c_tgt}.tag == {tag_idx}LL)"
                return f"({c_tgt}->tag == {tag_idx}LL)"

            case TypedVariantAssert(target=tgt, tag=tag):
                c_tgt = self.emit_val(tgt, lines)
                tag_idx = self._tag_index(tgt.type_val, tag)
                if isinstance(tgt.type_val, QOptionType):
                    opt_field = tgt.type_val.get_option(tag) if tag is not None else None
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
                elif isinstance(tgt.type_val, QVariantType):
                    if not c_tgt.isidentifier():
                        tmp_v = self.fresh_tmp("_vtgt")
                        lines.append(f"QVariantVal {tmp_v} = {c_tgt};")
                        c_tgt = tmp_v
                    lines.append(f"if ({c_tgt}.tag != {tag_idx}LL) quest_raise_variant_error();")
                    return self._emit_qval_extract(f"{c_tgt}.payload", expr.type_val)
                else:
                    lines.append("quest_raise_variant_error();")
                    return "((void)0)"

            case TypedCase():
                if expr.type_val == OK_TYPE:
                    self.emit_to(expr, None, lines)
                    return "((void)0)"
                tmp = self.fresh_tmp("_case_res")
                c_type = self.c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedSelect(target=tgt, field=fld):
                if isinstance(tgt, TypedVar) and tgt.name == "arrayOp" and fld == "error":
                    return "(&quest_exc_arrayOp_error)"
                if isinstance(tgt, TypedVar) and tgt.name == "string" and fld == "error":
                    return "(&quest_exc_string_error)"
                if isinstance(tgt, TypedVar) and tgt.name == "dynamic" and fld == "error":
                    return "(&quest_exc_dynamic_error)"
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QTupleType):
                    val_idx = self._tuple_field_index(tgt.type_val, fld)
                    return f"{c_tgt}->_{val_idx}"
                elif isinstance(tgt.type_val, QRecordType):
                    return self._emit_record_field_access(
                        c_tgt, tgt.type_val, fld, expr.type_val, lines, as_ref=False
                    )
                else:
                    return f"{c_tgt}->qf_{fld}"

            case TypedSelectRef(target=tgt, field=fld):
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QTupleType):
                    val_idx = self._tuple_field_index(tgt.type_val, fld)
                    return f"(&({c_tgt}->_{val_idx}))"
                elif isinstance(tgt.type_val, QRecordType):
                    return self._emit_record_field_access(
                        c_tgt, tgt.type_val, fld, expr.type_val, lines, as_ref=True
                    )
                else:
                    return f"(&({c_tgt}->qf_{fld}))"

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
                            if isinstance(target_elem_t, QRecordType):
                                c_init = self._coerce_record_val(c_init, args[1], target_elem_t)
                            elif (
                                isinstance(target_elem_t, QVariantType)
                                and isinstance(args[1].type_val, QVariantType)
                                and args[1].type_val != target_elem_t
                            ):
                                c_init = self._emit_variant_upcast(
                                    c_init, args[1].type_val, target_elem_t, lines
                                )
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
                            if isinstance(target_elem_t, QRecordType):
                                c_item = self._coerce_record_val(c_item, args[2], target_elem_t)
                            elif (
                                isinstance(target_elem_t, QVariantType)
                                and isinstance(args[2].type_val, QVariantType)
                                and args[2].type_val != target_elem_t
                            ):
                                c_item = self._emit_variant_upcast(
                                    c_item, args[2].type_val, target_elem_t, lines
                                )
                            wrap = _qval_wrap(c_item, target_elem_t)
                            lines.append(f"{c_arr}->data[{c_idx}] = {wrap};")
                            return "((void)0)"
                    elif mod_name == "dynamic":
                        if fld == "new" and len(args) == 1 and len(type_args) == 1:
                            desc = self.c_type_descriptor(type_args[0])
                            c_val = self.emit_val(args[0], lines)
                            wrap = _qval_wrap(c_val, args[0].type_val)
                            return f"quest_dynamic_new({desc}, {wrap})"
                        elif fld == "be" and len(args) == 1 and len(type_args) == 1:
                            desc = self.c_type_descriptor(type_args[0])
                            c_dyn = self.emit_val(args[0], lines)
                            call_str = f"quest_dynamic_be({desc}, {c_dyn})"
                            return _qval_unwrap(call_str, type_args[0], self)
                        elif fld == "copy" and len(args) == 1:
                            c_dyn = self.emit_val(args[0], lines)
                            return f"quest_dynamic_new({c_dyn}->type_desc, {c_dyn}->payload)"

                # Preceding descriptor arguments from type_args
                descriptor_args = [self.c_type_descriptor(targ) for targ in type_args]

                if isinstance(effective_func, TypedVar) and effective_func.name in self.top_fun_names:
                    c_func = mangle_ident(effective_func.name)
                    c_args = list(descriptor_args)
                    fun, _ = self.top_funs_dict[effective_func.name]
                    _, formal_params, _, ret_type = self._collect_fun_params(fun)
                    for formal_p, actual_a in zip(formal_params, args):
                        c_args.append(self._emit_call_arg(formal_p.type_val, actual_a, lines))
                    args_str = ", ".join(c_args)
                    call_str = f"{c_func}({args_str})"
                    if isinstance(ret_type, QTypeVar) and expr.type_val != ret_type:
                        call_str = _qval_unwrap(call_str, expr.type_val, self)
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    return call_str
                else:
                    fn_ptr_t = _closure_fn_ptr_type(effective_func.type_val, self.record_ctx)
                    clos_val = self.emit_val(effective_func, lines)
                    _, inner_formal = self._collect_fun_quantifiers(effective_func.type_val)
                    if isinstance(inner_formal, QFunType):
                        formal_types = [p.type_val for p in inner_formal.params]
                    else:
                        formal_types = [a.type_val for a in args]
                    c_args = list(descriptor_args)
                    for pt, actual_a in zip(formal_types, args):
                        c_args.append(self._emit_call_arg(pt, actual_a, lines))
                    all_c_args = [f"{clos_val}->env"] + c_args
                    args_str = ", ".join(all_c_args)
                    call_str = f"(({fn_ptr_t})({clos_val}->fn))({args_str})"
                    formal_ret = inner_formal.result_type if isinstance(inner_formal, QFunType) else None
                    if isinstance(formal_ret, QTypeVar) and expr.type_val != formal_ret:
                        call_str = _qval_unwrap(call_str, expr.type_val, self)
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
                if isinstance(target_elem_t, QRecordType):
                    c_val = self._coerce_record_val(c_val, val, target_elem_t)
                elif (
                    isinstance(target_elem_t, QVariantType)
                    and isinstance(val.type_val, QVariantType)
                    and val.type_val != target_elem_t
                ):
                    c_val = self._emit_variant_upcast(
                        c_val, val.type_val, target_elem_t, lines
                    )
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

            case TypedTypeApp(func=func):
                return self.emit_val(func, lines)

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
                                block_lines.append(f"{c_ident} = ({c_type}){val_c};")
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
                    if isinstance(expected_fld_t, QRecordType):
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
                    lines.append(f"QArray *{target_dest};")
                n = len(elems)
                lines.append(
                    f"{target_dest} = (QArray *)quest_alloc(sizeof(QArray) + (size_t)({n}LL) * sizeof(QVal));"
                )
                lines.append(f"{target_dest}->length = {n}LL;")
                for i, elem in enumerate(elems):
                    c_elem = self.emit_val(elem, lines)
                    if isinstance(t.element_type, QRecordType):
                        c_elem = self._coerce_record_val(c_elem, elem, t.element_type)
                    elif (
                        isinstance(t.element_type, QVariantType)
                        and isinstance(elem.type_val, QVariantType)
                        and elem.type_val != t.element_type
                    ):
                        c_elem = self._emit_variant_upcast(
                            c_elem, elem.type_val, t.element_type, lines
                        )
                    wrap = _qval_wrap(c_elem, t.element_type)
                    lines.append(f"{target_dest}->data[{i}LL] = {wrap};")

            case TypedArrayRep(count=cnt, init_val=init_v, type_val=t):
                c_cnt = self.emit_val(cnt, lines)
                c_init = self.emit_val(init_v, lines)
                if isinstance(t.element_type, QRecordType):
                    c_init = self._coerce_record_val(c_init, init_v, t.element_type)
                elif (
                    isinstance(t.element_type, QVariantType)
                    and isinstance(init_v.type_val, QVariantType)
                    and init_v.type_val != t.element_type
                ):
                    c_init = self._emit_variant_upcast(
                        c_init, init_v.type_val, t.element_type, lines
                    )
                wrap = _qval_wrap(c_init, t.element_type)
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_arr")
                    lines.append(f"QArray *{target_dest};")
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
                s_name = option_struct_name(t)
                if target_dest is None:
                    target_dest = self.fresh_tmp("_opt")
                    lines.append(f"{s_name} *{target_dest};")
                lines.append(f"{target_dest} = ({s_name} *)quest_alloc(sizeof({s_name}));")
                if ordinal_expr is not None:
                    c_ord = self.emit_val(ordinal_expr, lines)
                    lines.append(f"{target_dest}->tag = {c_ord};")
                else:
                    tag_idx = self._tag_index(t, tag) if tag is not None else ordinal
                    lines.append(f"{target_dest}->tag = {tag_idx}LL;")

                if payload is not None and tag is not None:
                    opt_field = t.get_option(tag)
                    if opt_field and opt_field.payload_type:
                        pt = opt_field.payload_type
                        if isinstance(pt, QTupleType) and isinstance(payload, TypedTuple):
                            for i, elem in enumerate(payload.elements):
                                c_elem = self.emit_val(elem, lines)
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
                                for i, f in enumerate(b_type.value_fields):
                                    branch_lines.append(f"{b_name}->_{i} = {c_tgt}->u.{branch.tags[0]}._{i};")
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
