# The Quest Programming Language

A modern implementation of **Quest**, Luca Cardelli's language based on higher-order subtyping
(System $F_{<:}^\omega$), impredicative bounded quantification, and type operators within a three-level universe:
- **Level 2 (Kinds):** `TYPE`, `POWER(T)`, and `ALL(X::K1) K2`.
- **Level 1 (Types and Type Operators):** Records, tuples, variants, options, functions, recursive types, and
  compile-time type operators (`Fun(X::K) T`).
- **Level 0 (Values):** First-class functions, mutable cells (`var`), exceptions, and modules.

The ultimate objective of this project is a **fully self-hosted compiler written in Quest itself**, targeting native
**AArch64 (ARM64)** machine code with an interactive in-process **JIT compiler**.

---

## Why?

I read Luca Cardelli's paper [*Typeful Programming*](http://lucacardelli.name/Papers/TypefulProg.pdf) when I was an undergraduate and I was taken both by its philosophical arguments – *"There exists an identifiable programming style based on the widespread use of type
information handled through mechanical typechecking techniques"* – and the power and elegance of its design. But, as far as I know, the original implementation was never made public and I never had a chance to use it.

Flash forward nearly four decades, I'm late to the party on agentic programming and vibe coding, but have recently gotten a taste of how much is possible. I wanted a spare-time project to stretch my skills in directing a model to build something interesting, so I decided to build a version of Quest that I could actually play with.

