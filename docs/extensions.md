# Necessary Extensions to the Core Language

This document specifies practical extensions to Cardelli's Quest language necessary for building command-line
utilities, file processors, operating system integrations, and in particular the **Step 5 Self-Hosted Compiler**
(`questc` written in Quest).

---

## Motivation

Cardelli's 1989 report (*The Quest Language and System*) defined Quest within an interactive environment.
In that model, programs were evaluated interactively at a prompt or within an integrated persistent environment.
However, writing a standalone compiler and developer tools in Quest requires fundamental operating system primitives
and native interoperation mechanisms that were absent from the original formal specification:

1. **Command-Line Arguments (`argc` / `argv`)**: Inspecting arguments passed from the shell (e.g. source file paths,
   compiler flags such as `-o`, `-I`, `--echo`).
2. **Process Termination & Exit Codes (`sysexit`)**: Signaling success (`0`) or syntax/type/I/O errors (`1`) to invoking
   shells, build systems, and CI runners. Note: `exit` is a reserved language keyword for loop termination in Quest,
   so the process termination primitive is named `sysexit`.
3. **Environment Variable Lookup (`getEnv`)**: Locating toolchains, search paths (`QUESTPATH`, `PATH`), or temporary
   directories (`TMPDIR`).
4. **Filesystem Status Queries (`fileExists`)**: Probing file accessibility before attempting stream open operations.
5. **Opaque C Data Structures & Native Bindings (`external`)**: Declaring native C runtime types (e.g. `QWriter *`,
   `QReader *`, OS file handles) and symbols without hardcoding ad-hoc compiler-internal special cases.

---

## The `System` Interface & Module

These facilities are unified under the standard `System` interface and provided by the builtin `system` module.

```quest
interface System
export
    error: Exception(Ok)
    (* Raised when an operating system operation encounters an unrecoverable failure. *)

    args: Array(String)
    (* Command-line arguments passed to the process.
       args[0] contains the executable name or invoked script, followed by options and operands. *)

    sysexit(code: Int): Ok
    (* Immediately terminates the process with the given integer exit status code.
       A code of 0 indicates normal termination; non-zero indicates an error. *)

    getEnv(name: String): String
    (* Retrieves the value of the environment variable named `name`.
       If the variable is not defined in the process environment, returns an empty string "". *)

    fileExists(path: String): Bool
    (* Returns true if a file or directory exists at `path` and is accessible, false otherwise. *)

    isFile(path: String): Bool
    (* Returns true if `path` exists and refers to a regular file, false otherwise. *)

    isDirectory(path: String): Bool
    (* Returns true if `path` exists and refers to a directory, false otherwise. *)

    makeDirectory(path: String): Ok
    (* Creates directory at `path`, creating intermediate parent directories as needed.
       Raises system.error if directory creation fails. *)

    removeFile(path: String): Ok
    (* Deletes file at `path`. Raises system.error if file does not exist or removal fails. *)

    removeDirectory(path: String): Ok
    (* Deletes empty directory at `path`. Raises system.error if directory is not empty or cannot be removed. *)

    renameFile(oldPath: String newPath: String): Ok
    (* Renames or moves a file or directory from `oldPath` to `newPath`.
       Raises system.error on failure. *)

    currentDirectory(): String
    (* Returns the absolute path of the current working directory. Raises system.error on failure. *)

    changeDirectory(path: String): Ok
    (* Changes the current working directory to `path`. Raises system.error on failure. *)

    listDirectory(path: String): Array(String)
    (* Returns an array of entry names in the directory at `path` (excluding "." and "..") in sorted order.
       Raises system.error on failure. *)
end;
```

### Runtime Initialization Contract
When compiling a Quest program to native code via the C backend:
1. The emitted C `main` function captures POSIX `(int argc, char **argv)`:
   ```c
   int main(int argc, char **argv) {
       quest_gc_init();
       quest_builtins_init(argc, argv);
       ...
   }
   ```
2. `quest_builtins_init(argc, argv)` initializes standard I/O streams and populates `quest_system_args` as a
   length-prefixed `QArray` of length `argc`, populating each index with a `QString` copy of `argv[i]`.
