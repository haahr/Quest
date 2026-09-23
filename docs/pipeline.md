# Compiler Phase Pipeline Framework and Driver Architecture

This document describes the compiler phase pipeline framework, phase naming conventions, execution modes, and the
command-line driver interface (`quest` / `quest_driver.py`).

---

## 1. Overview of the Pipeline Architecture

The compiler processes Quest programs through a linear sequence of modular passes. Each pass implements the uniform
`Phase` interface and is managed by `PhasePipeline`:

```
                        +---------------------------------------------+
                        |               CompilerContext               |
                        | - source_text, file_name, source_map        |
                        | - sink: DiagnosticSink                      |
                        | - env: Environment (global/toplevel)        |
                        | - options: CompilerOptions                  |
                        +---------------------------------------------+
                                               |
  Source Code                                  v
==============> [ Phase: tokenize ]  ===> (tokens)
                       |
                       v
                [ Phase: parse ]     ===> (untyped AST)
                       |
                       v
                [ Phase: typecheck ] ===> (typed AST)
                    /        \
                   v          v
   [ Phase: interpret ]    [ Phase: codegen_c ]
            |                       |
            v                       v
    (runtime value)           (C99 source)
            |                       |
      Interactive/REPL         Host Compiler (clang/gcc)
                                    |
                                    v
                              (Native Binary)
```

### 1.1. Pipeline Modes
The compiler driver exposes three execution pipelines:
- **Default Pipeline (`default_pipeline()`):** `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$ `interpret`.
  Used by default for `quest <file>`, `quest -e "<code>"`, and interactive REPL sessions.
- **Compilation Pipeline (`compile_pipeline()`):** `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$ `codegen_c`.
  Used by `quest compile <file>`, translating typed AST into C99 source and building native binaries.
- **Full Execution Pipeline (`full_pipeline()`):** `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$
  `codegen_c` $\to$ `run_c_compiled`.
  Used for automated end-to-end compiled testing via `quest --stop-after run_c_compiled <file>`.

---

## 2. Phase Naming Conventions (Verb / Action Form)

All compiler phases are named by their **Verb / Action Form**:
- `tokenize`: Lexical analysis from source text to token stream.
- `parse`: Syntactic parsing from token stream to untyped AST.
- `typecheck`: Semantic typing, kind well-formedness, subtyping, and elaboration to typed AST.
- `interpret`: Direct evaluation of typed AST via tree-walking interpreter (Step 3). Returns final phrase
  `QValue`. Output is silent if `ok` (`QOk`), formatted if non-ok. Runtime I/O operations execute as direct
  side effects.
- `codegen_c`: C code generation (Step 4), translating typed AST into portable C99 source.
- `run_c_compiled`: Host compilation and execution of generated C code. Runs the binary and captures standard output.

### Uniform Enforcement Across Interfaces
1. **CLI Milestones:** `quest --stop-after <phase>` and `quest --dump-after <phase>`.
2. **Golden Output Directories:** `tests/golden/<phase>/<test>.out` (with `interpret` and `run_c_compiled` both
   mapping to `tests/golden/run/<test>.out`).
3. **Diagnostic Error Directories:** `tests/errors/<phase>/<test>.quest`.
4. **Pipeline Registries:** Internal registration via `pipeline.register(phase)`.

---

## 3. Core Framework Components (`bootstrap/python/quest/pipeline.py`)

### 3.1. `CompilerOptions`
Encapsulates runtime configuration:
- `stop_after: Optional[str]`: Pipeline milestone to halt after (implicitly dumping output).
- `dump_after: set[str]`: Intermediate phase outputs to dump to stdout while continuing pipeline execution.
- `include_paths: list[Path]`: Search directories for imported interfaces and modules (`-I`).
- `echo: bool`: When true, echoes top-level binding signatures and evaluated values in batch mode.
- `show_offsets: bool`: Controls rendering of source offsets in AST dumps.
- `show_values: bool`: Controls rendering of parsed literal values in token dumps.
- `emit_c: bool`: When true, outputs C source code without invoking the host C compiler.
- `output_path: Optional[Path]`: Output path for binary executable or emitted C source.
- `nogc: bool`: Forces compilation with `-DQUEST_NOGC`, disabling Boehm GC linkage.
- `print_result: bool`: When true, compiled binaries print Cardelli-format output for the final top-level phrase.

### 3.2. `CompilerContext`
Maintains shared state across phases:
- `source_text: str`, `file_name: str`, `source_map: SourceMap`.
- `sink: DiagnosticSink`: Collects diagnostics. The pipeline halts immediately if `sink.has_errors` is true.
- `env: Environment`: Top-level symbol table, preserved across incremental phrases in REPL sessions.
- `options: CompilerOptions`.

### 3.3. `Phase` Abstract Base Class
```python
class Phase(ABC):
    name: str              # Canonical verb name (e.g. "typecheck", "codegen_c")
    description: str       # Short summary
    artifact_name: str     # Data structure name (e.g. "typed_ast", "c_source")

    @abstractmethod
    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[Any]:
        """Processes input_data, emitting errors to ctx.sink on failure."""
        pass

    @abstractmethod
    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        """Renders the output artifact to canonical text."""
        pass
