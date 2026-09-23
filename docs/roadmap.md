# Quest Project Implementation Roadmap

This document outlines the seven-stage architecture for the Quest programming language implementation,
following a staged compiler methodology (inspired by Jeremy Siek's *Essentials of Compilation*).

The ultimate project goal is a **fully self-hosted implementation written in Quest itself**, capable of compiling to
native **AArch64 (ARM64)** machine code and providing a **JIT compiler** for interactive execution.

---

## Roadmap Architecture Diagram

```
+-----------------------------------------------------------------------------------+
| BOOTSTRAP IN PYTHON (Located in bootstrap/python/quest/)                          |
|                                                                                   |
|  [Step 1] Lexer, Parser, AST (Immutable frozen dataclasses) [COMPLETE]            |
|       │                                                                           |
|       ▼                                                                           |
|  [Step 2] Bidirectional Typechecker & Type Evaluator (Kernel F<: subtyping)       |
|       │   [COMPLETE]                                                              |
|       ▼                                                                           |
|  [Step 3] Tree-Walking Interpreter & Interactive REPL [COMPLETE]                  |
|       │                                                                           |
|       ▼                                                                           |
|  [Step 4] Bootstrap C Transpiler (Compiles Quest AST -> C99 + Boehm GC -> Binary) |
+-----------------------------------------------------------------------------------+
        │
        ▼
+-----------------------------------------------------------------------------------+
| SELF-HOSTING & NATIVE TARGETING IN QUEST (Located in src/)                        |
|                                                                                   |
|  [Step 5] Self-Hosted Front-End, Typechecker, & C Compiler (Ported to Quest)       |
|       │   • Compile self-hosted Quest using Python bootstrap C emitter            |
|       │   • Achieve self-compilation loop: Quest compiles Quest                   |
|       ▼                                                                           |
|  [Step 6] Self-Hosted Native AArch64 Compiler (Nanopass Pipeline)                 |
|       │   • Direct code generation replacing C emission (linked with Boehm GC)    |
|       ▼                                                                           |
|  [Step 7] Native AArch64 JIT & Interactive Incremental Runtime                    |
|           • In-process dynamic code emission and execution for REPL               |
+-----------------------------------------------------------------------------------+
```

---

## Detailed Stage Breakdown

### Step 1: Bootstrap Front-End (Python) — *Complete*
- **Tokenizer (Lexer):** Handles alphanumeric and symbolic identifiers, nested comments `(* ... *)`, string/char
  escape sequences, listfix constructs (`of ... end`, `of(...)`), and keyword rules. Each token tracks its starting
  character offset from the input start.
- **Parser:** PEG / recursive descent parser handling Quest grammar (uniform right-associative infix operators,
  initial/final keyword blocks, whitespace separation).
- **Abstract Syntax Tree (AST):** Immutable functional AST definitions using `@dataclass(frozen=True)`, directly
  mirroring Quest's `Tuple` and `Option` algebraic data structures.

### Step 2: Bootstrap Typechecker & Evaluator (Python) — *Complete*
- **Three-Level Environment:** Kinds (Level 2), Types/Operators (Level 1), and Values (Level 0).
- **Bidirectional Typechecker:** Term-level checking ($\Gamma \vdash e \Leftarrow T$) and synthesis
  ($\Gamma \vdash e \Rightarrow T$) following Dunfield & Krishnaswami, propagating contextual type information without
  global constraint solving.
- **Type Evaluator:** Normal-order typed $\lambda$-calculus evaluator for compile-time type operators (`Fun(S)A`).
- **Subtyping Engine (Kernel $F_{<:}^\omega$):**
  - Quantifier subtyping with invariant bounds to guarantee decidability and strong normalization in polynomial time.
  - Structural subtyping for tuples (width/depth), records (evidence dictionary), variants, options, and contravariant/
    covariant functions.
  - Subtyping and implicit dereferencing of `Var` (read-write conjunction / coercion to value type), `Out`
    (contravariant), `Array`, and `Still`.
  - Recursive subtyping with cycle detection (Amadio-Cardelli coinductive algorithm $\Sigma$).
  - Recursive contractiveness validation ($C \succ X$, Cardelli & Longo Section 2.4/2.9, rule `[T µ]`).
  - Bounded quantification (`A<:B` $\equiv$ `A::POWER(B)`).
- **Local Type Inference & Signatures:** Signature matching, manifest type/kind expansion (`Def`, `DEF`, `_`), and
  argument/parameter reconciliation.

### Step 3: Bootstrap Tree-Walking Interpreter & REPL (Python) — *Complete (Phases 3.1–3.6)*
- Tree-walking applicative-order interpreter executing typed AST representations.
- Subphase progress:
  - **Phase 3.1 (Runtime Values & Memory):** `QValue` class hierarchy, primitives, aggregates, heap reference cells
    (`QRef`), Cardelli object identity (`is` / `isnot`), and deep structural equality. — *Complete*
  - **Phase 3.2 (Environment & Core Evaluation):** Scoped lexical frames (`RuntimeEnvironment`), operators, truncation
    towards zero for integer division/modulo, loops, and `DivideByZero` exception handling. — *Complete*
  - **Phase 3.3 (Functions, Structures & Mutation):** Closures (`QClosure`), recursive bindings, record/tuple member
    selection, mutable record fields, mutable arrays (`QArray`), and `case` pattern matching. — *Complete*
  - **Phase 3.4 (Exceptions & Dynamic Types):** Exception declarations (`exception`), raising (`raise`), try-catch
    handlers (`try...when...else`), dynamic type packaging (`dynamic`), type inspection (`inspect`), language-level
    `dynamic.error`, and Cardelli-format exception diagnostics. — *Complete*
  - **Phase 3.5 (Cardelli Standard Library Modules):** Builtin modules (`writer`, `reader`, `conv`, `ascii`, `int`,
    `real`, `string`, `arrayOp`, `dynamic`), streams/files, and top-level `import` system. — *Complete*
  - **Phase 3.6 (Pipeline Integration, CLI & Interactive REPL):** `InterpretPhase` integration, `--echo` batch mode,
    `-i` / `--interactive` REPL launch, and persistent interactive multi-line REPL (`quest/repl.py`). — *Complete*
- Interpreter architecture in [interpreter.md](interpreter.md); REPL guide in [repl.md](repl.md); implementation
  plan in [step3-interpreter.md](step3-interpreter.md).

### Step 4: Bootstrap C Transpiler (Python)
- Multi-pass translation pipeline emitting standard ISO C99 linked with Boehm GC (`libgc`) or libc (`--nogc`):
  - **Phase 4.1 (Runtime ABI & Core Pipeline):** 64-bit `QVal` representation, `runtime/quest_runtime.h`,
    `compiler_runner.py` toolchain discovery, and `codegen_c` pipeline integration. — *Complete*
  - **Phase 4.2a (Top-Level & Recursive Functions):** Direct C calling convention, static hoisting, uncurrying
    flattening, and mutual recursion. — *Complete*
  - **Phase 4.2b (Tuples & Concrete Records):** C struct generation, typedef hoisting, heap allocation via
    `quest_alloc`, named/indexed field selection, and mutable field updates. — *Complete*
  - **Phase 4.2c (Closures & Function Values):** First-class closures, environment capture, lambda lifting,
    and indirect dispatch. — *Complete*
  - **Phase 4.3 (Arrays & Strings):** Fixed-size/dynamic arrays and extended string operations. — *Complete*
  - **Phase 4.4 (Options & Variants):** Ordered options, tagged variants, tag checks, and case
    discrimination. — *Complete*
  - **Phase 4.5 (Subtyping & Dynamic Dispatch):** Prefix tuple subtyping, evidence-passing record
    dictionaries, object headers, and static variant tag remapping. — *Complete*
  - **Phase 4.6 (Exceptions & Panics):** Exception values, try-when exception handling, and
    stack unwinding. — *Complete*
  - **Phase 4.7 (Whole-Program Modules & Interfaces):** Multi-file compilation, interface checking, module records,
    and linking. — *Complete*
  - **Phase 4.8 (Runtime Type Descriptors & Dynamic Module):**
    - *4.8a:* Runtime `QTypeDescriptor` structures, base descriptors, interning table, and `QDynamic`. — *Complete*
    - *4.8b:* Compiler quantifier calling convention and call-site descriptor synthesis. — *Complete*
    - *4.8c:* `dynamic` module lowering (`dynamic.new`, `dynamic.be`, `dynamic.copy`, `dynamic.error`) and generic
      wrappers. — *Complete*
  - **Phase 4.9 (Fat Pointers, Aggregate Subtyping, Specialization & Flat Stride Arrays):**
    - *4.9a:* Uniform 16-byte `QRecordVal` fat pointers and aggregate subtyping across records and tuples. —
      *Complete*
    - *4.9b:* Bounded specialization for records (`A <: Record`) and variants (`V <: Variant`). — *Complete*
    - *4.9c:* Call-site specialization for unbounded quantifiers (`All(A::TYPE)`). — *Complete*
    - *4.9d:* Flat stride arrays (`Array(Record)`, `Array(Variant)`) with zero heap boxing. — *Complete*
  - **Phase 4.10 (Standard Library Builtins & OS Primitives):** Cardelli standard library interfaces in C (`Writer`,
    `Reader`, `Conv`, `Ascii`, `IntOp`, `RealOp`, `StringOp`) and `System` OS extensions (`args`, `sysexit`,
    `getEnv`, `fileExists`, `error`). — *Complete*
  - **Phase 4.11 (Unified Native Module Mechanism & Hybrid Modules):** Unified declarative module pipeline,
    first-class `external` syntax for opaque C data structures (`type T = external "..."`) and native symbols
    (`let x = external "..."`), elimination of legacy Section 8c, and lazy module loading with concrete value
    records. — *Complete*
  - **Phase 4.12 (`out` and `var` Parameter Bindings with `@` References):** Passing lvalues and reference locations
    (`@x`, `@r.f`, `@a[i]`, `@t.1`, `var(e)`, chained paths) to `out` and `var` parameters, strict write-only
    enforcement for `out`, callsite `@` syntax enforcement, closure capture restrictions, and native pointer lowering
    (`T *`) with pointer forwarding in C transpilation. — *Complete*
  - **Phase 4.13 (Existential Tuples & Dot-Projections):** Packing packages (weak sums `Tuple A::TYPE ... end`),
    path-type projection (`p.T`), member projection (`p.v`), closure adaptation thunks for abstract signatures,
    native unboxing for bounded path-types (`A <: T`), and structural tuple coercion in C transpilation. — *Complete*
  - **Phase 4.14 (Dynamic Subtyping & Compound Type Descriptors):** Static and dynamic compound type descriptors
    (records, tuples, variants, options, arrays, functions, opaques), unified structural subtyping in C runtime
    (`quest_is_subtype` with coinductive cycle detection), dynamic value adaptation (`quest_record_adapt` for width,
    permutation, and depth subtyping; `quest_variant_adapt` for tag remapping), static `.rodata` descriptor emission,
    and `inspect` expression branching. — *Complete*
  - **Phase 4.15 (Dynamic Serialization: `dynamic.extern` & `dynamic.intern`):** C runtime implementation of
    text-format serialization and deserialization of typed dynamic packages (`dynamic.extern` converting arbitrary typed
    values into serialized text streams with cyclic reference preservation, and `dynamic.intern` parsing stream
    inputs back into dynamically typed values validated against compound type descriptors). Fully compatible and
    interchangeable with the interpreter's JSON/JSOG representation (`dynamic_json.py`). Step 1 (`dynamic.extern` native
    emission, dynamic module builtin cleanup, static descriptor auto-registration) is complete; Step 2 (`dynamic.intern`
    streaming JSON parser and type deserialization) is in progress.
