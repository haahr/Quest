"""Quest Module and Interface File Loader.

Implements file-based loading of interfaces and modules for the Quest compiler
and interpreter:
- Resolves interface files as <name.lower()>.int.quest
- Resolves module files as <name.lower()>.mod.quest
- Search order: current file directory first, then include paths (-I)
- Verifies single top-level interface/module declaration matching filename
- Enforces interface conformance and case normalization
- Prevents cyclic dependencies with cycle detection
- Caches loaded modules for singleton evaluation
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import quest.ast as ast
from quest.diagnostics import QuestTypeError
from quest.grammar import parse_quest_program
from quest.tokens import SourceMap
from quest.tokenizer import Tokenizer

if TYPE_CHECKING:
    from quest.env import Environment, Scope
    from quest.interpreter import RuntimeEnvironment
    from quest.runtime import QValue
    from quest.typed_ast import TypedModule

DEFAULT_LIB_DIR = (Path(__file__).parent.parent.parent.parent / "lib").resolve()


def resolve_interface_file(
    name: str,
    current_dir: Optional[Path],
    include_paths: list[Path],
) -> Optional[Path]:
    """Finds <name.lower()>.int.quest in current_dir, include_paths, or DEFAULT_LIB_DIR."""
    filename = f"{name.lower()}.int.quest"
    if current_dir is not None:
        candidate = current_dir / filename
        if candidate.is_file():
            return candidate.resolve()

    for inc in include_paths:
        candidate = Path(inc) / filename
        if candidate.is_file():
            return candidate.resolve()

    env_lib = os.environ.get("QUEST_LIB")
    if env_lib:
        candidate = Path(env_lib) / filename
        if candidate.is_file():
            return candidate.resolve()

    if DEFAULT_LIB_DIR.is_dir():
        candidate = DEFAULT_LIB_DIR / filename
        if candidate.is_file():
            return candidate.resolve()

    return None


def resolve_module_file(
    name: str,
    current_dir: Optional[Path],
    include_paths: list[Path],
) -> Optional[Path]:
    """Finds <name.lower()>.mod.quest in current_dir, include_paths, or DEFAULT_LIB_DIR."""
    filename = f"{name.lower()}.mod.quest"
    if current_dir is not None:
        candidate = current_dir / filename
        if candidate.is_file():
            return candidate.resolve()

    for inc in include_paths:
        candidate = Path(inc) / filename
        if candidate.is_file():
            return candidate.resolve()

    env_lib = os.environ.get("QUEST_LIB")
    if env_lib:
        candidate = Path(env_lib) / filename
        if candidate.is_file():
            return candidate.resolve()

    if DEFAULT_LIB_DIR.is_dir():
        candidate = DEFAULT_LIB_DIR / filename
        if candidate.is_file():
            return candidate.resolve()

    return None


def load_interface(name: str, env: Environment) -> Scope:
    """Loads, validates, and elaborates an interface from a .int.quest file."""
    existing = env.lookup_interface(name)
    if existing is not None:
        return existing

    # Cycle detection
    norm_name = name.lower()
    if norm_name in [x.lower() for x in env._loading_interfaces]:
        chain = env._loading_interfaces + [name]
        raise QuestTypeError(
            f"Cyclic dependency detected in interface imports: {' -> '.join(chain)}"
        )

    file_path = resolve_interface_file(name, env.current_dir, env.include_paths)
    if file_path is None:
        from quest.builtins import BuiltinModuleRegistry
        builtin_iface = BuiltinModuleRegistry.get_interface(name, env)
        if builtin_iface is not None:
            env.register_interface(name, builtin_iface)
            return builtin_iface

        searched = [str(env.current_dir)] if env.current_dir else []
        searched.extend(str(p) for p in env.include_paths)
        if DEFAULT_LIB_DIR.is_dir():
            searched.append(str(DEFAULT_LIB_DIR))
        raise QuestTypeError(
            f"Undefined interface '{name}': cannot find interface file for '{name}' "
            f"(looked for '{norm_name}.int.quest' in {searched})"
        )

    try:
        source_text = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise QuestTypeError(f"Error reading interface file '{file_path}': {err}")

    source_map = SourceMap(source_text, str(file_path))
    tokenizer = Tokenizer(source_text, str(file_path))
    tokens = tokenizer.tokenize_all()
    prog = parse_quest_program(tokens, source_map)

    if not isinstance(prog, ast.Program):
        raise QuestTypeError(f"Malformed parse result in '{file_path}'")

    if len(prog.phrases) != 1:
        raise QuestTypeError(
            f"Interface file '{file_path.name}' must contain only a single interface declaration, "
            f"but found {len(prog.phrases)} phrases"
        )

    decl = prog.phrases[0]
    if not isinstance(decl, ast.InterfaceDecl):
        raise QuestTypeError(
            f"Expected interface declaration in '{file_path.name}', but found {type(decl).__name__}"
        )

    expected_base = file_path.name.split(".")[0].lower()
    if decl.name.lower() != expected_base or decl.name.lower() != norm_name:
        raise QuestTypeError(
            f"Interface declared in '{file_path.name}' has name '{decl.name}', which does not match file name"
        )

    saved_dir = env.current_dir
    env.current_dir = file_path.parent
    env._loading_interfaces.append(name)
    try:
        from quest.modules import elaborate_interface
        typed_iface = elaborate_interface(decl, env)
        if decl.name != name:
            env.register_interface(name, typed_iface.scope)
        return typed_iface.scope
    finally:
        env._loading_interfaces.pop()
        env.current_dir = saved_dir


def load_module(name: str, expected_interface: str, env: Environment) -> TypedModule:
    """Loads, validates, and elaborates a module from a .mod.quest file."""
    if name in env.loaded_modules_ast:
        return env.loaded_modules_ast[name]

    # Cycle detection
    norm_name = name.lower()
    if norm_name in [x.lower() for x in env._loading_modules]:
        chain = env._loading_modules + [name]
        raise QuestTypeError(
            f"Cyclic dependency detected in module imports: {' -> '.join(chain)}"
        )

    file_path = resolve_module_file(name, env.current_dir, env.include_paths)
    if file_path is None:
        from quest.builtins import BuiltinModuleRegistry
        builtin_ast = BuiltinModuleRegistry.get_module_ast(name, env)
        if builtin_ast is not None:
            env.loaded_modules_ast[name] = builtin_ast
            return builtin_ast

        searched = [str(env.current_dir)] if env.current_dir else []
        searched.extend(str(p) for p in env.include_paths)
        if DEFAULT_LIB_DIR.is_dir():
            searched.append(str(DEFAULT_LIB_DIR))
        raise QuestTypeError(
            f"Undefined module '{name}': cannot find module file for '{name}' "
            f"(looked for '{norm_name}.mod.quest' in {searched})"
        )

    try:
        source_text = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise QuestTypeError(f"Error reading module file '{file_path}': {err}")

    source_map = SourceMap(source_text, str(file_path))
    tokenizer = Tokenizer(source_text, str(file_path))
    tokens = tokenizer.tokenize_all()
    prog = parse_quest_program(tokens, source_map)

    if not isinstance(prog, ast.Program):
        raise QuestTypeError(f"Malformed parse result in '{file_path}'")

    if len(prog.phrases) != 1:
        raise QuestTypeError(
            f"Module file '{file_path.name}' must contain only a single module definition, "
            f"but found {len(prog.phrases)} phrases"
        )

    decl = prog.phrases[0]
    if not isinstance(decl, ast.ModuleDecl):
        raise QuestTypeError(
            f"Expected module definition in '{file_path.name}', but found {type(decl).__name__}"
        )

    expected_base = file_path.name.split(".")[0].lower()
    if decl.name.lower() != expected_base or decl.name.lower() != norm_name:
        raise QuestTypeError(
            f"Module declared in '{file_path.name}' has name '{decl.name}', which does not match file name"
        )

    if decl.interface_name != expected_interface:
        raise QuestTypeError(
            f"Module '{decl.name}' in '{file_path.name}' implements interface '{decl.interface_name}', "
            f"expected '{expected_interface}'"
        )

    saved_dir = env.current_dir
    saved_scope = env.current_scope
    env.current_dir = file_path.parent
    env._loading_modules.append(name)
    try:
        # Ensure target interface is loaded
        if env.lookup_interface(expected_interface) is None:
            load_interface(expected_interface, env)

        from quest.modules import elaborate_module
        from quest.env import Scope
        temp_scope = Scope(parent=env.base_scope, name=f"temp_load_{decl.name}")
        env.current_scope = temp_scope
        typed_mod = elaborate_module(decl, env)

        env.loaded_modules_ast[name] = typed_mod
        if decl.name != name:
            env.loaded_modules_ast[decl.name] = typed_mod
        return typed_mod
    finally:
        env.current_scope = saved_scope
        env._loading_modules.pop()
        env.current_dir = saved_dir


def load_module_for_interpreter(
    name: str,
    expected_interface: str,
    r_env: RuntimeEnvironment,
) -> Optional[QValue]:
    """Loads and evaluates a module from disk for the interpreter."""
    if name in r_env.evaluated_modules:
        return r_env.evaluated_modules[name]

    if name in r_env.loaded_modules_ast:
        typed_mod = r_env.loaded_modules_ast[name]
    else:
        from quest.env import Environment
        type_env = Environment()
        type_env.include_paths = list(r_env.include_paths)
        type_env.current_dir = r_env.current_dir
        typed_mod = load_module(name, expected_interface, type_env)
        r_env.loaded_modules_ast[name] = typed_mod

    from quest.builtins import BuiltinModuleRegistry
    builtin_rec = BuiltinModuleRegistry.get_runtime_module(name)
    if not typed_mod.bindings and builtin_rec is not None:
        r_env.evaluated_modules[name] = builtin_rec
        return builtin_rec

    from quest.interpreter import eval_binding
    from quest.runtime import QRecord

    mod_env = r_env.push_scope()
    for b in typed_mod.bindings:
        eval_binding(b, mod_env)

    exported_fields = {}
    for val_name in typed_mod.scope.values:
        exported_fields[val_name] = mod_env.lookup(val_name)

    rec = QRecord(exported_fields)
    r_env.evaluated_modules[name] = rec
    return rec
