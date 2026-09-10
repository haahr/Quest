"""Quest Module, Interface, and Import Elaboration (Phase 6).

Implements Cardelli's module system for Quest:
- Interface declarations with type formals, manifest types, and value signatures.
- Module definitions with conformance checking (type equality, subkinding, subtyping).
- Information hiding via opaque type variables for abstract interface types.
- Top-level and module-level import resolution with BuiltinModuleRegistry integration.
"""

from __future__ import annotations

from typing import Callable, Optional

import quest.ast as ast
from quest.builtins import BuiltinModuleRegistry
from quest.diagnostics import QuestTypeError
from quest.elaborate_types import (
    elaborate_kind,
    elaborate_kind_binding,
    elaborate_type,
)
from quest.env import (
    Environment,
    Scope,
    TypeSymbol,
    ValueSymbol,
)
from quest.typed_ast import (
    TypedBinding,
    TypedImport,
    TypedImportItem,
    TypedInterface,
    TypedModule,
)
from quest.types import (
    TYPE_KIND,
    QRecordField,
    QRecordType,
    QType,
    QTypeVar,
    is_subkind,
    is_subtype,
    is_type_equal,
)


def elaborate_interface(decl: ast.InterfaceDecl, env: Environment) -> TypedInterface:
    """Elaborates an interface declaration into a specification scope and TypedInterface."""
    interface_scope = Scope(name=f"interface_{decl.name}", parent=env.current_scope)

    # 1. Resolve imports into interface_scope
    for imp in decl.imports:
        source_interface_scope = env.lookup_interface(imp.interface_name)
        if source_interface_scope is None:
            source_interface_scope = BuiltinModuleRegistry.get_interface(imp.interface_name, env)
            if source_interface_scope is not None:
                env.register_interface(imp.interface_name, source_interface_scope)
        if source_interface_scope is None:
            raise QuestTypeError(
                f"Undefined interface '{imp.interface_name}' in import of interface '{decl.name}'",
                offset=decl.offset,
            )
        if not imp.names:
            for type_name, type_sym in source_interface_scope.types.items():
                interface_scope.declare_type(type_sym)
            for kind_name, kind_sym in source_interface_scope.kinds.items():
                interface_scope.declare_kind(kind_sym)
        else:
            for name in imp.names:
                type_symbol = source_interface_scope.lookup_type_local(name)
                if type_symbol is not None:
                    interface_scope.declare_type(type_symbol)
                    continue
                value_symbol = source_interface_scope.lookup_value_local(name)
                if value_symbol is not None:
                    interface_scope.declare_value(value_symbol)
                    continue
                kind_symbol = source_interface_scope.lookup_kind_local(name)
                if kind_symbol is not None:
                    interface_scope.declare_kind(kind_symbol)
                    continue
                mod_type = BuiltinModuleRegistry.get_module_type(name, env)
                if mod_type is None:
                    mod_type = BuiltinModuleRegistry._build_record_type_from_scope(
                        source_interface_scope
                    )
                env.register_module(name, source_interface_scope)
                interface_scope.declare_value(ValueSymbol(name=name, type_val=mod_type))

    # 2. Elaborate signatures in a child scope of the interface
    saved_scope = env.current_scope
    env.current_scope = interface_scope
    try:
        for sig in decl.signatures:
            if isinstance(sig, ast.TypeFormal):
                bound_kind = elaborate_kind(sig.bound, env) if sig.bound else TYPE_KIND
                symbol_id = env.fresh_symbol_id()
                type_symbol = TypeSymbol(name=sig.name, symbol_id=symbol_id, kind=bound_kind, definition=None)
                interface_scope.declare_type(type_symbol)

            elif isinstance(sig, ast.LetTypeBinding):
                bound_kind = elaborate_kind(sig.bound, env) if sig.bound is not None else None
                concrete_def = elaborate_type(sig.type_val, env)
                symbol_id = env.fresh_symbol_id()
                type_symbol = TypeSymbol(
                    name=sig.name,
                    symbol_id=symbol_id,
                    kind=bound_kind,
                    definition=concrete_def,
                )
                interface_scope.declare_type(type_symbol)

            elif isinstance(sig, ast.FieldSig):
                if sig.name:
                    val_type = elaborate_type(sig.type_sig, env)
                    val_symbol = ValueSymbol(
                        name=sig.name,
                        type_val=val_type,
                        is_var=(sig.mode == ast.ParamMode.VAR),
                        is_out=(sig.mode == ast.ParamMode.OUT),
                    )
                    interface_scope.declare_value(val_symbol)

            elif isinstance(sig, ast.DefKindBinding):
                kind_symbol = elaborate_kind_binding(sig, env)
                interface_scope.declare_kind(kind_symbol)
    finally:
        env.current_scope = saved_scope

    env.register_interface(decl.name, interface_scope)
    return TypedInterface(name=decl.name, signatures=(), scope=interface_scope, offset=decl.offset)


