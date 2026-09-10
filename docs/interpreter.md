# Quest Bootstrap Tree-Walking Interpreter & REPL

This document details the architecture, runtime value representation, evaluation engine, and semantic decisions
implemented for the Step 3 bootstrap tree-walking interpreter in `bootstrap/python/quest/runtime.py` and
`bootstrap/python/quest/interpreter.py`.

---

## 1. Subsystem Overview

The Step 3 interpreter executes typed Quest abstract syntax trees (`TypedProgram`) directly without bytecode
compilation or machine code generation. It serves three primary purposes:

1. **Bootstrap Ground Truth:** Provides immediate operational semantics validating the typechecker and grammar.
2. **Interactive Development:** Powers the interactive REPL and single-phrase execution (`quest -c "... "`).
3. **Reference Verification:** Acts as an executable specification to verify subsequent native ARM64 code generation.

The interpreter consumes the typed AST produced by `typecheck` and produces runtime Quest values (`QValue`).

```
                              ┌─────────────────────────┐
                              │    TypedProgram AST     │
                              └────────────┬────────────┘
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            bootstrap/python/quest/                                  │
│                                                                                     │
│   ┌───────────────────────────────┐           ┌─────────────────────────────────┐   │
│   │   RuntimeEnvironment          │           │   Operational Evaluator         │   │
│   │   (interpreter.py)            │           │   (interpreter.py)              │   │
│   │                               │           │                                 │   │
│   │   • Scoped lexical frames     │           │   • eval_expr(expr, env)        │   │
│   │   • push_scope() / pop_scope()│ ◄───────► │   • eval_binding(binding, env)  │   │
│   │   • define() / lookup()       │           │   • eval_program(program, env)  │   │
│   │   • assign() / QRef mutation  │           │   • _LoopExit / QuestException  │   │
│   └───────────────────────────────┘           └────────────────┬────────────────┘   │
│                                                                │                    │
│                                                                ▼                    │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │   Runtime Values & Memory Model (runtime.py)                                │   │
│   │                                                                             │   │
│   │   • QOk, QBool, QInt, QReal, QChar, QString                                 │   │
│   │   • QRecord (sorted keys), QTuple (positional/named), QArray (mutable)      │   │
│   │   • QVariant, QOption, QClosure, QBuiltinFun, QRef, QDynamicVal             │   │
│   │   • Cardelli 'is' / 'isnot' (qvalue_is) & deep equality (qvalue_structural) │   │
│   │   • Canonical string formatting with cycle detection (qvalue_to_str)        │   │
│   └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
                              ┌─────────────────────────┐
                              │   Output QValue / I/O   │
                              └─────────────────────────┘
```

---

## 2. Runtime Value Hierarchy (`QValue`)

All runtime Quest values derive from the abstract base class `QValue` in `quest/runtime.py`. Every `QValue` provides
a human-readable `type_name` and a `to_str(visited)` method supporting cycle detection.

### 2.1. Primitive Values

| Class | Quest Type | Underlying Python Representation | Canonical Format (`to_str`) |
| :--- | :--- | :--- | :--- |
| `QOk` | `Ok` | Singleton unit instance (`OK_VALUE`) | `"ok"` |
| `QBool` | `Bool` | Singletons `TRUE_VALUE`, `FALSE_VALUE` | `"true"`, `"false"` |
| `QInt` | `Int` | 64-bit signed integer (`int`) | `"42"`, `"-7"` |
| `QReal` | `Real` | 64-bit IEEE float (`float`) | `"2.0"`, `"3.14"` (guarantees decimal) |
| `QChar` | `Char` | 1-character string (`str`) | `"'a'"`, `"'\\n'"`, `"'\\''"` |
| `QString` | `String` | UTF-8 string (`str`) | `"\"hello\\n\""` |

### 2.2. Aggregates and Data Structures

- **`QRecord(fields: dict[str, QValue])`:**
  - Represents unordered collections of labeled fields.
  - Canonical formatting sorts fields alphabetically: `record a=1 b="two" end`.
- **`QTuple(elements: tuple[QValue, ...], labels: Optional[tuple[Optional[str], ...]])`:**
  - Represents ordered sequences supporting dual access: positional indexing via `get_by_index(i)` and labeled
    member selection via `get_by_name(label)`.
  - Formats positional tuples as `tuple 1 2 "three" end` and labeled tuples as `tuple count=10 name="ten" end`.
- **`QArray(elements: list[QValue])`:**
  - Represents fixed-size, mutable linear buffers (`get(i)`, `set(i, val)`, `size()`).
  - Formats as `array of 1 2 3 end`.
