# Self-Hosting Prerequisites for Quest

This document specifies the foundational capabilities, data structures, runtime libraries, and operating system
primitives required to implement the **Step 5 Self-Hosted Front-End and Compiler** (`questc` written in Quest).

It details the features currently used by the Python bootstrap implementation (`bootstrap/python/quest/`) that are
absent from core Quest or Cardelli's standard library specification (*Typeful Programming* §11.2), organizing them
into modular subsystems that can be developed incrementally.

---

## 1. Core Data Structures & Collections

The Python bootstrap relies on built-in collections (`list`, `dict`, `set`, `deque`) that must be implemented as
standard libraries in Quest.

### 1.1. Growable Dynamic Arrays (`Vector(T)` / `List(T)`)
- **Python Usage**: `list.append()`, `list.pop()`, slicing `list[i:j]`, concatenation `list1 + list2`.
- **Quest Limitation**: Quest arrays (`Array(T)`) are fixed-capacity (`array of(size default)`).
- **Required Functionality**:
  - Automatic geometric resizing capacity.
  - Operations: `new()`, `push(item)`, `pop()`, `get(idx)`, `set(idx, item)`, `size()`, `clear()`, `toArray()`.
  - Used for: Token streams, AST node children, diagnostic error queues, statement sequences, and emitter lines.

### 1.2. Associative Maps / Hash Tables (`Map(K, V)`)
- **Python Usage**: `dict[K, V]` throughout all compiler phases.
- **Key Use Cases**:
  - Symbol tables in `Scope`: `dict[str, ValueSymbol]`, `dict[str, TypeSymbol]`, `dict[int, TypeSymbol]`.
  - Subtyping substitution mappings: `dict[int, QType]` (mapping symbol IDs to types).
  - Parser packrat memoization cache: mapping `(SyntaxTarget, pos)` pairs to parse results.
  - Module registry and AST cache: mapping canonical path strings to module records and typed ASTs.
  - Struct and type name caches in the C code generator.
- **Required Functionality**:
  - Generic key-value store with string hashing (`djb2` or `fnv1a`) and integer identity hashing.
  - Support for composite keys (e.g. hashing pairs of integers or target/offset pairs).

### 1.3. Sets (`Set(T)`)
- **Python Usage**: `set[T]` for deduplication and membership testing.
- **Key Use Cases**:
  - **Coinductive Subtyping Trail**: `trail: set[tuple[int, int]]` in `types.py` tracking visited pairs of symbol IDs
    to detect cycles during equi-recursive subtyping.
  - **Closure Free-Variable Analysis**: `seen: set[str]`, `bound: set[str]` in `analysis/closure.py`.
  - **Module Import Cycle Detection**: `active_imports: set[str]` in `module_loader.py`.
  - **Parser Error Expectations**: `expected_at_farthest: set[str]` in `parser.py`.
  - **Topological Sort**: Visited set in Kahn's algorithm and dependency DAG traversal.
- **Required Functionality**:
  - Operations: `new()`, `add(item)`, `contains(item)`, `remove(item)`, `size()`, `union(other)`, `diff(other)`.

### 1.4. Queues & Stacks
- **Key Use Cases**: Scope stacks in `env.py`, block nesting and token lookahead buffers, topological sort queues.
- **Implementation**: Easily implemented on top of the growable `Vector(T)`.

---

## 2. Operating System, Process Execution, and Filesystem Primitives

Currently, Quest's `System` interface provides:
`args: Array(String)`, `sysexit(code: Int): Ok`, `getEnv(name: String): String`, `fileExists(path: String): Bool`,
and `error: Exception(Ok)`.

To support compiling programs end-to-end to native binaries, the following OS primitives are needed:

### 2.1. Process Execution (`subprocess.run`)
- **Python Usage**: `compiler_runner.py` invokes the host C compiler (`clang` or `gcc`) to assemble and link generated
  C source into relocatable object files (`.o`) and executables.
- **Current Status**: Quest has no child process execution primitive.
- **Required Primitive**:
  ```quest
  system.exec(command: String): Int
  ```
  Returns the process exit code (0 for success, non-zero for failure). Can be implemented using standard C POSIX
  `system()` or `fork`/`execvp`.

