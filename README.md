# Quest Programming Language Implementation

An implementation of the **Quest** programming language, as specified by Luca Cardelli in [*Typeful Programming*](docs/TypefulProgramming.md) (DEC SRC Research Report 45, 1989 / 1993).

---

## 1. Overview and Objectives

Quest (a quasi-acronym for **Qu**antifiers and **S**ub**t**ypes) is a strongly typed, expression-based language integrating:
- **Three-level hierarchy:** Values (Level 0), Types and Type Operators (Level 1), and Kinds (Level 2).
- **Higher-order type system:** System $F_{<:}^\omega$ with bounded universal and existential quantifiers, higher-order type operators, recursive types, and power kinds (`POWER(B)`).
- **Subtyping and Inheritance:** Structural subtyping across tuples, records, variants, options, higher-order functions, and recursive types.
- **Unified Modules and Dynamic Typing:** Modules and interfaces represented as first-class tuples and signatures with manifest type/kind bindings; dynamic typing via self-describing automorphic types (`Dynamic` / `Auto`).
- **Execution Modes:** Both an interactive read-eval-print loop (REPL) and ahead-of-time (AOT) batch compilation.

The ultimate project goal is a **fully self-hosted implementation written in Quest itself**, capable of compiling to native **AArch64 (ARM64)** machine code and providing a **JIT compiler** for interactive execution.

---

## 2. Proposed Implementation Roadmap