3. In the Python bootstrap interpreter and REPL, `system.args` is initialized from `sys.argv`, and `system.sysexit`
   invokes `sys.exit(code)`.

---

## External Syntax & Opaque C Data Structures

To support native standard library modules and user-defined hybrid Quest/C extensions uniformly,
this implementation of Quest provides first-class `external` syntax for types and value bindings.

### 1. External Type Definitions
In module files (`.mod.quest`) or source files, an opaque C data structure is declared using `external`:
```quest
type Handle = external "QWriter *";
Let Handle = external "QWriter *";
```
- In the Quest type system, this is represented by `QExternalType(name, c_type)`.
- **Subtyping & Equivalence**: Two external types are equivalent if their underlying C types match
  (`c_type.strip() == other.c_type.strip()`). This ensures that an abstract interface type (e.g. `Handle::TYPE`)
  implemented as `Let Handle = external "QWriter *"` matches standard library types like `Writer.T`.
- **C Code Generation**: Variables of external types are emitted directly as the specified C type (e.g. `QWriter *`).
  When passed to generic polymorphic functions (`All(A::TYPE)`), external pointer types are boxed into `QVal`
  via `(QVal){ .p = (void *)(expr) }` and unboxed via `(C_TYPE)(val.p)`.

### 2. External Value Bindings
Native C functions and runtime constants are declared using `external`:
```quest
let stdout: Handle = external "quest_writer_output";
let file(name: String): Handle = external "quest_writer_file";
let maxVal: Int = external "QUEST_INT_MAX";
```
- When called directly on a known module (e.g. `fileio.stdout` or `writer.putString(w s)`), the compiler directly
  inlines the native C symbol or expression without allocating intermediate closures.
- When modules are treated as first-class values (e.g. `let m = fileio;`), module initializers instantiate closure
  trampolines (`QClosure *`) pointing to native wrapper functions.

---

## Usage Example

```quest
import system: System;
import writer: Writer;

if arrayOp.size(system.args) < 2 then
    writer.putString(writer.err "Usage: check_file <filename>\n");
    system.sysexit(1);
end;

let filename = system.args[1];
if not system.fileExists(filename) then
    writer.putString(writer.err {{"Error: file not found: " <> filename} <> "\n"});
    system.sysexit(1);
end;
```

---

## Hierarchical Module Namespaces and Signature Aliasing

Cardelli's *Typeful Programming* (§7.1) specified modules and interfaces within a flat global namespace.
While the speculative "systems of interfaces" section (§7.3) envisioned grouping interfaces to manage large
codebases, it provided neither concrete formal syntax nor filesystem mapping conventions. In large applications—such
as the self-hosted Quest compiler (`questc`)—a flat namespace invites name collisions and complicates repository
organization.

To solve this, this implementation of Quest introduces **hierarchical module and interface namespaces**
using forward slashes (`/`), coupled with **two-tier signature aliasing**:

### 1. Hierarchical Paths
- Modules and interfaces can be organized into arbitrary subdirectory trees:
  ```quest
  import util/random : util/Random;
  import :compiler/ast/Types;
  ```
- File lookup maps `/` directly to directory separators, resolving `util/random.mod.quest` and `util/random.int.quest`.
- Relative sibling resolution ensures that a module in `util/calc.mod.quest` can import `math : Math` and locate
  `util/math.mod.quest` before searching global include directories.
- In value expressions (such as `10 / 2`), `/` remains the division operator; the parser only recognizes `/` as a
  path separator in import items and module header interface specifications.

### 2. Two-Tier Signature Aliasing
To prevent local identifier collisions and provide concise local bindings, this implementation allows
explicit aliasing of both module instances and interface types/kinds:
- **Both Aliased**: `import rnd : Rnd = util/random : util/Random;`
  Binds the module record as `rnd` and interface types as `Rnd` (e.g. `Rnd_T`).
- **Module Aliased Only**: `import rnd = util/random : util/Random;`
  Binds the module record as `rnd` and interface types as `Random` (e.g. `Random_T`).
