# Quest Build Process & Separate Compilation Specification

This document specifies the architectural design of the Quest compiler build process, encompassing separate
compilation (the default) and whole-program compilation modes, compilation artifact management within a dedicated
build directory (`.build/`), interface and module dependency tracking via `.qi` and `.qm` files, queue-driven
transitive closure resolution, self-guarding idempotent module initialization, and build logging.

---

## 1. Overview and Operational Modes

The Quest compiler (`questc` / Python bootstrap driver) supports two distinct compilation strategies when building
executable binaries:

### 1.1. Separate Compilation (Default Mode)
In separate compilation mode:
- Each interface (`.int.quest`) is compiled independently into a C header file (`.h`) and a Quest Interface metadata
  file (`.qi`).
- Each module implementation (`.mod.quest`) is compiled independently into a C implementation file (`.c`), compiled by
  the host C compiler to an object file (`.o`), and accompanied by a Quest Module metadata file (`.qm`).
- A Quest main routine (`.quest`) is compiled into a `.c`, `.o`, and `.qm` metadata file.
- Single-module and single-interface compilations *always* operate in separate compilation mode.
- When compiling an application starting from a main routine, compilation is driven by a dependency queue that builds
  or updates only out-of-date units across the transitive closure of needed modules, followed by linking all object
  files with the Quest runtime into an executable.

### 1.2. Whole-Program Compilation (`--whole-program`)
In whole-program compilation mode:
- Can only be initiated by pointing the compiler at a non-module, non-interface `.quest` file (a **Quest main
  routine**).
- The compiler traverses the entire AST and all imported modules in memory, resolving all bindings into a single
  unified compilation unit.
- Generates a single consolidated C file (e.g. `main.c`), with no `.qi` or `.qm` metadata files produced or read from
  disk.
- The single C file is compiled and linked directly to produce the native executable.
- *Note:* Bytecode/AST interpretation (`interpret`) always operates in whole-program mode, evaluating loaded modules
  directly in memory.

The remainder of this document specifies the architecture and rules for **Separate Compilation**.

---

## 2. Compilation Units vs. The Full Build Process

A fundamental architectural distinction exists between **compiling an individual compilation unit** and executing a
**full build**:

```
                       ┌─────────────────────────┐
                       │   Quest Main Routine    │ (non-module, non-interface .quest)
                       └────────────┬────────────┘
                                    │ triggers
                                    ▼
                       ┌─────────────────────────┐
                       │   Full Build Process    │ (Queue-driven dependency resolution)
                       └────────────┬────────────┘
                                    │ orchestrates
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│ Interface Compilation │ │  Module Compilation   │ │  Main Compilation   │
│ (.int.quest -> .h/.qi)│ │ (.mod.quest ->        │ │ (.quest ->          │
│                       │ │   .qm/.c/.o)          │ │   .qm/.c/.o)        │
└───────────────────────┘ └───────────────────────┘ └───────────────────────┘
```

1. **Compilation of an Interface (`.int.quest`):**
   - Validates that the file contains exactly one `interface` declaration.
   - Typechecks the interface signatures in isolation (or with imported interfaces).
   - Emits:
     - `.h`: C typedefs, struct signatures, and function prototypes.
     - `.qi`: Serialized public interface metadata (types, kinds, signatures, and imported interfaces).
   - Does not invoke the host C compiler.

2. **Compilation of a Module (`.mod.quest`):**
   - Validates that the file contains exactly one `module` definition conforming to its declared interface.
   - Loads imported interfaces (regenerating stale `.h`/`.qi` as needed) to typecheck module members.
   - Notes imported modules without recursively compiling their implementations.
   - Emits:
     - `.c`: C implementation code and exported module record initialization functions.
     - `.qm`: Quest Module metadata recording imported modules, imported interfaces, and dependency timestamps.
   - Invokes host C compiler (`clang` or `gcc`) to compile `.c` to `.o`.

3. **Compilation of a Main Routine (`.quest`):**
   - Typechecks the top-level phrases and expressions against imported interfaces.
   - Emits:
     - `.c`: C implementation containing the `main()` entrypoint.
     - `.qm`: Metadata recording all imported modules and imported interfaces.
     - `.o`: Relocatable object file compiled from `.c`.

4. **Full Build Process (Targeting a Quest Main Routine):**
   - Initiated when the compiler driver is invoked on a Quest main routine (e.g. `questc main.quest` or
     `questc -o myapp app.quest`).
   - Executes a queue-driven build loop that determines the transitive closure of needed modules, checks staleness,
     rebuilds out-of-date interfaces and modules, and links all object files into the final executable.

---

