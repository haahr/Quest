# Quest Bootstrap Tree-Walking Interpreter & REPL Plan (Step 3)

This document preserves the comprehensive architecture, output semantics, standard library modules, and implementation
plan for **Step 3: The Bootstrap Tree-Walking Interpreter and Interactive REPL** in `bootstrap/python/quest/`.

---

## 1. Architectural Overview

The interpreter consumes the typed AST (`TypedProgram`, `TypedBinding`, `TypedExpr`) produced by the `typecheck` phase
and executes it via direct tree-walking evaluation.

```
+------------------------------------+
| TypedProgram / TypedExpr           |
| (from Typecheck Phase)             |
+------------------------------------+
                 │
                 ▼
+------------------------------------+
| tree_eval_expr(expr, runtime_env)  |
| - Runtime Values (QInt, QReal...)  |
| - Call Frames & Lexical Scopes     |
| - Mutable Cell References (QRef)   |
| - Cardelli Standard Library Modules|
| - Direct I/O Side Effects          |
| - Exception Stack Unwinding        |
+------------------------------------+
                 │
                 ▼
+------------------------------------+
| Final Value (QValue) / REPL Echo   |
+------------------------------------+
```

---

## 2. Output Semantics and Execution Modes

The interpreter strictly separates direct I/O side effects from phase return values:

1. **I/O As Side Effects:**
   - I/O operations (such as `writer.putString`) write directly to standard output/error as runtime side effects.
   - I/O is **not** captured, buffered, or tracked as `InterpretPhase` data.

2. **Phase Output (`InterpretPhase`):**
   - The result of `InterpretPhase.run` is the evaluated `QValue` of the program's final phrase.
   - `InterpretPhase.dump(value)`:
     - If the value is `ok` (`QOk`), output is **completely silent** (empty string).
     - If the value is non-ok, renders the canonical formatted value string.

3. **Batch Execution vs. REPL Discipline:**
   - **Batch Execution (`quest file.quest`):** By default, runs silently (Option A). Emits only explicit I/O
     side effects. Top-level expressions and bindings execute without echoing their values. If the `--interactive`
     flag is specified, echoes every top-level binding and expression result.
   - **Interactive REPL (`quest` without arguments, or REPL session):** Always echoes binding signatures and evaluated
     results (Option B):
     ```quest
     Quest> let x: Int = 40 + 2;
     val x: Int = 42
     Quest> x * 2;
     84 : Int
     ```

---

## 3. Standard Library Modules (Cardelli Specification)

In accordance with Luca Cardelli's *Typeful Programming* (Section 11.3), standard operations are organized into
pre-linked modules and interfaces in the root environment:

- **`writer: Writer`:** Character and string output (`writer.output`, `writer.putString`, `writer.putChar`,
  `writer.flush`).
- **`reader: Reader`:** Character and string input (`reader.input`, `reader.getString`, `reader.getChar`).
- **`conv: Conv`:** Value to string conversions (`conv.int`, `conv.real`, `conv.bool`, `conv.okay`).
- **`ascii: Ascii`:** Ascii character encoding conversions (`ascii.char`, `ascii.val`).
- **`int: IntOp` & `real: RealOp`:** Numeric operations and functions.
- **`string: StringOp`:** String manipulation (`string.length`, `string.getSub`, `string.cat`).
- **`arrayOp: ArrayOp`:** Array operations (`arrayOp.new`, `arrayOp.size`, `arrayOp.get`, `arrayOp.set`).

---

## 4. Multi-Phase Implementation Plan

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
- Canonical value string formatter (`qvalue_to_str(val: QValue) -> str`) and structural equality predicates.

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

### Phase 3: Functions, Compound Structures & Mutation
- First-class function closure creation (`TypedFun` -> `QClosure`).
- Application evaluation (`TypedApp`): evaluate callee, evaluate arguments, bind parameters in fresh activation scope,
  evaluate body.
- Recursive functions (`let rec f = ...`) with cyclic closure environments.
- Record and tuple creation (`TypedRecord`, `TypedTuple`) and member selection.
- Array creation (`TypedArray`, `TypedArrayRep`), indexing, and element mutation.
- Record field mutation (`r.field := value`).
- Option/Variant construction and `case` pattern matching (`TypedCase`).

### Phase 4: Exceptions & Cardelli Standard Library Modules (`quest/builtins.py`)
- Exception declaration (`TypedExceptionDecl`).
- Raising exceptions (`TypedRaise` via Python control-flow exception `QuestRuntimeException`).
- Try-handler evaluation (`TypedTry`): evaluate body; if exception matches handler tag, bind payload and evaluate
  handler body; otherwise propagate or fallback to `else_branch`.
- Pre-linked standard library module implementations: `writer: Writer`, `reader: Reader`, `conv: Conv`,
  `ascii: Ascii`, `string: StringOp`, `int: IntOp`, `real: RealOp`, `arrayOp: ArrayOp`.

### Phase 5: Pipeline Integration, CLI & Interactive REPL (`quest/repl.py`)
- `InterpretPhase` registered in `PhasePipeline` following `typecheck`:
  - Output: final phrase `QValue`.
  - Silent when `QOk`, formatted when non-ok.
- CLI driver support: default execution runs through `interpret`. Flag `--interactive` enables top-level echo in batch.
- Interactive multi-line REPL (`quest` without files) maintaining persistent `Environment` and `RuntimeEnvironment`.
- Integration tests in `tests/python/test_interpreter.py` and compiler golden tests in `tests/golden/interpret/`.

---

## 5. Native Quest Call Stack Traces & Runtime Error Handling

To provide high-fidelity runtime diagnostics (rather than raw Python tracebacks), the interpreter maintains a stack
of Quest activation frames:
- **Activation Frame Tracking (`RuntimeStackFrame`):** Pushes frame with function name, file name, call offset, and
  scope; pops upon normal or exceptional return.
- **Source-Mapped Traceback Formatting:** Formats unhandled exceptions or runtime errors using `SourceMap` with exact
  file, line, column, and caret underlines.

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
- [type-system.md](type-system.md): Semantic types, subtyping, and elaboration.
- [diagnostics.md](diagnostics.md): Diagnostic reporting architecture.