- **Interface Aliased with Module**: `import :Rnd = util/random : util/Random;`
  Binds the module record as `random` and interface types as `Rnd`.
- **Standalone Interface Aliased**: `import :Rnd = :util/Random;`
  Binds interface types as `Rnd` into scope without instantiating any module.
- **Multiple Modules**: `import r1 = util/rand1, r2 = util/rand2 : util/Random;`

### 3. C Name Mangling
In emitted C code and precompiled object files, slashes are mangled to `__` (double underscore):
- Module record: `qv_util__random`
- Module initializer: `qv_mod_util__random_init`
- Direct functions: `qv_util__random_next`
Single underscores (`_`) continue to separate module prefixes from member names, preventing symbol collisions.

---

## The `Word` Interface & Module

Cardelli's *Typeful Programming* (§9.3, *Type violations*) observes:
> "Bit and word operations could be provided through a sound built-in `Word` interface."

Following Modula-3's `Word` package design and Cardelli's specification, this implementation provides
`word : Word` as a top-level standard library module and interface. It exposes 64-bit unsigned bitwise,
logical shift, arithmetic, and machine-level representation conversions with zero abstraction overhead.

### 1. The `Word` Interface (`lib/word.int.quest`)

```quest
interface Word export
    (* Abstract 64-bit unsigned word type *)
    T::TYPE

    (* Number of bits in Word.T *)
    bits: Int

    (* Bitwise NOT (~w) *)
    notBits(w: T): T

    (* Bitwise AND (w1 & w2) *)
    andBits(w1: T w2: T): T

    (* Bitwise OR (w1 | w2) *)
    orBits(w1: T w2: T): T

    (* Bitwise XOR (w1 ^ w2) *)
    xorBits(w1: T w2: T): T

    (* Logical bit shift: left if count > 0, right if count < 0, 0 if |count| >= 64 *)
    shift(w: T count: Int): T

    (* Circular bitwise rotation: left if count > 0, right if count < 0 (modulo 64) *)
    rotate(w: T count: Int): T

    (* Extract width bits starting at bit pos, returned right-aligned *)
    extract(w: T pos: Int width: Int): T

    (* Replace width bits in w starting at bit pos with the lowest width bits of val *)
    replace(w: T val: T pos: Int width: Int): T

    (* Number of set bits (population count / Hamming weight) *)
    popCount(w: T): Int

    (* Number of leading zero bits (64 if w is 0) *)
    countLeadingZeros(w: T): Int

    (* Number of trailing zero bits (64 if w is 0) *)
    countTrailingZeros(w: T): Int

    (* Unsigned 64-bit addition modulo 2^64 *)
    add(w1: T w2: T): T

    (* Unsigned 64-bit subtraction modulo 2^64 *)
    sub(w1: T w2: T): T

    (* Unsigned 64-bit multiplication modulo 2^64 *)
    mul(w1: T w2: T): T

    (* Unsigned 64-bit division; raises DivideByZero if w2 is 0 *)
    div(w1: T w2: T): T

    (* Unsigned 64-bit modulo; raises DivideByZero if w2 is 0 *)
    mod(w1: T w2: T): T

    (* Convert word to signed 64-bit integer (two's complement interpretation) *)
    toInt(w: T): Int

    (* Convert signed 64-bit integer to word (two's complement bit pattern) *)
    fromInt(n: Int): T

    (* Returns true if w1 < w2 as unsigned 64-bit words *)
    lt(w1: T w2: T): Bool

    (* Returns true if w1 <= w2 as unsigned 64-bit words *)
    le(w1: T w2: T): Bool

    (* Returns true if w1 > w2 as unsigned 64-bit words *)
    gt(w1: T w2: T): Bool

    (* Returns true if w1 >= w2 as unsigned 64-bit words *)
    ge(w1: T w2: T): Bool

    (* Convert word bit pattern to 64-bit IEEE-754 floating point real *)
    toReal(w: T): Real

    (* Convert 64-bit IEEE-754 floating point real to word bit pattern *)
    fromReal(r: Real): T

    (* Returns true if bit at index pos (0 <= pos < 64) is set *)
    getBit(w: T pos: Int): Bool

    (* Returns word with bit at index pos set to 1 *)
    setBit(w: T pos: Int): T

    (* Returns word with bit at index pos cleared to 0 *)
    clearBit(w: T pos: Int): T
end;
```

