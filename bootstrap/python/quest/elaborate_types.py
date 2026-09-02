"""Quest Syntactic AST to Semantic Type and Kind Elaboration."""

from __future__ import annotations

from typing import Any, Optional, Union

import quest.ast as ast
from quest.types import (
    TYPE_KIND,
    KindError,
    QKind,
    QTypeKind,
    QPowerKind,
    QAllKind,
    QKindVar,
    QType,
    QTupleField,
    QTupleType,
    QRecordField,
    QRecordType,
    QVariantField,
    QVariantType,
    QOptionField,
    QOptionType,
    QParam,
    QFunType,
    QVarType,
    QArrayType,
    QOutType,
    QQuantifier,
    QAllType,
    QAutoType,
    QTypeFormal,
    QTypeFun,
    QTypeApp,
    QRecType,
    QRecGroupType,
    QTypeVar,
    QAbstractType,
    check_kind,
    check_kind_well_formed,
    synth_kind,
)
from quest.env import (
    Environment,
    KindSymbol,
    Scope,
    TypeSymbol,
    ValueSymbol,
)


# ============================================================================
# 1. Kind Elaboration
# ============================================================================

def elaborate_kind(ast_kind: ast.Kind, env: Environment) -> QKind:
    """Elaborates a syntactic AST Kind into a semantic QKind."""
    match ast_kind:
        case ast.KindType():
            return TYPE_KIND

        case ast.KindPower(bound=bound):
            bound_type = elaborate_type(bound, env)
            check_kind(bound_type, TYPE_KIND, env)
            return QPowerKind(bound=bound_type)

        case ast.KindAll(param_name=pname, param_kind=pkind, body_kind=bkind):
            param_kind_val = elaborate_kind(pkind, env)
            symbol_id = env.fresh_symbol_id()
            env.push_scope(f"kind_{pname}")
            try:
                env.current_scope.declare_type(
                    TypeSymbol(name=pname, symbol_id=symbol_id, kind=param_kind_val)
                )
                body_kind_val = elaborate_kind(bkind, env)
            finally:
                env.pop_scope()
            return QAllKind(
                param_name=pname,
                param_id=symbol_id,
                param_kind=param_kind_val,
                result_kind=body_kind_val,
            )

        case ast.KindId(name=name, offset=offset):
            sym = env.lookup_kind(name)
            if sym is None:
                raise KindError(f"Undefined kind '{name}' at offset {offset}")
            return QKindVar(name=sym.name, symbol_id=sym.symbol_id)

        case ast.KindManifest(interface_name=iface_name, kind_name=kname, offset=offset):
            interface_scope = env.lookup_interface(iface_name)
            if interface_scope is None:
                raise KindError(
                    f"Undefined interface '{iface_name}' in manifest kind "
                    f"'{iface_name}_{kname}' at offset {offset}"
                )
            sym = interface_scope.lookup_kind(kname)
            if sym is None:
                raise KindError(
                    f"Undefined kind '{kname}' in interface '{iface_name}' "
                    f"at offset {offset}"
                )
            return QKindVar(
                name=f"{iface_name}_{kname}",
                symbol_id=sym.symbol_id,
            )

        case _:
            raise KindError(f"Unsupported AST kind node '{ast_kind}' at offset {getattr(ast_kind, 'offset', 0)}")


# ============================================================================
# 2. Type Elaboration
# ============================================================================