## 3. Dedicated Build Directory Layout (`.build/`)

To prevent intermediate artifacts from polluting source directories, all generated files (`.qi`, `.h`, `.qm`, `.c`,
`.o`, and `build.log`) reside strictly within a dedicated build directory:
- **Default Directory:** `.build/` in the project root.
- **Customizable:** Configurable via the `--build-dir <dir>` command-line option.
- **Source Tree Cleanliness:** Source directories (`lib/`, `tests/`, etc.) contain only source files and are never
  written to by the compiler.

```
quest/
├── lib/                             # Source files only
│   └── util/
│       ├── path.int.quest
│       └── path.mod.quest
│
└── .build/                          # Mirror build directory
    ├── build.log                    # Compilation and queue audit trail
    ├── util/
    │   ├── path.h                   # Generated interface header
    │   ├── path.qi                  # Generated interface metadata
    │   ├── path.c                   # Generated module C implementation
    │   ├── path.qm                  # Generated module metadata
    │   └── path.o                   # Compiled native object file
    └── tests/
        └── test_path.qm             # Main routine metadata
        └── test_path.c              # Main routine C code
        └── test_path.o              # Main routine object file
```

### 3.1. Path Mapping Conventions
1. **Modules and Interfaces:**
   Artifact paths map directly to the canonical module path inside `.build/`:
   - Interface `util/Path` (`lib/util/path.int.quest`) -> `.build/util/path.qi`, `.build/util/path.h`.
   - Module `util/path` (`lib/util/path.mod.quest`):
     `.build/util/path.qm`, `.build/util/path.c`, `.build/util/path.o`.
2. **Main Routines:**
   Artifacts mirror the source file path relative to the working directory or project root:
   - `tests/test_path.quest` -> `.build/tests/test_path.qm`, `.build/tests/test_path.c`, `.build/tests/test_path.o`.
3. **C Compiler Include Paths:**
   When compiling generated `.c` files to `.o`, the host C compiler is invoked with `-I <build-dir> -I runtime`,
   allowing `#include "util/path.h"` to resolve directly against generated headers in `.build/`.
4. **No Colocated Main and Module Files:**
   A program cannot contain both an `m.quest` and an `m.mod.quest` at the same logical path. Because both files
   would emit `.build/m.qm`, `.build/m.c`, and `.build/m.o`, their compilation artifacts would collide. The driver
   detects and forbids this conflict.

---

## 4. Compilation Artifacts and Metadata Formats

The compilation process produces four distinct artifact types alongside source code:

| Artifact | Source File | Purpose | Generated By | Consumed By |
| :--- | :--- | :--- | :--- | :--- |
| **`.qi`** | `.int.quest` | Quest Interface metadata | Interface Compiler | Module Compiler, Importers |
| **`.h`** | `.int.quest` | C header file (structs, typedefs) | Interface Compiler | C Compiler (`clang`/`gcc`) |
| **`.qm`** | `.mod.quest`, `.quest` | Module metadata (imports) | Module/Main Compiler| Build Queue, Linker |
| **`.c`/`.o`**| `.mod.quest`, `.quest` | C source and native object code | Module Compiler & C Compiler | Host Linker |

### 4.1. Retirement of `.d` Files
Historically, dependency tracking relied on Make-style `.d` files containing object prerequisite lines. This approach
proved brittle and incomplete because Make `.d` files only track object-level relationships and do not capture Quest
interface-to-module contracts or semantic metadata.
- **Decision:** `.d` files are fully retired.
- All module dependency tracking and transitive closure resolution is governed directly by `.qm` files.

### 4.2. Quest Interface Metadata (`.qi`)
A `.qi` file contains the complete type signature of an interface:
- Canonical interface name and declaring source path.
- List of imported interfaces.
- Exported type declarations (abstract types, manifest definitions, records, variants, options).
- Exported value signatures and parameter modes (`val`, `var`, `out`).

### 4.3. Quest Module Metadata (`.qm`)
A `.qm` file records the build manifest for an implementation module or main routine:
- `name`: Canonical module name (e.g. `"util/path"`) or `"<main>"`.
- `interface`: Declared interface name (for modules; `null` for main routines).
- `source`: Path to source file (`.mod.quest` or `.quest`).
- `object`: Path to compiled `.o` file in `.build/`.
- `imported_modules`: Array of imported modules: `[ { "name": "util/strutil", "interface": "util/Strutil" }, ... ]`.
- `imported_interfaces`: Array of imported interfaces with source paths and timestamps:
  `[ { "name": "util/Path", "source": "lib/util/path.int.quest", "mtime": 1727891234 }, ... ]`.

