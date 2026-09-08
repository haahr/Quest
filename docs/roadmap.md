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
|  [Step 3] Tree-Walking Interpreter & Interactive REPL [IN PROGRESS]               |
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
- Multi-pass translation pipeline:
  1. *Desugaring*: Expand listfix forms, while/for loops, `andif`/`orif`.
  2. *Closure Conversion*: Explicit environments and function pointers.
  3. *Data Representation Lowering*: Untagged 64-bit integers, uniform pointer representations, static dictionaries.
  4. *C99 Code Generation*: Standalone C output linked with Boehm GC (`libgc`).
  5. *Exception Handling*: Exception lowering for compiled C execution.
  6. *Module System*: Multi-file include path lookup and separate compilation linking.

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
