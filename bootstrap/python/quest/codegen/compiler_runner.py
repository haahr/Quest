"""Host C Compiler Driver and Binary Execution Runner."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def find_c_compiler() -> str:
    """Locates host C compiler (clang preferred, fallback to gcc)."""
    for candidate in ("clang", "gcc"):
        path = shutil.which(candidate)
        if path is not None:
            return path
    raise RuntimeError("No C compiler (clang or gcc) found in PATH")


def get_runtime_dir() -> Path:
    """Returns absolute path to repository runtime/ directory."""
    # Assuming bootstrap/python/quest/codegen/ -> repo_root / runtime
    this_file = Path(__file__).resolve()
    repo_root = this_file.parent.parent.parent.parent.parent
    runtime_dir = repo_root / "runtime"
    if not runtime_dir.exists():
        raise RuntimeError(f"Runtime directory not found at {runtime_dir}")
    return runtime_dir


def detect_gc_flags(nogc: bool = False) -> list[str]:
    """Detects Boehm GC include/lib flags, falling back to -DQUEST_NOGC."""
    if nogc:
        return ["-DQUEST_NOGC"]

    candidates = [
        Path("/opt/homebrew/opt/bdw-gc"),
        Path("/usr/local/opt/bdw-gc"),
        Path("/usr"),
    ]
    for prefix in candidates:
        inc = prefix / "include"
        lib = prefix / "lib"
        if (inc / "gc.h").exists():
            flags = [f"-I{inc}"]
            if (lib / "libgc.dylib").exists() or (lib / "libgc.so").exists() or (lib / "libgc.a").exists():
                flags.extend([f"-L{lib}", "-lgc"])
                return flags

    # Fallback to nogc if not found
    return ["-DQUEST_NOGC"]


def compile_c_source(
    c_source: str,
    output_binary: Optional[Path | str] = None,
    nogc: bool = False,
    compiler_path: Optional[str] = None,
    extra_flags: Optional[list[str]] = None,
    output_path: Optional[Path | str] = None,
) -> Path:
    """Compiles a generated C source string into an executable binary."""
    out_target = output_path if output_path is not None else output_binary
    if out_target is None:
        raise ValueError("output_binary or output_path must be specified")
    target_bin = Path(out_target)
    compiler = compiler_path or find_c_compiler()
    runtime_dir = get_runtime_dir()
    runtime_c = runtime_dir / "quest_runtime.c"

    # Create temporary .c file for the source
    with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False, encoding="utf-8") as f:
        f.write(c_source)
        temp_c_path = Path(f.name)

    try:
        cmd = [
            compiler,
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-O2",
            f"-I{runtime_dir}",
            str(runtime_c),
            str(temp_c_path),
            "-o",
            str(target_bin),
        ]
        cmd.extend(detect_gc_flags(nogc=nogc))
        if extra_flags:
            cmd.extend(extra_flags)

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"C compilation failed with exit code {proc.returncode}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"{proc.stderr}"
            )
        return target_bin
    finally:
        if temp_c_path.exists():
            temp_c_path.unlink()


def run_binary(
    binary_path: Path,
    args: Optional[list[str]] = None,
    env: Optional[dict[str, str]] = None,
    input_data: Optional[str] = None,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    """Executes a compiled binary and returns stdout/stderr/returncode."""
    cmd = [str(binary_path)] + (args or [])
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        input=input_data,
        timeout=timeout,
    )