---

## 5. Interface Import Resolution & Staleness Rules

When compiling any source file (module, interface, or main routine) that imports an interface `I`:

```
                           ┌─────────────────────────┐
                           │   Import Interface I    │
                           └────────────┬────────────┘
                                        │
                         Find I.int.quest, I.qi, I.h
                                        │
               ┌────────────────────────┴────────────────────────┐
               ▼                                                 ▼
       I.int.quest exists                              Only I.qi and I.h exist
               │                                                 │
       ┌───────┴───────┐                                         │
       ▼               ▼                                         │
  I.qi or I.h     I.qi and I.h                                   │
    missing         present                                      │
       │               │                                         │
       │         Check datestamps:                               │
       │       I.int.quest > I.qi/I.h?                           │
       │         ┌─────┴─────┐                                   │
       │       Yes           No                                  │
       ▼       ▼             ▼                                   ▼
  ┌─────────────────┐   ┌─────────────────┐             ┌─────────────────┐
  │   OUT OF DATE   │   │   UP TO DATE    │             │   UP TO DATE    │
  │ Compile I first │   │  Read from .qi  │             │ (Precompiled/   │
  │ into .build/    │   │                 │             │  No Source)     │
  └─────────────────┘   └─────────────────┘             └─────────────────┘
```

The compiler applies three strict rules in order:

1. **Rule 1 (Source and Artifacts Present):**
   If `I.int.quest`, `I.qi`, and `I.h` all exist:
   - Compare filesystem modification timestamps (`mtime`).
   - If `I.int.quest` is newer than `I.qi` or `I.h`, the artifacts are **out of date**.
   - If `I.qi` and `I.h` are both newer than or equal to `I.int.quest`, the artifacts are **up to date**.

2. **Rule 2 (Source Present, Artifacts Incomplete):**
   If `I.int.quest` exists but either `I.qi` or `I.h` is missing from `.build/`, the artifacts are **out of date**.

3. **Rule 3 (Binary Distribution / Precompiled Mode):**
   If `I.qi` and `I.h` exist in `.build/` (or an include directory) but `I.int.quest` does not exist:
   - The artifacts are assumed to be **up to date**.
   - This explicitly enables compiling against distributed precompiled Quest standard libraries or third-party
     packages without requiring the original source files.

### 5.1. Action on Interface Staleness
If an interface is determined to be **out of date**:
1. The compiler immediately pauses the dependent compilation unit.
2. The interface compiler compiles `I.int.quest`, generating `I.h` and `I.qi` in `.build/`.
3. If interface compilation fails, compilation aborts with diagnostic messages referencing `I.int.quest`.
4. Once regenerated, the compiler resumes compiling the dependent unit, reading signatures from the fresh `I.qi`.

---

## 6. Module Import Handling During Compilation

When compiling source code (a module `M` or a main routine) that contains:
```quest
import util/path : util/Path;
```

The compiler adheres to strict separation of concerns:
1. **Interface Binding Only:**
   - The compiler resolves and loads the interface `util/Path` using the rules in §5.
   - It checks that all usages of `path.<member>` conform to the signatures declared in `util/Path`.
2. **Deferred Module Implementation:**
   - The compiler does **not** load, parse, or compile `util/path.mod.quest` during this step.
   - It records the dependency tuple `(name: "util/path", interface: "util/Path")`.
3. **Artifact Persistence:**
   - When compiling a module or main routine, this tuple is written to the `.qm` metadata file under `imported_modules`.

---

## 7. The Queue-Driven Full Build Process

Building a Quest application begins with a Quest main routine. The build engine employs a **FIFO work queue** to compute
and rebuild the transitive closure of required modules.

```
                              ┌────────────────────┐
                              │  Queue main.quest  │
                              └─────────┬──────────┘
                                        │
                                        ▼
                               ┌─────────────────┐
                       ┌──────>│ Queue Empty?    ├──────> [ Proceed to Link ]
                       │       └────────┬────────┘
                       │                │ No
                       │                ▼
                       │       ┌─────────────────┐
                       │       │  Pop next item  │
                       │       └────────┬────────┘
                       │                │
                       ▼                ▼
                 Is item stale?
                 - Missing .qm, .c, or .o?
                 - source > .qm or .c?
                 - Any imported interface source > .qm?
                       ┌────────────────┴────────────────┐
                      Yes                                No
                       ▼                                 ▼
             [ Compile Item ]                    [ Read Item .qm ]
             - Rebuild stale interfaces          - Enqueue unvisited
             - Enqueue unvisited modules           imported modules
             - Emit .qm, .c, .o in .build/       - Record .o for linker
             - Record .o for linker
                       │                                 │
                       └────────────────┬────────────────┘
                                        │
                                        └───────┘
```

