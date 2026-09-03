# Quest Diagnostic, Error, and Warning Handling Architecture

This document specifies the comprehensive design for diagnostics, error reporting, warnings, error recovery, and
runtime error handling across the Quest compiler, interpreter, and REPL.

---

## 1. Design Goals and Principles

1. **Lightweight Offset Tracking:** Every error or warning identifies its location using a 0-indexed character offset
   in the source text, mapping to `(file, line, column)` coordinates on demand via `SourceMap`.
2. **Clear Separation of Problem, Context, and Remedy:**
   - **Problem (`Severity`):** The operational status (`FATAL`, `ERROR`, `WARNING`, `INFO`).
   - **Context (`notes` & `secondary_labels`):** Explanatory source positions and background information (e.g. "type
     defined here", "previously declared here").
   - **Remedy (`help_text` & `suggestions`):** Prescriptive advice or machine-applicable code replacements.
3. **Single-Pass Error Accumulation & Poison Recovery:** The typechecker can collect multiple independent errors across
   a compilation unit instead of halting on the very first error, using an error sentinel type (`QErrorType`) to prevent
   cascading false positives.
4. **Immediate Fatal Abort with Full Prior Diagnostic Reporting:** Unrecoverable conditions (such as Internal Compiler
   Errors) emit a `FATAL` diagnostic which raises a `FatalDiagnosticError`. The outermost driver catches this exception
   and renders all prior accumulated diagnostics alongside the fatal diagnostic before terminating.
5. **Human and Machine Readability:** Formatter supports terminal rendering (with ANSI color highlighting and
   ASCII/Unicode source box gutters) as well as structured JSON/LSP output.
6. **Quest-Aware Runtime Stack Traces:** Runtime errors in the tree-walking interpreter provide native Quest call stack
   traces with source locations, function names, and callee expressions.

---

## 2. Core Diagnostic Data Structures

### 2.1. Severity
```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Callable

class Severity(Enum):
    """Operational severity of a diagnostic message."""
    FATAL = "fatal"      # Unrecoverable error / Internal Compiler Error (ICE); stops all passes
    ERROR = "error"      # User error; compilation proceeds to collect more errors if possible
    WARNING = "warning"  # Compilation proceeds; potential bug or style issue
    INFO = "info"        # Informational note or statistic
```

### 2.2. Labels and Actionable Suggestions
```python
@dataclass(frozen=True)
class DiagnosticLabel:
    """An annotated source position highlighting code context within a diagnostic."""
    offset: int
    length: int = 1
    message: Optional[str] = None
    is_primary: bool = True

@dataclass(frozen=True)
class CodeSuggestion:
    """An actionable fix that can be automatically applied by an IDE/LSP or displayed as a diff."""
    offset: int
    length: int
    replacement: str
    description: str
```

### 2.3. The `Diagnostic` Object and Fatal Exception
```python
@dataclass
class Diagnostic:
    severity: Severity                                # FATAL, ERROR, WARNING, or INFO
    message: str                                      # Primary error description
    primary_label: Optional[DiagnosticLabel] = None   # Underline on faulty code (if source-linked)
    secondary_labels: list[DiagnosticLabel] = field(
        default_factory=list
    )                                                 # Contextual positions (e.g. "type defined here")
    notes: list[str] = field(default_factory=list)    # Explanatory background facts
    help_text: Optional[str] = None                   # Actionable human advice
    suggestions: list[CodeSuggestion] = field(
        default_factory=list
    )                                                 # Machine-applicable quick-fixes
    error_code: Optional[str] = None                  # e.g., "E0102" or "ICE9001"

class FatalDiagnosticError(Exception):
    """Raised immediately by DiagnosticSink when a FATAL diagnostic is emitted."""
    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
```

---

## 3. Diagnostic Sink & Reporting Pipeline

### 3.1. `DiagnosticSink`
Instead of exclusively raising arbitrary exceptions, compiler passes emit diagnostics to a `DiagnosticSink`:

```
+----------------+       emit(diag)       +-------------------+
| Compiler Pass  | ---------------------> |  DiagnosticSink   |
| (Typechecker / |                        |  - errors: list   |
|  Elaborator)   | <--------------------- |  - warnings: list |
+----------------+   has_errors?          +-------------------+
        |                                           |
        | FATAL emitted?                            | render(source_map)
        v (raises FatalDiagnosticError)             v
+------------------------------------+    +-------------------+
| Outermost Driver (catches fatal,   | -> | Terminal / Stream |
| prints accumulated diagnostics)    |    +-------------------+
+------------------------------------+
```

```python
class DiagnosticSink:
    """Collects diagnostics during compilation phases."""
    def __init__(self, fail_fast: bool = False, warnings_as_errors: bool = False):
        self.diagnostics: list[Diagnostic] = []
        self.fail_fast = fail_fast
        self.warnings_as_errors = warnings_as_errors

    def emit(self, diag: Diagnostic) -> None:
        self.diagnostics.append(diag)
        if diag.severity == Severity.FATAL:
            raise FatalDiagnosticError(diag)
        if self.fail_fast and diag.severity == Severity.ERROR:
            raise FatalDiagnosticError(diag)

    @property
    def has_errors(self) -> bool:
        return any(
            d.severity in (Severity.FATAL, Severity.ERROR)
            or (self.warnings_as_errors and d.severity == Severity.WARNING)
            for d in self.diagnostics
        )

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity in (Severity.FATAL, Severity.ERROR))

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == Severity.WARNING)
```

### 3.2. Outermost Driver Handling
```python
def compile_stream(source_text: str, file_name: str) -> int:
    source_map = SourceMap(source_text, file_name)
    sink = DiagnosticSink()
    try:
        tokens = tokenize_with_sink(source_text, file_name, sink)
        tree = parse_with_sink(tokens, source_map, sink)
        typed_tree = elaborate_with_sink(tree, env, sink)
        if sink.has_errors:
            render_diagnostics(sink, source_map)
            return 1
        return 0
    except FatalDiagnosticError:
        # Render all diagnostics accumulated up to the fatal error, including the fatal error itself
        render_diagnostics(sink, source_map)
        return 2
```

---

## 4. Phase-by-Phase Diagnostic Strategy

### 4.1. Tokenizer & Parser
- **Tokenizer:**
  - Errors: Invalid characters, unterminated string literals, unterminated block comments `(* ... *)`, malformed
    numeric literals.
  - Recovery: Tokenizer can emit an `ERROR_TOKEN` and continue to find other lexical issues, or fail-fast on malformed
    files.
- **Parser (PEG / Packrat):**
  - Errors: Syntax errors at the furthest parsed token offset.
  - Information: Expected token kinds vs encountered token kind.

### 4.2. Kind & Type Elaboration (Phase 2)
- **Error Accumulation with Poison Type (`QErrorType`):**
  - When an expression fails typechecking (e.g. `1 + "str"`), the typechecker records a `Diagnostic(ERROR, ...)` in the
    sink and returns `TypedErrorExpr(type_val=QErrorType())`.
  - `QErrorType` is a universal sentinel:
    - `is_subtype(QErrorType(), AnyType) == True`
    - `is_subtype(AnyType, QErrorType()) == True`
    - Synthesizing an operation on `QErrorType` produces `QErrorType` *without emitting secondary errors*.
  - This stops a single bad variable definition from generating 50 downstream errors across an entire module.
- **Compiler Warnings:**
  - **Unused Local Bindings:** `let unused = ...` where `unused` is never read in scope.
  - **Variable Shadowing:** Declaring `let x = ...` when an outer `x` is in scope (configurable warning).
  - **Unreachable Code:** Expressions appearing after `exit` or `raise` within a block.
  - **Redundant Explicit Dereferencing:** Using `@var` in an expression where implicit dereference occurs.
  - **Incomplete Pattern Matching:** Warning if a `case` or `inspect` omits branches and lacks an `else` branch.
- **Internal Compiler Errors (`FATAL`):**
  - AST node invariant violations (e.g. malformed synthetic nodes or missing type annotations during lowering).

### 4.3. Runtime Interpreter & Execution (Phase 3)
Runtime errors are divided into two categories:

#### 1. Language-Level Quest Exceptions (`TypedRaise` / `TypedTry`)
- User-defined exceptions declared with `let exc = exception of T end;` and raised via `raise exc with payload`.
- Caught by `try ... when exc with p => ... end`.
- If uncaught, the runtime unrolls the call stack and displays a formatted exception report:
  ```
  Unhandled Quest Exception: StackUnderflow (payload: "empty stack")
    Traceback (most recent call last):
      File "stack.quest", line 18, in pop
        raise StackUnderflow with "empty stack"
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      File "main.quest", line 5, in run
        let item = stack.pop()
                   ^^^^^^^^^^^
      File "main.quest", line 12, in <toplevel>
        run()
        ^^^^^
  ```

#### 2. System / Language Invariant Violations
- **Division by Zero:** `x / 0` or `x mod 0`.
- **Array Out of Bounds:** Accessing `arr[i]` where `i < 0` or `i >= arr.length`.
- **Pattern Match Exhaustion:** Option or Variant tag without matching `when` arm and no `else`.
- **Dynamic Type Failure:** Dynamic `inspect` tag without matching arm and no `else`.
- **Uninitialized Variable Access:** Cyclic recursion accessing uninitialized cell.

#### Runtime Call Stack Frame Model
```python
@dataclass
class RuntimeStackFrame:
    function_name: str
    file_name: str
    call_offset: int
    call_length: int
    scope_name: str

class QuestRuntimeError(Exception):
    def __init__(self, message: str, offset: int = 0, length: int = 1):
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.length = length
        self.quest_traceback: list[RuntimeStackFrame] = []

    def format_traceback(self, source_map_provider: Callable[[str], Any]) -> str:
        lines = [f"Runtime Error: {self.message}", "Traceback (most recent call last):"]
        for frame in reversed(self.quest_traceback):
            sm = source_map_provider(frame.file_name)
            loc = sm.locate(frame.call_offset)
            lines.append(f"  File \"{frame.file_name}\", line {loc.line}, in {frame.function_name}")
            source_line = sm.format_error(frame.call_offset, frame.call_length, "").splitlines()
            if len(source_line) > 1:
                lines.extend(f"    {l}" for l in source_line[1:])
        return "\n".join(lines)
```

---

## 5. Diagnostic Renderer & Visual Formatting

### 5.1. Output Format Example
```
error[E0105]: record type mismatch
  --> src/geometry.quest:14:10
   |
 4 | Let Point = Tuple x: Int y: Int end;
   |             ^ note: expected type defined here
...
14 | let p: Point = tuple x = 10 y = "20" end;
   |                ^ field 'y' has type 'String', expected 'Int'
   |
   = help: try converting the string using 'Int.fromString(y)'
```

---

## 6. Implementation & Integration Roadmap

1. **Step 2.5 (Foundation):**
   - Create `quest/diagnostics.py` implementing `Severity` (`FATAL`, `ERROR`, `WARNING`, `INFO`), `DiagnosticLabel`,
     `CodeSuggestion`, `Diagnostic`, `FatalDiagnosticError`, `DiagnosticSink`, and `DiagnosticRenderer`.
   - Ensure diagnostic formatting operates purely on `SourceMap` offsets.
2. **Step 3 Integration (Interpreter):**
   - Implement `QuestRuntimeError` and `RuntimeStackFrame` tracking inside `tree_eval_expr` and function calls in
     `interpreter.py`.
   - Ensure unhandled exceptions and runtime errors print clean, source-mapped Quest stack traces.
3. **Step 3 REPL Integration:**
   - REPL uses `DiagnosticSink` to display concise inline diagnostics without blowing away the REPL session.
4. **Step 4 (Typechecker Error Recovery & Warnings):**
   - Introduce `QErrorType` and optional multi-error collection in `typechecker.py`.
