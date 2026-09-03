# Quest Bootstrap Tree-Walking Interpreter & REPL Plan (Step 3)

This document preserves the comprehensive architecture and multi-phase implementation plan for **Step 3: The Bootstrap
Tree-Walking Interpreter and Interactive REPL** for Quest in `bootstrap/python/quest/`.

---

## 1. Architectural Overview

The interpreter consumes the typed AST (`TypedProgram`, `TypedBinding`, `TypedExpr`) produced by term elaboration and
executes it via direct tree-walking evaluation.

```
+------------------------------------+
| TypedProgram / TypedExpr           |
| (from Term Elaboration Phase 2)    |
+------------------------------------+
                 |
                 v
+------------------------------------+
| tree_eval_expr(expr, runtime_env)  |
| - Runtime Values (QInt, QReal...)  |
| - Call Frames & Scopes             |
| - Mutable Cell References (QRef)   |
| - Dynamic Dispatch & Pattern Match |
| - Exception Stack Unwinding        |
+------------------------------------+
                 |
                 v
+------------------------------------+
| Execution Result / Output / REPL   |
+------------------------------------+
```

---

## 2. Multi-Phase Implementation Plan

### Phase 1: Runtime Values & Memory Model (`quest/runtime.py`)
- Define runtime value representation hierarchy (`QValue`):
  - **Primitives:** `QInt(value: int)`, `QReal(value: float)`, `QBool(value: bool)`, `QChar(value: str)`,
    `QString(value: str)`, `QOk()`.
  - **Aggregates:**
    - `QRecord(fields: dict[str, QValue])`
    - `QTuple(elements: tuple[QValue, ...])`
    - `QArray(elements: list[QValue])` (mutable element buffer)
  - **Sum / Disjoint Types:**
    - `QVariant(tag: str, payload: Optional[QValue])`
    - `QOption(tag: str, payload: Optional[QValue])`
  - **Functions & Closures:**
    - `QClosure(params: tuple[str, ...], body: TypedExpr, captured_env: RuntimeEnvironment)`
    - `QBuiltinFun(name: str, fn: Callable[..., QValue])`
  - **Mutability:**
    - `QRef(value: QValue)` (heap cell for `var` bindings and assignable fields)
  - **Dynamic & Exceptions:**
    - `QExceptionVal(name: str, payload: Optional[QValue])`
    - `QDynamicVal(value: QValue, type_val: QType)`
- Canonical value string formatter (`qvalue_to_str(val: QValue) -> str`) and equality predicates.

### Phase 2: Runtime Environment & Core Evaluation (`quest/interpreter.py`)
- `RuntimeEnvironment` with scoped lexical frame chains (`lookup`, `define`, `assign`, `push_scope`, `pop_scope`).
- Arithmetic, logical, and relational operators (`+`, `-`, `*`, `/`, `mod`, `<`, `<=`, `>`, `>=`, `=`, `<>`).
- Short-circuit boolean evaluations (`andif`, `orif`).
- Mutable variable assignment (`TypedAssign`) and dereferencing (`TypedDerefCell`).
- Control flow structures:
  - Conditionals (`TypedIf`)
  - Loops (`TypedLoop`, `TypedWhile`, `TypedFor` with `:upto` and `:downto`)
  - Loop termination (`TypedExit` via internal Python control-flow exception `_LoopExit`).
  - Scoped blocks (`TypedBlock`).

### Phase 3: Functions, Closures & Recursion
- First-class function closure creation (`TypedFun` -> `QClosure`).
- Application evaluation (`TypedApp`): evaluate callee, evaluate arguments, bind parameters in a fresh activation
  scope, evaluate body.
- Recursive functions (`let rec f = ...`) with cyclic closure environments.
- Type applications (`TypedTypeApp`): evaluate inner expression (type erasure at runtime).

### Phase 4: Compound Data Structures & Mutation
- Record creation (`TypedRecord`) and field selection (`TypedSelect`).
- Tuple creation (`TypedTuple`) and indexing/selection.
- Array creation (`TypedArray`, `TypedArrayRep`).
- Array indexing (`TypedIndex`) and element assignment (`TypedIndexAssign`).
- Record field mutation (`r.field := value` updating the `QRef` cell).

### Phase 5: Variants, Options & Pattern Matching
- Option creation (`TypedOption`) and Variant creation (`TypedVariant`).
- Case expression matching (`TypedCase`): match tag against branches, unpack payload binding into branch scope,
  evaluate matching branch body, fall back to `else_branch`.

### Phase 6: Exceptions & Dynamic Typing
- Exception declaration (`TypedExceptionDecl`).
- Raising exceptions (`TypedRaise` via Python control-flow exception `QuestRuntimeException`).
- Try-handler evaluation (`TypedTry`): evaluate body; if exception matches handler tag, bind payload and evaluate
  handler body; otherwise propagate or fallback to `else_branch`.
- Dynamic typing: `TypedDynamic(expr)` packaging value with its type, `TypedInspect` type-case matching.

### Phase 7: Interfaces, Modules & Standalone CLI (`quest_run.py`)
- Module evaluation (`TypedModule`): evaluate bindings sequentially, capture exported members into a `QRecord` or
  `QModuleValue`.
- Standalone CLI runner: `python3 bootstrap/python/quest_run.py <file.quest>` with error diagnostics and exit codes.

### Phase 8: Interactive REPL (`quest_repl.py`) & End-to-End Suite
- Multi-line input REPL maintaining persistent `Environment` (types) and `RuntimeEnvironment` (values).
- Expression evaluation auto-printing (`it = <val> : <Type>`).
- End-to-end integration tests (`tests/python/test_interpreter.py`).

---

## 3. Native Quest Call Stack Traces & Runtime Error Handling

To provide high-fidelity runtime diagnostics (rather than raw Python tracebacks), the interpreter maintains a stack
of Quest activation frames:

- **Activation Frame Tracking (`RuntimeStackFrame`):**
  - When evaluating `TypedApp`, push a frame with `function_name`, `file_name`, `call_offset`, and `scope_name`.
  - Pop the frame upon normal or exceptional return.
- **Runtime Error & Exception Capture (`QuestRuntimeError`):**
  - Both uncaught language-level exceptions (`raise E with payload`) and system invariant violations (division by zero,
    array out of bounds, non-exhaustive match failure) capture the current `list[RuntimeStackFrame]`.
- **Source-Mapped Traceback Formatting:**
  - Formatted using `SourceMap` to display file, line, column, function name, and underlined source call-site:
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
- **Reference:** See [`diagnostics.md`](diagnostics.md) for full details.

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
- [type-system.md](type-system.md): Semantic types, subtyping, and elaboration.