- **`QList(elements: tuple[QValue, ...])`:**
  - Represents immutable linear lists.
  - Formats as `list of 1 2 3 end` (or `list of end` for empty lists).
- **`QVariant(tag, payload)` & `QOption(tag, payload, ordinal=0)`:**
  - Represent tagged sum types with optional payloads.
  - `QOption` tracks the zero-based declaration index `ordinal` of the tag, accessible via the `ordinal` operator.
  - Formats as `variant red with 42 end` or `option none end`.

### 2.3. Closures, Functions, and Mutability

- **`QClosure(params, body, env, name=None)`:**
  - Captures the formal parameter names, typed body AST, and lexical activation `RuntimeEnvironment`.
  - Formats as `"<fun>"` (or `"<fun:name>"` if named).
- **`QBuiltinFun(name, fn, doc=None)`:**
  - Wraps host Python callables for primitive operations and standard library modules. Formats as `"<builtin:name>"`.
- **`QRef(value: QValue)`:**
  - Represents mutable heap cells allocated for `let var` bindings, assignable record fields (`r.a := v`), and
    variable parameters (`:var`).
  - Supports `deref() -> QValue` and `assign(new_value: QValue)`. Formats as `ref(<val>)`.
- **`QDynamicVal(value: QValue, type_val: Any)` & `QExceptionVal(name: str, payload: Optional[QValue])`:**
  - Envelopes for dynamic typing (`dynamic.new(:T v)`) and runtime exception tagging.

---

## 3. Operational Evaluation Engine

The evaluator in `quest/interpreter.py` evaluates typed expressions and bindings:

### 3.1. Scoped Runtime Environment (`RuntimeEnvironment`)
- Operates as a tree of lexical environment frames (`parent: Optional[RuntimeEnvironment]`).
- `push_scope()`: Creates an inner scope for block expressions, function applications, and loop variable frames.
- `pop_scope()`: Restores the enclosing scope.
- `define(name, value)`: Binds a symbol in the local frame.
- `lookup(name)`: Searches outward from innermost to outermost frame; raises `QuestRuntimeError` if missing.
- `assign(name, new_value)`: Resolves an existing variable and either mutates its `QRef` cell or updates the binding.
- `create_root_env()`: Factory pre-populating:
  - Standard constants: `true`, `false`, `ok`, and `DivideByZero`.
  - Monadic operators: `not` (boolean negation), `extent` (array size), `ordinal` (option tag index).
  - Dyadic arithmetic and comparison operators: `+`, `-`, `*`, `/`, `%`, `mod`, `<`, `<=`, `>`, `>=`,
    `++`, `--`, `**`, `//`, `^^`, `<<`, `<<=`, `>>`, `>>=`, `<>`, `/\`, `\/`, `is`, `isnot`.
  - Pre-linked standard library module records: `arrayOp`, `ascii`, `conv`, `dynamic`, `int`, `list`, `reader`,
    `real`, `string`, `writer`.

### 3.2. Evaluation Rules

- **Literals:** Directly construct corresponding primitive `QValue` objects.
- **Variables & Dereferencing:**
  - `TypedVar(name, symbol)`: Evaluates to the symbol's value (or `QRef` cell) in `env`.
  - `TypedDerefCell(target)`: Evaluates `target`; if a `QRef`, extracts `ref.deref()`.
  - `TypedVarCell(value)`: Allocates a new heap reference cell `QRef(eval_expr(value))`.
  - `TypedAssign(target, value)`: Evaluates `value`, mutates the target reference cell, and returns `OK_VALUE`.
- **Arithmetic & Modulo:**
  - Evaluates integer operators (`+`, `-`, `*`, `/`, `mod`, `%`) and real operators (`++`, `--`, `**`, `//`, `^^`).
- **Relational & Equality:**
  - Integer comparisons `<`, `<=`, `>`, `>=`.
  - Real comparisons `<<`, `<<=`, `>>`, `>>=`.
  - String concatenation `<>`.
  - Equality `is` via `qvalue_is()`; inequality `isnot`.
- **Monadic Operators:**
  - Evaluates `not` (inverts `QBool`), `extent` (returns `QInt` array size), and `ordinal` (returns `QInt` tag index).
- **Conditionals:**
  - `TypedIf`: Evaluates condition; conditionally evaluates `then_branch` or `else_branch`. Short-circuit logic
    (`andif`, `orif`) is handled directly via desugared `TypedIf` nodes.