### 2.2. Directory Creation (`mkdir` / `os.makedirs`)
- **Python Usage**: When compiling hierarchical modules (e.g. `quest compile -c util/calc.mod.quest`), the compiler
  ensures subdirectories (such as `util/`) exist before writing `.c`, `.o`, and `.int.h` artifacts.
- **Required Primitive**:
  ```quest
  system.mkdir(path: String): Ok
  ```
  Creates directories recursively (`mkdir -p` semantics).

### 2.3. File Removal (`removeFile` / `os.unlink`)
- **Python Usage**: Deleting temporary generated `.c` files after host compilation completes.
- **Required Primitive**:
  ```quest
  system.removeFile(path: String): Ok
  ```

### 2.4. File Status Metadata (`isDir` / `os.stat`)
- **Python Usage**: Distinguishing directories from files when scanning `-I` include search paths.
- **Required Primitive**:
  ```quest
  system.isDir(path: String): Bool
  ```

### 2.5. Path Utility Library (`Path`)
- **Python Usage**: `pathlib.Path` for dirname, basename, extension, path concatenation, and normalization.
- **Implementation**: Can be implemented in pure Quest on top of string utilities:
  - `join(dir: String, file: String): String`
  - `dirName(path: String): String`
  - `baseName(path: String): String`
  - `extension(path: String): String`
  - `normalize(path: String): String`

### 2.6. Host Toolchain Discovery (`shutil.which`)
- **Python Usage**: Locating `clang` or `gcc` in the host `$PATH`.
- **Implementation**: Pure Quest function reading `system.getEnv("PATH")`, splitting on `:`, and checking
  `system.fileExists`.

---

## 3. String Processing & Text Manipulation

Quest provides `String` and `stringOp` (`length`, `getChar`, `setChar`, `getSub`, `setSub`, `cat`, `conc`, `equal`).
However, compiler passes require richer text operations.

### 3.1. Splitting & Joining
- `split(s: String, delim: String): Vector(String)`: Used for lines, path components, and token streams.
- `splitlines(s: String): Vector(String)`: Used for indexing source maps and extracting diagnostic source lines.
- `join(delim: String, items: Vector(String)): String`: Used throughout code generation (`"\n".join(lines)`,
  `", ".join(params)`).

### 3.2. Prefix, Suffix, and Substring Search
- `startsWith(s: String, prefix: String): Bool`: Used for identifier prefixes (`qv_`) and comment markers.
- `endsWith(s: String, suffix: String): Bool`: Used for file extension detection (`.int.quest`, `.mod.quest`).
- `find(s: String, sub: String): Int`: Substring searching.
- `strip(s: String): String`: Trimming leading and trailing whitespace.

### 3.3. String Replacement & Escaping
- `replace(s: String, oldSub: String, newSub: String): String`:
  - Mangling module paths: `replace("/", "__")`.
  - Escaping C string and character literals: replacing `\n`, `\t`, `\"`, `\\`.

### 3.4. Character Classification
- `isDigit(c: Char): Bool`
- `isAlpha(c: Char): Bool`
- `isAlnum(c: Char): Bool`
- `isSpace(c: Char): Bool`
- Can be written in Quest using ASCII ordinal code comparisons via `ascii.val(c)`.

### 3.5. String Parsing (Inverse of `Conv`)
- **Cardelli's `Conv` Limitation**: Cardelli's `Conv` interface is strictly a one-way formatting library converting
  values **to** `String` (`conv.int(n)`, `conv.real(r)`, `conv.bool(b)`, etc.). It has no inverse parsing functions.
- **Required Capabilities**:
  - `toInt(s: String): Int` (or integer parsing from character streams).
  - `toReal(s: String): Real` (or IEEE-754 floating point parsing).
  - `toBool(s: String): Bool`.
- **Implementation Options**:
  1. Extend `Conv` with native C runtime functions (`quest_conv_to_int`, `quest_conv_to_real` wrapping `strtoll` and
     `strtod`).
  2. Implement pure Quest stream arithmetic in the tokenizer for integers (`acc * 10 + digit`), while providing
     native C support for reals.

### 3.6. String Building (`StringBuilder`)
- In C code generation, emitting thousands of lines via immutable string concatenation (`<>`) incurs significant
  quadratic allocation overhead. A `StringBuilder` accumulating characters or chunks into a growable buffer is
  essential for compiler performance.