def elaborate_module(
    decl: ast.ModuleDecl,
    env: Environment,
    binding_elaborator: Optional[Callable[[ast.BindingNode, Environment, int], TypedBinding]] = None,
) -> TypedModule:
    """Elaborates and typechecks a module against its interface, enforcing information hiding."""
    target_interface_scope = env.lookup_interface(decl.interface_name)
    if target_interface_scope is None:
        raise QuestTypeError(
            f"Undefined interface '{decl.interface_name}' for module '{decl.name}'",
            offset=decl.offset,
        )

    module_internal_scope = Scope(name=f"module_internal_{decl.name}", parent=env.base_scope)

    # 1. Resolve imports into module_internal_scope
    for imp in decl.imports:
        source_interface_scope = env.lookup_interface(imp.interface_name)
        if source_interface_scope is None:
            source_interface_scope = BuiltinModuleRegistry.get_interface(imp.interface_name, env)
            if source_interface_scope is not None:
                env.register_interface(imp.interface_name, source_interface_scope)
        if source_interface_scope is None:
            raise QuestTypeError(
                f"Undefined interface '{imp.interface_name}' in import of module '{decl.name}'",
                offset=decl.offset,
            )
        if not imp.names:
            for type_name, type_sym in source_interface_scope.types.items():
                module_internal_scope.declare_type(type_sym)
            for kind_name, kind_sym in source_interface_scope.kinds.items():
                module_internal_scope.declare_kind(kind_sym)
        else:
            for name in imp.names:
                type_symbol = source_interface_scope.lookup_type_local(name)
                if type_symbol is not None:
                    module_internal_scope.declare_type(type_symbol)
                    continue
                value_symbol = source_interface_scope.lookup_value_local(name)
                if value_symbol is not None:
                    module_internal_scope.declare_value(value_symbol)
                    continue
                kind_symbol = source_interface_scope.lookup_kind_local(name)
                if kind_symbol is not None:
                    module_internal_scope.declare_kind(kind_symbol)
                    continue
                mod_type = BuiltinModuleRegistry.get_module_type(name, env)
                if mod_type is None:
                    mod_type = BuiltinModuleRegistry._build_record_type_from_scope(
                        source_interface_scope
                    )
                env.register_module(name, source_interface_scope)
                module_internal_scope.declare_value(ValueSymbol(name=name, type_val=mod_type))

    # 2. Elaborate module internal bindings
    if binding_elaborator is None:
        from quest.typechecker import _elaborate_binding
        binding_elaborator = _elaborate_binding

    saved_scope = env.current_scope
    env.current_scope = module_internal_scope
    typed_bindings: list[TypedBinding] = []
    try:
        for b in decl.bindings:
            typed_b = binding_elaborator(b, env, 0)
            typed_bindings.append(typed_b)

        # 3. Conformance checking against interface
        type_subst: dict[int, QType] = {}
        for type_name, interface_type_symbol in target_interface_scope.types.items():
            mod_type_symbol = module_internal_scope.lookup_type_local(type_name)
            if mod_type_symbol is None:
                raise QuestTypeError(
                    f"Module '{decl.name}' does not implement required type '{type_name}' "
                    f"from interface '{decl.interface_name}'",
                    offset=decl.offset,
                )
            if interface_type_symbol.definition is not None:
                mod_def = (
                    mod_type_symbol.definition
                    if mod_type_symbol.definition is not None
                    else mod_type_symbol.type_val
                )
                if not is_type_equal(mod_def, interface_type_symbol.definition, env):
                    raise QuestTypeError(
                        f"Module '{decl.name}' defines manifest type '{type_name}' "
                        f"incompatibly with interface '{decl.interface_name}'",
                        offset=decl.offset,
                    )
            if interface_type_symbol.kind is not None and mod_type_symbol.kind is not None:
                if not is_subkind(mod_type_symbol.kind, interface_type_symbol.kind, env):
                    raise QuestTypeError(
                        f"Type '{type_name}' in module '{decl.name}' does not satisfy "
                        f"kind bound from interface '{decl.interface_name}'",
                        offset=decl.offset,
                    )
            if interface_type_symbol.definition is None:
                concrete_def = (
                    mod_type_symbol.definition
                    if mod_type_symbol.definition is not None
                    else mod_type_symbol.type_val
                )
                type_subst[interface_type_symbol.symbol_id] = concrete_def

        for val_name, interface_val_symbol in target_interface_scope.values.items():
            mod_val_symbol = module_internal_scope.lookup_value_local(val_name)
            if mod_val_symbol is None:
                raise QuestTypeError(
                    f"Module '{decl.name}' does not implement required value '{val_name}' "
                    f"from interface '{decl.interface_name}'",
                    offset=decl.offset,
                )
            expected_type = interface_val_symbol.type_val.substitute(type_subst)
            if not is_subtype(mod_val_symbol.type_val, expected_type, env):
                raise QuestTypeError(
                    f"Value '{val_name}' in module '{decl.name}' has type '{mod_val_symbol.type_val}', "
                    f"which is not a subtype of interface signature '{expected_type}'",
                    offset=decl.offset,
                )
    finally:
        env.current_scope = saved_scope

    # 4. Create exported module scope (strictly opaque for abstract interface types)
    module_export_scope = Scope(name=f"module_export_{decl.name}")
    export_type_subst: dict[int, QType] = {}

    for type_name, interface_type_symbol in target_interface_scope.types.items():
        if interface_type_symbol.definition is None:
            export_sym_id = env.fresh_symbol_id()
            opaque_type_symbol = TypeSymbol(
                name=type_name,
                symbol_id=export_sym_id,
                kind=interface_type_symbol.kind,
                definition=None,
            )
            module_export_scope.declare_type(opaque_type_symbol)
            export_type_subst[interface_type_symbol.symbol_id] = QTypeVar(
                name=f"{decl.name}.{type_name}",
                symbol_id=export_sym_id,
                bound=interface_type_symbol.kind,
            )
        else:
            manifest_type_symbol = TypeSymbol(
                name=type_name,
                symbol_id=env.fresh_symbol_id(),
                kind=interface_type_symbol.kind,
                definition=interface_type_symbol.definition,
            )
            module_export_scope.declare_type(manifest_type_symbol)

    for val_name, interface_val_symbol in target_interface_scope.values.items():
        exported_val_type = interface_val_symbol.type_val.substitute(export_type_subst)
        module_export_scope.declare_value(
            ValueSymbol(
                name=val_name,
                type_val=exported_val_type,
                is_var=interface_val_symbol.is_var,
                is_out=interface_val_symbol.is_out,
            )
        )

    env.register_module(decl.name, module_export_scope)

    rec_fields = tuple(
        QRecordField(name=v.name, type_val=v.type_val, is_var=v.is_var)
        for v in module_export_scope.values.values()
    )
    env.current_scope.declare_value(
        ValueSymbol(name=decl.name, type_val=QRecordType(fields=rec_fields))
    )

    return TypedModule(
        name=decl.name,
        interface_name=decl.interface_name,
        bindings=tuple(typed_bindings),
        scope=module_export_scope,
        offset=decl.offset,
    )


