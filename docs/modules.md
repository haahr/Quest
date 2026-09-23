# Quest Module System and File Imports

This document describes the Quest module system based on Luca Cardelli's *Typeful Programming* (§7.1), including interfaces, module implementations, information hiding, file-based loading conventions, search path resolution, and evaluation semantics.

---

## 1. Overview and Theoretical Foundations

Quest implements a first-order module system as described by Luca Cardelli in *Typeful Programming* (1991, §7.1):

- **Interfaces (`interface ... export ... end`):** Specifications describing types, kinds, and value signatures. They define the public contract that implementation modules must satisfy.
- **Modules (`module m: I ... export ... end`):** Implementations that provide concrete definitions matching an interface. Modules can have private local state and bindings hidden behind the interface.
- **Information Hiding & Abstract Types:**
  - An abstract type declared in an interface (`T::TYPE`) is opaque to consumers of any module implementing that interface.
  - In the module's export scope, `T` becomes an opaque type variable unique to that module instance (`m.T`), preventing clients from depending on its internal representation.
  - A manifest type declared in an interface (`Def T = Int` or `Let T = Int`) is transparent, and its definition is known to all clients.
- **Singleton Module Semantics:** Modules are instantiated at most once at link time. When multiple modules or phrases import the same module (e.g. in diamond dependencies), all importers share the identical runtime record and mutable state cells.

---

## 2. File Conventions & Search Rules

When the Quest compiler or interpreter encounters an import for an interface or module that is not already registered in the lexical environment or built-in registry (`BuiltinModuleRegistry`), it automatically loads it from disk.

### 2.1. File Extensions and Case Normalization
- **Interfaces:** Saved with the extension `.int.quest`.
- **Modules:** Saved with the extension `.mod.quest`.
- **Case Normalization:** When searching for a file, the compiler always converts the identifier to lowercase:
  - An interface `Counter` or `counter` maps to `counter.int.quest`.
  - A module `Stack` or `stack` maps to `stack.mod.quest`.
  This ensures deterministic, portable behavior across case-sensitive (Linux) and case-insensitive (macOS, Windows) filesystems.

### 2.2. Search Order Precedence
The file loader searches directories in the following strict order:
1. **Implicit Active Directory:** The directory containing the active `.quest` file is searched first. For interactive execution (`<stdin>`, `<repl>`, `<string>`), this defaults to the current working directory (`Path.cwd()`).
2. **Explicit Include Paths (`-I`):** Any directories specified on the command line via `-I` / `--include` (or configured in `CompilerOptions.include_paths`), searched in command-line order.

A file in the active directory shadows any file with the same name in the include paths.

---

## 3. Single Definition Rule and Strict Validation

To keep compilation units clean, modular, and predictable, interface and module files must adhere to strict structural constraints:

1. **Single Top-Level Phrase:**
   A `.int.quest` file must contain **strictly one** top-level phrase: an `interface` declaration.
   A `.mod.quest` file must contain **strictly one** top-level phrase: a `module` definition.
   Top-level expressions, `let` bindings, or standalone `import` statements outside the construct are prohibited.
2. **Name Matching:**
   The identifier declared in the file must match the filename base (case-insensitively). For example, `counter.int.quest` must declare `interface Counter` (or `counter`), not `interface Bag`.
3. **Interface Conformance:**
   In a module file `m.mod.quest`, the interface specified in the module header (`module m: I`) must match the expected interface requested by the importer.
4. **Cycle Detection:**
   The loader tracks the active import chain. Circular imports among interfaces (e.g., `A` imports `B` which imports `A`) or modules are detected and reported as compile-time errors displaying the cycle path.

---

## 4. Syntax and Usage

### 4.1. Interface Declarations (`.int.quest`)
An interface declaration exports abstract types, manifest types, kinds, and value signatures:

```quest
(* counter.int.quest *)
interface Counter
export
    T::TYPE
    new(init: Int): T
    inc(c: T): T
    get(c: T): Int
end;
```

Interfaces can also import other interfaces using a leading `import` clause:
```quest
interface ExtendedCounter
import : Counter
export
    reset(c: Counter.T): Counter.T
end;
```

### 4.2. Module Definitions (`.mod.quest`)
A module provides concrete implementations for the members specified in its interface:

```quest
(* counter.mod.quest *)
module counter : Counter
export
    Let T = Int;
    let new(init: Int): T = init;
    let inc(c: T): T = c + 1;
    let get(c: T): Int = c;
end;
```

Modules can declare internal imports before their export block:
```quest
(* app.mod.quest *)
module app : App
import counter: Counter
export
    let run(): Int = counter.get(counter.inc(counter.new(10)));
end;
```

### 4.3. Top-Level Imports (`main.quest`)
Client programs import interfaces and modules using `import`:

- **Importing an Interface (Types and Kinds into Scope):**
  ```quest
  import : Counter;
  ```
  Binds the types and kinds defined in `Counter` directly into the current scope.

- **Importing Modules:**
  ```quest
  import counter: Counter;
  ```
  Loads `Counter` (if not already loaded), loads and typechecks `counter` against `Counter`, and binds the module record `counter` in the current scope.

Multiple modules of the same interface or different interfaces can be imported in a single statement:
```quest
import c1 c2: Counter greeter: Greeter;
```

---

## 5. Singleton Evaluation & Diamond Dependencies

Cardelli's module system defines modules as link-time singletons. At runtime:
- Each module is evaluated at most once when first imported.
- Subsequent imports of the same module retrieve the cached module record (`QRecord`).
- Mutable state (`let var`) encapsulated within a module is preserved across all importing sites.

### Example: Shared Mutable State Across Diamond Imports
```
        +---------------+
        |  store.mod    |  (let var count = 0)
        +---------------+
          /           \
         /             \
+---------------+   +---------------+
| clienta.mod   |   | clientb.mod   |  (both import store: Store)
+---------------+   +---------------+
         \             /
          \           /
        +---------------+
        |   main.quest  |  (imports clienta and clientb)
        +---------------+
```

When `clienta` invokes `store.inc()`, the mutation is immediately visible when `clientb` calls `store.get()`. Both clients interact with the exact same runtime instance.

---

## 6. Compiler CLI Integration

The Quest driver (`quest`) and compiler pipeline support include paths using the standard `-I` flag:

```bash
# Search current directory first, then ./lib and ./interfaces:
quest -I ./lib -I ./interfaces main.quest

# In interactive REPL mode:
quest -i -I ./lib

# Native C compilation mode:
quest compile -I ./lib main.quest -o main_app
```

---

## 7. Compilation Architecture & Implementation Roadmap

The Quest C compiler's module support is designed in two complementary stages:

### Stage 1: Whole-Program Compilation (Initial Implementation)
In Stage 1, the compiler starts from a root source file, processes all explicit and implicit `import` declarations
recursively, and builds a complete in-memory typed AST model of the program (`Environment.loaded_modules_ast`).
When all imports have been resolved, typechecked, and verified, the compiler emits a single self-contained C
translation unit (`.c` file) that compiles directly with standard C99:

1. **Acyclic Dependency Enforcement (Cardelli §7.1):**
   - As Cardelli explicitly specifies (*Typeful Programming* §7.1, p. 55): *"The import dependencies of both
     modules and interfaces must form a directed acyclic graph; that is, mutually recursive imports are not
     allowed to guarantee that the linking process is deterministic."*
   - Neither interfaces nor modules may form cycles. Topological sort order is guaranteed to be unambiguous
     and deterministic.
2. **Module Export Representation (First-Class `QRecordVal` Fat Pointers):**
   - Each module `m : I` compiles to a top-level C record variable `static QRecordVal qv_m;`.
   - The interface `I` specifies the record struct shape `QT_I` containing function pointers, closures, and values.
   - `qv_m` stores `.val` pointing to the allocated payload struct and `.dict` pointing to the static identity
     evidence dictionary `&offsetdict_I_I`.
3. **Abstract Type Erasure to `QVal`:**
   - In interface records, abstract types (`T::TYPE`) cannot have known concrete scalar representations across
     compilation boundaries. Field signatures in the interface record use uniform 64-bit words (`QVal` / `void *`),
     and concrete implementations wrap values into `QVal` (`_qval_wrap`) during module record initialization.
4. **Manifest Type Erasure:**
   - Interface records (`QT_<Interface>`) only store value components (`FieldSig`); manifest types (`Def T = ...`)
     and kinds are erased at runtime and do not generate struct fields.
5. **Topological Module Initialization (`_init`):**
   - Each module emits an initialization function `static void qv_mod_<name>_init(void)` protected by an idempotent
     boolean flag `static bool qv_mod_<name>_initialized;`.
   - The initializer recursively calls the initializers of all its dependencies in topological order, allocates
     the payload struct, executes the module's internal statements and `let var` bindings, and writes the exported
     members into the module record.
   - `main()` invokes the initializers of all top-level imported modules before executing the main script phrases.
     This guarantees singleton semantics across diamond dependency graphs.
6. **Identifier Mangling:**
   - Internal module variables, lifted lambdas, and closures are prefixed with their module name
     (`qv_<module>_<name>`), preventing name collisions in the single translation unit.
7. **Unified Native Module Mechanism (Approach B):**
   - All standard library modules (`writer`, `reader`, `conv`, `ascii`, `int`, `real`, `string`, `system`,
     `arrayOp`, `dynamic`) and user-defined hybrid modules are unified under the standard `TypedModule` pipeline.
   - Builtin functions and constants are annotated with `c_symbol`, `inline_template`, and `c_val`.
   - Direct calls on known modules inline native calls directly without closure overhead.
   - First-class module records populate closure trampolines (`qv_<mod>_<name>_trampoline`) and concrete evaluated
     constants, providing full Cardelli first-class module semantics.

