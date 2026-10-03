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


def is_c_compilation_mode(env: Environment) -> bool:
    """Checks whether the compiler environment is actively compiling or generating C code."""
    opts = getattr(env, "options", None)
    if opts is None:
        return False
    if getattr(opts, "whole_program", False):
        return False
    if getattr(opts, "stop_after", None) in ("codegen_c", "run_c_compiled"):
        return True
    if getattr(opts, "emit_c", False):
        return True
    if getattr(opts, "output_path", None) is not None:
        return True
    if any(p in ("codegen_c", "run_c_compiled") for p in getattr(opts, "dump_after", ())):
        return True
    return False


def _is_artifact_stale(artifact: Path, sources: list[Path]) -> bool:
    """Returns True if artifact does not exist or any source file has a newer mtime."""
    if not artifact.is_file():
        return True
    try:
        art_mtime = artifact.stat().st_mtime
        for src in sources:
            if src.is_file() and src.stat().st_mtime > art_mtime:
                return True
        return False
    except OSError:
        return True


def resolve_interface_file(
    name: str,
    current_dir: Optional[Path],
    include_paths: list[Path],
) -> Optional[Path]:
    """Finds <name.lower()>.qi or <name.lower()>.int.quest in current_dir, include_paths, or DEFAULT_LIB_DIR."""
    source_file = resolve_interface_source_file(name, current_dir, include_paths)
    source_mtime = source_file.stat().st_mtime if source_file and source_file.is_file() else None

    stem = name.lower()
    dirs_to_check: list[Path] = []
    if current_dir is not None:
        dirs_to_check.append(current_dir)
    for inc in include_paths:
        dirs_to_check.append(Path(inc))
    env_lib = os.environ.get("QUEST_LIB")
    if env_lib:
        dirs_to_check.append(Path(env_lib))
    if DEFAULT_LIB_DIR.is_dir():
        dirs_to_check.append(DEFAULT_LIB_DIR)

    for d in dirs_to_check:
        qi_candidate = d / f"{stem}.qi"
        if qi_candidate.is_file():
            if source_mtime is None or qi_candidate.stat().st_mtime >= source_mtime:
                return qi_candidate.resolve()

    return source_file


