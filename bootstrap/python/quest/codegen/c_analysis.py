"""C-specific AST and Program Analysis for Quest C Transpiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quest.analysis.closure import LambdaAnalysis, analyze_closures
from quest.env import ValueSymbol
from quest.typed_ast import (
    TypedApp,
    TypedException,
    TypedExpr,
    TypedExprStmt,
    TypedFun,
    TypedImport,
    TypedLetType,
    TypedLetValue,
    TypedModule,
    TypedNode,
    TypedParam,
    TypedProgram,
    TypedRecord,
    TypedSelect,
    TypedTypeApp,
    TypedVar,
)
from quest.codegen.c_types import (
    RecordNamingContext,
    is_record_subtype,
    is_tuple_subtype,
    is_variant_subtype,
    option_struct_name,
    record_struct_name,
    tuple_struct_name,
    type_to_c_tag,
)
from quest.types import (
    QAllType,
    QArrayType,
    QFunType,
    QOptionType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTupleType,
    QType,
    QTypeVar,
    QVariantType,
    resolve_record_bound,
    resolve_variant_bound,
)


@dataclass
class CLambdaInfo:
    """C-specific decoration of a lifted lambda closure."""
    id: str
    fun: TypedFun
    free_vars: list[tuple[str, QType]]
    env_struct_name: Optional[str]
    c_fn_name: str
    closure_var_name: Optional[str] = None


@dataclass
class CProgramAnalysis:
    """Pre-emission analysis results for a TypedProgram."""
    sorted_modules: list[TypedModule]
    agg_types: list[tuple[str, QType]]
    variant_types: list[QVariantType]
    needed_dicts: set[tuple[QRecordType, QRecordType]]
    tuple_coercions: set[tuple[QTupleType, QTupleType]]
    variant_coercions: set[tuple[QVariantType, QVariantType]]
    top_funs: list[tuple[str, TypedFun, Any]]
    top_vars: list[tuple[str, TypedExpr, Any]]
    top_fun_names: set[str]
    top_var_names: set[str]
    val_referenced_top_funs: set[str]
    lifted_lambdas: list[CLambdaInfo]
    lambda_info_by_id: dict[int, CLambdaInfo]
    top_funs_dict: dict[str, tuple[TypedFun, Any]]
    specializations: dict[tuple[str, tuple[QType, ...]], tuple[str, TypedFun]]


def topological_sort_modules(modules: list[TypedModule]) -> list[TypedModule]:
    """Sorts modules in dependency order (callees before callers)."""
    by_name = {m.name: m for m in modules}
    visited: set[str] = set()
    order: list[TypedModule] = []

    def visit(m: TypedModule):
        if m.name in visited:
            return
        visited.add(m.name)
        for b in m.bindings:
            if isinstance(b, TypedImport):
                for item in b.items:
                    for name in item.names:
                        if name in by_name:
                            visit(by_name[name])
        order.append(m)

    for m in modules:
        visit(m)
    return order


def find_val_referenced_top_funs(prog: TypedProgram, top_fun_names: set[str]) -> set[str]:
    """Finds all top-level functions that are referenced in value positions."""
    referenced: set[str] = set()

    def scan(node: Any) -> None:
        if node is None:
            return
        match node:
            case TypedApp(func=f, args=args):
                effective_f = f
                while isinstance(effective_f, TypedTypeApp):
                    effective_f = effective_f.func
                if isinstance(effective_f, TypedVar) and effective_f.name in top_fun_names:
                    for a in args:
                        scan(a)
                    return
                scan(f)
                for a in args:
                    scan(a)
            case TypedVar(name=name):
                if name in top_fun_names:
                    referenced.add(name)
            case _:
                if isinstance(node, (list, tuple)):
                    for item in node:
                        scan(item)
                elif hasattr(node, "__dataclass_fields__"):
                    for field_name in node.__dataclass_fields__:
                        scan(getattr(node, field_name))

    scan(prog)
    return referenced


def collect_fun_quantifiers(fun_type: QType) -> tuple[tuple[QQuantifier, ...], QType]:
    """Extracts any universal quantifiers wrapping a function type."""
    quants: tuple[QQuantifier, ...] = ()
    curr = fun_type
    while isinstance(curr, QAllType):
        quants = quants + curr.quantifiers
        curr = curr.body
    return quants, curr


def is_specialization_needed(t: QType) -> bool:
    """Returns True if type t contains records or variants requiring call-site specialization."""
    if isinstance(t, (QRecordType, QVariantType)):
        return True
    if resolve_record_bound(t) is not None or resolve_variant_bound(t) is not None:
        return True
    if isinstance(t, QTupleType):
        return any(is_specialization_needed(f.type_val) for f in t.value_fields)
    if isinstance(t, QArrayType):
        return is_specialization_needed(t.element_type)
    if isinstance(t, QOptionType):
        return any(
            is_specialization_needed(o.payload_type)
            for o in t.options
            if o.payload_type is not None
        )
    return False


def substitute_typed_node(node: Any, subst: dict[int, QType]) -> Any:
    """Clones a TypedNode AST replacing any QType references with subst."""
    if node is None or isinstance(node, (int, float, str, bool)):
        return node
    if isinstance(node, QType):
        return node.substitute(subst)
    if isinstance(node, ValueSymbol):
        return ValueSymbol(
            name=node.name,
            type_val=node.type_val.substitute(subst),
            is_var=node.is_var,
            is_out=node.is_out,
            symbol_id=node.symbol_id,
        )
    if isinstance(node, (list, tuple)):
        return type(node)(substitute_typed_node(x, subst) for x in node)
    if isinstance(node, TypedNode):
        kwargs = {}
        for f_name in node.__dataclass_fields__:
            val = getattr(node, f_name)
            kwargs[f_name] = substitute_typed_node(val, subst)
        return type(node)(**kwargs)
    return node


def specialize_typed_fun(
    name: str,
    fun: TypedFun,
    type_args: tuple[QType, ...],
) -> tuple[str, TypedFun]:
    """Clones a TypedFun substituting type parameters for call-site specialization."""
    quants, inner_t = collect_fun_quantifiers(fun.type_val)
    subst: dict[int, QType] = {}
    instantiated_ids: set[int] = set()
    quant_names: dict[str, QType] = {}
    for q, targ in zip(quants, type_args):
        subst[q.symbol_id] = targ
        instantiated_ids.add(q.symbol_id)
        quant_names[q.name] = targ

    def collect_internal_type_vars(node: Any) -> None:
        if isinstance(node, QTypeVar) and node.name in quant_names:
            subst[node.symbol_id] = quant_names[node.name]
        elif hasattr(node, "__dataclass_fields__"):
            for f_name in node.__dataclass_fields__:
                collect_internal_type_vars(getattr(node, f_name))
        elif isinstance(node, (list, tuple)):
            for item in node:
                collect_internal_type_vars(item)

    for p in fun.params:
        collect_internal_type_vars(p)
    collect_internal_type_vars(fun.body)

    remaining_quants = tuple(
        q.substitute(subst) for q in quants if q.symbol_id not in instantiated_ids
    )
    new_inner_t = inner_t.substitute(subst)
    if remaining_quants:
        new_type_val: QType = QAllType(quantifiers=remaining_quants, body=new_inner_t)
    else:
        new_type_val = new_inner_t

    new_params = tuple(substitute_typed_node(p, subst) for p in fun.params)
    new_body = substitute_typed_node(fun.body, subst)
    cloned_fun = TypedFun(
        params=new_params,
        body=new_body,
        type_val=new_type_val,
        offset=fun.offset,
    )
    clean_name = name.replace(".", "_")
    type_tags = "_".join(type_to_c_tag(t) for t in type_args)
    spec_ident = f"{clean_name}_spec_{type_tags}"
    return spec_ident, cloned_fun


def find_specialization_calls(node: Any) -> list[tuple[str, tuple[QType, ...]]]:
    """Finds all polymorphic function calls needing call-site specialization."""
    calls: list[tuple[str, tuple[QType, ...]]] = []

    def scan(n: Any) -> None:
        if n is None:
            return
        match n:
            case TypedApp(func=f, args=args):
                effective_func = f
                type_args: list[QType] = []
                while isinstance(effective_func, TypedTypeApp):
                    type_args = list(effective_func.type_args) + type_args
                    effective_func = effective_func.func

                func_name = None
                if isinstance(effective_func, TypedVar):
                    func_name = effective_func.name
                elif (
                    isinstance(effective_func, TypedSelect)
                    and isinstance(effective_func.target, TypedVar)
                ):
                    func_name = f"{effective_func.target.name}.{effective_func.field}"

                if func_name and type_args:
                    if any(is_specialization_needed(t) for t in type_args):
                        calls.append((func_name, tuple(type_args)))

                scan(f)
                for a in args:
                    scan(a)
            case _:
                if isinstance(n, (list, tuple)):
                    for item in n:
                        scan(item)
                elif hasattr(n, "__dataclass_fields__"):
                    for field_name in n.__dataclass_fields__:
                        scan(getattr(n, field_name))

    scan(node)
    return calls


def collect_aggregate_types(
    node: Any, ctx: RecordNamingContext
) -> tuple[list[tuple[str, QType]], list[QVariantType]]:
    """Traverses an AST to find all unique aggregate types (tuples, records, options, variants)."""
    visited_names: set[str] = set()
    result: list[tuple[str, QType]] = []
    variant_types: list[QVariantType] = []

    def visit_type(t: Optional[QType]) -> None:
        if t is None:
            return
        if isinstance(t, QTupleType):
            for f in t.value_fields:
                visit_type(f.type_val)
            name = tuple_struct_name(t)
            if name not in visited_names:
                visited_names.add(name)
                result.append((name, t))
        elif isinstance(t, QRecordType):
            for f in t.fields:
                visit_type(f.type_val)
            name = record_struct_name(t, ctx)
            if name not in visited_names:
                visited_names.add(name)
                result.append((name, t))
        elif isinstance(t, QOptionType):
            for o in t.options:
                if o.payload_type:
                    visit_type(o.payload_type)
            name = option_struct_name(t)
            if name not in visited_names:
                visited_names.add(name)
                result.append((name, t))
        elif isinstance(t, QVariantType):
            if t not in variant_types:
                variant_types.append(t)
            for v in t.variants:
                if getattr(v, "type_val", None):
                    visit_type(v.type_val)
        elif hasattr(t, "params") and hasattr(t, "result_type"):
            for p in getattr(t, "params", ()):
                visit_type(getattr(p, "type_val", None))
            visit_type(getattr(t, "result_type", None))
        elif hasattr(t, "element_type"):
            visit_type(getattr(t, "element_type", None))
        elif hasattr(t, "inner_type"):
            visit_type(getattr(t, "inner_type", None))
        if hasattr(t, "bound"):
            bound = getattr(t, "bound")
            if hasattr(bound, "bound"):
                visit_type(getattr(bound, "bound"))
        if hasattr(t, "quantifiers") and hasattr(t, "body"):
            for q in getattr(t, "quantifiers", ()):
                if hasattr(q, "bound") and hasattr(q.bound, "bound"):
                    visit_type(getattr(q.bound, "bound"))
            visit_type(getattr(t, "body", None))

    def visit_node(n: Any) -> None:
        if n is None:
            return
        if isinstance(n, QType):
            visit_type(n)
        if isinstance(n, TypedLetType) and n.symbol.definition is not None:
            if isinstance(n.symbol.definition, QRecordType):
                ctx.register_alias(n.name, n.symbol.definition)
        if isinstance(n, TypedRecord):
            concrete_t = QRecordType(
                fields=tuple(
                    QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var)
                    for fld in n.fields
                )
            )
            visit_type(concrete_t)
        if hasattr(n, "type_val") and isinstance(getattr(n, "type_val"), QType):
            visit_type(getattr(n, "type_val"))
        if hasattr(n, "symbol"):
            sym = getattr(n, "symbol")
            if hasattr(sym, "type_val") and isinstance(getattr(sym, "type_val"), QType):
                visit_type(getattr(sym, "type_val"))
            if hasattr(sym, "definition") and isinstance(getattr(sym, "definition"), QType):
                visit_type(getattr(sym, "definition"))
        if hasattr(n, "definition") and isinstance(getattr(n, "definition"), QType):
            visit_type(getattr(n, "definition"))

        if isinstance(n, (list, tuple)):
            for item in n:
                visit_node(item)
            return

        if hasattr(n, "__dataclass_fields__"):
            for field_name in n.__dataclass_fields__:
                visit_node(getattr(n, field_name))

    visit_node(node)
    return result, variant_types


def analyze_program_for_c(
    prog: TypedProgram,
    record_ctx: RecordNamingContext,
    loaded_modules: Optional[dict[str, TypedModule]] = None,
) -> CProgramAnalysis:
    """Performs full program analysis required for C code generation."""
    from quest.builtins import BuiltinModuleRegistry

    # Collect modules from both loaded_modules and prog.phrases
    all_module_map: dict[str, TypedModule] = {}
    if loaded_modules:
        for mod in loaded_modules.values():
            if isinstance(mod, TypedModule):
                all_module_map[mod.name] = mod
    for phrase in prog.phrases:
        if isinstance(phrase, TypedModule):
            all_module_map[phrase.name] = phrase

    sorted_modules = topological_sort_modules(list(all_module_map.values()))

    # 1. Top-level phrases in prog
    top_funs: list[tuple[str, TypedFun, Any]] = []
    top_vars: list[tuple[str, TypedExpr, Any]] = []

    for phrase in prog.phrases:
        match phrase:
            case TypedModule():
                pass
            case TypedLetValue(name=name, value=val, symbol=symbol):
                if isinstance(val, TypedFun):
                    top_funs.append((name, val, symbol))
                else:
                    top_vars.append((name, val, symbol))
            case TypedException(name=name, type_val=t) as exc_node:
                if name:
                    top_vars.append((name, exc_node, type("Symbol", (), {"type_val": t})()))
            case TypedExprStmt(expr=TypedException(name=name, type_val=t) as exc_node):
                if name:
                    top_vars.append((name, exc_node, type("Symbol", (), {"type_val": t})()))
            case _:
                pass

    top_fun_names = {name for name, _, _ in top_funs}
    top_var_names = {name for name, _, _ in top_vars}
    top_funs_dict = {name: (fun, sym) for name, fun, sym in top_funs}

    # Index module functions for possible specialization
    module_funs_dict: dict[str, tuple[TypedFun, Any]] = {}
    for mod in sorted_modules:
        clean_mod = mod.name.replace(".", "_")
        for b in mod.bindings:
            if isinstance(b, TypedLetValue) and isinstance(b.value, TypedFun):
                module_funs_dict[f"{mod.name}.{b.name}"] = (b.value, b.symbol)
                module_funs_dict[f"{clean_mod}.{b.name}"] = (b.value, b.symbol)

    # 2. Call-site specialization discovery and synthesis
    specializations: dict[tuple[str, tuple[QType, ...]], tuple[str, TypedFun]] = {}
    worklist: list[Any] = list(prog.phrases)

    while worklist:
        curr_node = worklist.pop(0)
        found_calls = find_specialization_calls(curr_node)
        for fname, targs in found_calls:
            spec_key = (fname, targs)
            if spec_key in specializations:
                continue
            orig = top_funs_dict.get(fname) or module_funs_dict.get(fname)
            if orig is None:
                continue
            orig_fun, orig_sym = orig
            spec_ident, spec_fun = specialize_typed_fun(fname, orig_fun, targs)
            specializations[spec_key] = (spec_ident, spec_fun)
            top_funs.append((spec_ident, spec_fun, orig_sym))
            top_funs_dict[spec_ident] = (spec_fun, orig_sym)
            top_fun_names.add(spec_ident)
            worklist.append(spec_fun)

    # 3. Aggregate and variant types collection across prog and all specialized functions
    agg_types, variant_types = collect_aggregate_types(prog, record_ctx)

    for _, sfun, _ in top_funs:
        s_agg, s_var = collect_aggregate_types(sfun, record_ctx)
        for item in s_agg:
            if item not in agg_types:
                agg_types.append(item)
        for v in s_var:
            if v not in variant_types:
                variant_types.append(v)

    for mod in sorted_modules:
        for b in mod.bindings:
            b_agg, b_var = collect_aggregate_types(b, record_ctx)
            for item in b_agg:
                if item not in agg_types:
                    agg_types.append(item)
            for v in b_var:
                if v not in variant_types:
                    variant_types.append(v)
        mod_rec_t = BuiltinModuleRegistry._build_record_type_from_scope(mod.scope)
        rec_tag = record_struct_name(mod_rec_t, record_ctx)
        if not any(tag == rec_tag for tag, _ in agg_types):
            agg_types.append((rec_tag, mod_rec_t))

    all_records = [t for _, t in agg_types if isinstance(t, QRecordType)]
    all_tuples = [t for _, t in agg_types if isinstance(t, QTupleType)]

    # 4. Pre-populate all subtyping coercions
    needed_dicts: set[tuple[QRecordType, QRecordType]] = set()
    tuple_coercions: set[tuple[QTupleType, QTupleType]] = set()
    variant_coercions: set[tuple[QVariantType, QVariantType]] = set()

    for t in all_records:
        needed_dicts.add((t, t))
        for s in all_records:
            if s != t and is_record_subtype(s, t):
                needed_dicts.add((t, s))

    for t in all_tuples:
        for s in all_tuples:
            if s != t and is_tuple_subtype(s, t):
                tuple_coercions.add((t, s))

    for t in variant_types:
        for s in variant_types:
            if s != t and is_variant_subtype(s, t):
                variant_coercions.add((t, s))

    top_names = top_fun_names | top_var_names
    val_referenced_top_funs = find_val_referenced_top_funs(prog, top_fun_names)

    # 5. Closures
    top_fun_objs = {id(f) for _, f, _ in top_funs}
    agnostic_lambdas = analyze_closures(prog, top_fun_objs, top_names)

    lifted_lambdas: list[CLambdaInfo] = []
    for l in agnostic_lambdas:
        c_fn_name = f"qv_{l.id}"
        fvars_tuples = [(v.name, v.type_val) for v in l.free_vars]
        env_struct = f"struct QEnv_{l.id}" if fvars_tuples else None
        closure_var = f"qv_{l.id}_closure" if not fvars_tuples else None
        lifted_lambdas.append(
            CLambdaInfo(
                id=l.id,
                fun=l.fun,
                free_vars=fvars_tuples,
                env_struct_name=env_struct,
                c_fn_name=c_fn_name,
                closure_var_name=closure_var,
            )
        )

    lambda_info_by_id = {id(l.fun): l for l in lifted_lambdas}

    return CProgramAnalysis(
        sorted_modules=sorted_modules,
        agg_types=agg_types,
        variant_types=variant_types,
        needed_dicts=needed_dicts,
        tuple_coercions=tuple_coercions,
        variant_coercions=variant_coercions,
        top_funs=top_funs,
        top_vars=top_vars,
        top_fun_names=top_fun_names,
        top_var_names=top_var_names,
        val_referenced_top_funs=val_referenced_top_funs,
        lifted_lambdas=lifted_lambdas,
        lambda_info_by_id=lambda_info_by_id,
        top_funs_dict=top_funs_dict,
        specializations=specializations,
    )
