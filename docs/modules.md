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

## See Also
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver options.
- [type-system.md](type-system.md): Type system, subtyping, and signature elaboration.
- [interpreter.md](interpreter.md): Tree-walking interpreter and runtime environment.
- [syntax.md](syntax.md): Concrete syntax and grammar rules.