### 2. Concrete C Representation and Direct Expression Inlining
- **Underlying Type**: `Word.T` is backed in C by `uint64_t` (`typedef uint64_t QWord;`).
- **Word Size Constant**: `word.bits` evaluates to `64`.
- **Universal Word Boxing (`QVal`)**: In `QVal`, `Word.T` maps to the raw unsigned 64-bit word member `uint64_t u;`.
  Boxing is performed via `((QVal){ .u = (expr) })` and unboxing via `(expr).u`.
- **Pure Quest Functions**: `getBit`, `setBit`, and `clearBit` are implemented directly in Quest source code
  within `lib/word.mod.quest`, composed from `shift`, `andBits`, `orBits`, and `notBits`.
- **Direct Expression Inlining**: Builtin calls on the `word` module are directly inlined into C expressions:
  - `notBits(w)` $\to$ `(~(w))`
  - `andBits(w1 w2)` $\to$ `((w1) & (w2))`
  - `orBits(w1 w2)` $\to$ `((w1) | (w2))`
  - `xorBits(w1 w2)` $\to$ `((w1) ^ (w2))`
  - `add(w1 w2)` $\to$ `((w1) + (w2))` (unsigned wrapping modulo $2^{64}$ is guaranteed by standard C)
  - `sub(w1 w2)` $\to$ `((w1) - (w2))`
  - `mul(w1 w2)` $\to$ `((w1) * (w2))`
  - `div(w1 w2)` $\to$ `quest_word_div(w1, w2)` (checks for divisor `0` and raises `DivideByZero`)
  - `mod(w1 w2)` $\to$ `quest_word_mod(w1, w2)` (checks for divisor `0` and raises `DivideByZero`)
  - `lt(w1 w2)` $\to$ `((w1) < (w2))` (unsigned 64-bit comparison)
  - `le(w1 w2)` $\to$ `((w1) <= (w2))` (unsigned 64-bit comparison)
  - `gt(w1 w2)` $\to$ `((w1) > (w2))` (unsigned 64-bit comparison)
  - `ge(w1 w2)` $\to$ `((w1) >= (w2))` (unsigned 64-bit comparison)
  - `shift(w count)` $\to$ `quest_word_shift(w, count)` (logical right shift for negative counts, logical left shift
    for positive counts, returning `0` if $|count| \ge 64$ to avoid C undefined behavior)
  - `rotate(w count)` $\to$ `quest_word_rotate(w, count)` (circular rotation modulo 64)
  - `extract(w pos width)` $\to$ `quest_word_extract(w, pos, width)` (extracts `width` bits right-aligned)
  - `replace(w val pos width)` $\to$ `quest_word_replace(w, val, pos, width)` (replaces `width` bits starting at `pos`)
  - `popCount(w)` $\to$ `quest_word_pop_count(w)` (`__builtin_popcountll`)
  - `countLeadingZeros(w)` $\to$ `quest_word_count_leading_zeros(w)` (`__builtin_clzll`; 64 if $w = 0$)
  - `countTrailingZeros(w)` $\to$ `quest_word_count_trailing_zeros(w)` (`__builtin_ctzll`; 64 if $w = 0$)
  - `toInt(w)` $\to$ `((int64_t)(w))`
  - `fromInt(n)` $\to$ `((uint64_t)(n))`
  - `toReal(w)` $\to$ `(((QVal){ .u = (w) }).r)` (direct C99 union compound literal punning)
  - `fromReal(r)` $\to$ `(((QVal){ .r = (r) }).u)` (direct C99 union compound literal punning)
- **First-Class Closures**: When `word` functions are passed as first-class values or through records,
  the compiler generates closure trampolines (`qv_word_<op>_trampoline`) ensuring seamless higher-order interop.