To maintain clarity, traceability, and ease of porting, development proceeds in seven stages following a staged compiler architecture (inspired by Jeremy Siek's *Essentials of Compilation*):

```
+-----------------------------------------------------------------------------------+
| BOOTSTRAP IN PYTHON (Located in bootstrap/python/quest/)                          |
|                                                                                   |
|  [Step 1] Lexer, Parser, AST (Immutable frozen dataclasses)                       |
|       │                                                                           |
|       ▼                                                                           |
|  [Step 2] Bidirectional Typechecker & Type Evaluator (Kernel F<: subtyping)       |
|       │                                                                           |
|       ▼                                                                           |
|  [Step 3] Tree-Walking Interpreter (REPL & testing)                               |
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

### Step 1: Bootstrap Front-End (Python in `bootstrap/python/quest/`)
- **Tokenizer (Lexer):** Handles alphanumeric and symbolic identifiers, nested comments `(* ... *)`, string/char escape sequences, listfix constructs (`of ... end`, `of(...)`), and keyword capitalization rules. Each token tracks only its starting character offset from the input start.
- **Parser:** Recursive descent / Pratt parser handling Quest grammar (uniform right-associative infix operators, initial/final keyword blocks, whitespace separation).
- **Abstract Syntax Tree (AST):** Immutable functional AST definitions using `@dataclass(frozen=True)` (revisited if recursion requires mutability), directly mirroring Quest's `Tuple` and `Option` algebraic data structures.

### Step 2: Bootstrap Typechecker (Python)
- **Three-Level Environment:** Kinds, Types/Operators, and Values.
- **Bidirectional Typechecker:** Term-level checking ($\Gamma \vdash e \Leftarrow T$) and synthesis ($\Gamma \vdash e \Rightarrow T$) following Dunfield & Krishnaswami, propagating contextual type information and enabling local type inference without global unification.
- **Type Evaluator:** Normal-order typed $\lambda$-calculus evaluator for compile-time type operators (`Fun(S)A`, `ALL(S)K`).
- **Subtyping Engine (Kernel $F_{<:}$):**
  - Quantifier subtyping with invariant bounds to guarantee decidability and strong normalization in polynomial time.
  - Structural subtyping for tuples (width/depth), records (evidence dictionary), variants, options, and contravariant/covariant functions.
  - Subtyping and implicit dereferencing of `Var` (read-write conjunction / coercion to value type), `Out` (contravariant), `Array`, and `Still`.
  - Recursive subtyping with cycle detection (Amadio-Cardelli coinductive algorithm).
  - Bounded quantification (`A<:B` $\equiv$ `A::POWER(B)`).
- **Local Type Inference & Signatures:** Signature matching, manifest type/kind expansion (`Def`, `DEF`, `_`), and argument/parameter reconciliation.

### Step 3: Bootstrap Interpreter (Python)
- Tree-walking applicative-order interpreter.
- First-class closures, tuples, records, mutable cells (`var`), arrays, exceptions (`try...when...raise`), and basic standard library interfaces (`IntOp`, `StringOp`, `ArrayOp`, `Conv`, `Dynamic`).

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
- Implement essential collection and data structure libraries in Quest (hash tables/dictionaries, string buffers, extensible arrays) to support the compiler's own internals.
- Compile the self-hosted Quest compiler using the Python bootstrap transpiler.
- Validate bootstrap fixed-point: `Quest(Quest) == Quest`.

### Step 6: Native AArch64 Code Generator (Written in Quest)
- Replace C transpilation with native AArch64 machine code generation via small compiler passes:
  1. *Desugaring & Type Elimination*
  2. *Closure Conversion & Hoisting*
  3. *A-Normal Form (ANF) / Monadic IR*
  4. *Instruction Selection (AArch64 assembly AST)*
  5. *Liveness Analysis & Register Allocation (Graph Coloring / Linear Scan)*
  6. *Prolog/Epilog Generation & Binary/Assembly Emission (linked with `libgc`)*

### Step 7: AArch64 JIT & Interactive Runtime
- In-memory code buffer emission using executable memory allocation (`mmap` with `MAP_JIT` on macOS / `pthread_jit_write_protect_np`).
- Incremental compilation and dynamic linking of top-level REPL declarations into the live execution space.
- Native exception unwinding across in-process JIT frames and runtime helpers.

---

## 3. Architecture Decisions & Scope

### 3.1. Record and Variant Dispatch Strategy

In Quest, **tuples** (`Tuple ... end`) and **options** (`Option ... end`) are strictly ordered, allowing static compile-time field index calculation. In contrast, **records** (`Record ... end`) and **variants** (`Variant ... end`) are unordered named collections that support multiple inheritance (arbitrary DAG subtyping hierarchies).

#### Plan of Record: Approach A (Call-Site Evidence Passing) with Object Headers

The Plan of Record for record/variant dispatch is **Approach A: Call-Site Evidence Passing**, augmented with **Object Header Words**:

- **Mechanism for Static Dispatch:**  
  When a function expects a record type $R = \text{Record } x_1:T_1 \dots x_k:T_k \text{ end}$, it receives the record pointer along with an implicit **evidence dictionary** argument. The dictionary is a statically allocated array of field offsets:
  $$\text{dict} = [\text{offset}(x_1), \text{offset}(x_2), \dots, \text{offset}(x_k)]$$
  Field selection $r.x_i$ compiles to:
  $$\text{value} = *(\text{RecordPtr} + \text{dict}[i])$$
  On AArch64, this emits just two instructions:
  ```asm
  ldr  w1, [x_dict, #0]          ; Load field offset from static dictionary
  ldr  x0, [x_record, w1, uxtw]  ; Load field value from record object
  ```

- **Object Header Words for Static/Dynamic Transitions:**  
  All heap-allocated records and dynamic values carry a 1-word **Object Header** pointing to their runtime type descriptor / shape. For transitions between static and dynamic types (such as `Dynamic_T`, `Auto`, `inspect`, and base subsumptions to generic types like `Object`), the runtime inspects this header word directly to identify types and extract fields. This alleviates the need to pass explicit type evidence everywhere for general types.

- **The Cascading Thunk Allocation Issue:**  
  Under pure call-site evidence passing, when a higher-order function undergoes contravariant subtyping (e.g., passing `(Car -> Int)` where `(Object -> Int)` is expected), the compiler must synthesize an $\eta$-expansion adapter thunk to convert the caller's dictionary arguments to the callee's expected dictionary. In deeply nested higher-order pipelines or recursive callbacks, this can create cascading thunk allocations (`wrapper(wrapper(f))`), adding allocation overhead and interfering with tail calls.  
  Using object header words for general/dynamic types mitigates this issue by allowing functions expecting generic objects to read shape metadata directly from object headers without requiring synthesized dictionary wrapper thunks.

#### Comparison: Approach A vs. Approach B (Fat Pointers)

| Dimension | Approach A: Evidence Passing (Plan of Record) | Approach B: Fat Pointers / Coercions |
| :--- | :--- | :--- |
| **Value Representation** | **Strictly uniform 1 word (`uint64_t`)** everywhere. Records remain raw single pointers. | 2 words `(data_ptr, dict_ptr)` or heap-allocated box wrappers. |
| **Generic Collections (`Array(T)`)** | **Trivial & Uniform:** Array elements are always 1 word without special casing. | Requires heap boxing to store 2-word fat pointers into 1-word generic array slots. |
| **Subsumption Cost** | **Zero Allocation:** Upcasting simply passes a pointer to a static `.rodata` dictionary at call sites. | Constructs a 2-word struct on the stack or allocates a heap box on every upcast. |
| **Garbage Collection** | **Zero GC Overhead:** Dictionaries are static constants; GC only traces 1-word object pointers. | GC must trace dynamically allocated boxed fat-pointer nodes if stored in generic structures. |
| **Higher-Order Coercions** | Addressed via object headers and adapter thunks when needed. | Directly compatible without thunks since dictionary travels with the pointer. |
| **Registers & ABI** | Standard AAPCS64 register conventions; extra dictionary pointer passed in register. | Passes 2-word structs in register pairs (`x0`-`x1`). |

#### Differences from the Original Paper (Inline Caching + Hash Fallback)

In *Typeful Programming* (Section 6.3), Cardelli suggested:
> *"Because of multiple inheritance, it is not possible to compute statically the displacement of a field of a given name in an arbitrary record. Hence, some form of run-time lookup is required. This can be implemented rather efficiently through caching techniques that remember where a given name was found in a record 'last time', and do a full lookup only when this fails."*

Our design differs from Cardelli's original proposal in several crucial ways:

1. **Avoids Self-Modifying Code:** Inline caching requires rewriting instruction streams at runtime. On modern architectures—especially Apple Silicon / macOS AArch64—memory pages cannot be simultaneously writable and executable (W^X security). Modifying an inline cache requires page permission toggles (`pthread_jit_write_protect_np`) and CPU instruction cache flushes (`sys_icache_invalidate`), making inline cache misses very expensive.
2. **Deterministic $O(1)$ Performance:** Dictionary passing guarantees field access in exactly 2 memory loads with zero branch misses, avoiding cache thrashing in polymorphic call sites.
3. **Natural Fit for $F_{<:}^\omega$ Bounded Quantification:** When instantiating `let f(A <: Object)(r:A):Int = r.age;` with `A = Car`, the type application `f(:Car)` directly passes the static dictionary evidence for `Car <: Object`.

---

### 3.2. Typechecking and Subtyping: Bidirectional Typing & Kernel $F_{<:}$

#### Plan of Record: Dunfield & Krishnaswami Bidirectional Typing
- **Term-Level Typechecking:** We adopt the bidirectional typing discipline of Dunfield & Krishnaswami (2013 / 2021). Bidirectional typing cleanly separates checking ($\Gamma \vdash e \Leftarrow T$) from synthesis ($\Gamma \vdash e \Rightarrow T$), propagating type information downward into arguments, conditionals, and case branches. This provides predictable local type inference (e.g. omitting explicit type arguments `:Int`) without requiring complex global constraint-solving unification.
- **Mostly-Functional Architecture:** Bidirectional checkers map directly to pairs of pure, mutually recursive functions:
  ```python
  def check_type(env: Env, expr: Expr, expected_type: Type) -> TypedExpr: ...
  def synth_type(env: Env, expr: Expr) -> Tuple[TypedExpr, Type]: ...
  ```
  making the implementation easy to understand and direct to port to self-hosted Quest.
- **Implicit Dereferencing of Mutable Variables (`Var(T)`):**  
  In Quest, mutable variables declared as `let x = var 0;` have type `Var(Int)`. In value contexts expecting `T` (such as `x + 1`), `Var(T)` is implicitly coerced to `T`. The bidirectional typechecker elaborates this coercion into explicit `Deref` nodes in the typed AST / intermediate representations.

#### Theoretical Complications: Adapting Bidirectional Typing to $F_{<:}^\omega$ and Dependent Signatures
Standard bidirectional typing was formalized for **System $F$ with subtyping ($F_{<:}$)**, where types are purely static syntactic terms. In Quest ($F_{<:}^\omega$), applying bidirectional typing requires overcoming several complications:

1. **Interleaving Lazy Type Evaluation with Bidirectional Checking:**  
   In Quest, types can contain reducible operator applications (e.g., `Cond(True Int Bool)` or `List(Int)`). Before checking whether an expression $e$ matches an expected type $T$, $T$ must be evaluated lazily using the compile-time type-level $\lambda$-evaluator, taking into account bounded type variables (`X <: B`) in the environment.
2. **Dependent Component Types in Signatures:**  
   In tuple signatures (such as `Tuple A::TYPE a:A f(x:A):Int end`), subsequent component types depend on earlier type/value components. Bidirectional checking of tuple and module bindings must proceed strictly left-to-right, incrementally elaborating and extending the typing environment.
3. **Manifest Type Paths Across Modules (`A_X`, `X_U`):**  
   Resolving manifest paths requires interleaving signature normalization and manifest path expansion with bidirectional type synthesis.

#### Subtyping Strategy: Kernel $F_{<:}$ with Upgrade Path to Full $F_{<:}$
- **Initial Plan: Kernel $F_{<:}$ Subtyping.**  
  In 1992, Benjamin Pierce proved that subtyping in Full $F_{<:}$ (where universal quantifiers have contravariant bounds $A' <: A$) is undecidable. To ensure immediate decidability, termination, and polynomial-time checking during early development, our initial implementation uses **Kernel $F_{<:}$**, where quantifier bounds must match identically:
  $$\frac{\Gamma, X <: A \vdash B <: B'}{\Gamma \vdash (\forall X <: A.\, B) <: (\forall X <: A.\, B')}$$
- **Future Upgrade Path: Full $F_{<:}$ with Cycle Detection & Bounded Depth.**  
  Because recursive subtyping (`VarList(Int) <: List(Int)`) already requires a coinductive cycle-detection cache in `is_subtype`, switching to Full $F_{<:}$ in the future is completely isolated to a single rule in the subtyping function (adding contravariant bound checking with a recursion depth bound / fuel limit). The AST, parser, bidirectional checker, and code generators will remain 100% unchanged.

---

### 3.3. Source Phrasing and Module Scope

#### Interactive Scripts vs. Separately Compiled Modules
Quest source files (`.quest`) support two complementary operational forms:
1. **Interactive / Script Sequences:** Files containing arbitrary top-level type definitions (`Let`), value bindings (`let`), and expressions evaluated sequentially. This form is used for interactive REPL sessions, scripts, and standalone test programs in `tests/source/`.
2. **Modular Compilation Units:** Files structured as formal `interface ... end` and `module ... end` units with explicit imports/exports and manifest types/kinds (`Def`, `DEF`), used for separately compiled libraries and large subsystems.

#### Module Import Resolution Strategy
- **Steps 1–3 (Bootstrap Front-End, Typechecker, Interpreter):** Use **in-file / environment-based resolution**. Modules and interfaces defined earlier in the same file or pre-registered in the global environment (e.g. built-in standard interfaces like `IntOp` and `StringOp`) are resolved directly by name.
- **Step 4 onward (Batch Compilation & Native Toolchains):** Add **file-system include path lookup**. The compiler searches configured include directories for matching `<InterfaceName>.quest` / `<ModuleName>.quest` files and compiles or links dependencies on demand.

#### Language Scope: Systems of Interfaces ("Huge Programs") Excluded
In Section 8 of *Typeful Programming*, Cardelli discusses hierarchical systems of interfaces (*open*, *closed*, and *sealed* systems, introduced with the `system` keyword). 

As Cardelli notes in Section 3.3 of the paper:
> *"The example language is still speculative in some parts; the boundary between solid and tentative features can be detected by looking at the formal syntax in the Appendix. Features that have been given syntax there have also been implemented and are relatively well thought out. Other features described in the paper should be regarded with more suspicion."*

Because the `system` construct was an exploratory proposal (and is notably absent from the formal BNF grammar in Section 11.1 and the type rules in Section 11.2), **we will not support systems of interfaces (Section 8) in the initial implementation**.

---

### 3.4. Numeric Representation & Untagged 64-bit Integers

Because Quest is a statically typed language except at explicit dynamic boundaries (`Dynamic` / `Auto`), integer values do not need runtime tagging bits:

- **Plan of Record: Full 64-bit Untagged Integers:**  
  Integers (`Int`) are represented as unboxed, full-width 64-bit two's complement integers (`int64_t`), utilizing the complete $[-2^{63}, 2^{63}-1]$ range.
- **Integer Overflow Policy (Open Decision):**  
  Whether integer arithmetic performs silent two's-complement wrapping (standard C/AArch64 machine arithmetic) or raises an `IntOp.Overflow` exception is an open design choice to be finalized during runtime bring-up.
- **Garbage Collection Interaction:**  
  Because integers are untagged, in generic heap data structures integers occupy standard 64-bit slots. Boehm GC is configured with accurate stack frame scanning to minimize false retention.

---

### 3.5. Memory Management: Boehm-Demers-Weiser Garbage Collector

#### Plan of Record: Boehm GC (`libgc`)
To decouple garbage collection implementation from early compiler bring-up, we will use the **Boehm-Demers-Weiser conservative garbage collector (`libgc`)**, at least initially, across Step 4 (C transpiler), Step 6 (native AArch64 compiler), and Step 7 (AArch64 JIT).

- **Rationale:**  
  Implementing a custom, precise garbage collector (e.g. copying or generational mark-sweep) requires generating stack maps at every safepoint and managing register roots across call frames. Using Boehm GC allows us to focus immediately on language semantics, type checking, and code generation.

#### Potential Problems and Limitations of Boehm GC

While Boehm GC accelerates early development, it introduces specific challenges:

1. **Conservative Scanning & False Pointers (Memory Retention):**  
   Because Boehm GC scans registers, stack frames, and un-typed heap blocks conservatively, any non-pointer value (such as an unboxed 64-bit integer, float bit pattern, or bitmask) that happens to match a valid heap page address is treated as a live reference. In long-running processes (such as the interactive REPL or compiler daemon), this "false retention" can prevent dead data structures (like old ASTs or symbol tables) from being collected.
2. **Interior Pointers:**  
   Quest allows pointers to interior components of heap structures. Boehm GC must be configured with `GC_all_interior_pointers = 1`.
3. **AArch64 JIT Stack Visibility:**  
   When native AArch64 code is executed dynamically in the JIT (Step 7), all live heap pointers in registers must be spilled or kept in standard AAPCS64 frame layout so that Boehm GC's conservative stack scanner can find them during collections triggered inside JIT frames.
4. **External Dependency:**  
   Relying on `libgc` means self-hosted binaries (Step 6/7) must link against an external C library rather than being completely self-contained. A precise shadow-stack collector or custom runtime can be considered as a post-bootstrap enhancement once the compiler is self-hosting.

---

### 3.6. Dynamic Types: Scope of Serialization (`Dynamic_T`)

Quest provides first-class dynamic types via `Dynamic_T` (`Auto A::TYPE with a:A end`) along with disk serialization routines `dynamic.extern(writer, d)` and `dynamic.intern(reader)`.

#### Plan of Record: Non-Code Value Serialization Only
In our implementation, `dynamic.extern` and `dynamic.intern` will be **restricted to pure data values** (primitives, tuples, records, options, variants, arrays, and type descriptors). **We will not support serializing functions or closures.**

- **Rationale:**  
  In ahead-of-time (AOT) and JIT native compilation, closures capture raw function code pointers and environment structures. Serializing closures to disk across processes or across compiler runs cannot be done safely without serializing full ASTs/bytecode and bundling a dynamic linker to resolve machine code addresses subject to Address Space Layout Randomization (ASLR). If `dynamic.extern` is attempted on a value containing a function closure, an exception will be raised.

---

### 3.7. Exception Handling Strategy

Quest supports first-class exception values and dynamic stack unwinding (`exception`, `raise`, `try ... when ... end`).

While exception handling in the tree-walking interpreter (Step 3) is straightforward via Python's native exception mechanisms, exception handling in compiled code (Step 4 C transpilation and Step 6/7 native AArch64 and JIT) involves non-trivial architectural decisions:
- In C (Step 4): Options include `setjmp`/`longjmp` stacks, explicit tagged-result returns, or thread-local handler chains.
- In Native AArch64 & JIT (Steps 6 & 7): Options include handwritten explicit stack handler chains (pushing/popping saved register contexts on `try` entry/exit) versus return-code propagation.

**Plan of Record:**  
We will address the complex architectural and implementation issues surrounding exception handling specifically when designing and implementing **Step 4 (C transpiler)** and **Step 7 (JIT runtime)**. For now, the precise lowering and unwinding mechanisms are left **unspecified**.

---

### 3.8. Standard Library Extensions & Bootstrapping Data Structures

The standard library specified in the appendix of *Typeful Programming* (Section 11.3) is deliberately minimal, providing only `ArrayOp` (fixed-size arrays), `Ascii`, `Conv`, `Dynamic`, `IntOp`, `List` (linked lists), `Reader`, `RealOp`, `StringOp`, `Value`, and `Writer`. Notably missing are core data structures required by any real-world compiler:
- **Dictionaries / Hash Maps (`Dict` / `Map`):** Essential for symbol tables, environment lookups, interned string tables, and type caches.
- **Extensible Buffers / String Builders:** In Quest, strings are immutable and `<>` allocates a new string. Building a lexer/parser with `<>` causes $O(N^2)$ performance and excessive GC allocations.
- **Dynamic Arrays / Vectors:** Resizable array buffers for token streams, AST child lists, and IR instructions.

**Plan of Record:**
1. We will design and implement these basic data structure modules in Quest alongside the compiler, extending the minimal set described in the paper's appendix.
2. To ensure that porting the Python bootstrap to Quest in Step 5 is viable, the Python bootstrap (Steps 1–4) will be designed using data structures and abstractions that directly map to what will be implemented in Quest (avoiding heavy reliance on Python-specific language magic).

---

### 3.9. Source Position Tracking & Diagnostic Mapping

To keep token and AST representations lightweight and easily portable to Quest:
- **Offset-Only Tokens:** Each token records only its starting character offset (`offset: int`) from the beginning of the input stream. The end offset is computed on demand as `offset + len(lexeme)`.
- **In-Memory Source Text & Line/Column Mapping:** The compiler retains the entire source text in memory as a string. A utility function maps any character offset to its 1-indexed `(line, column)` pair on demand when emitting compiler diagnostics, error messages, and underlined source code snippets.

---

### 3.10. Type Representation, Recursive Subtyping, and Scoping Infrastructure

To support type checking, local bidirectional type inference, and compile-time type-level $\lambda$-evaluation, the compiler's semantic type system is organized into modular subsystems:

#### Modular Separation (`types.py` & `env.py`)
- **`bootstrap/python/quest/types.py`**: Houses the semantic kind and type hierarchies (`QKind`, `QType`), lazy type evaluation, substitution, and equi-recursive subtyping algorithms.
- **`bootstrap/python/quest/env.py`**: Houses the lexical symbol table infrastructure (`Scope`, `Environment`, and `Symbol` definitions).

#### Naming Conventions
- **Quest Language Semantic Entities:** Follow the `Q` prefix and `Type`/`Kind` suffix convention to avoid collisions with host language primitives and clearly demarcate language levels:
  - *Kinds:* `QKind`, `QTypeKind`, `QPowerKind`, `QAllKind`, `QKindVar`.
  - *Types:* `QType`, `QIntType`, `QRealType`, `QBoolType`, `QCharType`, `QStringType`, `QOkType`, `QDynamicType`, `QExceptionType`, `QTupleType`, `QRecordType`, `QVariantType`, `QOptionType`, `QFunType`, `QVarType`, `QArrayType`, `QOutType`, `QAllType`, `QAutoType`, `QTypeFun`, `QTypeApp`, `QRecType`, `QRecGroupType`, `QTypeVar`, `QAbstractType`.
  - *Inference Metavariables:* `QTypeMeta` (prunable unification variables for local inference).
- **Compiler Infrastructure Classes:** Entities that manage scoping and analysis are compiler-internal mechanisms rather than Quest language constructs, and therefore do not use a `Q` prefix:
  - *Symbols:* `Symbol`, `ValueSymbol`, `TypeSymbol`, `KindSymbol`.
  - *Scoping & Analysis:* `Scope`, `Environment`, `TypeChecker`.

#### Key Design Elements
1. **Equi-Recursive Subtyping & Mutual Recursion:**  
   Matching *Typeful Programming*, recursive types use equi-recursive subtyping ($\text{Rec}(X::K) T \equiv T[\text{Rec}(X::K) T / X]$) without requiring explicit user fold/unfold annotations. Mutually recursive definitions (`Let Rec A = ... and B = ...`) are represented as a dedicated `QRecGroupType(bindings: dict[str, QType])` node that unfolds lazily on demand. The subtyping engine employs a coinductive assumption trail of evaluated symbol pairs $\Sigma \vdash S \le T$ to prevent infinite loops on cyclic types.
2. **Named Type Parameters with Symbol Identity:**  
   Bound type parameters ($\forall X <: T$) are represented as `QTypeVar(name: str, symbol_id: int)` referencing unique symbol identities. This preserves human-readable identifier names for compiler error diagnostics while ensuring capture-avoiding substitution and exact identity comparisons during lazy evaluation.
3. **Early Type Path Resolution (No `QTypePath`):**  
   Because Quest has no dependent types (runtime values cannot project static types), all syntactic type paths (`ast.TypePath`) and module-qualified names (`M_T`, `M.T`) are resolved immediately during type elaboration against the `Environment`, ensuring that `QType` contains only canonical semantic types.
4. **Local Bidirectional Type Inference (No Global Constraint Solver):**  
   Matching *Typeful Programming*, the compiler deliberately avoids complex ML-style global constraint solving. Full type annotations are required on top-level definitions and function parameters; type arguments in polymorphic applications and composite expression types are synthesized or checked locally using `QTypeMeta` unification metavariables.
5. **Ordered Scopes for Dependent Signatures:**  
   `Scope` maintains an ordered sequence of declarations so that dependent components (e.g. in `Tuple A::TYPE a:A f(x:A):Int end` or interface exports) are evaluated lazily and added to the typing context in strict left-to-right order.
6. **Stateless Representation of Manifest vs. Abstract Types:**  
   Rather than using ambient mode flags in the typechecker, type transparency is controlled structurally via `TypeSymbol(name, symbol_id, kind, definition)`:
   - Inside an implementing module, `definition` points to the concrete `QType` (transparent).
   - Outside in client scopes, `definition` is `None` (abstract, bounded by `kind`), causing lazy evaluation to treat it as a rigid type constant.
7. **Full Subkinding on Kinds:**  
   Implements full subkinding ($K_1 \le K_2$) across all kind forms:
   - *Reflexivity:* $K \le K$.
   - *Power to Type:* $\text{POWER}(T) \le \text{TYPE}$ for any valid type $T$.
   - *Power to Power:* $\text{POWER}(S) \le \text{POWER}(T) \iff S \le T$ (delegating to equi-recursive `is_subtype`).
   - *Higher-Order Operator Kinds (`QAllKind`):* $\text{ALL}(X::K_1) K_2 \le \text{ALL}(Y::K_1') K_2' \iff K_1' \le K_1 \land K_2 \le K_2'[Y \mapsto X]$ (contravariant in parameter kind, covariant in result kind with $\alpha$-renaming).
   - *Kind Aliases:* `DEF K = Kind` definitions resolve lazily via the `Environment`.
8. **Kind Synthesis & Well-Kindedness Verification:**  
   - `synth_kind(type_val, env) -> QKind`: Computes the most specific minimal kind (e.g. `TYPE` for proper types, $\text{POWER}(B)$ for bounded variables, $\text{ALL}(X::K_1) K_2$ for type functions).
   - `check_kind(type_val, expected_kind, env)`: Validates that synthesized kind is a subkind of `expected_kind`, raising `KindError` on mismatches.
   - `check_kind_well_formed(kind, env)`: Enforces the proper type invariant ($\text{POWER}(T) \implies T :: \text{TYPE}$) and validates operator kind parameter/result bounds.
   - *Non-Unfolding Recursive Types:* $\text{Rec}(X::K) T$ verifies that under context $\Gamma, X::K$, body $T$ conforms to $K$ without expanding recursive cycles.

#### Summary Complexity Matrix

| Complexity Area | Key Difficulty | Architectural Solution |
| :--- | :--- | :--- |
| **Recursive Subtyping** | Infinite expansion loops & polarity flips | Lazy evaluation + coinductive symbol-pair trail $\Sigma$ |
| **Dependent Signatures** | Fields depend on earlier type parameters | Ordered `Scope` with left-to-right incremental elaboration |
| **Type-Level $\lambda$-Calculus** | $\beta$-reduction & variable capture | Lazy evaluation + `QTypeVar` with unique `symbol_id` |
| **Module Manifest Types** | Inside is concrete, outside is abstract | Structural `TypeSymbol(kind, definition)` (no ambient flags) |
| **Diamond Imports** | Disparate import paths for same interface | Canonical interface symbol interning in `Environment` |

---

## 4. Comprehensive Test-Driven Verification Strategy

The examples in *Typeful Programming* provide essential starting points, but are insufficient on their own to fully exercise the language. A cornerstone of the implementation strategy is the construction of a **large, self-contained suite of Quest test programs (`.quest`)** built from day one, covering all features and complex feature interactions, and continually expanded to prevent regressions.

### 4.1. Test Suite Layout

All test source files live in a single directory to minimize structural overhead:
- **`tests/source/<name>.quest`**: Self-contained Quest source files.

Verification of both intermediate compiler passes and end-to-end execution is driven by a **golden file testing system**:
- **`tests/golden/<compiler-phase>/<name>.out`**: Expected standard output produced by `<compiler-phase>` when processing `tests/source/<name>.quest` (exit code 0). If this file exists, the phase's standard output must match it exactly.
- **`tests/golden/<compiler-phase>/<name>.error`**: Expected diagnostic error output produced by `<compiler-phase>` when processing `tests/source/<name>.quest` (exit code $\ne 0$). If this file exists, the phase must fail and match the diagnostic output.

### 4.2. Custom Test Runner Tooling

Testing will be driven by a **self-contained, custom test runner CLI** (`run_tests.py` in the bootstrap phase, designed to be cleanly ported to Quest as `run_tests.quest` in Step 5):

- **Zero External Dependencies:** Built using standard library facilities only, ensuring immediate portability across environments and backends without requiring external packages (like `pytest`).
- **Flexible Execution & Filtering:**
  - Run specific compiler phases: `python3 run_tests.py --phase <P>`
  - Run specific test cases: `python3 run_tests.py --test <name>`
  - Run all phases end-to-end: `python3 run_tests.py --all`
  - Update golden expectation files: `python3 run_tests.py --update-golden`
- **Granular Pass/Fail Reporting:** Displays clear diffs when phase output diverges from `tests/golden/<phase>/<name>.out` or `tests/golden/<phase>/<name>.error`.

### 4.3. Compiler Phases Tested

The compiler will be structured as a sequence of small, verifiable phases (following the *Essentials of Compilation* approach). As each phase is designed and implemented, corresponding golden subdirectories under `tests/golden/<phase>/` will be populated to verify that phase independently:

| Phase Name (`P`) | Description / Input $\to$ Output | Golden Output Format (`tests/golden/<P>/<name>.*`) |
| :--- | :--- | :--- |
| `tokenize` | Tokenization: `.quest` source $\to$ stream of `<line>:<col>\t<KIND>\t<lexeme>` | `.out` lists tokens with positions; `.error` contains lexical diagnostic messages. |
| `parse` | Parsing: Token stream $\to$ canonical 2-space indented S-expression AST | `.out` contains AST S-expression; `.error` contains syntax error diagnostic messages. |


### 4.4. Feature and Interaction Coverage

The test suite in `tests/source/` will explicitly cover:
1. **Syntax & Lexical Edge Cases:** Symbolic right-associative infixes, listfix variations (`of .. end`, `of(n a)`), nested comments, multi-line string/char escapes, whitespace vs parenthesis precedence.
2. **Control Flow & Imperative Constructs:** Conditionals (`if`, `elsif`, `else`, `andif`, `orif`), iteration (`loop/exit`, `while`, `for upto/downto`), and exceptions (`exception`, `raise`, `try/when/else`).
3. **Type System & Operators ($F_{<:}^\omega$):** Universal/existential quantification, impredicative polymorphism (e.g. `Endo`), higher-order compile-time type operators (Church booleans, `Cond`, `Opt`, `List`), and normal-order type reduction.
4. **Subtyping & Inheritance:** Tuple width/depth subtyping, record multiple-inheritance DAGs with evidence dictionaries, variant/option subtyping with `case`, function contravariance, mutable reference rules (`Var` invariance, `Out` contravariance, `@` and `var` coercions), and recursive subtyping (`VarList(Int) <: List(Int)`).
5. **Dynamic & System Programming:** Automorphic types (`Auto`), `inspect` discrimination, `Dynamic_T` packaging/narrowing, disk persistence (`extern`/`intern`), and unsound modules with `Value`.
6. **Feature Interactions:** Complex combinations such as bounded polymorphism + closures + mutable cells, recursive types + options + first-class functions, and diamond import module graphs with manifest type extraction (`A_X`, `X_U`).

### 4.5. Zero-Regression Rule and Continuous Cross-Validation

- **Zero-Regression Rule:** Every bug, crash, or edge case discovered across any development phase must immediately produce a minimal reproduction test in `tests/source/<name>.quest` (along with its golden expectations) before fixing the bug.
- **Cross-Stage Validation:** The exact same `.quest` source files in `tests/source/` are evaluated across all backends (Python interpreter, Python C transpiler, self-hosted Quest C transpiler, native AArch64 AOT, and JIT) to guarantee complete semantic consistency across every milestone.
