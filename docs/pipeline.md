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
                       |
                       v
                [ Phase: interpret ] ===> (runtime value / output)
                       |
                       v
                [ Phase: codegen ]   ===> (AArch64 machine code / C)
```

---

## 2. Phase Naming Conventions (Verb / Action Form)

All compiler phases are named by their **Verb / Action Form**:
- `tokenize`: Lexical analysis from source text to token stream.
- `parse`: Syntactic parsing from token stream to untyped AST.
- `typecheck`: Semantic typing, kind well-formedness, subtyping, and elaboration to typed AST.
- `interpret`: Evaluation of typed AST via tree-walking interpreter (Step 3).
- `codegen`: Code generation to C or native AArch64 machine code.

### Uniform Enforcement Across Interfaces
1. **CLI Milestones:** `quest --stop-after <phase>` and `quest --dump-after <phase>`.
2. **Golden Output Directories:** `tests/golden/<phase>/<test>.out`.
3. **Diagnostic Error Directories:** `tests/errors/<phase>/<test>.quest`.
4. **Pipeline Registries:** Internal registration via `pipeline.register(phase)`.

---

## 3. Core Framework Components (`bootstrap/python/quest/pipeline.py`)

### 3.1. `CompilerOptions`
Encapsulates runtime configuration:
- `stop_after: Optional[str]`: Pipeline milestone to halt after (implicitly dumping output).
- `dump_after: set[str]`: Intermediate phase outputs to dump to stdout while continuing pipeline execution.
- `include_paths: list[Path]`: Search directories for imported interfaces and modules (`-I`).
- `show_offsets: bool`: Controls rendering of source offsets in AST dumps.
- `show_values: bool`: Controls rendering of parsed literal values in token dumps.

### 3.2. `CompilerContext`
Maintains shared state across phases:
- `source_text: str`, `file_name: str`, `source_map: SourceMap`.
- `sink: DiagnosticSink`: Collects diagnostics. The pipeline halts immediately if `sink.has_errors` is true.
- `env: Environment`: Top-level symbol table, preserved across incremental phrases in REPL sessions.
- `options: CompilerOptions`.

### 3.3. `Phase` Abstract Base Class
```python
class Phase(ABC):
    name: str              # Canonical verb name (e.g. "typecheck")
    description: str       # Short summary
    artifact_name: str     # Data structure name (e.g. "typed_ast")

    @abstractmethod
    def run(self, input_data: Any, ctx: CompilerContext) -> Optional[Any]:
        """Processes input_data, emitting errors to ctx.sink on failure."""
        pass

    @abstractmethod
    def dump(self, output_data: Any, ctx: CompilerContext) -> str:
        """Renders the output artifact to canonical text."""
        pass
```

### 3.4. `PhasePipeline`
Manages the sequence of passes and provides two primary entry points:
- **`compile_file(path: Path, options, ctx) -> PipelineResult`:** Batch compilation mode.
- **`compile_phrase(phrase_text: str, options, ctx) -> PipelineResult`:** Incremental mode for the interactive REPL,
  preserving `ctx.env` across phrases.

---

## 4. Command-Line Interface (`quest` / `quest_driver.py`)

The unified driver accepts files, standard input, or inline code:

```bash
# Execute through default target (interpret/run)
quest file.quest

# Stop after a specific phase and print its canonical output:
quest --stop-after tokenize file.quest
quest --stop-after parse file.quest
quest --stop-after typecheck file.quest

# Dump intermediate outputs while continuing:
quest --dump-after parse --stop-after typecheck file.quest

# Inline code:
quest -c "let x = 1;" --stop-after typecheck

# Add search paths for imports:
quest -I ./lib -I ./interfaces main.quest
```

Accepts both dashed (`--stop-after`) and underscored (`--stop_after`) flag formats.

### Exit Codes
- `0`: Successful compilation / execution (or successful early dump).
- `1`: User code error (diagnostic rendered via `DiagnosticRenderer`).
- `70` (`EX_SOFTWARE`): Internal compiler error / fatal diagnostic.

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [syntax.md](syntax.md): Lexer, parser, and AST specification.
- [type-system.md](type-system.md): Type system, subtyping, and elaboration.
- [testing.md](testing.md): Testing framework and test runner conventions.
- [diagnostics.md](diagnostics.md): Diagnostic reporting architecture.
