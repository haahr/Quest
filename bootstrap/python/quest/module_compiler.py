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
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.module_loader import (
    DEFAULT_LIB_DIR,
    load_interface,
    resolve_interface_file,
    resolve_module_file,
)
from quest.modules import elaborate_module
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap


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
) -> tuple[Path, Path]:
    """Compiles an AST ModuleDecl into .c and .o files."""
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load target interface (from .qi or .int.quest)
    target_interface_scope = env.lookup_interface(module_decl.interface_name)
    if target_interface_scope is None:
        target_interface_scope = load_interface(module_decl.interface_name, env)

    # 2. Load any imported interfaces or modules
    for imp in module_decl.imports:
        if env.lookup_interface(imp.interface_name) is None:
            load_interface(imp.interface_name, env)
        for iname in imp.names:
            if iname not in env.loaded_modules_ast:
                from quest.module_loader import load_module
                load_module(iname, imp.interface_name, env)

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
                interface_header = cand_h.name

    # 5. Determine exported functions
    exported_funs = set(target_interface_scope.values.keys())

    # 6. Emit C source
    emitter = CEmitter(echo=False, module_prefix=module_decl.name)
    c_source = emitter.emit_module(
        typed_mod,
        loaded_modules=env.loaded_modules_ast,
        interface_header=interface_header,
        exported_funs=exported_funs,
    )

    base = stem_name or module_decl.name.lower()
    c_file = output_dir / f"{base}.c"
    o_file = output_dir / f"{base}.o"

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

    return c_file, o_file


def compile_module_file(
    mod_path: Path,
    output_dir: Optional[Path] = None,
    include_paths: Optional[list[Path]] = None,
    compiler_path: Optional[str] = None,
    nogc: bool = False,
    extra_c_flags: Optional[list[str]] = None,
) -> tuple[Path, Path]:
    """Compiles a Quest module file (.mod.quest) into .c and .o files."""
    mod_path = Path(mod_path).resolve()
    if not mod_path.is_file():
        raise FileNotFoundError(f"Module file not found: '{mod_path}'")

    if output_dir is None:
        output_dir = mod_path.parent
    else:
        output_dir = Path(output_dir).resolve()

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

    return compile_module(
        decl,
        env,
        output_dir=output_dir,
        include_paths=include_paths,
        compiler_path=compiler_path,
        nogc=nogc,
        extra_c_flags=extra_c_flags,
        source_map=source_map,
        stem_name=stem,
    )