def resolve_interface_source_file(
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


def resolve_object_file(
    name: str,
    current_dir: Optional[Path],
    include_paths: list[Path],
) -> Optional[Path]:
    """Finds <name.lower()>.o in current_dir, include_paths, or DEFAULT_LIB_DIR."""
    filename = f"{name.lower()}.o"
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


def canonicalize_module_path(
    file_path: Path,
    include_paths: list[Path],
) -> str:
    """Computes canonical hierarchical name relative to include_paths, QUEST_LIB, or DEFAULT_LIB_DIR."""
    all_roots: list[Path] = []
    env_lib = os.environ.get("QUEST_LIB")
    if env_lib:
        all_roots.append(Path(env_lib).resolve())
    for inc in include_paths:
        all_roots.append(Path(inc).resolve())
    if DEFAULT_LIB_DIR.is_dir():
        all_roots.append(DEFAULT_LIB_DIR.resolve())

    all_roots.sort(key=lambda p: len(p.parts), reverse=True)
    resolved = file_path.resolve()
    for root in all_roots:
        try:
            rel = resolved.relative_to(root)
            parts = list(rel.parts)
            filename = parts[-1]
            for ext in (".int.quest", ".mod.quest", ".qi", ".o"):
                if filename.endswith(ext):
                    filename = filename[: -len(ext)]
                    break
            parts[-1] = filename
            return "/".join(parts)
        except ValueError:
            continue

    filename = resolved.name
    for ext in (".int.quest", ".mod.quest", ".qi", ".o"):
        if filename.endswith(ext):
            filename = filename[: -len(ext)]
            break
    return filename


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

    # 3-way staleness check and on-demand interface compilation in C compilation mode
    if is_c_compilation_mode(env):
        opts = getattr(env, "options", None)
        build_dir = getattr(opts, "build_dir", None)
        if build_dir is not None:
            out_root = Path(build_dir).resolve()
        elif Path(".build").is_dir():
            out_root = Path(".build").resolve()
        elif file_path is not None and "/" in name:
            rel_parts = len(Path(name.lower()).parts)
            out_root = file_path.parents[rel_parts - 1].resolve()
        else:
            out_root = (env.current_dir or Path.cwd()).resolve()

        int_src = resolve_interface_source_file(name, env.current_dir, env.include_paths)
        if int_src is None and file_path and file_path.name.endswith(".int.quest"):
            int_src = file_path

        canon_name = canonicalize_module_path(int_src, env.include_paths) if int_src else name.lower()
        if "/" in canon_name:
            target_sub = out_root / Path(canon_name).parent
        else:
            target_sub = out_root

        stem = Path(canon_name).name.lower()
        qi_file = target_sub / f"{stem}.qi"
        h_file = target_sub / f"{stem}.h"

        if not qi_file.is_file() and file_path and file_path.suffix == ".qi":
            cand_h = file_path.with_suffix(".h")
            if cand_h.is_file():
                qi_file = file_path
                h_file = cand_h

        # 3-way staleness check (§5 of docs/build-process.md)
        stale = False
        if int_src and int_src.is_file():
            if not qi_file.is_file() or not h_file.is_file():
                # Rule 2: source exists, artifacts incomplete -> OUT OF DATE
                stale = True
            else:
                # Rule 1: source and artifacts exist -> compare timestamps
                src_mtime = int_src.stat().st_mtime
                if src_mtime > qi_file.stat().st_mtime or src_mtime > h_file.stat().st_mtime:
                    stale = True
        elif qi_file and qi_file.is_file() and h_file and h_file.is_file():
            # Rule 3: binary distribution mode (artifacts exist, no source) -> UP TO DATE
            stale = False

        if stale and int_src and int_src.is_file():
            from quest.interface_compiler import compile_interface_file
            target_sub.mkdir(parents=True, exist_ok=True)
            search_paths = list(env.include_paths)
            if out_root not in search_paths:
                search_paths.insert(0, out_root)
            h_file, qi_file = compile_interface_file(
                int_src,
                output_dir=target_sub,
                include_paths=search_paths,
                build_dir=out_root,
            )

        if qi_file and qi_file.is_file():
            from quest.interface_compiler import load_interface_from_qi_file
            if out_root not in env.include_paths:
                env.include_paths.insert(0, out_root)
            scope = load_interface_from_qi_file(qi_file, env)
            env.register_interface(name, scope)
            decl_name = name.split("/")[-1]
            if decl_name != name:
                env.register_interface(decl_name, scope)
            if canon_name != name:
                env.register_interface(canon_name, scope)
            return scope

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
            f"(looked for '{norm_name}.qi' or '{norm_name}.int.quest' in {searched})"
        )

    if file_path.suffix == ".qi":
        from quest.interface_compiler import load_interface_from_qi_file
        scope = load_interface_from_qi_file(file_path, env)
        env.register_interface(name, scope)
        decl_name = name.split("/")[-1]
        if decl_name != name:
            env.register_interface(decl_name, scope)
        canon_name = canonicalize_module_path(file_path, env.include_paths)
        if canon_name != name:
            env.register_interface(canon_name, scope)
        return scope

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
    if decl.name.lower() != expected_base or decl.name.lower() != norm_name.split("/")[-1]:
        raise QuestTypeError(
            f"Interface declared in '{file_path.name}' has name '{decl.name}', which does not match file name"
        )

    canon_name = canonicalize_module_path(file_path, env.include_paths)

    saved_dir = env.current_dir
    env.current_dir = file_path.parent
    env._loading_interfaces.append(name)
    try:
        from quest.modules import elaborate_interface
        typed_iface = elaborate_interface(decl, env)
        env.register_interface(name, typed_iface.scope)
        if decl.name != name:
            env.register_interface(decl.name, typed_iface.scope)
        if canon_name != name:
            env.register_interface(canon_name, typed_iface.scope)
        return typed_iface.scope
    finally:
        env._loading_interfaces.pop()
        env.current_dir = saved_dir


