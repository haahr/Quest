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
    if isinstance(ast_kind, ast.KindType):
        return TYPE_KIND

    if isinstance(ast_kind, ast.KindPower):
        bound_type = elaborate_type(ast_kind.bound, env)
        check_kind(bound_type, TYPE_KIND, env)
        return QPowerKind(bound=bound_type)

    if isinstance(ast_kind, ast.KindAll):
        param_kind = elaborate_kind(ast_kind.param_kind, env)
        symbol_id = env.fresh_symbol_id()
        env.push_scope(f"kind_{ast_kind.param_name}")
        try:
            env.current_scope.declare_type(
                TypeSymbol(name=ast_kind.param_name, symbol_id=symbol_id, kind=param_kind)
            )
            body_kind = elaborate_kind(ast_kind.body_kind, env)
        finally:
            env.pop_scope()
        return QAllKind(
            param_name=ast_kind.param_name,
            param_id=symbol_id,
            param_kind=param_kind,
            result_kind=body_kind,
        )

    if isinstance(ast_kind, ast.KindId):
        sym = env.lookup_kind(ast_kind.name)
        if sym is None:
            raise KindError(f"Undefined kind '{ast_kind.name}' at offset {ast_kind.offset}")
        return QKindVar(name=sym.name, symbol_id=sym.symbol_id)

    if isinstance(ast_kind, ast.KindManifest):
        iface_scope = env.lookup_interface(ast_kind.interface_name)
        if iface_scope is None:
            raise KindError(
                f"Undefined interface '{ast_kind.interface_name}' in manifest kind "
                f"'{ast_kind.interface_name}_{ast_kind.kind_name}' at offset {ast_kind.offset}"
            )
        sym = iface_scope.lookup_kind(ast_kind.kind_name)
        if sym is None:
            raise KindError(
                f"Undefined kind '{ast_kind.kind_name}' in interface '{ast_kind.interface_name}' "
                f"at offset {ast_kind.offset}"
            )
        return QKindVar(
            name=f"{ast_kind.interface_name}_{ast_kind.kind_name}",
            symbol_id=sym.symbol_id,
        )

    raise KindError(f"Unsupported AST kind node '{ast_kind}' at offset {getattr(ast_kind, 'offset', 0)}")


# ============================================================================
# 2. Type Elaboration
# ============================================================================