def elaborate_type(ast_type: ast.Type, env: Environment) -> QType:
    """Elaborates a syntactic AST Type into a semantic QType."""
    match ast_type:
        case ast.TypePath(path=path, offset=offset):
            if len(path) == 1:
                name = path[0]
                sym = env.lookup_type(name)
                if sym is None:
                    raise KindError(f"Undefined type '{name}' at offset {offset}")
                if sym.definition is not None:
                    return sym.definition
                return QTypeVar(name=sym.name, symbol_id=sym.symbol_id, bound=sym.kind)

            if len(path) == 2:
                mod_name, type_name = path
                mod_scope = env.lookup_module(mod_name) or env.lookup_interface(mod_name)
                if mod_scope is None:
                    raise KindError(
                        f"Undefined module/interface '{mod_name}' in type path "
                        f"'{mod_name}.{type_name}' at offset {offset}"
                    )
                sym = mod_scope.lookup_type(type_name)
                if sym is None:
                    raise KindError(
                        f"Undefined type '{type_name}' in module/interface '{mod_name}' "
                        f"at offset {offset}"
                    )
                if sym.definition is not None:
                    return sym.definition
                return QTypeVar(name=f"{mod_name}.{type_name}", symbol_id=sym.symbol_id, bound=sym.kind)

            raise KindError(f"Multi-segment type paths not supported: '{'.'.join(path)}'")

        case ast.TypeInfix(left=left, op=op, right=right, offset=offset):
            left_type = elaborate_type(left, env)
            right_type = elaborate_type(right, env)
            if op == "->":
                return QFunType(params=(QParam("", left_type),), result_type=right_type)
            raise KindError(f"Unsupported infix type operator '{op}' at offset {offset}")

        case ast.TypeTuple(fields=tup_fields):
            fields: list[QTupleField] = []
            env.push_scope("tuple_sig")
            try:
                for f in tup_fields:
                    field_type = elaborate_type(f.type_sig, env)
                    check_kind(field_type, TYPE_KIND, env)
                    fields.append(QTupleField(name=f.name if f.name else None, type_val=field_type))
                    if f.name:
                        env.current_scope.declare_value(
                            ValueSymbol(
                                name=f.name,
                                type_val=field_type,
                                is_var=(f.mode == ast.ParamMode.VAR),
                                is_out=(f.mode == ast.ParamMode.OUT),
                            )
                        )
            finally:
                env.pop_scope()
            return QTupleType(tuple(fields))

        case ast.TypeRecord(fields=rec_fields):
            fields = tuple(
                QRecordField(
                    name=f.name,
                    type_val=elaborate_type(f.type_sig, env),
                    is_var=f.is_var,
                )
                for f in rec_fields
            )
            return QRecordType(fields)

        case ast.TypeVariant(fields=var_fields):
            variants = tuple(
                QVariantField(
                    name=v.tag,
                    type_val=elaborate_type(v.type_sig, env) if v.type_sig else None,
                    is_var=v.is_var,
                )
                for v in var_fields
            )
            return QVariantType(variants)

        case ast.TypeOption(variants=opt_variants):
            options: list[QOptionField] = []
            for opt in opt_variants:
                if not opt.payload_sig:
                    options.append(QOptionField(name=opt.tag, payload_type=None))
                elif len(opt.payload_sig) == 1:
                    payload = elaborate_type(opt.payload_sig[0].type_sig, env)
                    options.append(QOptionField(name=opt.tag, payload_type=payload))
                else:
                    payload = QTupleType(tuple(elaborate_type(f.type_sig, env) for f in opt.payload_sig))
                    options.append(QOptionField(name=opt.tag, payload_type=payload))
            return QOptionType(tuple(options))

        case ast.TypeFun(params=params, body=body):
            env.push_scope("type_fun")
            try:
                formals: list[QTypeFormal] = []
                for p in params:
                    bound_kind = elaborate_kind(p.bound, env)
                    symbol_id = env.fresh_symbol_id()
                    env.current_scope.declare_type(
                        TypeSymbol(name=p.name, symbol_id=symbol_id, kind=bound_kind)
                    )
                    formals.append(QTypeFormal(name=p.name, symbol_id=symbol_id, bound=bound_kind))
                body_type = elaborate_type(body, env)
                return QTypeFun(params=tuple(formals), body=body_type)
            finally:
                env.pop_scope()

        case ast.TypeApp(constructor=ctor, arguments=arguments):
            ctor_type = elaborate_type(ctor, env)
            args = tuple(elaborate_type(arg, env) for arg in arguments)
            return QTypeApp(constructor=ctor_type, arguments=args)

        case ast.TypeAll(quantifiers=quants_ast, result_type=res_type):
            env.push_scope("all_type")
            try:
                quants: list[QQuantifier] = []
                val_params: list[QParam] = []
                for q in quants_ast:
                    bound_kind = elaborate_kind(q.bound, env)
                    if isinstance(bound_kind, QPowerKind):
                        # Value formal parameter: x : T (represented via Power(T))
                        val_type = bound_kind.bound
                        val_params.append(QParam(name=q.name, type_val=val_type))
                        env.current_scope.declare_value(ValueSymbol(name=q.name, type_val=val_type))
                    else:
                        symbol_id = env.fresh_symbol_id()
                        env.current_scope.declare_type(
                            TypeSymbol(name=q.name, symbol_id=symbol_id, kind=bound_kind)
                        )
                        quants.append(QQuantifier(name=q.name, symbol_id=symbol_id, bound=bound_kind))
                body = elaborate_type(res_type, env)
                fn_body: QType = QFunType(params=tuple(val_params), result_type=body) if val_params else body
                if quants:
                    return QAllType(quantifiers=tuple(quants), body=fn_body)
                return fn_body
            finally:
                env.pop_scope()

        case ast.TypeAuto(type_param=tparam, kind_bound=kbound, signature=signature):
            env.push_scope("auto_type")
            try:
                kind_bound_val = elaborate_kind(kbound, env)
                param_name = tparam or "T"
                symbol_id = env.fresh_symbol_id()
                env.current_scope.declare_type(
                    TypeSymbol(name=param_name, symbol_id=symbol_id, kind=kind_bound_val)
                )
                fields = tuple(
                    QRecordField(
                        name=f.name,
                        type_val=elaborate_type(f.type_sig, env),
                        is_var=(f.mode == ast.ParamMode.VAR),
                    )
                    for f in signature
                )
                return QAutoType(
                    type_param=param_name,
                    symbol_id=symbol_id,
                    kind_bound=kind_bound_val,
                    signature=fields,
                )
            finally:
                env.pop_scope()

        case ast.TypeRec(var_name=vname, bound=bound_ast, body=body_ast):
            env.push_scope(f"rec_{vname}")
            try:
                bound = elaborate_kind(bound_ast, env)
                symbol_id = env.fresh_symbol_id()
                env.current_scope.declare_type(
                    TypeSymbol(name=vname, symbol_id=symbol_id, kind=bound)
                )
                body = elaborate_type(body_ast, env)
                return QRecType(
                    var_name=vname,
                    symbol_id=symbol_id,
                    bound=bound,
                    body=body,
                )
            finally:
                env.pop_scope()

        case ast.TypeArray(element_type=elem):
            return QArrayType(elaborate_type(elem, env))

        case ast.TypeVar(element_type=elem):
            return QVarType(elaborate_type(elem, env))

        case ast.TypeOut(element_type=elem):
            return QOutType(elaborate_type(elem, env))

        case ast.TypeManifest(module_name=mname, type_name=tname, offset=offset):
            mod_scope = env.lookup_module(mname) or env.lookup_interface(mname)
            if mod_scope is None:
                raise KindError(
                    f"Undefined module/interface '{mname}' in manifest type "
                    f"'{mname}_{tname}' at offset {offset}"
                )
            sym = mod_scope.lookup_type(tname)
            if sym is None:
                raise KindError(
                    f"Undefined type '{tname}' in module/interface '{mname}' "
                    f"at offset {offset}"
                )
            if sym.definition is not None:
                return sym.definition
            return QTypeVar(
                name=f"{mname}_{tname}",
                symbol_id=sym.symbol_id,
                bound=sym.kind,
            )

        case _:
            raise KindError(f"Unsupported AST type node '{ast_type}' at offset {getattr(ast_type, 'offset', 0)}")