### 7.1. Build Algorithm

1. **Initialization:**
   - Let `work_queue` be a FIFO queue of compilation items (`main.quest` or module names).
   - Let `discovered_modules` be a set of canonical module names to prevent duplicate enqueueing.
   - Let `linked_objects` be an ordered set of object file paths (`.o`) to pass to the linker.
   - Enqueue the Quest main routine `main.quest`.

2. **Queue Processing Loop:**
   While `work_queue` is not empty, dequeue `item`:

   - **Determine Paths:**
     - For main routine: source is `main.quest`; artifacts are `.build/main.qm`, `.build/main.c`, `.build/main.o`.
     - For module `M`: source is `M.mod.quest`; artifacts are `.build/M.qm`, `.build/M.c`, `.build/M.o`.

   - **Check Staleness:**
     An item is **up to date** (precompiled / binary distribution mode) if:
     - `.qm` and `.o` (or `.c`) exist, and no source `.quest` or `.mod.quest` exists on disk.
     Otherwise, when source is present, an item is **stale** if:
     1. Any corresponding artifact (`.qm`, `.c`, or `.o`) is missing from `.build/`.
     2. `mtime(source) > mtime(.qm)` or `mtime(source) > mtime(.c)` or `mtime(.c) > mtime(.o)`.
     3. Any interface `I` in `.qm.imported_interfaces` has `mtime(I.int.quest) > mtime(.qm)` (the **Transitive Interface
        Invalidation Rule**; see §7.2).

   - **Action if Stale:**
     - Compile the source file (`main.quest` or `M.mod.quest`).
     - For each imported interface: verify and regenerate `I.qi` / `I.h` per §5.
     - Emit `.qm` and `.c` into `.build/`.
     - Compile `.c` to `.o` via the host C compiler (`clang -c ... -o .build/...`).
     - For each module `Dep` in `imported_modules`: if `Dep` is not in `discovered_modules`, add `Dep` to
       `discovered_modules` and enqueue `Dep`.
     - Add `.o` to `linked_objects`.

   - **Action if Up to Date:**
     - Read the existing `.qm` file from `.build/`.
     - For each module `Dep` in `.qm.imported_modules`: if `Dep` is not in `discovered_modules`, add `Dep` to
       `discovered_modules` and enqueue `Dep`.
     - Add `.o` to `linked_objects`.

3. **Termination:**
   When the queue is empty, all units in the transitive closure are guaranteed to have current `.qm`, `.c`, and
   `.o` files in `.build/`.

### 7.2. The Transitive Interface Invalidation Rule
A critical flaw in naive separate compilation systems is the *Fragile Interface Problem*:
> If an interface `util/Strutil` is updated, `util/path.mod.quest` may not have been touched, meaning
> `path.mod.quest` is *older* than `path.c` and `path.qm`. However, `path.c` was compiled against struct offsets and
> prototypes in the *previous* `strutil.h`. Skipping `path` produces binary desynchronization and runtime faults.

**Resolution:** When inspecting an existing `.qm` file during staleness checking, the compiler checks the datestamps
of all interfaces recorded in `imported_interfaces`. If any interface source (`I.int.quest`) is newer than `M.qm`,
unit `M` is deemed **stale** and recompiled against the updated interface.

---

## 8. Self-Guarding Idempotent Module Initialization & Linking

### 8.1. Initialization Mechanics
Initialization order does **not** depend on compilation order or queue order. Each compiled module `M` emits a
self-guarding, idempotent initialization function `qv_mod_<M>_init()`:

```c
static bool qv_mod_M_initialized = false;

void qv_mod_M_init(void) {
    if (qv_mod_M_initialized) return;
    qv_mod_M_initialized = true;

    /* Initialize direct dependencies first */
    qv_mod_dep1_init();
    qv_mod_dep2_init();

    /* Evaluate top-level module bindings and instantiate module record */
    ...
}
```

- **Dynamic Depth-First Post-Order:** Because each module's initializer recursively invokes the initializers of the
  modules it directly imports before running its own body, initialization order is dynamically resolved at runtime in
  strict dependency order (dependencies initialize before dependents).
- **Idempotency:** The `qv_mod_M_initialized` guard ensures every module record is evaluated exactly once, even in
  diamond dependency topologies (e.g. `A` imports `B` and `C`, both importing `D`).
- **Main Routine Entry:** In `main()`, the generated C code simply invokes `qv_mod_dep_init()` for the modules directly
  imported by the main routine.

