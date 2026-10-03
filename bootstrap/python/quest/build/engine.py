"""Queue-driven build engine for Quest programs and modules."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import quest.ast as ast
from quest.build.logger import BuildLogger
from quest.build.manifest import (
    ImportedInterfaceRef,
    ImportedModuleRef,
    ModuleManifest,
    is_manifest_stale,
    read_qm,
    write_qm,
)
from quest.codegen import compile_c_to_object, link_objects
from quest.codegen.c_emitter import CEmitter
from quest.env import Environment
from quest.grammar import parse_quest_program
from quest.module_compiler import compile_module_file
from quest.module_loader import (
    DEFAULT_LIB_DIR,
    canonicalize_module_path,
    load_interface,
    resolve_interface_source_file,
    resolve_module_file,
)
from quest.pipeline import CompilerOptions
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap
from quest.typechecker import TypeElaborator

RUNTIME_BUILTINS = {"dynamic"}


class BuildError(Exception):
    """Raised when the build process fails due to syntax, type, cycle, or linking errors."""
    pass


@dataclass
class BuildResult:
    """Result of a queue-driven build execution."""
    output_binary: Path
    compiled_units: list[str] = field(default_factory=list)
    linked_objects: list[Path] = field(default_factory=list)
    exit_code: int = 0


def detect_module_cycle(graph: dict[str, list[str]]) -> Optional[list[str]]:
    """Detects cycles in a directed graph of module dependencies using DFS."""
    visited: set[str] = set()
    rec_stack: list[str] = []

    def dfs(node: str) -> Optional[list[str]]:
        visited.add(node)
        rec_stack.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                cycle = dfs(neighbor)
                if cycle:
                    return cycle
            elif neighbor in rec_stack:
                idx = rec_stack.index(neighbor)
                return rec_stack[idx:] + [neighbor]
        rec_stack.pop()
        return None

    for node in graph:
        if node not in visited:
            cycle = dfs(node)
            if cycle:
                return cycle
    return None


class BuildEngine:
    """Drives incremental separate compilation and linking via a FIFO queue."""

    def __init__(
        self,
        build_dir: Optional[Path] = None,
        include_paths: Optional[list[Path]] = None,
        verbose: bool = False,
        log_file: Optional[Path] = None,
        nogc: bool = False,
        compiler_path: Optional[str] = None,
        extra_c_flags: Optional[list[str]] = None,
    ) -> None:
        self.build_dir = (build_dir or Path(".build")).resolve()
        self.include_paths = [Path(p).resolve() for p in (include_paths or [])]
        self.verbose = verbose
        actual_log = log_file if log_file is not None else (self.build_dir / "build.log")
        self.logger = BuildLogger(log_file=actual_log, verbose=verbose)
        self.nogc = nogc
        self.compiler_path = compiler_path
        self.extra_c_flags = extra_c_flags or []
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def _get_search_paths(self, current_dir: Optional[Path] = None) -> list[Path]:
        paths = [self.build_dir]
        if current_dir is not None:
            c_res = current_dir.resolve()
            if c_res not in paths:
                paths.append(c_res)
        for p in self.include_paths:
            if p not in paths:
                paths.append(p)
        if DEFAULT_LIB_DIR.is_dir() and DEFAULT_LIB_DIR.resolve() not in paths:
            paths.append(DEFAULT_LIB_DIR.resolve())
        return paths

    def compile_main_unit(
        self,
        main_file: Path,
    ) -> tuple[Path, Path, Path, list[ImportedModuleRef]]:
        """Compiles a main routine (.quest) into .qm, .c, and .o under build_dir."""
        stem = main_file.stem
        c_path = self.build_dir / f"{stem}.c"
        o_path = self.build_dir / f"{stem}.o"
        qm_path = self.build_dir / f"{stem}.qm"

        source_text = main_file.read_text(encoding="utf-8")
        source_map = SourceMap(source_text, str(main_file))
        tokens = Tokenizer(source_text, str(main_file)).tokenize_all()
        ast_prog = parse_quest_program(tokens, source_map)

        if not isinstance(ast_prog, ast.Program):
            raise BuildError(f"File '{main_file}' is not a Quest program")

        for phrase in ast_prog.phrases:
            if isinstance(phrase, (ast.ModuleDecl, ast.InterfaceDecl)):
                raise BuildError(
                    f"File '{main_file}' contains a module/interface declaration; "
                    "use module compiler for libraries."
                )

        search_paths = self._get_search_paths(main_file.parent)
        env = Environment()
        env.current_dir = main_file.parent
        env.include_paths = search_paths
        env.options = CompilerOptions(
            build_dir=self.build_dir,
            stop_after="codegen_c",
            include_paths=search_paths,
        )

        imported_modules: list[ImportedModuleRef] = []
        imported_interfaces: list[ImportedInterfaceRef] = []

        for phrase in ast_prog.phrases:
            if isinstance(phrase, ast.ImportPhrase):
                for it in phrase.items:
                    iface_path = it.effective_interface_path
                    self.logger.log("RESOLVE INTERFACE", f"'{iface_path}'")
                    if env.lookup_interface(iface_path) is None and env.lookup_interface(it.interface_name) is None:
                        load_interface(iface_path, env)
                    imp_src = resolve_interface_source_file(iface_path, env.current_dir, env.include_paths)
                    imp_mtime = imp_src.stat().st_mtime if imp_src and imp_src.is_file() else 0.0
                    imported_interfaces.append(
                        ImportedInterfaceRef(
                            name=iface_path,
                            source=str(imp_src.resolve()) if imp_src else "",
                            mtime=imp_mtime,
                        )
                    )
                    for iname, mpath in zip(it.names, it.effective_module_paths):
                        mod_ref = mpath if mpath else iname
                        imported_modules.append(ImportedModuleRef(name=mod_ref, interface=iface_path))

        typed_prog = TypeElaborator(env=env).elaborate_program(ast_prog, env=env)
        emitter = CEmitter(echo=False, module_prefix=stem, env=env)
        c_code = emitter.emit_program(typed_prog)

        self.logger.log("EMIT C", str(c_path))
        c_path.write_text(c_code, encoding="utf-8")

        self.logger.log("HOST COMPILE", f"clang -c {c_path} -o {o_path}")
        compile_c_to_object(
            c_path,
            o_path,
            include_paths=search_paths,
            nogc=self.nogc,
            compiler_path=self.compiler_path,
            extra_flags=self.extra_c_flags,
        )

        manifest = ModuleManifest(
            name="<main>",
            interface=None,
            source=str(main_file.resolve()),
            object=str(o_path.resolve()),
            imported_modules=imported_modules,
            imported_interfaces=imported_interfaces,
        )
        self.logger.log("WRITE QM", str(qm_path))
        write_qm(manifest, qm_path)

        return (c_path, o_path, qm_path, imported_modules)

    def build_main(
        self,
        main_file: Path,
        output_binary: Optional[Path] = None,
    ) -> BuildResult:
        """Executes full separate compilation and linking for a Quest main routine."""
        main_file = main_file.resolve()
        if not main_file.is_file():
            raise BuildError(f"Main routine file not found: {main_file}")

        # Collision check on main routine
        colocated_mod = main_file.parent / f"{main_file.stem}.mod.quest"
        if colocated_mod.is_file():
            raise BuildError(
                f"Conflict: colocated main routine '{main_file.name}' and module '{colocated_mod.name}' "
                f"cannot coexist at '{main_file.parent}'"
            )

        if output_binary is None:
            target_bin = (self.build_dir / main_file.stem).resolve()
        else:
            target_bin = output_binary.resolve()

        self.logger.log(
            "BUILD START",
            f"target={main_file} mode=separate build_dir={self.build_dir}",
        )

        work_queue: deque[tuple[str, str, Optional[Path]]] = deque()
        # Queue item: (kind, name, source_path)
        work_queue.append(("main", main_file.stem, main_file))
        self.logger.log("QUEUE INIT", f"enqueued main routine '{main_file.stem}'")

        discovered_modules: set[str] = set()
        linked_objects: list[Path] = []
        compiled_units: list[str] = []
        module_graph: dict[str, list[str]] = {}

        while work_queue:
            kind, item_name, source_path = work_queue.popleft()
            self.logger.log("POP QUEUE", f"'{item_name}' (kind={kind})")

            if kind == "main":
                assert source_path is not None
                stem = source_path.stem
                qm_path = self.build_dir / f"{stem}.qm"
                c_path = self.build_dir / f"{stem}.c"
                o_path = self.build_dir / f"{stem}.o"

                stale = False
                reason = ""
                if not qm_path.is_file() or not c_path.is_file() or not o_path.is_file():
                    stale = True
                    reason = f"missing artifacts in {self.build_dir}"
                elif (
                    source_path.stat().st_mtime > qm_path.stat().st_mtime
                    or source_path.stat().st_mtime > c_path.stat().st_mtime
                    or c_path.stat().st_mtime > o_path.stat().st_mtime
                ):
                    stale = True
                    reason = "source file newer than artifacts"
                else:
                    manifest = read_qm(qm_path)
                    if manifest is None:
                        stale = True
                        reason = f"cannot parse {qm_path}"
                    else:
                        stale = is_manifest_stale(manifest, qm_path)
                        reason = "manifest indicates stale" if stale else ""

                if stale:
                    self.logger.log("EVAL STALENESS", f"'{item_name}' -> STALE ({reason})")
                    self.logger.log("COMPILE MAIN", f"'{item_name}'")
                    _, _, _, imported_mods = self.compile_main_unit(source_path)
                    compiled_units.append(item_name)
                else:
                    self.logger.log("EVAL STALENESS", f"'{item_name}' -> UP TO DATE")
                    manifest = read_qm(qm_path)
                    assert manifest is not None
                    imported_mods = manifest.imported_modules

                if o_path not in linked_objects:
                    linked_objects.append(o_path)

                for dep in imported_mods:
                    norm_dep = dep.name.lower()
                    if norm_dep in RUNTIME_BUILTINS:
                        continue
                    if dep.name not in discovered_modules and norm_dep not in discovered_modules:
                        discovered_modules.add(dep.name)
                        discovered_modules.add(norm_dep)
                        self.logger.log("ENQUEUE MODULE", f"'{dep.name}' (from main import)")
                        work_queue.append(("module", dep.name, None))

            elif kind == "module":
                search_paths = self._get_search_paths(main_file.parent)
                mod_src = resolve_module_file(item_name, main_file.parent, search_paths)

                canon_name = canonicalize_module_path(mod_src, search_paths) if mod_src else item_name.lower()
                if "/" in canon_name:
                    target_sub = self.build_dir / Path(canon_name).parent
                else:
                    target_sub = self.build_dir
                target_sub.mkdir(parents=True, exist_ok=True)
                stem = Path(canon_name).name.lower()

                qm_path = target_sub / f"{stem}.qm"
                c_path = target_sub / f"{stem}.c"
                o_path = target_sub / f"{stem}.o"

                # Check collision with colocated .quest
                if mod_src is not None:
                    colocated_quest = mod_src.parent / f"{stem}.quest"
                    if colocated_quest.is_file():
                        raise BuildError(
                            f"Conflict: colocated module '{mod_src.name}' and main routine "
                            f"'{colocated_quest.name}' cannot coexist at '{mod_src.parent}'"
                        )

                stale = False
                reason = ""
                if mod_src is None:
                    # Binary mode: if qm and o exist without source, it is up to date
                    if qm_path.is_file() and o_path.is_file():
                        stale = False
                    else:
                        raise BuildError(
                            f"Undefined module '{item_name}': cannot find source file "
                            f"or precompiled object in {search_paths}"
                        )
                else:
                    if not qm_path.is_file() or not c_path.is_file() or not o_path.is_file():
                        stale = True
                        reason = f"missing artifacts in {target_sub}"
                    elif (
                        mod_src.stat().st_mtime > qm_path.stat().st_mtime
                        or mod_src.stat().st_mtime > c_path.stat().st_mtime
                        or c_path.stat().st_mtime > o_path.stat().st_mtime
                    ):
                        stale = True
                        reason = "module source newer than artifacts"
                    else:
                        manifest = read_qm(qm_path)
                        if manifest is None:
                            stale = True
                            reason = f"cannot parse {qm_path}"
                        else:
                            stale = is_manifest_stale(manifest, qm_path)
                            reason = "manifest indicates stale" if stale else ""

                if stale:
                    assert mod_src is not None
                    self.logger.log("EVAL STALENESS", f"'{item_name}' -> STALE ({reason})")
                    self.logger.log("COMPILE MODULE", f"'{item_name}'")
                    compile_module_file(
                        mod_src,
                        output_dir=target_sub,
                        include_paths=search_paths,
                        build_dir=self.build_dir,
                        nogc=self.nogc,
                        compiler_path=self.compiler_path,
                        extra_c_flags=self.extra_c_flags,
                    )
                    compiled_units.append(item_name)
                    manifest = read_qm(qm_path)
                else:
                    self.logger.log("EVAL STALENESS", f"'{item_name}' -> UP TO DATE")
                    manifest = read_qm(qm_path)

                if manifest is None:
                    raise BuildError(f"Failed to load module manifest: {qm_path}")

                if o_path not in linked_objects:
                    linked_objects.append(o_path)

                module_graph[item_name] = [dep.name for dep in manifest.imported_modules]

                for dep in manifest.imported_modules:
                    norm_dep = dep.name.lower()
                    if norm_dep in RUNTIME_BUILTINS:
                        continue
                    if dep.name not in discovered_modules and norm_dep not in discovered_modules:
                        discovered_modules.add(dep.name)
                        discovered_modules.add(norm_dep)
                        self.logger.log("ENQUEUE MODULE", f"'{dep.name}' (from {item_name} import)")
                        work_queue.append(("module", dep.name, None))

        self.logger.log("QUEUE EMPTY", f"transitive closure verified ({len(linked_objects)} units)")

        # Cycle detection
        cycle = detect_module_cycle(module_graph)
        if cycle:
            cycle_str = " -> ".join(cycle)
            raise BuildError(f"Cyclic module dependency detected: {cycle_str}")

        # Native link
        self.logger.log("HOST LINK", f"linking {len(linked_objects)} objects into {target_bin}")
        link_objects(
            linked_objects,
            output_binary=target_bin,
            nogc=self.nogc,
            compiler_path=self.compiler_path,
            extra_flags=self.extra_c_flags,
        )
        self.logger.log("BUILD COMPLETE", f"exit_code=0 binary={target_bin}")

        return BuildResult(
            output_binary=target_bin,
            compiled_units=compiled_units,
            linked_objects=linked_objects,
            exit_code=0,
        )