# ============================================================================
# 3. Type and Kind Declarations Elaboration
# ============================================================================

def elaborate_kind_binding(binding: ast.DefKindBinding, env: Environment) -> KindSymbol:
    """Elaborates a DEF K = Kind declaration and registers it in the current scope."""
    kind_val = elaborate_kind(binding.kind_val, env)
    check_kind_well_formed(kind_val, env)
    symbol = KindSymbol(name=binding.name, symbol_id=env.fresh_symbol_id(), kind=kind_val)
    return env.current_scope.declare_kind(symbol)


def elaborate_type_binding(
    binding: Union[ast.LetTypeBinding, ast.DefTypeBinding],
    env: Environment,
) -> TypeSymbol:
    """Elaborates a single Let T = Type or Def T = Type declaration."""
    symbol_id = env.fresh_symbol_id()
    declared_bound = elaborate_kind(binding.bound, env) if binding.bound else TYPE_KIND
    check_kind_well_formed(declared_bound, env)

    if binding.params:
        # Desugar parameterized type definition Let T(X::K): ResultKind = Body into TypeFun
        env.push_scope(f"type_fun_{binding.name}")
        try:
            formals: list[QTypeFormal] = []
            for p in binding.params:
                p_bound = elaborate_kind(p.bound, env)
                p_id = env.fresh_symbol_id()
                env.current_scope.declare_type(TypeSymbol(name=p.name, symbol_id=p_id, kind=p_bound))
                formals.append(QTypeFormal(name=p.name, symbol_id=p_id, bound=p_bound))
            body_type = elaborate_type(binding.type_val, env)
            check_kind(body_type, declared_bound, env)
            qtype_val = QTypeFun(params=tuple(formals), body=body_type)
        finally:
            env.pop_scope()

        # Fold parameter kinds into overall operator kind telescope
        overall_kind: QKind = declared_bound
        for formal in reversed(formals):
            overall_kind = QAllKind(
                param_name=formal.name,
                param_id=formal.symbol_id,
                param_kind=formal.bound,
                result_kind=overall_kind,
            )
        bound_kind = overall_kind
    elif binding.is_rec:
        # Single recursive type definition Let Rec T = Body
        env.push_scope(f"rec_{binding.name}")
        try:
            env.current_scope.declare_type(TypeSymbol(name=binding.name, symbol_id=symbol_id, kind=declared_bound))
            body_type = elaborate_type(binding.type_val, env)
            check_kind(body_type, declared_bound, env)
            qtype_val = QRecType(var_name=binding.name, symbol_id=symbol_id, bound=declared_bound, body=body_type)
        finally:
            env.pop_scope()
        bound_kind = declared_bound
    else:
        qtype_val = elaborate_type(binding.type_val, env)
        check_kind(qtype_val, declared_bound, env)
        bound_kind = declared_bound

    # Validate overall kind conformance
    check_kind(qtype_val, bound_kind, env)
    symbol = TypeSymbol(name=binding.name, symbol_id=symbol_id, kind=bound_kind, definition=qtype_val)
    return env.current_scope.declare_type(symbol)


