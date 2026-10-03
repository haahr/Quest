"""Quest Module Compiler (Phase 4.16 Step 2).

Compiles Quest module implementation files (.mod.quest) into:
1. Standard C99 source (<name>.c) including the interface header and defining
   direct C functions (qv_<mod>_<func>), closure trampolines, module record
   (QRecordVal qv_<mod>), and idempotent initialization (qv_mod_<mod>_init).
2. Native relocatable object file (<name>.o) via the host C compiler.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import quest.ast as ast
from quest.codegen.c_emitter import CEmitter
from quest.codegen.compiler_runner import compile_c_to_object
from quest.diagnostics import QuestTypeError
from quest.build.manifest import (
    ImportedInterfaceRef,
    ImportedModuleRef,
    ModuleManifest,
    write_qm,
)
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.module_loader import (
    DEFAULT_LIB_DIR,
    canonicalize_interface_name,
    canonicalize_module_name,
    canonicalize_module_path,
    load_interface,
    resolve_interface_file,
    resolve_interface_source_file,
    resolve_module_file,
)
from quest.modules import elaborate_module
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap


class ModuleCompileResult(tuple):
    """Tuple of (c_file, o_file) with additional metadata attributes."""
    c_file: Path
    o_file: Path
    qm_file: Path

    def __new__(cls, c_file: Path, o_file: Path, qm_file: Path):
        obj = super().__new__(cls, (c_file, o_file))
        obj.c_file = c_file
        obj.o_file = o_file
        obj.qm_file = qm_file
        return obj


def compile_module(
    module_decl: ast.ModuleDecl,
    env: Environment,
    output_dir: Optional[Path] = None,
    include_paths: Optional[list[Path]] = None,
    compiler_path: Optional[str] = None,
    nogc: bool = False,
    extra_c_flags: Optional[list[str]] = None,
    source_map: Optional[SourceMap] = None,
    stem_name: Optional[str] = None,
    canonical_name: Optional[str] = None,
    emit_deps: bool = False,
    source_file: Optional[Path] = None,
    build_dir: Optional[Path] = None,
) -> ModuleCompileResult:
    """Compiles an AST ModuleDecl into .c, .o, and .qm files."""
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    if getattr(env, "options", None) is None:
        from quest.pipeline import CompilerOptions
        env.options = CompilerOptions(stop_after="codegen_c", build_dir=build_dir)

    if canonical_name is None and source_file is not None:
        canonical_name = canonicalize_module_path(source_file, env.include_paths)

    imported_modules: list[ImportedModuleRef] = []
    imported_interfaces: list[ImportedInterfaceRef] = []

    # 1. Load target interface (from .qi or .int.quest)
    target_interface_scope = env.lookup_interface(module_decl.interface_name)
    if target_interface_scope is None:
        target_interface_scope = load_interface(module_decl.interface_name, env)

    tgt_src = resolve_interface_source_file(
        module_decl.interface_name, env.current_dir, env.include_paths
    )
    canon_target_interface = canonicalize_interface_name(
        tgt_src, env.include_paths, module_decl.interface_name
    )
    tgt_mtime = tgt_src.stat().st_mtime if tgt_src and tgt_src.is_file() else 0.0
    imported_interfaces.append(
        ImportedInterfaceRef(
            name=canon_target_interface,
            source=str(tgt_src.resolve()) if tgt_src else "",
            mtime=tgt_mtime,
        )
    )

    # 2. Load any imported interfaces or modules
    for imp in module_decl.imports:
        iface_path = imp.effective_interface_path
        if env.lookup_interface(iface_path) is None and env.lookup_interface(imp.interface_name) is None:
            load_interface(iface_path, env)

        imp_src = resolve_interface_source_file(iface_path, env.current_dir, env.include_paths)
        canon_imp_iface = canonicalize_interface_name(imp_src, env.include_paths, iface_path)
        imp_mtime = imp_src.stat().st_mtime if imp_src and imp_src.is_file() else 0.0
        imported_interfaces.append(
            ImportedInterfaceRef(
                name=canon_imp_iface,
                source=str(imp_src.resolve()) if imp_src else "",
                mtime=imp_mtime,
            )
        )

        for iname, mpath in zip(imp.names, imp.effective_module_paths):
            mod_ref = mpath if mpath else iname
            mod_src = resolve_module_file(mod_ref, env.current_dir, env.include_paths)
            canon_mod_ref = canonicalize_module_name(mod_src, env.include_paths, mod_ref)
            imported_modules.append(ImportedModuleRef(name=canon_mod_ref, interface=canon_imp_iface))

    # 3. Elaborate module
    typed_mod = elaborate_module(module_decl, env)

    # 4. Check for interface header (.h)
    interface_name = module_decl.interface_name
    header_name = f"{interface_name.lower()}.h"
    interface_header: Optional[str] = None
    search_dirs = [output_dir]
    if env.current_dir:
        search_dirs.append(env.current_dir)
    search_dirs.extend(include_paths or [])
    search_dirs.append(DEFAULT_LIB_DIR)

    for s_dir in search_dirs:
        cand = s_dir / header_name
        if cand.is_file():
            interface_header = header_name
            break

    if interface_header is None:
        intf_file = resolve_interface_file(interface_name, env.current_dir, include_paths or [])
        if intf_file:
            cand_h = intf_file.parent / f"{intf_file.name.split('.')[0]}.h"
            if cand_h.is_file():
                rel_cand = None
                for s_dir in search_dirs:
                    try:
                        rel_cand = cand_h.relative_to(s_dir)
                        break
                    except ValueError:
                        continue
                interface_header = str(rel_cand) if rel_cand is not None else cand_h.name

    # 5. Determine exported functions
    exported_funs = set(target_interface_scope.values.keys())

    mod_name = canonical_name or module_decl.name
    if mod_name != typed_mod.name:
        from dataclasses import replace
        typed_mod = replace(typed_mod, name=mod_name)

    # 6. Emit C source
    emitter = CEmitter(echo=False, module_prefix=mod_name, env=env)
    c_source = emitter.emit_module(
        typed_mod,
        loaded_modules=env.loaded_modules_ast,
        interface_header=interface_header,
        exported_funs=exported_funs,
    )

    base = stem_name or module_decl.name.lower()
    c_file = output_dir / f"{base}.c"
    o_file = output_dir / f"{base}.o"
    c_file.parent.mkdir(parents=True, exist_ok=True)
    o_file.parent.mkdir(parents=True, exist_ok=True)

    c_file.write_text(c_source, encoding="utf-8")

    # 7. Compile .c to .o
    compile_dirs = list(dict.fromkeys(search_dirs))
    compile_c_to_object(
        c_file,
        o_file,
        include_paths=compile_dirs,
        nogc=nogc,
        compiler_path=compiler_path,
        extra_flags=extra_c_flags,
    )

    if emit_deps:
        from quest.module_loader import (
            canonicalize_module_path,
            resolve_object_file,
        )
        dep_objects: list[str] = []
        for imp in module_decl.imports:
            for iname, mpath in zip(imp.names, imp.effective_module_paths):
                mod_ref = mpath if mpath else iname
                f_path = resolve_module_file(mod_ref, env.current_dir, env.include_paths)
                canon = canonicalize_module_path(f_path, env.include_paths) if f_path else mod_ref
                if "/" in canon:
                    obj_rel = f"{canon.lower()}.o"
                    if obj_rel not in dep_objects:
                        dep_objects.append(obj_rel)
                else:
                    obj_cand = resolve_object_file(canon, env.current_dir, env.include_paths)
                    if obj_cand is not None:
                        obj_rel = f"{canon.lower()}.o"
                        if obj_rel not in dep_objects:
                            dep_objects.append(obj_rel)

        target_rel = f"{mod_name.lower()}.o"
        deps_dir = o_file.parent / ".deps"
        deps_dir.mkdir(parents=True, exist_ok=True)
        dep_file = deps_dir / f"{o_file.stem}.d"
        prereqs_str = " ".join(dep_objects)
        dep_file.write_text(f"{target_rel}: {prereqs_str}\n", encoding="utf-8")

    # 8. Emit .qm metadata file
    qm_file = output_dir / f"{base}.qm"
    manifest = ModuleManifest(
        name=mod_name,
        interface=canon_target_interface,
        source=str(source_file.resolve()) if source_file else "",
        object=str(o_file.resolve()),
        imported_modules=imported_modules,
        imported_interfaces=imported_interfaces,
    )
    write_qm(manifest, qm_file)

    return ModuleCompileResult(c_file, o_file, qm_file)


def compile_module_file(
    mod_path: Path,
    output_dir: Optional[Path] = None,
    include_paths: Optional[list[Path]] = None,
    compiler_path: Optional[str] = None,
    nogc: bool = False,
    extra_c_flags: Optional[list[str]] = None,
    emit_deps: bool = False,
    build_dir: Optional[Path] = None,
) -> ModuleCompileResult:
    """Compiles a Quest module file (.mod.quest) into .c, .o, and .qm files."""
    mod_path = Path(mod_path).resolve()
    if not mod_path.is_file():
        raise FileNotFoundError(f"Module file not found: '{mod_path}'")

    source_text = mod_path.read_text(encoding="utf-8")
    source_map = SourceMap(source_text, str(mod_path))
    tokenizer = Tokenizer(source_text, str(mod_path))
    tokens = tokenizer.tokenize_all()
    prog = parse_quest_program(tokens, source_map)

    if not isinstance(prog, ast.Program) or len(prog.phrases) != 1:
        raise QuestTypeError(
            f"Module file '{mod_path.name}' must contain exactly one module declaration"
        )

    decl = prog.phrases[0]
    if not isinstance(decl, ast.ModuleDecl):
        raise QuestTypeError(
            f"Expected module declaration in '{mod_path.name}', found {type(decl).__name__}"
        )

    file_name = mod_path.name
    if file_name.endswith(".mod.quest"):
        stem = file_name[:-len(".mod.quest")]
    elif file_name.endswith(".quest"):
        stem = file_name[:-len(".quest")]
    else:
        stem = mod_path.stem

    env = Environment()
    env.current_dir = mod_path.parent
    env.include_paths = list(include_paths) if include_paths else []
    if build_dir is not None:
        b_dir = Path(build_dir).resolve()
        if b_dir not in env.include_paths:
            env.include_paths.insert(0, b_dir)

    from quest.module_loader import canonicalize_module_path
    canon_name = canonicalize_module_path(mod_path, env.include_paths)

    if build_dir is not None and output_dir is None:
        target_sub = Path(build_dir).resolve()
        if "/" in canon_name:
            target_sub = target_sub / Path(canon_name).parent
        output_dir = target_sub
    elif output_dir is None:
        output_dir = mod_path.parent
    else:
        output_dir = Path(output_dir).resolve()

    return compile_module(
        decl,
        env,
        output_dir=output_dir,
        include_paths=env.include_paths,
        compiler_path=compiler_path,
        nogc=nogc,
        extra_c_flags=extra_c_flags,
        source_map=source_map,
        stem_name=stem,
        canonical_name=canon_name,
        emit_deps=emit_deps,
        source_file=mod_path,
        build_dir=build_dir,
    )


def compile_hierarchical_module(
    canonical_name: str,
    output_dir: Path,
    current_dir: Optional[Path] = None,
    include_paths: Optional[list[Path]] = None,
    compiler_path: Optional[str] = None,
    nogc: bool = False,
    extra_c_flags: Optional[list[str]] = None,
    emit_deps: bool = False,
) -> tuple[Path, Path, Path, Path]:
    """Compiles a hierarchical interface and module by canonical name into output_dir.

    Returns (qi_file, h_file, c_file, o_file).
    """
    from quest.interface_compiler import compile_interface_file
    from quest.module_loader import (
        resolve_interface_file,
        resolve_interface_source_file,
        resolve_module_file,
    )

    inc_paths = list(include_paths) if include_paths else []
    out_dir = Path(output_dir).resolve()

    intf_src_path = resolve_interface_source_file(canonical_name, current_dir, inc_paths)
    if intf_src_path is None:
        intf_src_path = resolve_interface_file(canonical_name, current_dir, inc_paths)
    if intf_src_path is None:
        raise QuestTypeError(f"Cannot resolve interface file for '{canonical_name}'")

    mod_path = resolve_module_file(canonical_name, current_dir, inc_paths)
    if mod_path is None:
        raise QuestTypeError(f"Cannot resolve module file for '{canonical_name}'")

    target_subdir = out_dir / Path(canonical_name).parent if "/" in canonical_name else out_dir
    target_subdir.mkdir(parents=True, exist_ok=True)

    search_paths = list(inc_paths)
    if out_dir not in search_paths:
        search_paths.append(out_dir)

    stem = Path(canonical_name).name.lower()
    target_h = target_subdir / f"{stem}.h"
    target_qi = target_subdir / f"{stem}.qi"
    if intf_src_path.suffix == ".qi":
        h_file = target_h
        qi_file = target_qi
    elif (
        target_h.is_file()
        and target_qi.is_file()
        and target_h.stat().st_mtime >= intf_src_path.stat().st_mtime
        and target_qi.stat().st_mtime >= intf_src_path.stat().st_mtime
    ):
        h_file = target_h
        qi_file = target_qi
    else:
        h_file, qi_file = compile_interface_file(
            intf_src_path,
            output_dir=target_subdir,
            include_paths=search_paths,
        )
    c_file, o_file = compile_module_file(
        mod_path,
        output_dir=target_subdir,
        include_paths=search_paths,
        compiler_path=compiler_path,
        nogc=nogc,
        extra_c_flags=extra_c_flags,
        emit_deps=emit_deps,
    )
    return (qi_file, h_file, c_file, o_file)

