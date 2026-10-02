# Self-Hosting Prerequisites for Quest

This document specifies the foundational capabilities, data structures, runtime libraries, and operating system
primitives required to implement the **Step 5 Self-Hosted Front-End and Compiler** (`questc` written in Quest).

It details the features currently used by the Python bootstrap implementation (`bootstrap/python/quest/`) that are
absent from core Quest or Cardelli's standard library specification (*Typeful Programming* §11.2), organizing them
into modular subsystems that can be developed incrementally.

---

## 1. Core Data Structures & Collections

The primary collection libraries required for self-hosting have been implemented and are documented in
`docs/new-libraries.md`:
- `collections/vector : collections/Vector` (growable dynamic arrays `Vector(T)`)
- `collections/hashMap : collections/HashMap` (compact ordered hash tables `HashMap(K, V)`)
- `collections/hashSet : collections/HashSet` (hash sets `HashSet(T)` built on `HashMap`)

Queues and stacks (used for scope stacks in `env.py`, block nesting and token lookahead buffers, and
topological sort queues) are straightforwardly implemented on top of `collections/vector`.

---

## 2. Operating System, Process Execution, and Filesystem Primitives

Quest's `System` interface provides operating system and filesystem primitives:
`args`, `sysexit`, `getEnv`, `fileExists`, `isFile`, `isDirectory`, `makeDirectory`, `removeFile`,
`removeDirectory`, `renameFile`, `currentDirectory`, `changeDirectory`, and `listDirectory`.

To support compiling programs end-to-end to native binaries without relying on external drivers, the
remaining OS primitive is:

### 2.1. Process Execution (`subprocess.run`)
- **Python Usage**: `compiler_runner.py` invokes the host C compiler (`clang` or `gcc`) to assemble and link generated
  C source into relocatable object files (`.o`) and executables.
- **Current Status**: Quest has no child process execution primitive; compilation currently delegates to Python driver.
- **Required Primitive**:
  ```quest
  system.exec(command: String): Int
  ```
  Returns the process exit code (0 for success, non-zero for failure). Can be implemented using standard C POSIX
  `system()` or `fork`/`execvp`.

### 2.2. Host Toolchain Discovery (`shutil.which`)
- **Python Usage**: Locating `clang` or `gcc` in the host `$PATH`.
- **Implementation**: Pure Quest function reading `system.getEnv("PATH")`, splitting on `:`, and checking
  `system.fileExists`.

## 3. Algorithms and Math Utilities

### 3.1. Binary Search (`bisect.bisect_right`)
- **Usage**: `tokens.py` maps a character offset to `(line, column)` in $O(\log N)$ time by searching an array of line
  start offsets.
- **Implementation**: A simple `binarySearchRight(arr: Array(Int), target: Int): Int` in pure Quest.

### 3.2. Sorting Algorithms (`sorted`, `list.sort`)
- **Usage**:
  - **Canonical Record Field Ordering**: Cardelli §4.1 specifies record type labels are ordered lexicographically
    to determine field layout and tuple representations.
  - **Diagnostic Ordering**: Sorting compiler diagnostics by line and column before displaying.
  - **Syntax Error Messages**: Sorting expected token names.
- **Implementation**: Generic Quicksort or Mergesort parameterized by a comparison function:
  ```quest
  sort(A::TYPE arr: Vector(A), compare: Fun(a: A, b: A): Int): Ok
  ```

### 3.3. Graph Topological Sort
- **Usage**: Topological sorting of modules to verify acyclic imports (Cardelli §7.1) and generate module
  initialization sequences.
- **Implementation**: Graph adjacency list with Kahn's algorithm or DFS in pure Quest.

---

## 4. Command-Line Argument Parsing

- **Python Usage**: `argparse.ArgumentParser` handles positional arguments (`main.quest`, `foo.o`), options with
  values (`-o <file>`, `-I <dir>`, `--stop-after <phase>`), and boolean flags (`-c`, `--emit-c`, `--nogc`).
- **Quest Solution**: A dedicated CLI option parsing library built on top of `system.args: Array(String)`.

---

## 5. Language-Level Architectural Adaptations

Migrating the Python object-oriented codebase to Quest requires structural adaptations to match Quest's type system:

### 5.1. Class Hierarchies to Algebraic Data Types (`Variant`)
- In Python, AST nodes (`ExprIf`, `ExprFun`, `ExprRecord`) and types (`QFunType`, `QRecordType`) are classes
  inheriting from `ASTNode` and `QType`, inspected using `isinstance()`.
- In Quest, there are no classes or inheritance. All AST and Type structures must be modeled as **recursive variant
  types** (`Let Rec Expr = Variant if: Tuple ... end fun: Tuple ... end ... end`) and inspected via
  `case expr of ... end`.

### 5.2. RAII / Context Managers to Higher-Order Functions
- In Python, `with env.scoped():` manages entering and leaving lexical scopes.
- In Quest, scope lifecycle should use higher-order functions:
  ```quest
  env.withScope("local", fun(s: Scope): Ret ... end)
  ```
  using `try ... when` to guarantee `popScope` runs on normal exit or exception.

### 5.3. Multi-Pattern Matching
- Python 3.10+ matches pairs of types simultaneously (`match (sub, sup): case (QTupleType(...), QTupleType(...)):`).
- Quest `case` dispatches on one variant at a time, requiring nested `case` expressions.

---

## 6. Implementation Roadmap & Priority Matrix

Completed subsystems (`collections/vector`, `collections/hashMap`, `collections/hashSet`, `util/maybe`,
`util/stringBuilder`, `util/strutil`, and `util/path`) are documented in `docs/new-libraries.md`.
Remaining prerequisites:

| Subsystem | Components | Priority | Strategy |
| :--- | :--- | :--- | :--- |
| **OS Primitives** | `system.exec` | **P1** | Extend `System` (native C backing) |
| **Algorithms** | Binary search, Quicksort, Topological sort | **P1** | Pure Quest algorithms |
| **CLI Parser** | Flag and option parsing over `system.args` | **P2** | Pure Quest CLI library |
| **AST & Type Models** | Recursive `Variant` definitions | **P2** | Compiler architecture |