def elaborate_mutual_rec_type_group(
    bindings: list[Union[ast.LetTypeBinding, ast.DefTypeBinding]],
    env: Environment,
) -> list[TypeSymbol]:
    """Elaborates a mutually recursive group of type declarations (Let Rec T1 = ... and T2 = ...)."""
    # 1. Allocate symbol IDs and declared bounds for all bindings
    pre_symbols: list[tuple[str, int, QKind, Union[ast.LetTypeBinding, ast.DefTypeBinding]]] = []
    for b in bindings:
        sym_id = env.fresh_symbol_id()
        bound = elaborate_kind(b.bound, env) if b.bound else TYPE_KIND
        check_kind_well_formed(bound, env)
        pre_symbols.append((b.name, sym_id, bound, b))

    # 2. Push temporary scope and register all abstract type symbols
    env.push_scope("mutual_rec_group")
    try:
        for name, sym_id, bound, _ in pre_symbols:
            env.current_scope.declare_type(TypeSymbol(name=name, symbol_id=sym_id, kind=bound))

        # 3. Elaborate each body in the mutually recursive scope
        group_entries: list[tuple[str, int, QKind, QType]] = []
        for name, sym_id, bound, b in pre_symbols:
            body_type = elaborate_type(b.type_val, env)
            check_kind(body_type, bound, env)
            group_entries.append((name, sym_id, bound, body_type))
    finally:
        env.pop_scope()

    # 4. Construct QRecGroupType for each binding and declare in the enclosing scope
    group_tuple = tuple(group_entries)
    declared_symbols: list[TypeSymbol] = []
    for idx, (name, sym_id, bound, _) in enumerate(group_entries):
        rec_group_type = QRecGroupType(bindings=group_tuple, active_index=idx)
        sym = TypeSymbol(name=name, symbol_id=sym_id, kind=bound, definition=rec_group_type)
        declared_symbols.append(env.current_scope.declare_type(sym))

    return declared_symbols