At the risk of having this project dismissed as AI slop, I will straightforwardly say that every line of code (and, other than this section, of documentation) in this project was written by Gemini (3.7 and 3.8 Flash, so far) in [Antigravity](https://antigravity.google/). I've been trying to keep the design clean and the code readable; I've found Dave Rensin's paper and methodology [*Elephants, Goldfish and the New Golden Age of Software Engineering (or, Design is the New Code)*](https://drensin.medium.com/elephants-goldfish-and-the-new-golden-age-of-software-engineering-c33641a48874) to be very helpful in that regard. But, if human-guided, AI-written code bothers you, please stay away.

Otherwise, if you're interested in an interesting waypoint in the history of programming languages, take it out for a spin. *— Paul Haahr*

---

## Roadmap Summary

The compiler is built using a staged bootstrap methodology across seven distinct phases:

| Stage | Language | Subsystem | Status |
| :--- | :--- | :--- | :--- |
| **Step 1** | Python | Front-End: Lexer, PEG Parser, and Untyped AST | **Complete** |
| **Step 2** | Python | Typechecker: $F_{<:}^\omega$ Subtyping, Equi-Recursion, Elaboration | **Complete** |
| **Step 3** | Python | Tree-Walking Interpreter & Interactive REPL | **Complete** |
| **Step 4** | Python | Bootstrap C Transpiler (emits C99 + Boehm GC) | **In Progress** (Phase 4.5 Complete) |
| **Step 5** | Quest | Self-Hosted Front-End & C Compiler (written in Quest) | Queued |
| **Step 6** | Quest | Self-Hosted Native AArch64 Compiler (Nanopass Pipeline) | Queued |
| **Step 7** | Quest | Native AArch64 JIT & Dynamic Incremental Runtime | Queued |

For full architectural details on each stage, see [docs/roadmap.md](docs/roadmap.md).

---

## Quickstart

### Prerequisites
- Python 3.11+ (used for the bootstrap compiler and test runner).
- Host C compiler (`clang` or `gcc`) for compiling generated C99 code.
- Optional: [Boehm GC](https://github.com/ivmai/bdw-gc) (`bdw-gc` via Homebrew: `brew install bdw-gc`).
  The compiler automatically falls back to standard libc allocations when `--nogc` is specified.

### Running and Compiling Quest Code
Use the unified compiler driver script `./quest`:

```bash
# Evaluate an inline Quest expression via the interpreter
./quest -c "let x: Int = 40 + 2; x"

# Execute a Quest file via the tree-walking interpreter
./quest program.quest

# Compile Quest source to a native binary (using host clang/gcc)
./quest compile program.quest

# Compile to an explicit output binary
./quest compile program.quest -o my_app

# Emit generated C99 source code without invoking the host compiler
./quest compile program.quest --emit-c

# Compile without Boehm GC (using standard libc malloc/calloc)
./quest compile program.quest --nogc -o my_app

# Compile and stop after a specific phase to inspect canonical output:
./quest --stop-after tokenize program.quest          # Dumps token stream
./quest --stop-after parse program.quest             # Dumps untyped S-expression AST
./quest --stop-after typecheck program.quest         # Dumps typed S-expression AST
./quest compile --stop-after codegen_c program.quest # Dumps emitted C99 source

# Dump intermediate representations while continuing:
./quest --dump-after parse --stop-after typecheck program.quest

# Add include search paths for imported interfaces/modules:
./quest -I ./lib -I ./interfaces main.quest
```

### Running Tests
The project includes comprehensive unit tests, golden-file integration tests, and inline diagnostic error tests:

```bash
# Run all golden integration tests and diagnostic error tests
python3 run_tests.py

# Run only golden tests or only diagnostic error tests
python3 run_tests.py --suite golden
python3 run_tests.py --suite errors

# Run all unit tests
PYTHONPATH=bootstrap/python python3 -m unittest discover -s tests/python
```

---

## Documentation Index

Comprehensive documentation for the language, formal semantics, and compiler subsystems is organized in `docs/`:

### Foundational Literature & Language Specification
- [docs/TypefulProgramming.md](docs/TypefulProgramming.md): Luca Cardelli's foundational treatise on Quest and typeful
  programming (1989/1993).
- [docs/ASemanticBasisForQuest.md](docs/ASemanticBasisForQuest.md): Cardelli & Longo (1991) formal semantic foundation
  for Quest's three-level system and subtyping theory.
- [docs/TheQuestLanguageAndSystem.md](docs/TheQuestLanguageAndSystem.md): System architecture and original bytecode
  interpreter design (1994).
- [docs/grammar.txt](docs/grammar.txt): Canonical EBNF grammar specification.

### Compiler Architecture & Subsystems
- [docs/pipeline.md](docs/pipeline.md): The compiler phase pipeline framework, dual-pipeline architecture (interpreter
  vs. C compilation), and CLI driver interface.
- [docs/codegen-c.md](docs/codegen-c.md): Bootstrap C transpiler architecture, AST lowering, statement expressions, and
  compiler runner.
- [docs/c-representation.md](docs/c-representation.md): C representation, uniform 64-bit `QVal` ABI, static assertions,
  and runtime library design.
- [docs/syntax.md](docs/syntax.md): Lexical scanning, character offset tracking, PEG parser combinators, and untyped
  AST structure.
- [docs/type-system.md](docs/type-system.md): Higher-order type system, subkinding, equi-recursive coinductive
  subtyping, recursive contractiveness ($C \succ X$), and bidirectional term typing.
- [docs/interpreter.md](docs/interpreter.md): Bootstrap tree-walking interpreter, runtime value hierarchy, scoped
  environment, Cardelli identity semantics, and operational evaluation engine.
- [docs/modules.md](docs/modules.md): Cardelli module system, interfaces, information hiding, file-based loading
  conventions (.int.quest / .mod.quest), and singleton evaluation semantics.
- [docs/diagnostics.md](docs/diagnostics.md): Structured diagnostic error reporting, severity levels, and caret
  rendering.
- [docs/runtime-design.md](docs/runtime-design.md): Compiled runtime architecture, evidence passing vs. fat pointers,
  AAPCS64 ABI, and garbage collection.
- [docs/testing.md](docs/testing.md): Test harness architecture: golden files, inline comment error tests, precursor
  validation, and bidirectional matching.

### Implementation Plans
- [docs/roadmap.md](docs/roadmap.md): Complete seven-stage implementation roadmap.
- [docs/step3-interpreter.md](docs/step3-interpreter.md): Detailed implementation plan for the Step 3 tree-walking
  interpreter and interactive REPL.
