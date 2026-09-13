"""C Code Generator for Quest AST (Emitting Standard ISO C99)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quest.codegen.c_types import (
    RecordNamingContext,
    mangle_ident,
    mangle_module_ident,
    option_struct_name,
    qtype_to_c_type,
    qtype_to_name_str,
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


@dataclass
class LambdaInfo:
    """Metadata for a lifted lambda closure."""
    id: str
    fun: TypedFun
    free_vars: list[tuple[str, QType]]
    env_struct_name: Optional[str]
    c_fn_name: str
    closure_var_name: Optional[str] = None


def _c_string_literal(s: str) -> str:
    """Escapes a Python string into a safe C string literal."""
    parts = []
    for ch in s:
        if ch == "\"":
            parts.append("\\\"")
        elif ch == "\\":
            parts.append("\\\\")
        elif ch == "\n":
            parts.append("\\n")
        elif ch == "\t":
            parts.append("\\t")
        elif ch == "\r":
            parts.append("\\r")
        elif 32 <= ord(ch) < 127:
            parts.append(ch)
        else:
            parts.append(f"\\x{ord(ch):02x}")
    return "\"" + "".join(parts) + "\""


def _c_char_literal(ch: str) -> str:
    """Escapes a single character into a safe C character literal."""
    if ch == "'":
        return "'\\''"
    if ch == "\\":
        return "'\\\\'"
    if ch == "\n":
        return "'\\n'"
    if ch == "\t":
        return "'\\t'"
    if ch == "\r":
        return "'\\r'"
    if 32 <= ord(ch) < 127:
        return f"'{ch}'"
    return f"'\\x{ord(ch):02x}'"


def _indent(text: str, spaces: int = 4) -> str:
    """Indents non-empty lines of text by the given number of spaces."""
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


def _qval_wrap(expr_str: str, t: QType) -> str:
    """Wraps a scalar or pointer expression into a QVal union initializer."""
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    if isinstance(t, QTypeVar):
        return expr_str
    if t == INT_TYPE or t == BOOL_TYPE or t == CHAR_TYPE:
        return f"((QVal){{ .i = (int64_t)({expr_str}) }})"
    if t == REAL_TYPE:
        return f"((QVal){{ .r = (double)({expr_str}) }})"
    if t == STRING_TYPE or isinstance(t, (QTupleType, QRecordType, QFunType, QAllType, QArrayType, QVariantType, QOptionType, QExceptionType)):
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    return f"((QVal){{ .u = 0 }})"


def _qval_unwrap(qval_expr: str, t: QType, emitter: Optional[Any] = None) -> str:
    """Extracts the underlying concrete scalar or pointer from a QVal expression."""
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return f"((QDynamic *)({qval_expr}.p))"
    if isinstance(t, QTypeVar):
        return qval_expr
    if t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
        return f"({qval_expr}.i)"
    if t == REAL_TYPE:
        return f"({qval_expr}.r)"
    if t == OK_TYPE:
        return "((void)0)"
    if emitter is not None:
        c_t = emitter.c_type(t)
        return f"(({c_t})({qval_expr}.p))"
    return f"({qval_expr}.p)"


def is_record_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QRecordType) or not isinstance(t, QRecordType):
        return False
    s_fields = {f.name: f.type_val for f in s.fields}
    for f in t.fields:
        if f.name not in s_fields or s_fields[f.name] != f.type_val:
            return False
    return True


def is_tuple_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QTupleType) or not isinstance(t, QTupleType):
        return False
    if len(s.value_fields) < len(t.value_fields):
        return False
    for i in range(len(t.value_fields)):
        if s.value_fields[i].type_val != t.value_fields[i].type_val:
            return False
    return True


def is_variant_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QVariantType) or not isinstance(t, QVariantType):
        return False
    t_map = {v.name: v.type_val for v in t.variants}
    for v in s.variants:
        if v.name not in t_map or v.type_val != t_map[v.name]:
            return False
    return True


def _closure_fn_ptr_type(fun_type: QType, ctx: Optional[RecordNamingContext] = None) -> str:
    """Constructs the C function pointer cast type for invoking a closure."""
    quantifiers: tuple[QQuantifier, ...] = ()
    cur_type = fun_type
    while isinstance(cur_type, QAllType):
        quantifiers = quantifiers + cur_type.quantifiers
        cur_type = cur_type.body

    if isinstance(cur_type, QFunType):
        if cur_type.result_type == OK_TYPE:
            ret_c = "void"
        elif isinstance(cur_type.result_type, QRecordType) and ctx is not None:
            ret_c = f"QRecordResult_{ctx.get_or_create_name(cur_type.result_type)}"
        else:
            ret_c = qtype_to_c_type(cur_type.result_type, ctx)
        param_types = ["void *"]
        # Quantifier descriptors appear immediately after env
        for _ in quantifiers:
            param_types.append("const QTypeDescriptor *")
        for p in cur_type.params:
            if isinstance(p.type_val, QRecordType):
                param_types.append("void *")
                d_name = ctx.offset_dict_struct_name(p.type_val) if ctx else "void"
                param_types.append(f"const {d_name} *")
            else:
                param_types.append(qtype_to_c_type(p.type_val, ctx))
        sig = ", ".join(param_types)
        return f"{ret_c} (*)({sig})"
    return "void * (*)(void *, ...)"


def _find_free_vars(fun: TypedFun, top_names: set[str]) -> list[tuple[str, QType]]:
    """Finds all free variables captured by a lambda from enclosing non-global scopes."""
    free_vars: list[tuple[str, QType]] = []
    seen: set[str] = set()

    def walk(node: Any, bound: set[str]) -> None:
        if node is None:
            return
        match node:
            case TypedVar(name=name, type_val=t):
                if name not in bound and name not in top_names and name not in seen:
                    seen.add(name)
                    free_vars.append((name, t))
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


def _find_val_referenced_top_funs(prog: TypedProgram, top_fun_names: set[str]) -> set[str]:
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


def _collect_aggregate_types(
    prog: TypedProgram, ctx: RecordNamingContext
) -> tuple[list[tuple[str, QType]], list[QVariantType]]:
    """Traverses the program to find all unique aggregate types (tuples, records, options, variants)."""
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

    def visit_node(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, TypedLetType) and node.symbol.definition is not None:
            if isinstance(node.symbol.definition, QRecordType):
                ctx.register_alias(node.name, node.symbol.definition)
        if isinstance(node, TypedRecord):
            concrete_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in node.fields))
            visit_type(concrete_t)
        if hasattr(node, "type_val") and isinstance(getattr(node, "type_val"), QType):
            visit_type(getattr(node, "type_val"))
        if hasattr(node, "symbol"):
            sym = getattr(node, "symbol")
            if hasattr(sym, "type_val") and isinstance(getattr(sym, "type_val"), QType):
                visit_type(getattr(sym, "type_val"))
            if hasattr(sym, "definition") and isinstance(getattr(sym, "definition"), QType):
                visit_type(getattr(sym, "definition"))
        if hasattr(node, "definition") and isinstance(getattr(node, "definition"), QType):
            visit_type(getattr(node, "definition"))

        if isinstance(node, (list, tuple)):
            for item in node:
                visit_node(item)
            return

        if hasattr(node, "__dataclass_fields__"):
            for field_name in node.__dataclass_fields__:
                visit_node(getattr(node, field_name))

    visit_node(prog)
    return result, variant_types


def _collect_lambdas(
    prog: TypedProgram, top_funs: list[tuple[str, TypedFun, Any]], top_names: set[str]
) -> list[LambdaInfo]:
    """Scans program to find all lambdas that need lifting and generates LambdaInfo."""
    lambdas: list[LambdaInfo] = []
    lambda_counter = 0

    # Top-level fun objects are not lifted lambdas
    top_fun_objs = {id(f) for _, f, _ in top_funs}

    def scan(node: Any) -> None:
        nonlocal lambda_counter
        if node is None:
            return
        if isinstance(node, TypedFun):
            if id(node) not in top_fun_objs:
                lambda_counter += 1
                lid = f"lambda_{lambda_counter}"
                c_fn_name = f"qv_{lid}"
                fvars = _find_free_vars(node, top_names)
                env_struct = f"struct QEnv_{lid}" if fvars else None
                closure_var = f"qv_{lid}_closure" if not fvars else None
                lambdas.append(
                    LambdaInfo(
                        id=lid,
                        fun=node,
                        free_vars=fvars,
                        env_struct_name=env_struct,
                        c_fn_name=c_fn_name,
                        closure_var_name=closure_var,
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
            if isinstance(p.type_val, QRecordType):
                dict_t = self.record_ctx.offset_dict_struct_name(p.type_val)
                dict_param = f"_dict_{p_c}"
                decls.append(f"void *{p_c}")
                decls.append(f"const {dict_t} *{dict_param}")
                forward_args.append(p_c)
                forward_args.append(dict_param)
            else:
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

    def emit_program(
        self,
        prog: TypedProgram,
        loaded_modules: Optional[dict[str, TypedModule]] = None,
    ) -> str:
        """Translates a TypedProgram into a full standard C99 source file string."""
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
        # 0. Aggregate and variant types collection
        agg_types, variant_types = _collect_aggregate_types(prog, self.record_ctx)

        # Collect aggregate types from module bindings and module interface records
        for mod in sorted_modules:
            for b in mod.bindings:
                b_agg, b_var = _collect_aggregate_types(b, self.record_ctx)
                for item in b_agg:
                    if item not in agg_types:
                        agg_types.append(item)
                for v in b_var:
                    if v not in variant_types:
                        variant_types.append(v)
            mod_rec_t = BuiltinModuleRegistry._build_record_type_from_scope(mod.scope)
            rec_tag = record_struct_name(mod_rec_t, self.record_ctx)
            if not any(tag == rec_tag for tag, _ in agg_types):
                agg_types.append((rec_tag, mod_rec_t))

        all_records = [t for _, t in agg_types if isinstance(t, QRecordType)]
        all_tuples = [t for _, t in agg_types if isinstance(t, QTupleType)]

        # Pre-populate all subtyping coercions present among types
        for t in all_records:
            self.needed_dicts.add((t, t))
            for s in all_records:
                if s != t and is_record_subtype(s, t):
                    self.needed_dicts.add((t, s))

        for t in all_tuples:
            for s in all_tuples:
                if s != t and is_tuple_subtype(s, t):
                    self.tuple_coercions.add((t, s))

        for t in variant_types:
            for s in variant_types:
                if s != t and is_variant_subtype(s, t):
                    self.variant_coercions.add((t, s))

        # Top-level phrases in prog (excluding TypedModule which are emitted separately)
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

        self.top_fun_names = {name for name, _, _ in top_funs}
        self.top_var_names = {name for name, _, _ in top_vars}
        top_names = self.top_fun_names | self.top_var_names
        self.val_referenced_top_funs = _find_val_referenced_top_funs(prog, self.top_fun_names)

        self.lifted_lambdas = _collect_lambdas(prog, top_funs, top_names)
        self.lambda_info_by_id = {id(l.fun): l for l in self.lifted_lambdas}

        lines: list[str] = [
            "/* Emitted by Quest Bootstrap C Transpiler */",
            "#include \"quest_runtime.h\"",
            "",
        ]

        if agg_types:
            lines.append("/* Forward declarations for aggregate types */")
            for tag_name, _ in agg_types:
                lines.append(f"typedef struct {tag_name} {tag_name};")
            lines.append("")

        if sorted_modules:
            lines.append("/* Forward declarations and state for compiled modules */")
            for mod in sorted_modules:
                mod_rec_t = BuiltinModuleRegistry._build_record_type_from_scope(mod.scope)
                rec_struct = self.record_struct_name(mod_rec_t)
                clean_mod = mod.name.replace(".", "_")
                lines.append(f"static {rec_struct} *qv_{clean_mod};")
                lines.append(f"static bool qv_mod_{clean_mod}_initialized = false;")
                lines.append(f"static void qv_mod_{clean_mod}_init(void);")
            lines.append("")

        if agg_types:
            lines.append("/* Aggregate struct definitions */")
            for tag_name, t in agg_types:
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
                lines.append(f"typedef struct QRecordResult_{rec_name} {{")
                lines.append("    void *val;")
                lines.append(f"    const {dict_t} *dict;")
                lines.append(f"}} QRecordResult_{rec_name};")
            lines.append("")

        if self.needed_dicts:
            lines.append("/* Static evidence dictionaries for record subtyping */")
            for tgt, src in sorted(
                self.needed_dicts,
                key=lambda p: (
                    self.record_ctx.get_or_create_name(p[0]),
                    self.record_ctx.get_or_create_name(p[1]),
                ),
            ):
                inst_name = self.record_ctx.offset_dict_instance_name(tgt, src)
                dict_t = self.record_ctx.offset_dict_struct_name(tgt)
                src_sname = self.record_struct_name(src)
                if not tgt.fields:
                    lines.append(f"static const {dict_t} {inst_name} = {{ 0 }};")
                else:
                    entries = [
                        f"offsetof({src_sname}, qf_{f.name})"
                        for f in sorted(tgt.fields, key=lambda fld: fld.name)
                    ]
                    lines.append(f"static const {dict_t} {inst_name} = {{ {', '.join(entries)} }};")
            lines.append("")

        if self.tuple_coercions:
            lines.append("/* Compile-time static assertions for tuple subtyping */")
            for tgt, src in sorted(
                self.tuple_coercions,
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

        if self.variant_coercions:
            lines.append("/* Static tag remapping tables for variant subtyping */")
            for tgt, src in sorted(
                self.variant_coercions,
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

        # 1. Environment struct definitions for capturing lambdas
        capturing_lambdas = [l for l in self.lifted_lambdas if l.free_vars]
        if capturing_lambdas:
            lines.append("/* Environment structs for capturing closures */")
            for l in capturing_lambdas:
                lines.append(f"{l.env_struct_name} {{")
                for vname, vtype in l.free_vars:
                    c_type = self.c_type(vtype)
                    lines.append(f"    {c_type} {mangle_ident(vname)};")
                lines.append("};")
                lines.append("")

        # 2. Static declarations for top-level non-void variables
        if top_vars:
            for name, val, symbol in top_vars:
                if symbol.type_val != OK_TYPE:
                    c_ident = mangle_ident(name)
                    if isinstance(symbol.type_val, QRecordType) and not self._is_exact_record_literal(symbol.type_val, val):
                        dict_t = self.record_ctx.offset_dict_struct_name(symbol.type_val)
                        lines.append(f"static void *{c_ident};")
                        lines.append(f"static const {dict_t} *_dict_{c_ident};")
                        self.var_dict_names[name] = f"_dict_{c_ident}"
                    else:
                        c_type = self.c_type(symbol.type_val)
                        lines.append(f"static {c_type} {c_ident};")
            lines.append("")

        # 3. Forward declarations for top-level functions
        if top_funs:
            lines.append("/* Forward declarations for top-level functions */")
            for name, fun, _sym in top_funs:
                quants, params, _body, ret_type = self._collect_fun_params(fun)
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else (
                    f"QRecordResult_{self.record_ctx.get_or_create_name(ret_type)}"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, _ = self._param_signatures(params, quants)
                param_sig = "void" if not decls else ", ".join(decls)
                lines.append(f"static {ret_c} {c_name}({param_sig});")
            lines.append("")

        # 4. Forward declarations for lifted lambdas
        if self.lifted_lambdas:
            lines.append("/* Forward declarations for lifted lambdas */")
            for l in self.lifted_lambdas:
                quants, _ = self._collect_fun_quantifiers(l.fun.type_val)
                ret_type = l.fun.type_val.result_type if isinstance(l.fun.type_val, QFunType) else l.fun.type_val
                if isinstance(ret_type, QAllType):
                    _, inner = self._collect_fun_quantifiers(ret_type)
                    ret_type = inner.result_type if isinstance(inner, QFunType) else inner
                ret_c = "void" if ret_type == OK_TYPE else (
                    f"QRecordResult_{self.record_ctx.get_or_create_name(ret_type)}"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, _ = self._param_signatures(l.fun.params, quants)
                param_sigs = ["void *_raw_env"] + decls
                sig = ", ".join(param_sigs)
                lines.append(f"static {ret_c} {l.c_fn_name}({sig});")
            lines.append("")

        # 5. Static closures for non-capturing lambdas
        non_capturing = [l for l in self.lifted_lambdas if not l.free_vars]
        if non_capturing:
            lines.append("/* Static closures for non-capturing lambdas */")
            for l in non_capturing:
                lines.append(f"static QClosure {l.closure_var_name} = {{ (void *){l.c_fn_name}, NULL }};")
            lines.append("")

        # 6. Trampolines and static closures for value-referenced top-level functions
        self.top_funs_dict = {name: (fun, sym) for name, fun, sym in top_funs}
        top_funs_dict = self.top_funs_dict
        if self.val_referenced_top_funs:
            lines.append("/* Trampoline functions and static closures for first-class top-level functions */")
            for name in sorted(self.val_referenced_top_funs):
                fun, _ = top_funs_dict[name]
                c_name = mangle_ident(name)
                tramp_name = f"{c_name}_trampoline"
                quants, params, _, ret_type = self._collect_fun_params(fun)
                ret_c = "void" if ret_type == OK_TYPE else (
                    f"QRecordResult_{self.record_ctx.get_or_create_name(ret_type)}"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, forward_args = self._param_signatures(params, quants)
                param_sigs = ["void *env"] + decls
                sig = ", ".join(param_sigs)
                args_str = ", ".join(forward_args)
                lines.append(f"static {ret_c} {tramp_name}({sig}) {{")
                lines.append("    (void)env;")
                if ret_type == OK_TYPE:
                    lines.append(f"    {c_name}({args_str});")
                    lines.append("    return;")
                else:
                    lines.append(f"    return {c_name}({args_str});")
                lines.append("}")
                lines.append(f"static QClosure {c_name}_closure = {{ (void *){tramp_name}, NULL }};")
                lines.append("")

        # 7. Function definitions for top-level functions
        if top_funs:
            lines.append("/* Function definitions */")
            for name, fun, _sym in top_funs:
                quants, params, body, ret_type = self._collect_fun_params(fun)
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else (
                    f"QRecordResult_{self.record_ctx.get_or_create_name(ret_type)}"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
                decls, _ = self._param_signatures(params, quants)
                param_sig = "void" if not decls else ", ".join(decls)
                lines.append(f"static {ret_c} {c_name}({param_sig}) {{")
                saved_descriptors = dict(self.in_scope_type_descriptors)
                for q in quants:
                    self.in_scope_type_descriptors[q.name] = f"descriptor_{q.name}"
                saved_param_dicts = dict(self.param_dict_names)
                for p in params:
                    if isinstance(p.type_val, QRecordType):
                        self.param_dict_names[p.name] = f"_dict_{mangle_ident(p.name)}"
                fn_lines: list[str] = []
                # Silence unused descriptor warnings
                for q in quants:
                    fn_lines.append(f"(void)descriptor_{q.name};")
                if ret_type == OK_TYPE:
                    self.emit_to(body, None, fn_lines)
                    fn_lines.append("return;")
                elif isinstance(ret_type, QRecordType):
                    ret_val = self.emit_val(body, fn_lines)
                    dict_expr = None
                    if isinstance(body, TypedVar):
                        dict_expr = self.param_dict_names.get(body.name) or self.var_dict_names.get(body.name)
                    if dict_expr is None:
                        actual_record_t = body.type_val
                        if isinstance(body, TypedRecord):
                            actual_record_t = QRecordType(fields=tuple(QRecordField(name=f.name, type_val=f.value.type_val, is_var=f.is_var) for f in body.fields))
                        if isinstance(actual_record_t, QRecordType):
                            d_name = self.record_ctx.offset_dict_instance_name(ret_type, actual_record_t)
                            dict_expr = f"&{d_name}"
                    rec_name = self.record_ctx.get_or_create_name(ret_type)
                    fn_lines.append(
                        f"return (QRecordResult_{rec_name}){{ (void *){ret_val}, {dict_expr if dict_expr else 'NULL'} }};"
                    )
                elif isinstance(ret_type, QTupleType) and isinstance(body.type_val, QTupleType) and body.type_val != ret_type:
                    ret_val = self.emit_val(body, fn_lines)
                    cast_t = self.c_type(ret_type)
                    fn_lines.append(f"return ({cast_t}){ret_val};")
                elif isinstance(ret_type, QVariantType) and isinstance(body.type_val, QVariantType) and body.type_val != ret_type:
                    ret_val = self.emit_val(body, fn_lines)
                    tmp_v = self.fresh_tmp("_vup")
                    tagmap_name = f"tagmap_{type_to_c_tag(ret_type)}_{type_to_c_tag(body.type_val)}"
                    fn_lines.append(f"QVariant *{tmp_v} = (QVariant *)quest_alloc(sizeof(QVariant));")
                    fn_lines.append(f"{tmp_v}->descriptor = NULL;")
                    fn_lines.append(f"{tmp_v}->tag = {tagmap_name}[{ret_val}->tag];")
                    fn_lines.append(f"{tmp_v}->payload = {ret_val}->payload;")
                    fn_lines.append(f"return {tmp_v};")
                else:
                    ret_val = self.emit_val(body, fn_lines)
                    fn_lines.append(f"return {ret_val};")
                self.param_dict_names = saved_param_dicts
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
                ret_c = "void" if ret_type == OK_TYPE else (
                    f"QRecordResult_{self.record_ctx.get_or_create_name(ret_type)}"
                    if isinstance(ret_type, QRecordType)
                    else self.c_type(ret_type)
                )
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

                saved_param_dicts = dict(self.param_dict_names)
                for p in l.fun.params:
                    if isinstance(p.type_val, QRecordType):
                        self.param_dict_names[p.name] = f"_dict_{mangle_ident(p.name)}"

                if ret_type == OK_TYPE:
                    self.emit_to(l.fun.body, None, fn_lines)
                    fn_lines.append("return;")
                elif isinstance(ret_type, QRecordType):
                    ret_val = self.emit_val(l.fun.body, fn_lines)
                    dict_expr = None
                    if isinstance(l.fun.body, TypedVar):
                        dict_expr = self.param_dict_names.get(l.fun.body.name) or self.var_dict_names.get(l.fun.body.name)
                    if dict_expr is None:
                        actual_record_t = l.fun.body.type_val
                        if isinstance(l.fun.body, TypedRecord):
                            actual_record_t = QRecordType(fields=tuple(QRecordField(name=f.name, type_val=f.value.type_val, is_var=f.is_var) for f in l.fun.body.fields))
                        if isinstance(actual_record_t, QRecordType):
                            d_name = self.record_ctx.offset_dict_instance_name(ret_type, actual_record_t)
                            dict_expr = f"&{d_name}"
                    rec_name = self.record_ctx.get_or_create_name(ret_type)
                    fn_lines.append(
                        f"return (QRecordResult_{rec_name}){{ (void *){ret_val}, {dict_expr if dict_expr else 'NULL'} }};"
                    )
                elif isinstance(ret_type, QTupleType) and isinstance(l.fun.body.type_val, QTupleType) and l.fun.body.type_val != ret_type:
                    ret_val = self.emit_val(l.fun.body, fn_lines)
                    cast_t = self.c_type(ret_type)
                    fn_lines.append(f"return ({cast_t}){ret_val};")
                elif isinstance(ret_type, QVariantType) and isinstance(l.fun.body.type_val, QVariantType) and l.fun.body.type_val != ret_type:
                    ret_val = self.emit_val(l.fun.body, fn_lines)
                    tmp_v = self.fresh_tmp("_vup")
                    tagmap_name = f"tagmap_{type_to_c_tag(ret_type)}_{type_to_c_tag(l.fun.body.type_val)}"
                    fn_lines.append(f"QVariant *{tmp_v} = (QVariant *)quest_alloc(sizeof(QVariant));")
                    fn_lines.append(f"{tmp_v}->descriptor = NULL;")
                    fn_lines.append(f"{tmp_v}->tag = {tagmap_name}[{ret_val}->tag];")
                    fn_lines.append(f"{tmp_v}->payload = {ret_val}->payload;")
                    fn_lines.append(f"return {tmp_v};")
                else:
                    ret_val = self.emit_val(l.fun.body, fn_lines)
                    fn_lines.append(f"return {ret_val};")

                self.param_dict_names = saved_param_dicts
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
                    param_decls = quant_decls + [f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}" for p in params]
                    sig = "void" if not param_decls else ", ".join(param_decls)
                    lines.append(f"static {ret_c} {m_ident}({sig});")

                # Trampolines for module functions so they can be wrapped in QClosure for exported record
                for fname, ffun, fsym in mod_funs:
                    m_ident = mangle_module_ident(clean_mod, fname)
                    tramp_name = f"{m_ident}_trampoline"
                    quants, params, _, ret_type = self._collect_fun_params(ffun)
                    ret_c = "void" if ret_type == OK_TYPE else self.c_type(ret_type)
                    quant_decls = [f"const QTypeDescriptor *descriptor_{q.name}" for q in quants]
                    param_decls = quant_decls + [f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}" for p in params]
                    param_sigs = ["void *env"] + param_decls
                    sig = ", ".join(param_sigs)
                    f_args = [f"descriptor_{q.name}" for q in quants] + [mangle_module_ident(clean_mod, p.name) for p in params]
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
                    param_decls = quant_decls + [f"{self.c_type(p.type_val)} {mangle_module_ident(clean_mod, p.name)}" for p in params]
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
                    if ret_type == OK_TYPE:
                        mod_emitter.emit_to(body, None, fn_lines)
                        fn_lines.append("return;")
                    else:
                        ret_val = mod_emitter.emit_val(body, fn_lines)
                        fn_lines.append(f"return {ret_val};")
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
                mod_emitter.current_env_vars = {vname: mangle_module_ident(clean_mod, vname) for vname, _, _ in mod_vars}
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
                lines.append(f"    qv_{clean_mod} = ({rec_struct} *)quest_alloc(sizeof({rec_struct}));")
                lines.append(f"    qv_{clean_mod}->header.descriptor = NULL;")
                for fld in sorted(mod_rec_t.fields, key=lambda f: f.name):
                    # Check if exported field is a function
                    matching_fun = next((ff for fn, ff, _ in mod_funs if fn == fld.name), None)
                    if matching_fun is not None:
                        tramp_name = f"{mangle_module_ident(clean_mod, fld.name)}_trampoline"
                        clos_tmp = self.fresh_tmp(f"_{clean_mod}_{fld.name}_clos")
                        lines.append(f"    QClosure *{clos_tmp} = (QClosure *)quest_alloc(sizeof(QClosure));")
                        lines.append(f"    {clos_tmp}->fn = (void *){tramp_name};")
                        lines.append(f"    {clos_tmp}->env = NULL;")
                        lines.append(f"    qv_{clean_mod}->qf_{fld.name} = {clos_tmp};")
                    else:
                        m_ident = mangle_module_ident(clean_mod, fld.name)
                        lines.append(f"    qv_{clean_mod}->qf_{fld.name} = {m_ident};")
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
                elif isinstance(symbol.type_val, QRecordType) and not self._is_exact_record_literal(symbol.type_val, val):
                    phrase_lines = []
                    val_c = self.emit_val(val, phrase_lines)
                    dict_expr = None
                    if isinstance(val, TypedVar):
                        dict_expr = self.param_dict_names.get(val.name) or self.var_dict_names.get(val.name)
                    if dict_expr is None and val_c in self.var_dict_names:
                        dict_expr = self.var_dict_names[val_c]
                    if dict_expr is None:
                        actual_record_t = val.type_val
                        if isinstance(val, TypedRecord):
                            actual_record_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in val.fields))
                        if isinstance(actual_record_t, QRecordType):
                            d_name = self.record_ctx.offset_dict_instance_name(symbol.type_val, actual_record_t)
                            dict_expr = f"&{d_name}"
                    phrase_lines.append(f"{c_ident} = (void *){val_c};")
                    phrase_lines.append(f"_dict_{c_ident} = {dict_expr if dict_expr else 'NULL'};")
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
                    tagmap_name = f"tagmap_{type_to_c_tag(symbol.type_val)}_{type_to_c_tag(val.type_val)}"
                    phrase_lines.append(f"{c_ident} = (QVariant *)quest_alloc(sizeof(QVariant));")
                    phrase_lines.append(f"{c_ident}->descriptor = NULL;")
                    phrase_lines.append(f"{c_ident}->tag = {tagmap_name}[{val_c}->tag];")
                    phrase_lines.append(f"{c_ident}->payload = {val_c}->payload;")
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
                self.emit_to(val, c_tgt, lines)
                return "((void)0)"

            case TypedRecord(fields=flds):
                concrete_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in flds))
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
                if isinstance(tgt.type_val, QOptionType):
                    tag_idx = 0
                    for i, opt in enumerate(tgt.type_val.options):
                        if opt.name == tag:
                            tag_idx = i
                            break
                    return f"({c_tgt}->tag == {tag_idx}LL)"
                elif isinstance(tgt.type_val, QVariantType):
                    tag_idx = 0
                    for i, v in enumerate(tgt.type_val.variants):
                        if v.name == tag:
                            tag_idx = i
                            break
                    return f"({c_tgt}->tag == {tag_idx}LL)"
                else:
                    return f"({c_tgt}->tag == 0LL)"

            case TypedVariantAssert(target=tgt, tag=tag):
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QOptionType):
                    tag_idx = 0
                    opt_field = None
                    for i, opt in enumerate(tgt.type_val.options):
                        if opt.name == tag:
                            tag_idx = i
                            opt_field = opt
                            break
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
                    tag_idx = 0
                    for i, v in enumerate(tgt.type_val.variants):
                        if v.name == tag:
                            tag_idx = i
                            break
                    lines.append(f"if ({c_tgt}->tag != {tag_idx}LL) quest_raise_variant_error();")
                    elem_t = expr.type_val
                    if elem_t == INT_TYPE or elem_t == BOOL_TYPE or elem_t == CHAR_TYPE:
                        return f"({c_tgt}->payload.i)"
                    elif elem_t == REAL_TYPE:
                        return f"({c_tgt}->payload.r)"
                    elif elem_t == STRING_TYPE or isinstance(elem_t, (QTupleType, QRecordType, QFunType, QArrayType, QVariantType, QOptionType)):
                        c_elem_t = self.c_type(elem_t)
                        return f"(({c_elem_t})({c_tgt}->payload.p))"
                    elif elem_t == OK_TYPE:
                        return "((void)0)"
                    else:
                        return f"({c_tgt}->payload)"
                else:
                    lines.append(f"quest_raise_variant_error();")
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
                    val_idx = None
                    for i, vf in enumerate(tgt.type_val.value_fields):
                        if vf.name == fld:
                            val_idx = i
                            break
                    if val_idx is None:
                        if fld.startswith("_"):
                            val_idx = int(fld[1:])
                        elif fld.isdigit():
                            val_idx = int(fld)
                        else:
                            raise ValueError(f"Cannot resolve tuple field '{fld}' in {tgt.type_val}")
                    return f"{c_tgt}->_{val_idx}"
                elif isinstance(tgt.type_val, QRecordType):
                    dict_name = None
                    if isinstance(tgt, TypedVar):
                        dict_name = self.param_dict_names.get(tgt.name) or self.var_dict_names.get(tgt.name)
                    if dict_name is None and c_tgt in self.var_dict_names:
                        dict_name = self.var_dict_names[c_tgt]
                    if dict_name is not None:
                        c_fld_t = self.c_type(expr.type_val)
                        return f"(*({c_fld_t} *)((char *){c_tgt} + {dict_name}->offset_{fld}))"
                    return f"{c_tgt}->qf_{fld}"
                else:
                    return f"{c_tgt}->qf_{fld}"

            case TypedSelectRef(target=tgt, field=fld):
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QTupleType):
                    val_idx = None
                    for i, vf in enumerate(tgt.type_val.value_fields):
                        if vf.name == fld:
                            val_idx = i
                            break
                    if val_idx is None:
                        if fld.startswith("_"):
                            val_idx = int(fld[1:])
                        elif fld.isdigit():
                            val_idx = int(fld)
                        else:
                            raise ValueError(f"Cannot resolve tuple field '{fld}' in {tgt.type_val}")
                    return f"(&({c_tgt}->_{val_idx}))"
                elif isinstance(tgt.type_val, QRecordType):
                    dict_name = None
                    if isinstance(tgt, TypedVar):
                        dict_name = self.param_dict_names.get(tgt.name) or self.var_dict_names.get(tgt.name)
                    if dict_name is None and c_tgt in self.var_dict_names:
                        dict_name = self.var_dict_names[c_tgt]
                    if dict_name is not None:
                        c_fld_t = self.c_type(expr.type_val)
                        return f"(({c_fld_t} *)((char *){c_tgt} + {dict_name}->offset_{fld}))"
                    return f"(&({c_tgt}->qf_{fld}))"
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
                            wrap = _qval_wrap(c_init, args[1].type_val)
                            return f"quest_array_new({c_sz}, {wrap})"
                        elif fld == "size" and len(args) == 1:
                            c_arr = self.emit_val(args[0], lines)
                            return f"({c_arr}->length)"
                        elif fld == "get" and len(args) == 2:
                            c_arr = self.emit_val(args[0], lines)
                            c_idx = self.emit_val(args[1], lines)
                            lines.append(f"quest_check_array_bounds({c_arr}, {c_idx});")
                            elem_t = expr.type_val
                            if elem_t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
                                return f"({c_arr}->data[{c_idx}].i)"
                            elif elem_t == REAL_TYPE:
                                return f"({c_arr}->data[{c_idx}].r)"
                            elif elem_t == STRING_TYPE or elem_t == DYNAMIC_TYPE or (isinstance(elem_t, QTypeVar) and elem_t.name == "Dynamic.T") or isinstance(elem_t, (QTupleType, QRecordType, QFunType, QAllType, QArrayType, QVariantType, QOptionType, QExceptionType)):
                                c_elem_t = self.c_type(elem_t)
                                return f"(({c_elem_t})({c_arr}->data[{c_idx}].p))"
                            else:
                                return f"({c_arr}->data[{c_idx}])"
                        elif fld == "set" and len(args) == 3:
                            c_arr = self.emit_val(args[0], lines)
                            c_idx = self.emit_val(args[1], lines)
                            c_item = self.emit_val(args[2], lines)
                            lines.append(f"quest_check_array_bounds({c_arr}, {c_idx});")
                            wrap = _qval_wrap(c_item, args[2].type_val)
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
                        pt = formal_p.type_val
                        c_a = self.emit_val(actual_a, lines)
                        if isinstance(pt, QRecordType):
                            dict_expr = None
                            if isinstance(actual_a, TypedVar):
                                dict_expr = self.param_dict_names.get(actual_a.name) or self.var_dict_names.get(actual_a.name)
                            if dict_expr is None and c_a in self.var_dict_names:
                                dict_expr = self.var_dict_names[c_a]
                            if dict_expr is None:
                                actual_record_t = actual_a.type_val
                                if isinstance(actual_a, TypedRecord):
                                    actual_record_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in actual_a.fields))
                                if isinstance(actual_record_t, QRecordType):
                                    d_name = self.record_ctx.offset_dict_instance_name(pt, actual_record_t)
                                    dict_expr = f"&{d_name}"
                            c_args.append(f"(void *){c_a}")
                            c_args.append(dict_expr if dict_expr else "NULL")
                        elif isinstance(pt, QTupleType) and isinstance(actual_a.type_val, QTupleType) and actual_a.type_val != pt:
                            cast_t = self.c_type(pt)
                            c_args.append(f"(({cast_t}){c_a})")
                        elif isinstance(pt, QVariantType) and isinstance(actual_a.type_val, QVariantType) and actual_a.type_val != pt:
                            tmp_v = self.fresh_tmp("_vup")
                            tagmap_name = f"tagmap_{type_to_c_tag(pt)}_{type_to_c_tag(actual_a.type_val)}"
                            lines.append(f"QVariant *{tmp_v} = (QVariant *)quest_alloc(sizeof(QVariant));")
                            lines.append(f"{tmp_v}->descriptor = NULL;")
                            lines.append(f"{tmp_v}->tag = {tagmap_name}[{c_a}->tag];")
                            lines.append(f"{tmp_v}->payload = {c_a}->payload;")
                            c_args.append(tmp_v)
                        elif isinstance(pt, QTypeVar):
                            c_args.append(_qval_wrap(c_a, actual_a.type_val))
                        else:
                            c_args.append(c_a)
                    args_str = ", ".join(c_args)
                    call_str = f"{c_func}({args_str})"
                    if isinstance(ret_type, QTypeVar) and expr.type_val != ret_type:
                        call_str = _qval_unwrap(call_str, expr.type_val, self)
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    if isinstance(expr.type_val, QRecordType):
                        rec_name = self.record_ctx.get_or_create_name(expr.type_val)
                        tmp_res = self.fresh_tmp("_rec_res")
                        lines.append(f"QRecordResult_{rec_name} {tmp_res} = {call_str};")
                        tmp_val = self.fresh_tmp("_rec_val")
                        lines.append(f"void *{tmp_val} = {tmp_res}.val;")
                        self.var_dict_names[tmp_val] = f"{tmp_res}.dict"
                        return tmp_val
                    return call_str
                else:
                    fn_ptr_t = _closure_fn_ptr_type(effective_func.type_val, self.record_ctx)
                    clos_val = self.emit_val(effective_func, lines)
                    _, inner_formal = self._collect_fun_quantifiers(effective_func.type_val)
                    formal_types = [p.type_val for p in inner_formal.params] if isinstance(inner_formal, QFunType) else [a.type_val for a in args]
                    c_args = list(descriptor_args)
                    for pt, actual_a in zip(formal_types, args):
                        c_a = self.emit_val(actual_a, lines)
                        if isinstance(pt, QRecordType):
                            dict_expr = None
                            if isinstance(actual_a, TypedVar):
                                dict_expr = self.param_dict_names.get(actual_a.name) or self.var_dict_names.get(actual_a.name)
                            if dict_expr is None and c_a in self.var_dict_names:
                                dict_expr = self.var_dict_names[c_a]
                            if dict_expr is None:
                                actual_record_t = actual_a.type_val
                                if isinstance(actual_a, TypedRecord):
                                    actual_record_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in actual_a.fields))
                                if isinstance(actual_record_t, QRecordType):
                                    d_name = self.record_ctx.offset_dict_instance_name(pt, actual_record_t)
                                    dict_expr = f"&{d_name}"
                            c_args.append(f"(void *){c_a}")
                            c_args.append(dict_expr if dict_expr else "NULL")
                        elif isinstance(pt, QTupleType) and isinstance(actual_a.type_val, QTupleType) and actual_a.type_val != pt:
                            cast_t = self.c_type(pt)
                            c_args.append(f"(({cast_t}){c_a})")
                        elif isinstance(pt, QVariantType) and isinstance(actual_a.type_val, QVariantType) and actual_a.type_val != pt:
                            tmp_v = self.fresh_tmp("_vup")
                            tagmap_name = f"tagmap_{type_to_c_tag(pt)}_{type_to_c_tag(actual_a.type_val)}"
                            lines.append(f"QVariant *{tmp_v} = (QVariant *)quest_alloc(sizeof(QVariant));")
                            lines.append(f"{tmp_v}->descriptor = NULL;")
                            lines.append(f"{tmp_v}->tag = {tagmap_name}[{c_a}->tag];")
                            lines.append(f"{tmp_v}->payload = {c_a}->payload;")
                            c_args.append(tmp_v)
                        elif isinstance(pt, QTypeVar):
                            c_args.append(_qval_wrap(c_a, actual_a.type_val))
                        else:
                            c_args.append(c_a)
                    all_c_args = [f"{clos_val}->env"] + c_args
                    args_str = ", ".join(all_c_args)
                    call_str = f"(({fn_ptr_t})({clos_val}->fn))({args_str})"
                    formal_ret = inner_formal.result_type if isinstance(inner_formal, QFunType) else None
                    if isinstance(formal_ret, QTypeVar) and expr.type_val != formal_ret:
                        call_str = _qval_unwrap(call_str, expr.type_val, self)
                    if expr.type_val == OK_TYPE:
                        lines.append(f"{call_str};")
                        return "((void)0)"
                    if isinstance(expr.type_val, QRecordType):
                        rec_name = self.record_ctx.get_or_create_name(expr.type_val)
                        tmp_res = self.fresh_tmp("_rec_res")
                        lines.append(f"QRecordResult_{rec_name} {tmp_res} = {call_str};")
                        tmp_val = self.fresh_tmp("_rec_val")
                        lines.append(f"void *{tmp_val} = {tmp_res}.val;")
                        self.var_dict_names[tmp_val] = f"{tmp_res}.dict"
                        return tmp_val
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
                elem_t = expr.type_val
                if elem_t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
                    return f"({c_tgt}->data[{c_idx}].i)"
                elif elem_t == REAL_TYPE:
                    return f"({c_tgt}->data[{c_idx}].r)"
                elif elem_t == STRING_TYPE or elem_t == DYNAMIC_TYPE or (isinstance(elem_t, QTypeVar) and elem_t.name == "Dynamic.T") or isinstance(elem_t, (QTupleType, QRecordType, QFunType, QAllType, QArrayType, QVariantType, QOptionType, QExceptionType)):
                    c_elem_t = self.c_type(elem_t)
                    return f"(({c_elem_t})({c_tgt}->data[{c_idx}].p))"
                else:
                    return f"({c_tgt}->data[{c_idx}])"

            case TypedIndexAssign(target=tgt, index=idx, value=val):
                c_tgt = self.emit_val(tgt, lines)
                c_idx = self.emit_val(idx, lines)
                lines.append(f"quest_check_array_bounds({c_tgt}, {c_idx});")
                c_val = self.emit_val(val, lines)
                wrap = _qval_wrap(c_val, val.type_val)
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
                            elif isinstance(symbol.type_val, QRecordType) and not self._is_exact_record_literal(symbol.type_val, val):
                                tgt_type = symbol.type_val
                                tgt_dict_t = self.record_ctx.offset_dict_struct_name(tgt_type)
                                block_lines.append(f"void *{c_ident};")
                                val_c = self.emit_val(val, block_lines)
                                block_lines.append(f"{c_ident} = (void *){val_c};")
                                dict_expr = None
                                if isinstance(val, TypedVar):
                                    dict_expr = self.param_dict_names.get(val.name) or self.var_dict_names.get(val.name)
                                if dict_expr is None and val_c in self.var_dict_names:
                                    dict_expr = self.var_dict_names[val_c]
                                if dict_expr is None:
                                    actual_record_t = val.type_val
                                    if isinstance(val, TypedRecord):
                                        actual_record_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in val.fields))
                                    if isinstance(actual_record_t, QRecordType):
                                        d_name = self.record_ctx.offset_dict_instance_name(tgt_type, actual_record_t)
                                        dict_expr = f"&{d_name}"
                                block_lines.append(f"const {tgt_dict_t} *_dict_{c_ident} = {dict_expr};")
                                self.var_dict_names[name] = f"_dict_{c_ident}"
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
                                val_c = self.emit_val(val, block_lines)
                                tagmap_name = f"tagmap_{type_to_c_tag(symbol.type_val)}_{type_to_c_tag(val.type_val)}"
                                block_lines.append(f"QVariant *{c_ident} = (QVariant *)quest_alloc(sizeof(QVariant));")
                                block_lines.append(f"{c_ident}->descriptor = NULL;")
                                block_lines.append(f"{c_ident}->tag = {tagmap_name}[{val_c}->tag];")
                                block_lines.append(f"{c_ident}->payload = {val_c}->payload;")
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
                    if isinstance(expected_fld_t, (QRecordType, QVariantType)):
                        if elem.type_val != expected_fld_t or (
                            isinstance(elem, TypedVar)
                            and (elem.name in self.param_dict_names or elem.name in self.var_dict_names)
                        ):
                            raise NotImplementedError(
                                "Subtyped record or variant storage in aggregates requires runtime descriptors"
                            )
                    self.emit_to(elem, f"{target_dest}->_{val_idx}", lines)
                    val_idx += 1

            case TypedRecord(fields=flds, type_val=t):
                concrete_t = QRecordType(fields=tuple(QRecordField(name=fld.name, type_val=fld.value.type_val, is_var=fld.is_var) for fld in flds))
                struct_name = self.record_struct_name(concrete_t)
                alloc_expr = f"({struct_name} *)quest_alloc(sizeof({struct_name}))"
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_record")
                    lines.append(f"{struct_name} *{target_dest} = {alloc_expr};")
                else:
                    lines.append(f"{target_dest} = {alloc_expr};")
                lines.append(f"{target_dest}->header.descriptor = NULL;")
                for fld in flds:
                    self.emit_to(fld.value, f"{target_dest}->qf_{fld.name}", lines)

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
                if isinstance(t.element_type, (QRecordType, QVariantType)):
                    for elem in elems:
                        if elem.type_val != t.element_type or (
                            isinstance(elem, TypedVar)
                            and (elem.name in self.param_dict_names or elem.name in self.var_dict_names)
                        ):
                            raise NotImplementedError(
                                "Subtyped record or variant storage in aggregates requires runtime descriptors"
                            )
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
                    wrap = _qval_wrap(c_elem, elem.type_val)
                    lines.append(f"{target_dest}->data[{i}LL] = {wrap};")

            case TypedArrayRep(count=cnt, init_val=init_v, type_val=t):
                if isinstance(t.element_type, (QRecordType, QVariantType)):
                    if init_v.type_val != t.element_type or (
                        isinstance(init_v, TypedVar)
                        and (init_v.name in self.param_dict_names or init_v.name in self.var_dict_names)
                    ):
                        raise NotImplementedError(
                            "Subtyped record or variant storage in aggregates requires runtime descriptors"
                        )
                c_cnt = self.emit_val(cnt, lines)
                c_init = self.emit_val(init_v, lines)
                wrap = _qval_wrap(c_init, init_v.type_val)
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_arr")
                    lines.append(f"QArray *{target_dest};")
                lines.append(f"{target_dest} = quest_array_new({c_cnt}, {wrap});")

            case TypedVariant(tag=tag, payload=payload, type_val=t):
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_var")
                    lines.append(f"QVariant *{target_dest};")
                lines.append(f"{target_dest} = (QVariant *)quest_alloc(sizeof(QVariant));")
                lines.append(f"{target_dest}->descriptor = NULL;")
                tag_idx = 0
                for i, v in enumerate(t.variants):
                    if v.name == tag:
                        tag_idx = i
                        break
                lines.append(f"{target_dest}->tag = {tag_idx}LL;")
                if payload is not None:
                    c_payload = self.emit_val(payload, lines)
                    wrap = _qval_wrap(c_payload, payload.type_val)
                    lines.append(f"{target_dest}->payload = {wrap};")
                else:
                    lines.append(f"{target_dest}->payload = Q_OK_VAL;")

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
                    tag_idx = 0
                    if tag is not None:
                        for i, opt in enumerate(t.options):
                            if opt.name == tag:
                                tag_idx = i
                                break
                    else:
                        tag_idx = ordinal
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
                lines.append(f"switch ({c_tgt}->tag) {{")
                for branch in branches:
                    for tag in branch.tags:
                        tag_idx = 0
                        opt_or_var_field = None
                        if isinstance(target_type, QOptionType):
                            for i, opt in enumerate(target_type.options):
                                if opt.name == tag:
                                    tag_idx = i
                                    opt_or_var_field = opt
                                    break
                        elif isinstance(target_type, QVariantType):
                            for i, v in enumerate(target_type.variants):
                                if v.name == tag:
                                    tag_idx = i
                                    opt_or_var_field = v
                                    break
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
                                    branch_lines.append(f"{b_name}->qf_{f.name} = {c_tgt}->u.{branch.tags[0]}.qf_{f.name};")
                            else:
                                branch_lines.append(f"{b_name} = {c_tgt}->u.{branch.tags[0]}.val;")
                        elif isinstance(target_type, QVariantType):
                            if b_type == INT_TYPE or b_type == BOOL_TYPE or b_type == CHAR_TYPE:
                                branch_lines.append(f"{b_name} = {c_tgt}->payload.i;")
                            elif b_type == REAL_TYPE:
                                branch_lines.append(f"{b_name} = {c_tgt}->payload.r;")
                            elif b_type == STRING_TYPE or isinstance(b_type, (QTupleType, QRecordType, QFunType, QArrayType, QVariantType, QOptionType)):
                                branch_lines.append(f"{b_name} = ({c_b_type})({c_tgt}->payload.p);")
                            else:
                                branch_lines.append(f"{b_name} = {c_tgt}->payload;")

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
                        if b_type == INT_TYPE or b_type == BOOL_TYPE or b_type == CHAR_TYPE:
                            branch_lines.append(f"{b_name} = ({c_b_type})({caught_name}.payload.i);")
                        elif b_type == REAL_TYPE:
                            branch_lines.append(f"{b_name} = {caught_name}.payload.r;")
                        elif b_type == STRING_TYPE or isinstance(b_type, (QTupleType, QRecordType, QFunType, QArrayType, QVariantType, QOptionType, QExceptionType)):
                            branch_lines.append(f"{b_name} = ({c_b_type})({caught_name}.payload.p);")
                        else:
                            branch_lines.append(f"{b_name} = {caught_name}.payload;")
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