---

## 8. Unified Native Module Mechanism & Hybrid Quest/C Modules

Rather than treating built-in modules as ad-hoc compiler-internal special cases, Quest unifies all modules
(pure Quest modules, standard library modules, and user-defined hybrid modules) through a single architectural pipeline:

### 8.1. Declarative Module Architecture
- Built-in modules are represented as standard `TypedModule` ASTs registered in `BuiltinModuleRegistry`.
- Member functions can be pure Quest functions, native functions (`TypedNativeBinding` with `c_symbol` or
  `inline_template`), or external C values (`TypedExternal` with `c_val`).

### 8.2. Dual-Path Code Generation
The C backend optimizes module member access while preserving full first-class module semantics:
1. **Direct Call Lowering:**
   When a function is called directly on a known module (e.g. `writer.putString(w s)` or `conv.int(n)`), the compiler
   emits the direct C function call (`quest_writer_put_string(...)`) or expands the inline template, entirely bypassing
   closure allocation and dictionary dispatch.
2. **First-Class Concrete Value Records:**
   When a module is referenced as a value (e.g. `let m = writer;` or passed as a parameter), the module's initializer
   `qv_mod_<name>_init()` allocates the record payload and populates all fields with **concrete values**:
   - Native and Quest functions are wrapped in allocated `QClosure` structures pointing to static trampolines.
   - Native constants and evaluated `let` values are stored directly in the record fields.
   - Once loaded, no field accesses require dynamic getter hooks; all fields are concrete values stored in the record.

### 8.3. Hybrid Quest/C Modules
Developers can write modules that seamlessly combine Quest code and C implementations:
```quest
(* fileio.int.quest *)
interface FileIO
export
    Handle::TYPE
    stdout: Handle
    writeHello(h: Handle): Ok
end;

(* fileio.mod.quest *)
module fileio : FileIO
import writer: Writer
export
    Let Handle = external "QWriter *";
    let stdout: Handle = external "quest_writer_output";
    let writeHello(h: Handle): Ok =
        writer.putString(h "Hello Native!\n");
end;
```
Inside `fileio`, `writeHello` is a pure Quest function that calls into the native `writer` module, while `Handle`
and `stdout` bind directly to underlying C runtime types and symbols.

### 8.4. Lazy Loading Semantics
Following Cardelli's specification, module loading is lazy:
- Modules initialize on first reference or at the start of the program unit.
- Initialization is guarded by `qv_mod_<name>_initialized` to guarantee single evaluation.
- Dependencies are resolved and initialized in topological order prior to evaluating local bindings.

---

## 9. Separate Compilation Architecture (Phase 4.16)

Quest supports separate compilation of interfaces and modules, enabling modular builds and object linking:

### 9.1. Interface Compilation (`.int.quest` -> `.h` + `.qi`)
Compiling an interface (`quest -c counter.int.quest`) generates two complementary artifacts:
1. **C Header (`x.h`):**
   - Preprocessor guards (`#ifndef QUEST_INTF_X_H ... #endif`).
   - `#include "quest_runtime.h"`.
   - Recursive `#include "<dep>.h"` for any imported interfaces (`import : Dep`).
   - Abstract types (`T::TYPE`) erase to uniform 64-bit words (`typedef QVal quest_type_X_T;`).
   - Manifest types (`Def T = ...`) emit concrete C typedefs or struct definitions.
   - Function pointer typedefs (`typedef <Ret> (*quest_sig_X_<member>)(<Params>);`).
2. **Type Metadata (`x.qi`):**
   - Serialized JSON/JSOG envelope using Quest's shadow record types (`InterfaceDesc`):
     ```quest
     Let InterfaceTypeDecl = Record
         isManifest: Bool
         kind: String
         manifestType: String
         name: String
     end;

     Let InterfaceValueDecl = Record
         isPoly: Bool
         name: String
         typeSig: String
     end;

     Let InterfaceDesc = Record
         imports: Array(String)
         name: String
         types: Array(InterfaceTypeDecl)
         values: Array(InterfaceValueDecl)
     end;
     ```
   - Serialized via `dynamic.extern` / `jsog_encode` and deserialized via `dynamic.intern` / `jsog_decode`.
   - Allows the compiler to typecheck client code or implementing modules without the original `.int.quest` source.

---

## See Also
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver options.
- [c-representation.md](c-representation.md): C runtime ABI, record representation, and function calling conventions.
- [type-system.md](type-system.md): Type system, subtyping, and signature elaboration.
- [interpreter.md](interpreter.md): Tree-walking interpreter and runtime environment.
- [syntax.md](syntax.md): Concrete syntax and grammar rules.