---

## 4. Algorithms and Math Utilities

### 4.1. Binary Search (`bisect.bisect_right`)
- **Usage**: `tokens.py` maps a character offset to `(line, column)` in $O(\log N)$ time by searching an array of line
  start offsets.
- **Implementation**: A simple `binarySearchRight(arr: Array(Int), target: Int): Int` in pure Quest.

### 4.2. Sorting Algorithms (`sorted`, `list.sort`)
- **Usage**:
  - **Canonical Record Field Ordering**: Cardelli §4.1 specifies record type labels are ordered lexicographically
    to determine field layout and tuple representations.
  - **Diagnostic Ordering**: Sorting compiler diagnostics by line and column before displaying.
  - **Syntax Error Messages**: Sorting expected token names.
- **Implementation**: Generic Quicksort or Mergesort parameterized by a comparison function:
  ```quest
  sort(A::TYPE arr: Vector(A), compare: Fun(a: A, b: A): Int): Ok
  ```

### 4.3. Graph Topological Sort
- **Usage**: Topological sorting of modules to verify acyclic imports (Cardelli §7.1) and generate module
  initialization sequences.
- **Implementation**: Graph adjacency list with Kahn's algorithm or DFS in pure Quest.

---

## 5. Command-Line Argument Parsing

- **Python Usage**: `argparse.ArgumentParser` handles positional arguments (`main.quest`, `foo.o`), options with
  values (`-o <file>`, `-I <dir>`, `--stop-after <phase>`), and boolean flags (`-c`, `--emit-c`, `--nogc`).
- **Quest Solution**: A dedicated CLI option parsing library built on top of `system.args: Array(String)`.

---

## 6. Language-Level Architectural Adaptations

Migrating the Python object-oriented codebase to Quest requires structural adaptations to match Quest's type system:

### 6.1. Class Hierarchies to Algebraic Data Types (`Variant`)
- In Python, AST nodes (`ExprIf`, `ExprFun`, `ExprRecord`) and types (`QFunType`, `QRecordType`) are classes
  inheriting from `ASTNode` and `QType`, inspected using `isinstance()`.
- In Quest, there are no classes or inheritance. All AST and Type structures must be modeled as **recursive variant
  types** (`Let Rec Expr = Variant if: Tuple ... end fun: Tuple ... end ... end`) and inspected via
  `case expr of ... end`.

### 6.2. RAII / Context Managers to Higher-Order Functions
- In Python, `with env.scoped():` manages entering and leaving lexical scopes.
- In Quest, scope lifecycle should use higher-order functions:
  ```quest
  env.withScope("local", fun(s: Scope): Ret ... end)
  ```
  using `try ... when` to guarantee `popScope` runs on normal exit or exception.

### 6.3. Multi-Pattern Matching
- Python 3.10+ matches pairs of types simultaneously (`match (sub, sup): case (QTupleType(...), QTupleType(...)):`).
- Quest `case` dispatches on one variant at a time, requiring nested `case` expressions.

---

## 7. Implementation Roadmap & Priority Matrix

| Subsystem | Components | Priority | Strategy |
| :--- | :--- | :--- | :--- |
| **Collections** | `Vector(T)`, `Map(K, V)`, `Set(T)` | **P0** | Pure Quest modules (`lib/`) |
| **String Utilities** | `split`, `join`, `strip`, `replace`, etc. | **P0** | Pure Quest `stringUtil` library |
| **String Parsing** | `toInt(s)`, `toReal(s)` | **P0** | Extend `Conv` (native C backing) |
| **OS Primitives** | `system.exec`, `mkdir`, `removeFile`, `isDir` | **P1** | Extend `System` (native C backing) |
| **Path Library** | `join`, `dirName`, `baseName`, `normalize` | **P1** | Pure Quest path module |
| **Algorithms** | Binary search, Quicksort, Topological sort | **P1** | Pure Quest algorithms |
| **CLI Parser** | Flag and option parsing over `system.args` | **P2** | Pure Quest CLI library |
| **AST & Type Models** | Recursive `Variant` definitions | **P2** | Compiler architecture |