- **Loops & Control Flow:**
  - `TypedLoop`: Executes body repeatedly until `_LoopExit` is caught; returns `OK_VALUE`.
  - `TypedWhile`: Evaluates condition before each iteration; breaks on `false` or `_LoopExit`.
  - `TypedFor`: Binds the iteration variable in an isolated scope; iterates over inclusive bounds; returns `OK_VALUE`.
  - `TypedExit`: Raises `_LoopExit`.
- **Blocks:**
  - `TypedBlock`: Pushes scope, evaluates bindings sequentially, evaluates the result expression, pops scope.
- **Records & Tuples:**
  - `TypedRecord`: Evaluates fields, wrapping mutable fields (`is_var=True`) in `QRef`. Formats with sorted keys.
  - `TypedTuple`: Evaluates elements, preserving component labels from `QTupleType`. Supports `t.fieldName`.
  - `TypedSelect`: Resolves field on `QRecord` or `QTuple`; automatically dereferences `QRef` in value positions.
  - `TypedSelectRef`: Resolves field on `QRecord` returning the underlying `QRef` without dereferencing (for `@r.f`).
- **Arrays & Mutation:**
  - `TypedArray`: Evaluates elements into mutable `QArray`.
  - `TypedArrayRep`: Evaluates `init_val` exactly once and replicates it across `count` slots.
  - `TypedIndex`: Array indexing `arr[i]`. Raises `arrayOp.error` if out of bounds.
  - `TypedIndexAssign`: Array element mutation `arr[i] := v`. Raises `arrayOp.error` if out of bounds.
  - `TypedAssign`: Extends to record field mutation `r.field := v`.
- **Variants, Options, and Pattern Matching:**
  - `TypedVariant`: Injects tag with optional evaluated payload into `QVariant`.
  - `TypedOption`: Injects tag with optional evaluated payload and branch `ordinal`. Supports runtime ordinal
    expressions (`option ordinal(n) of T ...`), determining tag dynamically from index `n`.
  - `TypedVariantCheck`: Evaluates `target?tag`, returning `true` on match.
  - `TypedVariantAssert`: Evaluates `target!tag`. On `QOption`, returns a `QTuple` with 0-based ordinal as element 0
    followed by the payload components (e.g. `tuple 1 let x=true end`). On `QVariant`, returns the payload directly.
  - `TypedCase`: Evaluates target, matches `target.tag` against branch tags, binds payload to `binder` in child
    scope, and executes branch body. Evaluates `else_branch` if no tag matches.
- **Functions & Recursion:**
  - `TypedFun`: Captures current `env` in a `QClosure`.
  - `TypedTypeApp`: Evaluates callee directly (type erasure).
  - `TypedApp`: Evaluates callee and arguments, creates a child frame binding parameters to arguments, and
    evaluates closure body.
  - `TypedLetValue` with `is_rec=True`: Automatically binds recursive closures into their own environment frame.

---

## 4. Key Architectural & Semantic Decisions

### 4.1. Batch Mode vs. Interactive / REPL Output Semantics
- **Batch Mode (Default):**
  - Completely silent by default (Option A).
  - Emits only explicit runtime I/O side effects (e.g. from `writer.putString`).
  - Top-level bindings and expressions execute silently when executing files.
  - If `--interactive` is passed on the CLI, top-level binding signatures and evaluated results are echoed.
- **Inline Execution (`quest -c '<program>'`) and Interactive Mode:**
  - Evaluates phrases sequentially; only the final phrase produces output (consistent with batch phase semantics).
  - Uses Cardelli's canonical top-level interactive output notation:
    - **Expressions:** Formatted as `<value> : <Type>` (e.g. `42 : Int`). If the expression evaluates to `ok`
      (such as loops, assignments, or explicit `ok;`), output is completely silent.
    - **Value Declarations:** Formatted as `let <name>:<Type> = <value>` (or `let var <name>:<Type> = <value>`
      for mutable bindings). E.g. `let x:Int = 10`.
    - **Type Declarations:** Formatted as `Let <name>::<Kind> = <Type>` (e.g. `Let Color::TYPE = Option red green end`).
    - **Kind Declarations:** Formatted as `DEF <name> = <Kind>`.
- **Phase Output:**
  - `InterpretPhase` returns the final phrase `QValue`.
  - Phase dump output (`InterpretPhase.dump`) formats the final phrase via `format_interactive_result`.