### 8.2. Cycle Detection
While interfaces may cross-reference types freely, circular module implementation dependencies are invalid.
- At build time, the driver inspects the `.qm` dependency graph to detect cycles and emit descriptive errors before
  invoking the linker.
- At runtime, a recursion guard flag (`qv_mod_M_in_progress`) can optionally trap any circular initialization attempts.

### 8.3. Native Linking
Once the queue is empty, the driver invokes the host C compiler / linker:
```sh
clang -o app .build/main.o .build/util/path.o .build/util/strutil.o ... runtime/quest_runtime.o -lgc
```
Passing all discovered `.o` files in `linked_objects`.

---

## 9. Build Logging and Audit Trail

To make the separate compilation process completely transparent and debuggable, the compiler records all build events
to an audit log:
- **Default Location:** `<build-dir>/build.log` (e.g. `.build/build.log`).
- **Configuration:** Controlled via `--build-log <path>` or disabled via `--no-build-log`.
- **Verbose Console Output:** The `--verbose` CLI flag echoes all build log entries directly to `stderr` in real time.

### 9.1. Log File Structure
The log records structured timestamps, queue transitions, staleness evaluations, and tool invocations:

```
[2026-10-02T16:50:01] BUILD START: target=tests/source/stdlib/path_operations.quest mode=separate build_dir=.build
[2026-10-02T16:50:01] QUEUE INIT: enqueued main routine 'path_operations'
[2026-10-02T16:50:01] POP QUEUE: 'path_operations'
[2026-10-02T16:50:01] EVAL STALENESS: 'path_operations' -> STALE (.build/path_operations.qm missing)
[2026-10-02T16:50:01] COMPILE MAIN: 'path_operations'
[2026-10-02T16:50:01] RESOLVE INTERFACE: 'util/Path' -> 'lib/util/path.int.quest'
[2026-10-02T16:50:01] EVAL STALENESS: 'util/Path' (.build/util/path.qi, .h) -> UP TO DATE
[2026-10-02T16:50:01] WRITE QM: .build/path_operations.qm
[2026-10-02T16:50:01] EMIT C: .build/path_operations.c
[2026-10-02T16:50:01] HOST COMPILE: clang -c .build/path_operations.c -o .build/path_operations.o
[2026-10-02T16:50:01] ENQUEUE MODULE: 'util/path' (from main import)
[2026-10-02T16:50:01] POP QUEUE: 'util/path'
[2026-10-02T16:50:01] EVAL STALENESS: 'util/path' -> STALE (strutil.int.quest > path.qm)
[2026-10-02T16:50:01] COMPILE MODULE: 'util/path'
[2026-10-02T16:50:01] ENQUEUE MODULE: 'util/strutil' (from util/path import)
[2026-10-02T16:50:01] ENQUEUE MODULE: 'util/stringbuilder' (from util/path import)
[2026-10-02T16:50:01] WRITE QM: .build/util/path.qm
[2026-10-02T16:50:01] EMIT C: .build/util/path.c
[2026-10-02T16:50:01] HOST COMPILE: clang -c .build/util/path.c -o .build/util/path.o
[2026-10-02T16:50:02] POP QUEUE: 'util/strutil'
[2026-10-02T16:50:02] EVAL STALENESS: 'util/strutil' -> UP TO DATE
[2026-10-02T16:50:02] READ QM: .build/util/strutil.qm (no new unvisited modules)
...
[2026-10-02T16:50:03] QUEUE EMPTY: transitive closure verified (4 modules)
[2026-10-02T16:50:03] HOST LINK: clang -o app .build/path_operations.o .build/util/path.o ... -lquest_runtime
[2026-10-02T16:50:03] BUILD COMPLETE: exit_code=0
```

---

## 10. Summary of Architectural Guarantees

1. **Deterministic Staleness:** Interface and module updates propagate reliably through the transitive closure via the
   `.qm` invalidation rules, eliminating runtime struct offset mismatches and stale object crashes.
2. **Clean Source Tree:** All generated files (`.qi`, `.h`, `.qm`, `.c`, `.o`) live strictly under `.build/`.
3. **Decoupled Compilation Units:** Compiling a module never triggers compilation of other modules—it only records
   module names and validates against interface `.qi` files.
4. **Order-Independent Initialization:** Dynamic, self-guarding module initializers guarantee correct initialization
   order at runtime regardless of queue discovery order.
5. **Uniform Main Routines:** Main routines emit `.qm` files, allowing incremental builds to read imports without
   re-parsing source code.
6. **Full Auditability:** Every scheduling and staleness decision is captured in `build.log` and optionally displayed
   with `--verbose`.