def elaborate_import(phrase: ast.ImportPhrase, env: Environment) -> TypedImport:
    """Elaborates a top-level import statement, loading interfaces/modules from BuiltinModuleRegistry."""
    typed_items: list[TypedImportItem] = []
    for item in phrase.items:
        iface_name = item.interface_name
        iface_scope = env.lookup_interface(iface_name)
        if iface_scope is None:
            iface_scope = BuiltinModuleRegistry.get_interface(iface_name, env)
            if iface_scope is not None:
                env.register_interface(iface_name, iface_scope)

        if iface_scope is None:
            raise QuestTypeError(
                f"Undefined interface '{iface_name}' in import",
                offset=getattr(item, "offset", phrase.offset),
            )

        if not item.names:
            # import : Interface
            # Direct interface import: bind interface types and kinds into current scope
            for type_name, type_sym in iface_scope.types.items():
                env.current_scope.declare_type(type_sym)
            for kind_name, kind_sym in iface_scope.kinds.items():
                env.current_scope.declare_kind(kind_sym)
            typed_items.append(TypedImportItem(names=(), interface_name=iface_name))
        else:
            # import mod1, mod2: Interface
            for mod_name in item.names:
                mod_type = BuiltinModuleRegistry.get_module_type(mod_name, env)
                if mod_type is None:
                    mod_type = BuiltinModuleRegistry._build_record_type_from_scope(iface_scope)
                env.register_module(mod_name, iface_scope)
                env.current_scope.declare_value(ValueSymbol(name=mod_name, type_val=mod_type))
            typed_items.append(TypedImportItem(names=item.names, interface_name=iface_name))

    return TypedImport(items=tuple(typed_items), offset=phrase.offset)