- **Bootstrap Compiler Completion Prerequisites:**
  - *Separate Compilation & Object Linking:* Compiling modules independently to `.o` files with header/interface
    exports and linking.
  - *Dynamic Serialization Completion:* Finalizing Step 2 (`dynamic.intern`) in Phase 4.15.
- C transpiler architecture in [codegen-c.md](codegen-c.md);
  C ABI specification in [c-representation.md](c-representation.md);
  language extensions specification in [extensions.md](extensions.md).

### Step 5: Self-Hosted Compiler & Interpreter (Written in Quest)
- Port the Python implementations of Steps 1–4 into idiomatic Quest.
- Implement essential collection and data structure libraries in Quest (hash tables, string buffers, extensible arrays)
  to support the compiler's own internals.
- Compile the self-hosted Quest compiler using the Python bootstrap transpiler.
- Validate bootstrap fixed-point: `Quest(Quest) == Quest`.

### Step 6: Native AArch64 Code Generator (Written in Quest)
- Replace C transpilation with native AArch64 machine code generation via small nanopass compiler passes:
  1. *Desugaring & Type Elimination*
  2. *Closure Conversion & Hoisting*
  3. *A-Normal Form (ANF) / Monadic IR*
  4. *Instruction Selection (AArch64 assembly AST)*
  5. *Liveness Analysis & Register Allocation (Graph Coloring / Linear Scan)*
  6. *Prolog/Epilog Generation & Binary/Assembly Emission (linked with `libgc`)*
- Follows the evidence-passing object model detailed in [runtime-design.md](runtime-design.md).

### Step 7: Native AArch64 JIT & Interactive Incremental Runtime
- In-process dynamic code emission and execution for REPL.
- Dynamic patching and hot-swapping of evaluated phrases.

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [syntax.md](syntax.md): Lexer, parser, and untyped AST specification.
- [type-system.md](type-system.md): Semantic types, subtyping theory, and elaboration.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
- [runtime-design.md](runtime-design.md): Object representation (Evidence Passing vs Fat Pointers) and ABI.
- [interpreter.md](interpreter.md): Interpreter runtime architecture, value model, and semantic decisions.
- [step3-interpreter.md](step3-interpreter.md): Step 3 interpreter and REPL implementation plan.
- [extensions.md](extensions.md): Necessary OS and CLI extensions to the core language.
