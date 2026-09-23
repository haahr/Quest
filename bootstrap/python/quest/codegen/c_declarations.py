"""Declaration and header generation for Quest C Transpiler."""

from __future__ import annotations

from typing import Any, Callable, Optional

from quest.typed_ast import TypedExpr, TypedFun, TypedRecord
from quest.codegen.c_analysis import CLambdaInfo, CProgramAnalysis
from quest.codegen.c_types import (
    RecordNamingContext,
    mangle_ident,
    normalize_type,
    option_struct_name,
    record_struct_name,
    tuple_struct_name,
    type_to_c_tag,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    INT_TYPE,
    OK_TYPE,
    QAbstractType,
    QAllType,
    QArrayType,
    QExternalType,
    QFunType,
    QOptionType,
    QQuantifier,
    QRecordType,
    QTupleType,
    QType,
    QTypeVar,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    resolve_option_bound,
    resolve_record_bound,
    resolve_variant_bound,
)


class CDeclarationEmitter:
    """Emits forward declarations, structs, typedefs, evidence dictionaries, and trampolines."""

    def __init__(
        self,
        record_ctx: RecordNamingContext,
        c_type_fn: Callable[[QType], str],
        param_sigs_fn: Callable[[list[Any], tuple[QQuantifier, ...]], tuple[list[str], list[str]]],
        collect_quants_fn: Callable[[QType], tuple[tuple[QQuantifier, ...], QType]],
        is_exact_record_literal_fn: Callable[[QType, TypedExpr], bool],
    ):
        self.record_ctx = record_ctx
        self.c_type = c_type_fn
        self.param_signatures = param_sigs_fn
        self.collect_fun_quantifiers = collect_quants_fn
        self.is_exact_record_literal = is_exact_record_literal_fn
        self.emitted_descriptor_tags: list[str] = []

    def emit_forward_typedefs(self, agg_types: list[tuple[str, QType]]) -> list[str]:
        lines: list[str] = []
        if agg_types:
            lines.append("/* Forward declarations for aggregate types */")
            seen: set[str] = set()
            for tag_name, _ in agg_types:
                if tag_name not in seen:
                    seen.add(tag_name)
                    lines.append(f"typedef struct {tag_name} {tag_name};")
            lines.append("")
        return lines

    def emit_module_declarations(self, analysis: CProgramAnalysis) -> list[str]:
        lines: list[str] = []
        if analysis.sorted_modules:
            lines.append("/* Forward declarations and state for compiled modules */")
            for mod in analysis.sorted_modules:
                clean_mod = mod.name.replace(".", "_")
                lines.append(f"static QRecordVal qv_{clean_mod};")
                lines.append(f"static bool qv_mod_{clean_mod}_initialized = false;")
                lines.append(f"static void qv_mod_{clean_mod}_init(void);")
            lines.append("")
        return lines

    def emit_aggregate_structs(self, agg_types: list[tuple[str, QType]]) -> list[str]:
        lines: list[str] = []
        if not agg_types:
            return lines

        lines.append("/* Aggregate struct definitions */")
        seen: set[str] = set()
        for tag_name, t in agg_types:
            if tag_name in seen:
                continue
            seen.add(tag_name)
            lines.append(f"struct {tag_name} {{")
            if isinstance(t, QTupleType):
                if not t.value_fields:
                    lines.append("    char _unused;")
                else:
                    for i, f in enumerate(t.value_fields):
                        c_type = self.c_type(f.type_val)
                        lines.append(f"    {c_type} _{i};")
            elif isinstance(t, QRecordType):
                lines.append("    QRecordHeader header;")
                if not t.fields:
                    lines.append("    char _unused;")
                else:
                    for f in sorted(t.fields, key=lambda fld: fld.name):
                        c_type = self.c_type(f.type_val)
                        lines.append(f"    {c_type} qf_{f.name};")
            elif isinstance(t, QOptionType):
                lines.append("    int64_t tag;")
                payload_branches = [o for o in t.options if o.payload_type is not None]
                if payload_branches:
                    lines.append("    union {")
                    for o in payload_branches:
                        pt = o.payload_type
                        if isinstance(pt, QTupleType):
                            lines.append(f"        struct {tag_name}_{o.name}_payload {{")
                            for i, f in enumerate(pt.value_fields):
                                c_f_type = self.c_type(f.type_val)
                                f_ident = f"_{i}" if not f.name else f"_{i}"
                                lines.append(f"            {c_f_type} {f_ident};")
                            lines.append(f"        }} {o.name};")
                        elif isinstance(pt, QRecordType):
                            lines.append(f"        struct {tag_name}_{o.name}_payload {{")
                            for f in sorted(pt.fields, key=lambda fld: fld.name):
                                c_f_type = self.c_type(f.type_val)
                                lines.append(f"            {c_f_type} qf_{f.name};")
                            lines.append(f"        }} {o.name};")
                        else:
                            c_pt = self.c_type(pt)
                            lines.append(f"        struct {{ {c_pt} val; }} {o.name};")
                    lines.append("    } u;")
            lines.append("};")
            lines.append("")
        return lines

    def emit_evidence_dictionaries(
        self,
        agg_types: list[tuple[str, QType]],
        needed_dicts: set[tuple[QRecordType, QRecordType]],
    ) -> list[str]:
        lines: list[str] = []
        all_records = [t for _, t in agg_types if isinstance(t, QRecordType)]
        if all_records:
            lines.append("/* Evidence dictionary struct definitions */")
            for t in all_records:
                dict_t = self.record_ctx.offset_dict_struct_name(t)
                rec_name = self.record_ctx.get_or_create_name(t)
                lines.append(f"typedef struct {dict_t} {dict_t};")
                lines.append(f"struct {dict_t} {{")
                if not t.fields:
                    lines.append("    size_t _unused;")
                else:
                    for f in sorted(t.fields, key=lambda fld: fld.name):
                        lines.append(f"    size_t offset_{f.name};")
                lines.append("};")

            lines.append("")

        if needed_dicts:
            lines.append("/* Static evidence dictionaries for record subtyping */")
            for tgt, src in sorted(
                needed_dicts,
                key=lambda p: (
                    self.record_ctx.get_or_create_name(p[0]),
                    self.record_ctx.get_or_create_name(p[1]),
                ),
            ):
                inst_name = self.record_ctx.offset_dict_instance_name(tgt, src)
                dict_t = self.record_ctx.offset_dict_struct_name(tgt)
                src_sname = record_struct_name(src, self.record_ctx)
                if not tgt.fields:
                    lines.append(f"static const {dict_t} {inst_name} = {{ 0 }};")
                else:
                    entries = [
                        f"offsetof({src_sname}, qf_{f.name})"
                        for f in sorted(tgt.fields, key=lambda fld: fld.name)
                    ]
                    lines.append(f"static const {dict_t} {inst_name} = {{ {', '.join(entries)} }};")
            lines.append("")
        return lines

    def emit_coercion_tables(
        self,
        tuple_coercions: set[tuple[QTupleType, QTupleType]],
        variant_coercions: set[tuple[QVariantType, QVariantType]],
    ) -> list[str]:
        lines: list[str] = []
        if tuple_coercions:
            lines.append("/* Compile-time static assertions for tuple subtyping */")
            for tgt, src in sorted(
                tuple_coercions,
                key=lambda p: (tuple_struct_name(p[0]), tuple_struct_name(p[1])),
            ):
                tgt_name = tuple_struct_name(tgt)
                src_name = tuple_struct_name(src)
                for i in range(len(tgt.value_fields)):
                    lines.append(
                        f"static_assert(offsetof({src_name}, _{i}) == offsetof({tgt_name}, _{i}), "
                        f"tuple_coercion_{tgt_name}_{src_name}_{i});"
                    )
            lines.append("")

        if variant_coercions:
            lines.append("/* Static tag remapping tables for variant subtyping */")
            for tgt, src in sorted(
                variant_coercions,
                key=lambda p: (type_to_c_tag(p[0]), type_to_c_tag(p[1])),
            ):
                tgt_tag = type_to_c_tag(tgt)
                src_tag = type_to_c_tag(src)
                entries = [
                    str(next(j for j, tv in enumerate(tgt.variants) if tv.name == sv.name))
                    for sv in src.variants
                ]
                lines.append(
                    f"static const int64_t tagmap_{tgt_tag}_{src_tag}[{len(src.variants)}] = "
                    f"{{ {', '.join(entries)} }};"
                )
            lines.append("")
        return lines

    def emit_type_descriptors(
        self,
        agg_types: list[tuple[str, QType]],
        variant_types: list[QVariantType],
        desc_fn: Callable[[QType], str],
        all_program_types: Optional[list[QType]] = None,
    ) -> list[str]:
        lines: list[str] = []
        records: list[tuple[str, QRecordType]] = []
        tuples: list[tuple[str, QTupleType]] = []
        variants_and_options: list[tuple[str, Any]] = []
        arrays: list[tuple[str, QArrayType]] = []
        opaques: list[tuple[str, str]] = []
        seen_tags: set[str] = set()

        def visit(t: Optional[QType]) -> None:
            if t is None:
                return
            t = t.prune() if hasattr(t, "prune") else t
            t = normalize_type(t)
            if t in (INT_TYPE, REAL_TYPE, BOOL_TYPE, CHAR_TYPE, STRING_TYPE, OK_TYPE, DYNAMIC_TYPE):
                return
            if isinstance(t, QTypeVar) and t.name == "Dynamic.T":
                return
            if isinstance(t, QTupleType) and not t.fields:
                return
            if isinstance(t, QRecordType) or (rec_b := resolve_record_bound(t)) is not None:
                rec_t = t if isinstance(t, QRecordType) else rec_b
                tag = record_struct_name(rec_t, self.record_ctx)
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    records.append((tag, rec_t))
                    for f in rec_t.fields:
                        visit(f.type_val)
                return
            if isinstance(t, QTupleType):
                tag = tuple_struct_name(t)
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    tuples.append((tag, t))
                    for f in t.value_fields:
                        visit(f.type_val)
                return
            if isinstance(t, QVariantType) or (var_b := resolve_variant_bound(t)) is not None:
                var_t = t if isinstance(t, QVariantType) else var_b
                tag = type_to_c_tag(var_t)
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    variants_and_options.append((tag, var_t))
                    for v in var_t.variants:
                        if getattr(v, "type_val", None):
                            visit(v.type_val)
                return
            if isinstance(t, QOptionType) or (opt_b := resolve_option_bound(t)) is not None:
                opt_t = t if isinstance(t, QOptionType) else opt_b
                tag = option_struct_name(opt_t)
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    variants_and_options.append((tag, opt_t))
                    for o in opt_t.options:
                        if o.payload_type:
                            visit(o.payload_type)
                return
            if isinstance(t, QArrayType):
                elem_tag = type_to_c_tag(t.element_type)
                tag = f"array_{elem_tag}"
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    arrays.append((tag, t))
                    visit(t.element_type)
                return
            if isinstance(t, QExternalType):
                name = t.name or t.c_type
                tag = f"opaque_{mangle_ident(name)}"
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    opaques.append((tag, name))
                return
            if isinstance(t, (QTypeVar, QAbstractType)):
                name = t.name
                tag = f"opaque_{mangle_ident(name)}"
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    opaques.append((tag, name))
                return
            if isinstance(t, (QFunType, QAllType)):
                tag = f"fun_{type_to_c_tag(t)}"
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    opaques.append((tag, str(t)))
                return

        for _, t in agg_types:
            visit(t)
        for v in variant_types:
            visit(v)
        if all_program_types:
            for t in all_program_types:
                visit(t)

        if not seen_tags:
            return lines

        self.emitted_descriptor_tags = sorted(seen_tags)
        lines.append("/* Forward declarations for static type descriptors */")
        for tag in self.emitted_descriptor_tags:
            lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED;")
        lines.append("")

        lines.append("/* Static runtime type descriptors for compound and opaque types */")
        for tag, name in opaques:
            c_name = name.replace('"', '\\"')
            lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
            lines.append(f"    .kind = QTYPE_KIND_OPAQUE,")
            lines.append(f"    .name = \"{c_name}\",")
            lines.append(f"    .size = sizeof(QVal),")
            lines.append(f"    .alignment = sizeof(void *),")
            lines.append(f"    .is_subtype = quest_is_subtype,")
            lines.append(f"    .extra = NULL,")
            lines.append(f"}};")
            lines.append("")

        for tag, arr_t in arrays:
            elem_desc = desc_fn(arr_t.element_type)
            elem_name = str(arr_t.element_type).replace('"', '\\"')
            lines.append(f"static const QArrayTypeDescriptor qarr_desc_{tag} Q_UNUSED = {{")
            lines.append(f"    .element_type = {elem_desc},")
            lines.append(f"}};")
            lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
            lines.append(f"    .kind = QTYPE_KIND_ARRAY,")
            lines.append(f"    .name = \"Array({elem_name})\",")
            lines.append(f"    .size = sizeof(void *),")
            lines.append(f"    .alignment = sizeof(void *),")
            lines.append(f"    .is_subtype = quest_is_subtype,")
            lines.append(f"    .extra = &qarr_desc_{tag},")
            lines.append(f"}};")
            lines.append("")

        for tag, qtype in records:
            c_name = str(qtype).replace('"', '\\"')
            sorted_fields = sorted(qtype.fields, key=lambda f: f.name)
            n = len(sorted_fields)
            if n > 0:
                lines.append(f"static const struct {{")
                lines.append(f"    size_t field_count;")
                lines.append(f"    const QRecordFieldDescriptor fields[{n}];")
                lines.append(f"}} qrec_desc_{tag} Q_UNUSED = {{")
                lines.append(f"    .field_count = {n},")
                lines.append(f"    .fields = {{")
                for f in sorted_fields:
                    f_desc = desc_fn(f.type_val)
                    is_var_str = "true" if f.is_var else "false"
                    lines.append(
                        f"        {{ .name = \"{f.name}\", .type = {f_desc}, "
                        f".offset = offsetof(struct {tag}, qf_{f.name}), .is_var = {is_var_str} }},"
                    )
                lines.append(f"    }}")
                lines.append(f"}};")
                lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
                lines.append(f"    .kind = QTYPE_KIND_RECORD,")
                lines.append(f"    .name = \"{c_name}\",")
                lines.append(f"    .size = sizeof(struct {tag}),")
                lines.append(f"    .alignment = sizeof(void *),")
                lines.append(f"    .is_subtype = quest_is_subtype,")
                lines.append(f"    .extra = &qrec_desc_{tag},")
                lines.append(f"}};")
            else:
                lines.append(f"static const QRecordTypeDescriptor qrec_desc_{tag} Q_UNUSED = {{ .field_count = 0 }};")
                lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
                lines.append(f"    .kind = QTYPE_KIND_RECORD,")
                lines.append(f"    .name = \"Record end\",")
                lines.append(f"    .size = sizeof(void *),")
                lines.append(f"    .alignment = sizeof(void *),")
                lines.append(f"    .is_subtype = quest_is_subtype,")
                lines.append(f"    .extra = &qrec_desc_{tag},")
                lines.append(f"}};")
            lines.append("")

        for tag, qtype in tuples:
            c_name = str(qtype).replace('"', '\\"')
            val_fields = qtype.value_fields
            n = len(val_fields)
            if n > 0:
                lines.append(f"static const struct {{")
                lines.append(f"    size_t element_count;")
                lines.append(f"    const QTupleElementDescriptor elements[{n}];")
                lines.append(f"}} qtup_desc_{tag} Q_UNUSED = {{")
                lines.append(f"    .element_count = {n},")
                lines.append(f"    .elements = {{")
                for i, f in enumerate(val_fields):
                    f_desc = desc_fn(f.type_val)
                    name_str = f'"{f.name}"' if getattr(f, "name", None) is not None else "NULL"
                    lines.append(
                        f"        {{ .name = {name_str}, .type = {f_desc}, "
                        f".offset = offsetof(struct {tag}, _{i}) }},"
                    )
                lines.append(f"    }}")
                lines.append(f"}};")
                lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
                lines.append(f"    .kind = QTYPE_KIND_TUPLE,")
                lines.append(f"    .name = \"{c_name}\",")
                lines.append(f"    .size = sizeof(struct {tag}),")
                lines.append(f"    .alignment = sizeof(void *),")
                lines.append(f"    .is_subtype = quest_is_subtype,")
                lines.append(f"    .extra = &qtup_desc_{tag},")
                lines.append(f"}};")
            lines.append("")

        for tag, qtype in variants_and_options:
            c_name = str(qtype).replace('"', '\\"')
            cases = (
                [(v.name, getattr(v, "type_val", None), getattr(v, "is_var", False)) for v in qtype.variants]
                if isinstance(qtype, QVariantType)
                else [(o.name, o.payload_type, False) for o in qtype.options]
            )
            n = len(cases)
            if n > 0:
                lines.append(f"static const struct {{")
                lines.append(f"    size_t case_count;")
                lines.append(f"    const QVariantCaseDescriptor cases[{n}];")
                lines.append(f"}} qvar_desc_{tag} Q_UNUSED = {{")
                lines.append(f"    .case_count = {n},")
                lines.append(f"    .cases = {{")
                for i, (c_tag_name, p_type, is_var) in enumerate(cases):
                    p_desc = desc_fn(p_type) if p_type is not None else "NULL"
                    is_var_str = "true" if is_var else "false"
                    lines.append(
                        f"        {{ .name = \"{c_tag_name}\", .payload_type = {p_desc}, "
                        f".tag_index = {i}LL, .is_var = {is_var_str} }},"
                    )
                lines.append(f"    }}")
                lines.append(f"}};")
                kind_str = "QTYPE_KIND_VARIANT" if isinstance(qtype, QVariantType) else "QTYPE_KIND_OPTION"
                size_str = f"sizeof(struct {tag})" if isinstance(qtype, QOptionType) else "sizeof(QVariantVal)"
                lines.append(f"static const QTypeDescriptor quest_type_{tag} Q_UNUSED = {{")
                lines.append(f"    .kind = {kind_str},")
                lines.append(f"    .name = \"{c_name}\",")
                lines.append(f"    .size = {size_str},")
                lines.append(f"    .alignment = sizeof(void *),")
                lines.append(f"    .is_subtype = quest_is_subtype,")
                lines.append(f"    .extra = &qvar_desc_{tag},")
                lines.append(f"}};")
            lines.append("")
        return lines

    def emit_environment_structs(self, lifted_lambdas: list[CLambdaInfo]) -> list[str]:
        lines: list[str] = []
        capturing_lambdas = [l for l in lifted_lambdas if l.free_vars]
        if capturing_lambdas:
            lines.append("/* Environment structs for capturing closures */")
            for l in capturing_lambdas:
                lines.append(f"{l.env_struct_name} {{")
                for vname, vtype in l.free_vars:
                    c_type = self.c_type(vtype)
                    lines.append(f"    {c_type} {mangle_ident(vname)};")
                lines.append("};")
                lines.append("")
        return lines

    def emit_top_vars_declarations(
        self,
        top_vars: list[tuple[str, TypedExpr, Any]],
        var_dict_names: Optional[dict[str, str]] = None,
    ) -> list[str]:
        lines: list[str] = []
        if top_vars:
            for name, val, symbol in top_vars:
                if symbol.type_val != OK_TYPE:
                    c_ident = mangle_ident(name)
                    if isinstance(symbol.type_val, QRecordType):
                        lines.append(f"static QRecordVal {c_ident};")
                    else:
                        c_type = self.c_type(symbol.type_val)
                        lines.append(f"static {c_type} {c_ident};")
            lines.append("")
        return lines

    def emit_forward_declarations_and_trampolines(
        self,
        top_funs: list[tuple[str, TypedFun, Any]],
        lifted_lambdas: list[CLambdaInfo],
        val_referenced_top_funs: set[str],
        top_funs_dict: dict[str, tuple[TypedFun, Any]],
    ) -> list[str]:
        lines: list[str] = []

        if top_funs:
            lines.append("/* Forward declarations for top-level functions */")
            for name, fun, _sym in top_funs:
                quants, inner = self.collect_fun_quantifiers(fun.type_val)
                ret_type = inner.result_type if isinstance(inner, QFunType) else inner
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else (
                    "QRecordVal"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, _ = self.param_signatures(fun.params, quants)
                param_sig = "void" if not decls else ", ".join(decls)
                lines.append(f"static Q_UNUSED {ret_c} {c_name}({param_sig});")
            lines.append("")

        if lifted_lambdas:
            lines.append("/* Forward declarations for lifted lambdas */")
            for l in lifted_lambdas:
                quants, _ = self.collect_fun_quantifiers(l.fun.type_val)
                ret_type = l.fun.type_val.result_type if isinstance(l.fun.type_val, QFunType) else l.fun.type_val
                if isinstance(ret_type, QAllType):
                    _, inner = self.collect_fun_quantifiers(ret_type)
                    ret_type = inner.result_type if isinstance(inner, QFunType) else inner
                ret_c = "void" if ret_type == OK_TYPE else (
                    "QRecordVal"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, _ = self.param_signatures(l.fun.params, quants)
                param_sigs = ["void *_raw_env"] + decls
                sig = ", ".join(param_sigs)
                lines.append(f"static Q_UNUSED {ret_c} {l.c_fn_name}({sig});")
            lines.append("")

        non_capturing = [l for l in lifted_lambdas if not l.free_vars]
        if non_capturing:
            lines.append("/* Static closures for non-capturing lambdas */")
            for l in non_capturing:
                lines.append(f"static Q_UNUSED QClosure {l.closure_var_name} = {{ (void *){l.c_fn_name}, NULL }};")
            lines.append("")

        if val_referenced_top_funs:
            lines.append("/* Trampoline functions and static closures for first-class top-level functions */")
            for name in sorted(val_referenced_top_funs):
                fun, _ = top_funs_dict[name]
                c_name = mangle_ident(name)
                tramp_name = f"{c_name}_trampoline"
                quants, inner = self.collect_fun_quantifiers(fun.type_val)
                ret_type = inner.result_type if isinstance(inner, QFunType) else inner
                ret_c = "void" if ret_type == OK_TYPE else (
                    "QRecordVal"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, forward_args = self.param_signatures(fun.params, quants)
                param_sigs = ["void *env"] + decls
                sig = ", ".join(param_sigs)
                args_str = ", ".join(forward_args)
                lines.append(f"static Q_UNUSED {ret_c} {tramp_name}({sig}) {{")
                lines.append("    (void)env;")
                if ret_type == OK_TYPE:
                    lines.append(f"    {c_name}({args_str});")
                    lines.append("    return;")
                else:
                    lines.append(f"    return {c_name}({args_str});")
                lines.append("}")
                lines.append(f"static Q_UNUSED QClosure {c_name}_closure = {{ (void *){tramp_name}, NULL }};")
                lines.append("")
        return lines
