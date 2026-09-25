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
            from quest.module_loader import load_interface
            source_interface_scope = load_interface(imp.interface_name, env)
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


def create_module_export_scope(
    module_name: str,
    target_interface_scope: Scope,
    env: Environment,
) -> Scope:
    """Creates the exported scope for a module conforming to an interface scope."""
    module_export_scope = Scope(name=f"module_export_{module_name}")
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
                name=f"{module_name}.{type_name}",
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

    return module_export_scope


def elaborate_module(
    decl: ast.ModuleDecl,
    env: Environment,
    binding_elaborator: Optional[Callable[[ast.BindingNode, Environment, int], TypedBinding]] = None,
) -> TypedModule:
    """Elaborates and typechecks a module against its interface, enforcing information hiding."""
    target_interface_scope = env.lookup_interface(decl.interface_name)
    if target_interface_scope is None:
        target_interface_scope = BuiltinModuleRegistry.get_interface(decl.interface_name, env)
        if target_interface_scope is not None:
            env.register_interface(decl.interface_name, target_interface_scope)
    if target_interface_scope is None:
        from quest.module_loader import load_interface
        target_interface_scope = load_interface(decl.interface_name, env)

    module_internal_scope = Scope(name=f"module_internal_{decl.name}", parent=env.base_scope)

    # 1. Resolve imports into module_internal_scope
    for imp in decl.imports:
        iface_path = imp.effective_interface_path
        local_iface = imp.interface_name
        source_interface_scope = env.lookup_interface(local_iface) or env.lookup_interface(iface_path)
        if source_interface_scope is None:
            source_interface_scope = BuiltinModuleRegistry.get_interface(
                iface_path, env
            ) or BuiltinModuleRegistry.get_interface(local_iface, env)
            if source_interface_scope is not None:
                env.register_interface(iface_path, source_interface_scope)
        if source_interface_scope is None:
            from quest.module_loader import load_interface
            source_interface_scope = load_interface(iface_path, env)

        env.register_interface(local_iface, source_interface_scope)
        if local_iface != iface_path:
            env.register_interface(iface_path, source_interface_scope)

        if not imp.names:
            for type_name, type_sym in source_interface_scope.types.items():
                module_internal_scope.declare_type(type_sym)
            for kind_name, kind_sym in source_interface_scope.kinds.items():
                module_internal_scope.declare_kind(kind_sym)
        else:
            for local_name, mod_path in zip(imp.names, imp.effective_module_paths):
                if local_name == mod_path:
                    type_symbol = source_interface_scope.lookup_type_local(local_name)
                    if type_symbol is not None:
                        module_internal_scope.declare_type(type_symbol)
                        continue
                    value_symbol = source_interface_scope.lookup_value_local(local_name)
                    if value_symbol is not None:
                        module_internal_scope.declare_value(value_symbol)
                        continue
                    kind_symbol = source_interface_scope.lookup_kind_local(local_name)
                    if kind_symbol is not None:
                        module_internal_scope.declare_kind(kind_symbol)
                        continue
                from quest.module_loader import (
                    load_module,
                    resolve_module_file,
                    resolve_object_file,
                )
                on_disk = (
                    resolve_module_file(mod_path, env.current_dir, env.include_paths) is not None
                    or resolve_object_file(mod_path, env.current_dir, env.include_paths) is not None
                    or mod_path in env.precompiled_modules
                )
                if on_disk or mod_path in env.loaded_modules_ast:
                    if mod_path not in env.loaded_modules_ast:
                        load_module(mod_path, iface_path, env)
                    mod_scope = env.lookup_module(mod_path)
                    if mod_scope is not None:
                        mod_type = BuiltinModuleRegistry._build_record_type_from_scope(mod_scope)
                    else:
                        mod_type = BuiltinModuleRegistry._build_record_type_from_scope(source_interface_scope)
                else:
                    mod_type = BuiltinModuleRegistry.get_module_type(mod_path, env)
                    mod_scope = env.lookup_module(mod_path)
                    if mod_type is None:
                        if mod_path not in env.loaded_modules_ast:
                            load_module(mod_path, iface_path, env)
                        mod_scope = env.lookup_module(mod_path)
                        if mod_scope is not None:
                            mod_type = BuiltinModuleRegistry._build_record_type_from_scope(mod_scope)
                        else:
                            mod_type = BuiltinModuleRegistry._build_record_type_from_scope(source_interface_scope)
                registered_scope = mod_scope if mod_scope is not None else source_interface_scope
                env.register_module(mod_path, registered_scope)
                if local_name != mod_path:
                    env.register_module(local_name, registered_scope)
                module_internal_scope.declare_value(ValueSymbol(name=local_name, type_val=mod_type))

    # 2. Elaborate module internal bindings
    if binding_elaborator is None:
        from quest.typechecker import _elaborate_binding
        binding_elaborator = _elaborate_binding

    saved_scope = env.current_scope
    env.current_scope = module_internal_scope
    typed_bindings: list[TypedBinding] = []
    if decl.imports:
        from quest.typed_ast import TypedImportItem
        typed_items = tuple(
            TypedImportItem(
                names=imp.names,
                interface_name=imp.interface_name,
                module_paths=imp.module_paths,
                interface_path=imp.interface_path,
            )
            for imp in decl.imports
        )
        typed_bindings.append(TypedImport(items=typed_items, offset=decl.offset))
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
    module_export_scope = create_module_export_scope(decl.name, target_interface_scope, env)

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
    """Elaborates a top-level import statement, loading interfaces/modules from BuiltinModuleRegistry or files."""
    typed_items: list[TypedImportItem] = []
    for item in phrase.items:
        iface_path = item.effective_interface_path
        local_iface_name = item.interface_name
        iface_scope = env.lookup_interface(local_iface_name) or env.lookup_interface(iface_path)
        if iface_scope is None:
            iface_scope = BuiltinModuleRegistry.get_interface(
                iface_path, env
            ) or BuiltinModuleRegistry.get_interface(local_iface_name, env)
            if iface_scope is not None:
                env.register_interface(iface_path, iface_scope)

        if iface_scope is None:
            from quest.module_loader import load_interface
            iface_scope = load_interface(iface_path, env)

        env.register_interface(local_iface_name, iface_scope)
        if local_iface_name != iface_path:
            env.register_interface(iface_path, iface_scope)

        if not item.names:
            # import : Interface
            # Direct interface import: bind interface types and kinds into current scope
            for type_name, type_sym in iface_scope.types.items():
                env.current_scope.declare_type(type_sym)
            for kind_name, kind_sym in iface_scope.kinds.items():
                env.current_scope.declare_kind(kind_sym)
            typed_items.append(
                TypedImportItem(
                    names=(),
                    interface_name=local_iface_name,
                    module_paths=(),
                    interface_path=item.interface_path,
                )
            )
        else:
            # import mod1, mod2: Interface
            for local_mod_name, mod_path in zip(item.names, item.effective_module_paths):
                from quest.module_loader import (
                    load_module,
                    resolve_module_file,
                    resolve_object_file,
                )
                on_disk = (
                    resolve_module_file(mod_path, env.current_dir, env.include_paths) is not None
                    or resolve_object_file(mod_path, env.current_dir, env.include_paths) is not None
                    or mod_path in env.precompiled_modules
                )
                if on_disk or mod_path in env.loaded_modules_ast:
                    if mod_path not in env.loaded_modules_ast:
                        load_module(mod_path, iface_path, env)
                    mod_scope = env.lookup_module(mod_path)
                    if mod_scope is not None:
                        mod_type = BuiltinModuleRegistry._build_record_type_from_scope(mod_scope)
                    else:
                        mod_type = BuiltinModuleRegistry._build_record_type_from_scope(iface_scope)
                else:
                    mod_type = BuiltinModuleRegistry.get_module_type(mod_path, env)
                    mod_scope = env.lookup_module(mod_path)
                    if mod_type is None:
                        if mod_path not in env.loaded_modules_ast:
                            load_module(mod_path, iface_path, env)
                        mod_scope = env.lookup_module(mod_path)
                        if mod_scope is not None:
                            mod_type = BuiltinModuleRegistry._build_record_type_from_scope(mod_scope)
                        else:
                            mod_type = BuiltinModuleRegistry._build_record_type_from_scope(iface_scope)
                registered_scope = mod_scope if mod_scope is not None else iface_scope
                env.register_module(mod_path, registered_scope)
                if local_mod_name != mod_path:
                    env.register_module(local_mod_name, registered_scope)
                env.current_scope.declare_value(ValueSymbol(name=local_mod_name, type_val=mod_type))
            typed_items.append(
                TypedImportItem(
                    names=item.names,
                    interface_name=local_iface_name,
                    module_paths=item.module_paths,
                    interface_path=item.interface_path,
                )
            )

    return TypedImport(items=tuple(typed_items), offset=phrase.offset)
