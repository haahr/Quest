"""C-specific AST and Program Analysis for Quest C Transpiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quest.analysis.closure import LambdaAnalysis, analyze_closures
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
    TypedProgram,
    TypedRecord,
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
)
from quest.types import (
    QOptionType,
    QRecordField,
    QRecordType,
    QTupleType,
    QType,
    QVariantType,
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
                if isinstance(f, TypedVar) and f.name in top_fun_names:
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

    # 1. Aggregate and variant types collection
    agg_types, variant_types = collect_aggregate_types(prog, record_ctx)

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

    # 2. Pre-populate all subtyping coercions
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

    # 3. Top-level phrases in prog
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
    top_names = top_fun_names | top_var_names

    val_referenced_top_funs = find_val_referenced_top_funs(prog, top_fun_names)

    # 4. Closures
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
    top_funs_dict = {name: (fun, sym) for name, fun, sym in top_funs}

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
    )