```

### 3.4. Pipeline Construction Factories
- **`default_pipeline() -> PhasePipeline`:** Registers `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$ `interpret`.
- **`compile_pipeline() -> PhasePipeline`:** Registers `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$ `codegen_c`.
- **`full_pipeline() -> PhasePipeline`:** Registers `tokenize` $\to$ `parse` $\to$ `typecheck` $\to$
  `codegen_c` $\to$ `run_c_compiled`.

---

## 4. Command-Line Interface (`quest` / `quest_driver.py`)

The compiler driver provides two primary subcommands: interpreter mode (the default) and native C compilation.

### 4.1. Default Mode: Interpretation & REPL (`quest`)
```bash
# Start interactive REPL directly:
quest

# Execute Quest file silently via interpreter:
quest file.quest

# Echo top-level bindings and expression results in batch execution:
quest --echo file.quest

# Execute file, then drop into interactive REPL:
quest -i file.quest

# Stop after a specific phase and print its canonical output:
quest --stop-after tokenize file.quest
quest --stop-after parse file.quest
quest --stop-after typecheck file.quest
quest --stop-after interpret file.quest
quest --stop-after run_c_compiled file.quest

# Dump intermediate outputs while continuing:
quest --dump-after parse --stop-after typecheck file.quest

# Execute inline code string:
quest -e "let x = 10 + 20; x"

# Add search paths for imports:
quest -I ./lib -I ./interfaces main.quest
```

### 4.2. Compilation Mode: Native Executable & C Emitter (`quest compile`)
```bash
# Compile Quest source to native binary (defaults to ./file):
quest compile file.quest

# Compile with explicit output binary name:
quest compile file.quest -o my_app

# Compile binary that prints the final phrase result (interactive Cardelli format):
quest compile file.quest --print-result -o my_app

# Emit C source code to stdout without invoking host compiler:
quest compile file.quest --emit-c

# Emit C source code to an explicit .c file:
quest compile file.quest --emit-c -o out.c

# Compile without Boehm GC (uses standard libc malloc/calloc):
quest compile file.quest --nogc -o my_app

# Compile inline code string to native binary:
quest compile -e "let x = 42; x" -o test_bin

# Stop after intermediate compilation phase:
quest compile --stop-after typecheck file.quest
quest compile --dump-after typecheck --stop-after codegen_c file.quest
```

### Exit Codes
- `0`: Successful compilation / execution (or successful early dump).
- `1`: User code error or host compilation error (diagnostic rendered via `DiagnosticRenderer`).
- `70` (`EX_SOFTWARE`): Internal compiler error / fatal diagnostic.

---

## See Also
- [codegen-c.md](codegen-c.md): C Code Generator architecture, AST lowering, and compiler runner.
- [c-representation.md](c-representation.md): C representation, `QVal` union, and runtime ABI design.
- [README.md](../README.md): Project overview and quickstart.
- [modules.md](modules.md): Module system, interfaces, information hiding, and file loader.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [syntax.md](syntax.md): Lexer, parser, and AST specification.
- [type-system.md](type-system.md): Type system, subtyping, and elaboration.
- [testing.md](testing.md): Testing framework and test runner conventions.
- [diagnostics.md](diagnostics.md): Diagnostic reporting architecture.