def parse_dep_file(dep_file: Path) -> list[str]:
    """Parses a Makefile .d file and returns the list of prerequisite paths."""
    text = dep_file.read_text(encoding="utf-8")
    prereqs: list[str] = []
    in_prereqs = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not in_prereqs:
            _, rhs = line.split(":", 1)
            in_prereqs = True
            line = rhs.strip()
        if in_prereqs:
            if line.endswith("\\"):
                line = line[:-1].strip()
            for part in line.split():
                if part.endswith(".o") and part not in prereqs:
                    prereqs.append(part)
    return prereqs


def _load_precompiled_transitive_deps(
    obj_file: Optional[Path],
    file_path: Optional[Path],
    env: Environment,
    out_root: Optional[Path] = None,
) -> None:
    """Discovers and loads transitive module dependencies from a .d file or fallback source."""
    # 1. Try reading from .qm manifest first
    if obj_file is not None and obj_file.is_file():
        qm_cand = obj_file.with_suffix(".qm")
        if qm_cand.is_file():
            from quest.build.manifest import read_qm
            manifest = read_qm(qm_cand)
            if manifest:
                for imp_m in manifest.imported_modules:
                    mod_name = imp_m.name
                    dep_obj: Optional[Path] = None
                    if out_root is not None:
                        cand = out_root / f"{mod_name.lower()}.o"
                        if cand.is_file():
                            dep_obj = cand.resolve()
                    if dep_obj is None and env.current_dir is not None:
                        cand = env.current_dir / f"{mod_name.lower()}.o"
                        if cand.is_file():
                            dep_obj = cand.resolve()
                    if dep_obj is None:
                        for inc in env.include_paths:
                            cand = Path(inc) / f"{mod_name.lower()}.o"
                            if cand.is_file():
                                dep_obj = cand.resolve()
                                break
                    if dep_obj is not None and dep_obj.is_file():
                        if dep_obj not in env.linked_objects:
                            env.linked_objects.append(dep_obj)
                        env.precompiled_modules.add(mod_name)
                        _load_precompiled_transitive_deps(dep_obj, None, env, out_root)
                return

    # 2. Fallback: try reading from .deps/<stem>.d (or alongside .o)
    if obj_file is not None and obj_file.is_file():
        dep_candidates = [
            obj_file.parent / ".deps" / f"{obj_file.stem}.d",
            obj_file.with_suffix(".d"),
        ]
        for dep_file in dep_candidates:
            if dep_file.is_file():
                try:
                    prereqs = parse_dep_file(dep_file)
                    for prereq in prereqs:
                        dep_obj: Optional[Path] = None
                        if out_root is not None:
                            cand = out_root / prereq
                            if cand.is_file():
                                dep_obj = cand.resolve()
                        if dep_obj is None and env.current_dir is not None:
                            cand = env.current_dir / prereq
                            if cand.is_file():
                                dep_obj = cand.resolve()
                        if dep_obj is None:
                            for inc in env.include_paths:
                                cand = Path(inc) / prereq
                                if cand.is_file():
                                    dep_obj = cand.resolve()
                                    break
                        if dep_obj is None:
                            mod_name = prereq[:-2] if prereq.endswith(".o") else prereq
                            mod_file = resolve_module_file(mod_name, env.current_dir, env.include_paths)
                            if mod_file and mod_file.is_file():
                                from quest.module_compiler import compile_hierarchical_module
                                root = out_root if out_root is not None else DEFAULT_LIB_DIR
                                _, compiled_o = compile_hierarchical_module(
                                    mod_name,
                                    output_dir=root,
                                    current_dir=env.current_dir,
                                    include_paths=env.include_paths,
                                    emit_deps=True,
                                )
                                if compiled_o and compiled_o.is_file():
                                    dep_obj = compiled_o.resolve()

                        if dep_obj is not None and dep_obj.is_file():
                            if dep_obj not in env.linked_objects:
                                env.linked_objects.append(dep_obj)
                            mod_name = prereq[:-2] if prereq.endswith(".o") else prereq
                            env.precompiled_modules.add(mod_name)
                            _load_precompiled_transitive_deps(dep_obj, None, env, out_root)
                    return
                except Exception:
                    pass

    # 2. Fallback: parse .mod.quest if available
    if file_path and file_path.is_file():
        try:
            source_text = file_path.read_text(encoding="utf-8")
            source_map = SourceMap(source_text, str(file_path))
            tokenizer = Tokenizer(source_text, str(file_path))
            tokens = tokenizer.tokenize_all()
            prog = parse_quest_program(tokens, source_map)
            if (
                isinstance(prog, ast.Program)
                and len(prog.phrases) == 1
                and isinstance(prog.phrases[0], ast.ModuleDecl)
            ):
                for imp in prog.phrases[0].imports:
                    iface_path = imp.effective_interface_path
                    for iname, mpath in zip(imp.names, imp.effective_module_paths):
                        if mpath not in env.precompiled_modules and mpath not in env.loaded_modules_ast:
                            load_module(mpath, iface_path, env)
        except Exception:
            pass


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
    canon_name = canonicalize_module_path(file_path, env.include_paths) if file_path else name
    if canon_name in env.loaded_modules_ast:
        typed_mod = env.loaded_modules_ast[canon_name]
        if name != canon_name:
            env.loaded_modules_ast[name] = typed_mod
        return typed_mod

    def _synthesize_precompiled_module() -> TypedModule:
        target_interface_scope = env.lookup_interface(expected_interface)
        if target_interface_scope is None:
            target_interface_scope = load_interface(expected_interface, env)

        from quest.modules import create_module_export_scope
        module_export_scope = create_module_export_scope(canon_name, target_interface_scope, env)
        env.register_module(canon_name, module_export_scope)
        if name != canon_name:
            env.register_module(name, module_export_scope)
        short_name = canon_name.split("/")[-1]
        if short_name != canon_name and short_name != name:
            env.register_module(short_name, module_export_scope)

        from quest.typed_ast import TypedModule
        typed_mod = TypedModule(
            name=canon_name,
            interface_name=expected_interface,
            bindings=(),
            scope=module_export_scope,
            is_precompiled=True,
        )
        env.loaded_modules_ast[canon_name] = typed_mod
        if name != canon_name:
            env.loaded_modules_ast[name] = typed_mod
        if short_name != canon_name and short_name != name:
            env.loaded_modules_ast[short_name] = typed_mod
        return typed_mod

    if name in env.precompiled_modules or canon_name in env.precompiled_modules:
        return _synthesize_precompiled_module()

    # Hierarchical module separate compilation in C compilation mode
    if is_c_compilation_mode(env) and ("/" in canon_name or "/" in name):
        opts = getattr(env, "options", None)
        build_dir = getattr(opts, "build_dir", None)
        if build_dir is not None:
            out_root = Path(build_dir).resolve()
        elif file_path is not None:
            rel_parts = len(Path(canon_name).parts)
            out_root = file_path.parents[rel_parts - 1].resolve()
        else:
            out_root = (env.current_dir or Path.cwd()).resolve()

        obj_file = out_root / f"{canon_name}.o"
        sources: list[Path] = []
        if file_path and file_path.is_file():
            sources.append(file_path)
        intf_src = resolve_interface_file(expected_interface, env.current_dir, env.include_paths)
        if intf_src and intf_src.is_file():
            sources.append(intf_src)

        if obj_file.is_file():
            dep_candidates = [
                obj_file.parent / ".deps" / f"{obj_file.stem}.d",
                obj_file.with_suffix(".d"),
            ]
            for dep_file in dep_candidates:
                if dep_file.is_file():
                    try:
                        for prereq in parse_dep_file(dep_file):
                            cand = out_root / prereq
                            if cand.is_file():
                                sources.append(cand)
                            elif (DEFAULT_LIB_DIR / prereq).is_file():
                                sources.append(DEFAULT_LIB_DIR / prereq)
                    except Exception:
                        pass

        if _is_artifact_stale(obj_file, sources) and file_path is not None:
            from quest.module_compiler import compile_hierarchical_module
            compile_hierarchical_module(
                canon_name,
                output_dir=out_root,
                current_dir=env.current_dir,
                include_paths=env.include_paths,
                emit_deps=True,
            )

        if obj_file.is_file():
            if obj_file not in env.linked_objects:
                env.linked_objects.append(obj_file)
            env.precompiled_modules.add(name)
            env.precompiled_modules.add(canon_name)
            if out_root not in env.include_paths:
                env.include_paths.insert(0, out_root)
            _load_precompiled_transitive_deps(obj_file, file_path, env, out_root)
            return _synthesize_precompiled_module()

    if file_path is None:
        from quest.builtins import BuiltinModuleRegistry
        builtin_ast = BuiltinModuleRegistry.get_module_ast(name, env)
        if builtin_ast is not None:
            env.loaded_modules_ast[name] = builtin_ast
            return builtin_ast

        obj_file = resolve_object_file(name, env.current_dir, env.include_paths)
        if obj_file is not None or name in env.precompiled_modules:
            if obj_file is not None and obj_file not in env.linked_objects:
                env.linked_objects.append(obj_file)
            env.precompiled_modules.add(name)
            src_file = resolve_module_file(name, env.current_dir, env.include_paths)
            _load_precompiled_transitive_deps(obj_file, src_file, env, None)
            return _synthesize_precompiled_module()

        searched = [str(env.current_dir)] if env.current_dir else []
        searched.extend(str(p) for p in env.include_paths)
        if DEFAULT_LIB_DIR.is_dir():
            searched.append(str(DEFAULT_LIB_DIR))
        raise QuestTypeError(
            f"Undefined module '{name}': cannot find module file for '{name}' "
            f"(looked for '{norm_name}.mod.quest' or '{norm_name}.o' in {searched})"
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
    if decl.name.lower() != expected_base or decl.name.lower() != norm_name.split("/")[-1]:
        raise QuestTypeError(
            f"Module declared in '{file_path.name}' has name '{decl.name}', which does not match file name"
        )

    if (
        decl.interface_name != expected_interface
        and decl.interface_name.split("/")[-1] != expected_interface
        and decl.interface_name != expected_interface.split("/")[-1]
    ):
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
        if (
            decl.interface_name != expected_interface
            and env.lookup_interface(decl.interface_name) is None
        ):
            load_interface(decl.interface_name, env)

        from quest.modules import elaborate_module
        from quest.env import Scope
        temp_scope = Scope(parent=env.base_scope, name=f"temp_load_{decl.name}")
        env.current_scope = temp_scope
        typed_mod = elaborate_module(decl, env)

        env.loaded_modules_ast[name] = typed_mod
        if decl.name != name:
            env.loaded_modules_ast[decl.name] = typed_mod
        if canon_name != name:
            env.loaded_modules_ast[canon_name] = typed_mod
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

    file_path = resolve_module_file(name, r_env.current_dir, r_env.include_paths)
    canon_name = canonicalize_module_path(file_path, r_env.include_paths) if file_path else name
    if canon_name in r_env.evaluated_modules:
        val = r_env.evaluated_modules[canon_name]
        r_env.evaluated_modules[name] = val
        return val

    if name in r_env.loaded_modules_ast:
        typed_mod = r_env.loaded_modules_ast[name]
    elif canon_name in r_env.loaded_modules_ast:
        typed_mod = r_env.loaded_modules_ast[canon_name]
    else:
        from quest.env import Environment
        type_env = Environment()
        type_env.include_paths = list(r_env.include_paths)
        type_env.current_dir = r_env.current_dir
        typed_mod = load_module(name, expected_interface, type_env)
        r_env.loaded_modules_ast[name] = typed_mod
        if canon_name != name:
            r_env.loaded_modules_ast[canon_name] = typed_mod

    from quest.builtins import BuiltinModuleRegistry
    builtin_rec = BuiltinModuleRegistry.get_runtime_module(name)
    if not typed_mod.bindings and builtin_rec is not None:
        r_env.evaluated_modules[name] = builtin_rec
        if canon_name != name:
            r_env.evaluated_modules[canon_name] = builtin_rec
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
    if canon_name != name:
        r_env.evaluated_modules[canon_name] = rec
    return rec