def elaborate_type(ast_type: ast.Type, env: Environment) -> QType:
    """Elaborates a syntactic AST Type into a semantic QType."""
    if isinstance(ast_type, ast.TypePath):
        if len(ast_type.path) == 1:
            name = ast_type.path[0]
            sym = env.lookup_type(name)
            if sym is None:
                raise KindError(f"Undefined type '{name}' at offset {ast_type.offset}")
            if sym.definition is not None:
                return sym.definition
            return QTypeVar(name=sym.name, symbol_id=sym.symbol_id, bound=sym.kind)

        if len(ast_type.path) == 2:
            mod_name, type_name = ast_type.path
            mod_scope = env.lookup_module(mod_name) or env.lookup_interface(mod_name)
            if mod_scope is None:
                raise KindError(
                    f"Undefined module/interface '{mod_name}' in type path "
                    f"'{mod_name}.{type_name}' at offset {ast_type.offset}"
                )
            sym = mod_scope.lookup_type(type_name)
            if sym is None:
                raise KindError(
                    f"Undefined type '{type_name}' in module/interface '{mod_name}' "
                    f"at offset {ast_type.offset}"
                )
            if sym.definition is not None:
                return sym.definition
            return QTypeVar(name=f"{mod_name}.{type_name}", symbol_id=sym.symbol_id, bound=sym.kind)

        raise KindError(f"Multi-segment type paths not supported: '{'.'.join(ast_type.path)}'")

    if isinstance(ast_type, ast.TypeInfix):
        left_type = elaborate_type(ast_type.left, env)
        right_type = elaborate_type(ast_type.right, env)
        if ast_type.op == "->":
            return QFunType(params=(QParam("", left_type),), result_type=right_type)
        raise KindError(f"Unsupported infix type operator '{ast_type.op}' at offset {ast_type.offset}")

    if isinstance(ast_type, ast.TypeTuple):
        elements: list[QType] = []
        env.push_scope("tuple_sig")
        try:
            for f in ast_type.fields:
                field_type = elaborate_type(f.type_sig, env)
                check_kind(field_type, TYPE_KIND, env)
                elements.append(field_type)
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
        return QTupleType(tuple(elements))

    if isinstance(ast_type, ast.TypeRecord):
        fields = tuple(
            QRecordField(
                name=f.name,
                type_val=elaborate_type(f.type_sig, env),
                is_var=f.is_var,
            )
            for f in ast_type.fields
        )
        return QRecordType(fields)

    if isinstance(ast_type, ast.TypeVariant):
        variants = tuple(
            QVariantField(
                name=v.tag,
                type_val=elaborate_type(v.type_sig, env) if v.type_sig else None,
                is_var=v.is_var,
            )
            for v in ast_type.fields
        )
        return QVariantType(variants)

    if isinstance(ast_type, ast.TypeOption):
        options: list[QOptionField] = []
        for opt in ast_type.variants:
            if not opt.payload_sig:
                options.append(QOptionField(name=opt.tag, payload_type=None))
            elif len(opt.payload_sig) == 1:
                payload = elaborate_type(opt.payload_sig[0].type_sig, env)
                options.append(QOptionField(name=opt.tag, payload_type=payload))
            else:
                payload = QTupleType(tuple(elaborate_type(f.type_sig, env) for f in opt.payload_sig))
                options.append(QOptionField(name=opt.tag, payload_type=payload))
        return QOptionType(tuple(options))

    if isinstance(ast_type, ast.TypeFun):
        env.push_scope("type_fun")
        try:
            formals: list[QTypeFormal] = []
            for p in ast_type.params:
                bound_kind = elaborate_kind(p.bound, env)
                symbol_id = env.fresh_symbol_id()
                env.current_scope.declare_type(
                    TypeSymbol(name=p.name, symbol_id=symbol_id, kind=bound_kind)
                )
                formals.append(QTypeFormal(name=p.name, symbol_id=symbol_id, bound=bound_kind))
            body_type = elaborate_type(ast_type.body, env)
            return QTypeFun(params=tuple(formals), body=body_type)
        finally:
            env.pop_scope()

    if isinstance(ast_type, ast.TypeApp):
        ctor = elaborate_type(ast_type.constructor, env)
        args = tuple(elaborate_type(arg, env) for arg in ast_type.arguments)
        return QTypeApp(constructor=ctor, arguments=args)

    if isinstance(ast_type, ast.TypeAll):
        env.push_scope("all_type")
        try:
            quants: list[QQuantifier] = []
            for q in ast_type.quantifiers:
                bound_kind = elaborate_kind(q.bound, env)
                symbol_id = env.fresh_symbol_id()
                env.current_scope.declare_type(
                    TypeSymbol(name=q.name, symbol_id=symbol_id, kind=bound_kind)
                )
                quants.append(QQuantifier(name=q.name, symbol_id=symbol_id, bound=bound_kind))
            body = elaborate_type(ast_type.result_type, env)
            return QAllType(quantifiers=tuple(quants), body=body)
        finally:
            env.pop_scope()

    if isinstance(ast_type, ast.TypeAuto):
        env.push_scope("auto_type")
        try:
            kind_bound = elaborate_kind(ast_type.kind_bound, env)
            param_name = ast_type.type_param or "T"
            symbol_id = env.fresh_symbol_id()
            env.current_scope.declare_type(
                TypeSymbol(name=param_name, symbol_id=symbol_id, kind=kind_bound)
            )
            fields = tuple(
                QRecordField(
                    name=f.name,
                    type_val=elaborate_type(f.type_sig, env),
                    is_var=(f.mode == ast.ParamMode.VAR),
                )
                for f in ast_type.signature
            )
            return QAutoType(
                type_param=param_name,
                symbol_id=symbol_id,
                kind_bound=kind_bound,
                signature=fields,
            )
        finally:
            env.pop_scope()

    if isinstance(ast_type, ast.TypeRec):
        env.push_scope(f"rec_{ast_type.var_name}")
        try:
            bound = elaborate_kind(ast_type.bound, env)
            symbol_id = env.fresh_symbol_id()
            env.current_scope.declare_type(
                TypeSymbol(name=ast_type.var_name, symbol_id=symbol_id, kind=bound)
            )
            body = elaborate_type(ast_type.body, env)
            return QRecType(
                var_name=ast_type.var_name,
                symbol_id=symbol_id,
                bound=bound,
                body=body,
            )
        finally:
            env.pop_scope()

    if isinstance(ast_type, ast.TypeArray):
        return QArrayType(elaborate_type(ast_type.element_type, env))

    if isinstance(ast_type, ast.TypeVar):
        return QVarType(elaborate_type(ast_type.element_type, env))

    if isinstance(ast_type, ast.TypeOut):
        return QOutType(elaborate_type(ast_type.element_type, env))

    if isinstance(ast_type, ast.TypeManifest):
        mod_scope = env.lookup_module(ast_type.module_name) or env.lookup_interface(ast_type.module_name)
        if mod_scope is None:
            raise KindError(
                f"Undefined module/interface '{ast_type.module_name}' in manifest type "
                f"'{ast_type.module_name}_{ast_type.type_name}' at offset {ast_type.offset}"
            )
        sym = mod_scope.lookup_type(ast_type.type_name)
        if sym is None:
            raise KindError(
                f"Undefined type '{ast_type.type_name}' in module/interface '{ast_type.module_name}' "
                f"at offset {ast_type.offset}"
            )
        if sym.definition is not None:
            return sym.definition
        return QTypeVar(
            name=f"{ast_type.module_name}_{ast_type.type_name}",
            symbol_id=sym.symbol_id,
            bound=sym.kind,
        )

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