### 4.2. Cardelli Standard Library Modules for I/O
- Rather than inventing custom I/O primitives, runtime I/O strictly follows Cardelli's standard library modules:
  - `writer: Writer`: `putString`, `putChar`, `putInt`, `putReal`, `newLine`, `flush`.
  - `reader: Reader`: `getString`, `getChar`, `getInt`, `getReal`, `isEof`.
  - `conv: Conv`: String-to-number and number-to-string conversions.
  - `ascii: Ascii`: Character classification and ASCII conversions.
  - `int: IntOp`, `real: RealOp`, `string: StringOp`, `arrayOp: ArrayOp`: Dedicated operations.
- Runtime I/O functions write directly to `sys.stdout` and `sys.stderr` as unbuffered operational side effects.

### 4.3. Cardelli Identity vs. Content Equality (`is` / `isnot`)
- Implements Luca Cardelli's exact specification from *Typeful Programming* (Section 3.1):
  - **Ordinary Value Equality:** Applied to primitive types `Ok`, `Bool`, `Char`, `Int`, and `Real`.
  - **Object Identity ("Same Memory Location"):** Applied to all other types (`String`, `Array`, `Record`, `Tuple`,
    `Variant`, `Option`, `Closure`, `Ref`). Distinct string instances compare as `false` under `is`.
  - Content equality for strings is handled via `string.equal(s1, s2)`.
  - A deep recursive structural equality predicate (`qvalue_structural_eq`) with coinductive cycle detection is
    provided for test assertions and data comparisons.

### 4.4. Integer Division and Modulo Semantics
- **Truncation Toward Zero:** Integer division (`/`) and modulo (`%`, `mod`) truncate toward zero as specified by
  Cardelli (C/Modula-3/MIPS style), differing from Python's floor division:
  - `{0 - 7} / 2` evaluates to `-3` (Python `-7 // 2` is `-4`).
  - `{0 - 7} % 2` evaluates to `-1` (Python `-7 % 2` is `1`).
  - Satisfies invariant: `(a / b) * b + (a % b) == a`.
- **Divide by Zero:** Division or modulo by zero raises a language-level `DivideByZero` exception
  (`QuestException(DIVIDE_BY_ZERO_EXC)`), taking no payload.

### 4.5. Loop Bounds & Inclusive Iteration
- **Inclusive Range:** For loops (`for k = start upto stop do body end` and `downto`) execute over inclusive ranges
  (`start <= k <= stop` for `upto`, `start >= k >= stop` for `downto`).
- **Zero Iterations:** If bounds are inverted (`10 upto 5`), the loop body executes 0 times.
- **Isolated Loop Variable:** The loop variable `k` is scoped exclusively to the loop body and does not leak into
  the enclosing scope.

### 4.6. Canonical Formatting & Cycle Detection
- Record fields are formatted in sorted key order (`record a=1 b=2 end`) to ensure deterministic output for testing.
- Formatter tracks visited object memory addresses (`visited: set[int]`); upon detecting recursive reference cycles
  (e.g. self-referential mutable records `r.self := r`), emits `...` rather than overflowing the stack.

### 4.7. Array Operations & `arrayOp.error` Exception
- Out-of-bounds indexing (`arr[i]`), out-of-bounds assignment (`arr[i] := v`), and negative array repetition sizes
  raise `QuestException(QExceptionVal("arrayOp.error"))` following Cardelli's `ArrayOp` interface specification.

### 4.8. Array Repetition Evaluation Semantics
- In `array of(count init)`, `init` is evaluated exactly once, and its resulting value is shared across all `count`
  element positions (sharing the underlying object identity for compound or mutable values).

### 4.9. Tuple Member Selection
- Tuple members are selected by label via dot notation (`t.fieldName`) when component labels are present in the
  tuple signature (`tuple let fieldName = val end`). Unlabeled positional tuple components are accessed via pattern
  matching or function parameter binding; no synthetic numeric fields are introduced.

### 4.10. Exceptions and Exception Diagnostics
- **Exception Values & Declaration:**
  - `exception Name: Type end` creates a `QExceptionVal` tag and binds `Name` in the runtime environment.
  - `raise exc with payload end` evaluates `exc` (tag) and optional payload, raising a `QuestException`.
  - `try ... when exc with binder then ... else ... end` catches `QuestException`, matching by exception tag identity.
- **Root `DivideByZero` Exception:**
  - Bound in `Environment.create_root_env()` with `EXCEPTION_TYPE` as a language extension to Cardelli's spec.
- **Cardelli Diagnostic Format:**
  - Uncaught exceptions produce diagnostics matching Cardelli's interactive format:
    - With payload: `Exception: <name> with <payload_str>:<payload_type>`
    - Without payload (or Ok): `Exception: <name>`
