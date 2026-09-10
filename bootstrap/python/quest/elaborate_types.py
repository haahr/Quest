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
    QTupleComponent,
    QTupleField,
    QTupleTypeFormal,
    QTupleTypeBinding,
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
    QPathType,
    check_kind,
    check_kind_well_formed,
    check_type_contractive,
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
            with env.scoped(f"kind_{pname}"):
                env.current_scope.declare_type(
                    TypeSymbol(name=pname, symbol_id=symbol_id, kind=param_kind_val)
                )
                body_kind_val = elaborate_kind(bkind, env)
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

            if len(path) >= 2:
                # 1. Module or interface scope lookup
                mod_scope = env.lookup_module(path[0]) or env.lookup_interface(path[0])
                if mod_scope is not None:
                    curr_scope = mod_scope
                    for seg in path[1:-1]:
                        curr_scope = curr_scope.lookup_module(seg) or curr_scope.lookup_interface(seg)
                        if curr_scope is None:
                            raise KindError(
                                f"Undefined module/interface '{seg}' in type path '{'.'.join(path)}' "
                                f"at offset {offset}"
                            )
                    type_name = path[-1]
                    sym = curr_scope.lookup_type(type_name)
                    if sym is None:
                        raise KindError(
                            f"Undefined type '{type_name}' in module/interface '{path[-2]}' "
                            f"at offset {offset}"
                        )
                    if sym.definition is not None:
                        return sym.definition
                    return QTypeVar(name=".".join(path), symbol_id=sym.symbol_id, bound=sym.kind)

                # 2. Value binding lookup for path-dependent types (e.g. x.A or x.y.A)
                val_sym = env.lookup_value(path[0])
                if val_sym is not None:
                    if val_sym.is_var:
                        raise KindError(
                            f"Cannot project type from mutable variable '{path[0]}' at offset {offset}"
                        )
                    curr_type = val_sym.type_val.evaluate_lazily(env)
                    curr_root_name = path[0]
                    curr_root_sym_id = val_sym.symbol_id
                    for seg in path[1:-1]:
                        if not isinstance(curr_type, QTupleType):
                            raise KindError(
                                f"Cannot project field '{seg}' from non-tuple type '{curr_type}' "
                                f"at offset {offset}"
                            )
                        field_comp = curr_type.get_field(seg)
                        if field_comp is None or not isinstance(field_comp, QTupleField):
                            raise KindError(
                                f"Tuple '{curr_root_name}' has no field named '{seg}' at offset {offset}"
                            )
                        curr_type = field_comp.type_val.evaluate_lazily(env)
                        curr_root_name = f"{curr_root_name}.{seg}"

                    type_name = path[-1]
                    if not isinstance(curr_type, QTupleType):
                        raise KindError(
                            f"Cannot project type from non-tuple type '{curr_type}' at offset {offset}"
                        )
                    comp = curr_type.get_field(type_name)
                    if comp is None:
                        raise KindError(
                            f"Tuple '{curr_root_name}' has no component named '{type_name}' at offset {offset}"
                        )
                    if isinstance(comp, QTupleTypeFormal):
                        subst = {
                            f.symbol_id: QPathType(
                                root_name=curr_root_name,
                                root_symbol_id=curr_root_sym_id,
                                field_name=f.name,
                                bound=f.bound,
                            )
                            for f in curr_type.type_formals
                            if f.symbol_id != comp.symbol_id
                        }
                        bound = comp.bound.substitute_types(subst)
                        return QPathType(
                            root_name=curr_root_name,
                            root_symbol_id=curr_root_sym_id,
                            field_name=type_name,
                            bound=bound,
                        )
                    elif isinstance(comp, QTupleTypeBinding):
                        subst = {
                            f.symbol_id: QPathType(
                                root_name=curr_root_name,
                                root_symbol_id=curr_root_sym_id,
                                field_name=f.name,
                                bound=f.bound,
                            )
                            for f in curr_type.type_formals
                        }
                        return comp.type_val.substitute(subst)
                    else:
                        raise KindError(
                            f"Component '{type_name}' of tuple '{curr_root_name}' is a value field, "
                            f"not a type component, at offset {offset}"
                        )

                raise KindError(
                    f"Undefined identifier '{path[0]}' in type path '{'.'.join(path)}' at offset {offset}"
                )

        case ast.TypeInfix(left=left, op=op, right=right, offset=offset):
            left_type = elaborate_type(left, env)
            right_type = elaborate_type(right, env)
            if op == "->":
                return QFunType(params=(QParam("", left_type),), result_type=right_type)
            raise KindError(f"Unsupported infix type operator '{op}' at offset {offset}")

        case ast.TypeTuple(fields=tup_fields):
            components: list[QTupleComponent] = []
            with env.scoped("tuple_sig"):
                for f in tup_fields:
                    match f:
                        case ast.TypeFormal(name=name, bound=bound):
                            if not name or name == "_":
                                raise KindError(
                                    "Type formal in tuple signature must have an identifier",
                                    offset=getattr(f, "offset", None),
                                )
                            bound_kind = elaborate_kind(bound, env)
                            symbol_id = env.fresh_symbol_id()
                            env.current_scope.declare_type(
                                TypeSymbol(name=name, symbol_id=symbol_id, kind=bound_kind)
                            )
                            components.append(
                                QTupleTypeFormal(name=name, symbol_id=symbol_id, bound=bound_kind)
                            )

                        case ast.FieldSig(name=name, type_sig=type_sig, mode=mode):
                            field_type = elaborate_type(type_sig, env)
                            check_kind(field_type, TYPE_KIND, env)
                            components.append(
                                QTupleField(name=name if name else None, type_val=field_type)
                            )
                            if name:
                                env.current_scope.declare_value(
                                    ValueSymbol(
                                        name=name,
                                        type_val=field_type,
                                        is_var=(mode == ast.ParamMode.VAR),
                                        is_out=(mode == ast.ParamMode.OUT),
                                    )
                                )

                        case ast.LetTypeBinding(name=name, type_val=type_val, bound=bound):
                            bound_kind = elaborate_kind(bound, env) if bound else None
                            m_type = elaborate_type(type_val, env)
                            if bound_kind:
                                check_kind(m_type, bound_kind, env)
                            else:
                                check_kind(m_type, TYPE_KIND, env)
                            symbol_id = env.fresh_symbol_id()
                            env.current_scope.declare_type(
                                TypeSymbol(
                                    name=name,
                                    symbol_id=symbol_id,
                                    kind=bound_kind or TYPE_KIND,
                                    definition=m_type,
                                )
                            )
                            components.append(
                                QTupleTypeBinding(name=name, type_val=m_type, bound=bound_kind)
                            )

                        case ast.DefKindBinding(name=name, kind_val=kind_val):
                            k_val = elaborate_kind(kind_val, env)
                            env.current_scope.declare_kind(
                                KindSymbol(name=name, symbol_id=env.fresh_symbol_id(), kind=k_val)
                            )

                        case _:
                            raise KindError(f"Unexpected item in tuple signature: {f}")
            return QTupleType(tuple(components))

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
            variants: list[QVariantField] = []
            seen_tags: set[str] = set()
            for v in var_fields:
                tag = getattr(v, "tag", getattr(v, "name", ""))
                if tag in seen_tags:
                    raise KindError(f"Duplicate variant tag '{tag}'", offset=getattr(v, "offset", None))
                seen_tags.add(tag)
                variants.append(
                    QVariantField(
                        name=tag,
                        type_val=elaborate_type(v.type_sig, env) if v.type_sig else None,
                        is_var=v.is_var,
                    )
                )
            return QVariantType(tuple(variants))

        case ast.TypeOption(variants=opt_variants):
            options: list[QOptionField] = []
            for opt in opt_variants:
                if not opt.payload_sig:
                    options.append(QOptionField(name=opt.tag, payload_type=None))
                else:
                    fields = tuple(
                        QTupleField(
                            name=f.name if f.name else None,
                            type_val=elaborate_type(f.type_sig, env),
                        )
                        for f in opt.payload_sig
                    )
                    payload = QTupleType(fields)
                    options.append(QOptionField(name=opt.tag, payload_type=payload))
            return QOptionType(tuple(options))

        case ast.TypeFun(params=params, body=body):
            with env.scoped("type_fun"):
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

        case ast.TypeApp(constructor=ctor, arguments=arguments):
            ctor_type = elaborate_type(ctor, env)
            args = tuple(elaborate_type(arg, env) for arg in arguments)
            return QTypeApp(constructor=ctor_type, arguments=args)

        case ast.TypeAll(quantifiers=quants_ast, result_type=res_type):
            with env.scoped("all_type"):
                quants: list[QQuantifier] = []
                val_params: list[QParam] = []
                for q in quants_ast:
                    bound_kind = elaborate_kind(q.bound, env)
                    if isinstance(bound_kind, QPowerKind):
                        # Value formal parameter: x : T (represented via Power(T))
                        val_type = bound_kind.bound
                        is_var = getattr(q, "mode", ast.ParamMode.VALUE) == ast.ParamMode.VAR
                        is_out = getattr(q, "mode", ast.ParamMode.VALUE) == ast.ParamMode.OUT
                        val_params.append(
                            QParam(name=q.name, type_val=val_type, is_var=is_var, is_out=is_out)
                        )
                        env.current_scope.declare_value(
                            ValueSymbol(name=q.name, type_val=val_type, is_var=is_var)
                        )
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

        case ast.TypeAuto(type_param=tparam, kind_bound=kbound, signature=signature):
            with env.scoped("auto_type"):
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

        case ast.TypeRec(var_name=vname, bound=bound_ast, body=body_ast):
            with env.scoped(f"rec_{vname}"):
                bound = elaborate_kind(bound_ast, env)
                symbol_id = env.fresh_symbol_id()
                env.current_scope.declare_type(
                    TypeSymbol(name=vname, symbol_id=symbol_id, kind=bound)
                )
                body = elaborate_type(body_ast, env)
                check_type_contractive(
                    body,
                    {symbol_id},
                    var_name=vname,
                    offset=getattr(body_ast, "offset", 0),
                    env=env,
                )
                return QRecType(
                    var_name=vname,
                    symbol_id=symbol_id,
                    bound=bound,
                    body=body,
                )

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
    if binding.bound:
        declared_bound: Optional[QKind] = elaborate_kind(binding.bound, env)
        check_kind_well_formed(declared_bound, env)
    else:
        declared_bound = None

    if binding.params:
        # Desugar parameterized type definition Let T(X::K): ResultKind = Body into TypeFun
        target_bound = declared_bound if declared_bound is not None else TYPE_KIND
        with env.scoped(f"type_fun_{binding.name}"):
            formals: list[QTypeFormal] = []
            for p in binding.params:
                p_bound = elaborate_kind(p.bound, env)
                p_id = env.fresh_symbol_id()
                env.current_scope.declare_type(TypeSymbol(name=p.name, symbol_id=p_id, kind=p_bound))
                formals.append(QTypeFormal(name=p.name, symbol_id=p_id, bound=p_bound))
            body_type = elaborate_type(binding.type_val, env)
            check_kind(body_type, target_bound, env)
            qtype_val = QTypeFun(params=tuple(formals), body=body_type)

        # Fold parameter kinds into overall operator kind telescope
        overall_kind: QKind = target_bound
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
        target_bound = declared_bound if declared_bound is not None else TYPE_KIND
        with env.scoped(f"rec_{binding.name}"):
            env.current_scope.declare_type(TypeSymbol(name=binding.name, symbol_id=symbol_id, kind=target_bound))
            body_type = elaborate_type(binding.type_val, env)
            check_kind(body_type, target_bound, env)
            check_type_contractive(
                body_type,
                {symbol_id},
                var_name=binding.name,
                offset=binding.offset,
                env=env,
            )
            qtype_val = QRecType(var_name=binding.name, symbol_id=symbol_id, bound=target_bound, body=body_type)
        bound_kind = target_bound
    else:
        qtype_val = elaborate_type(binding.type_val, env)
        if declared_bound is not None:
            check_kind(qtype_val, declared_bound, env)
            bound_kind = declared_bound
        else:
            bound_kind = synth_kind(qtype_val, env)

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
    with env.scoped("mutual_rec_group"):
        for name, sym_id, bound, _ in pre_symbols:
            env.current_scope.declare_type(TypeSymbol(name=name, symbol_id=sym_id, kind=bound))

        # 3. Elaborate each body in the mutually recursive scope
        all_group_ids = {sym_id for _, sym_id, _, _ in pre_symbols}
        group_entries: list[tuple[str, int, QKind, QType]] = []
        for name, sym_id, bound, b in pre_symbols:
            body_type = elaborate_type(b.type_val, env)
            check_kind(body_type, bound, env)
            check_type_contractive(
                body_type,
                all_group_ids,
                var_name=name,
                offset=b.offset,
                env=env,
            )
            group_entries.append((name, sym_id, bound, body_type))

    # 4. Construct QRecGroupType for each binding and declare in the enclosing scope
    group_tuple = tuple(group_entries)
    declared_symbols: list[TypeSymbol] = []
    for idx, (name, sym_id, bound, _) in enumerate(group_entries):
        rec_group_type = QRecGroupType(bindings=group_tuple, active_index=idx)
        sym = TypeSymbol(name=name, symbol_id=sym_id, kind=bound, definition=rec_group_type)
        declared_symbols.append(env.current_scope.declare_type(sym))

    return declared_symbols
