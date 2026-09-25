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