- **Dynamic Type Reflection & `dynamic.error`:**
  - Dynamic packaging via `dynamic.new(:Type val)` (or inferred `dynamic.new(val)`) creates a
    `QDynamicVal(value, type_val)`.
  - Type narrowing via `dynamic.be(:Type d)` dynamically validates that `d`'s packaged type is a subtype of the target
    type, returning the unwrapped value or raising `dynamic.error` (`DYNAMIC_ERROR_EXC`) on mismatch.
  - Type inspection via `inspect dyn when Type with b then ... else ... end` checks subtyping dynamically.
  - If no `when` branch matches and no `else` branch is supplied, raises the language-level exception `dynamic.error`
    (`DYNAMIC_ERROR_EXC`).
  - Legacy bare `dynamic(val)` syntax is removed in favor of `dynamic.new`.

### 4.11. Standard Library Modules & Import System
- **Module Pre-linking & Import Semantics (Cardelli §11.3):**
  - Standard library modules (`arrayOp`, `ascii`, `conv`, `dynamic`, `int`, `list`, `reader`, `real`, `string`,
    `writer`) and their interfaces (`ArrayOp`, `Ascii`, `Conv`, `Dynamic`, `IntOp`, `List`, `Reader`, `RealOp`,
    `StringOp`, `Writer`) are pre-linked at the top level and in the interactive REPL. They can be used directly
    without an `import` statement outside of modules.
  - Standalone modules (`module ... end`) are isolated from top-level pre-linked module records and must explicitly
    import any required modules using `import mod: Interface`.
  - `BuiltinModuleRegistry` resolves all 10 standard interfaces and runtime module records.
- **List Operations (`list: List`):**
  - Built-in `list` module backed by runtime `QList` values.
  - Provides `nil`, `cons`, `null`, `head`, `tail`, `length`, `enum`, and `error`.
- **String Substring Precedence (`StringOp.precedesSub`):**
  - `string.precedesSub(s1, start1, size1, s2, start2, size2)` compares substrings lexicographically, raising
    `string.error` on invalid indices.
- **Dynamic Module (`dynamic: Dynamic`):**
  - Provides `new`, `be`, `copy`, `extern`, `intern`, and `error`.
- **I/O Streams & Files:**
  - `writer.output` connects to `sys.stdout`; `writer.err` connects to `sys.stderr` (language extension).
  - `writer.file(name)` and `reader.file(name)` manage real file handles, raising `writer.error` / `reader.error` on
    I/O failures.
  - `reader.input` connects to `sys.stdin`; `reader.ready()` returns 0.
- **Cardelli Negative Number Conventions:**
  - `conv.int` and `conv.real` prefix negative numbers with tilde `~` (e.g. `"~42"`).
- **String Mutability:**
  - `string.setChar` and `string.setSub` mutate `QString` values in-place while preserving object identity.
- **Array Operations:**
  - `arrayOp.new`, `arrayOp.size`, `arrayOp.get`, and `arrayOp.set` operate directly on the built-in `QArray` type
    and raise `arrayOp.error` on boundary violations.

---

## 5. Implementation Status

| Phase | Description | Components | Status |
| :--- | :--- | :--- | :--- |
| **3.1** | Runtime Values & Memory | `QValue` hierarchy, primitives, aggregates, identity/equality | **Complete** |
| **3.2** | Environment & Core Eval | `RuntimeEnvironment`, scoping, operators, loops, DivideByZero | **Complete** |
| **3.3** | Structures & Mutation | Record/tuple selection, array operations, `case` matching | **Complete** |
| **3.4** | Exceptions & Dynamic | `try...with`, `raise`, `inspect`, dynamic type reflection | **Complete** |
| **3.5** | Cardelli Stdlib Modules | 10 standard modules, I/O streams, pre-linking & imports | **Complete** |
| **3.6** | Pipeline & REPL | `InterpretPhase`, `--echo`, `-i`, interactive REPL (`repl.py`) | **Complete** |

---

## See Also

- [docs/repl.md](repl.md): Interactive REPL guide, prompts, multi-line rules, and terminal handling.
- [docs/step3-interpreter.md](step3-interpreter.md): Multi-phase implementation roadmap for Step 3.
- [docs/pipeline.md](pipeline.md): Compiler phase pipeline and unified CLI driver options.
- [docs/type-system.md](type-system.md): Typechecker architecture, semantic types, and term typing rules.
- [docs/TypefulProgramming.md](TypefulProgramming.md): Cardelli's foundational treatise on Quest and language semantics.
