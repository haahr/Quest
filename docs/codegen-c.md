# C Code Generator and Host Compilation Architecture (`codegen_c`)

This document specifies the architecture, code generation rules, statement-expression lowerings, and host compiler
driver for **Step 4: Bootstrap C Transpiler** (`bootstrap/python/quest/codegen/`).

---

## 1. Overview and Architecture

The C code generation phase (`CodegenCPhase`, canonical name `codegen_c`) translates a type-checked Quest AST
(`TypedProgram`) into portable C99 source code, which is then compiled into a native binary executable by invoking
the host C toolchain (`clang` or `gcc`).

```
Typed AST (TypedProgram)
           |
           v
+-----------------------+      c_types.py: Maps QType -> C scalar types, mangles identifiers
|      CEmitter         | <---
| (c_emitter.py)        |      AST Visitor: Lowers literals, bindings, operators, control flow
+-----------------------+
           |
           v  (C99 Source String)
+-----------------------+
|   compiler_runner.py  | <--- Locates clang/gcc, auto-detects Boehm GC, adds -I runtime/
+-----------------------+
           |
           v
    Native Binary (Executable)
```

### Module Structure (`bootstrap/python/quest/codegen/`)
- **`c_types.py`:** C scalar type mappings, identifier mangling (`qv_<name>`), operator name mangling, and type names.
- **`c_emitter.py`:** Core AST visitor class `CEmitter` generating C99 code for phrases, bindings, and expressions.
- **`compiler_runner.py`:** Discovers host compiler, auto-detects Boehm GC, compiles C source, and runs binaries.
- **`__init__.py`:** Package exports (`CEmitter`, `compile_c_source`, `run_binary`).

---

## 2. Type Mapping and Identifier Mangling (`c_types.py`)

### 2.1. Scalar Type Mapping
Quest scalar types map to native C99 types defined in `runtime/quest_runtime.h`:

| Quest Type | C Type | Description |
| :--- | :--- | :--- |
| `Int` | `QInt` (`int64_t`) | 64-bit signed integer |
| `Real` | `QReal` (`double`) | 64-bit IEEE-754 double precision float |
| `Bool` | `QBool` (`bool`) | C99 boolean (`true` / `false`) |
| `Char` | `QChar` (`char`) | 8-bit character (extended in 64-bit word when in `QVal`) |
| `String` | `QString *` | Pointer to heap-allocated string descriptor |
| `Ok` | `void` / `QVal` | Statement completion indicator (`Q_OK_VAL`) |
| Polymorphic / Generic | `QVal` | Uniform 64-bit value word union |

### 2.2. Identifier Namespacing
To prevent collisions with C99 keywords (`int`, `return`, `default`, `static`, etc.) and libc symbols:
- **Value and variable names** are prefixed with `qv_`:
  - `let x = 10` $ightarrow$ `QInt qv_x = 10LL;`
  - `let default = true` $ightarrow$ `QBool qv_default = true;`
- **Temporary variable names** are generated uniquely with fresh counters:
  - `_res_1`, `_if_res_2`, `_div_r_3`

### 2.3. Operator Mangling
When operators appear as first-class functions or bindings, they are mangled with the prefix `qv_sym_`:
- `+` $ightarrow$ `qv_sym_plus`
- `++` $ightarrow$ `qv_sym_plus_plus`
- `<>` $ightarrow$ `qv_sym_lessthan_greaterthan`
- `:=` $ightarrow$ `qv_sym_colon_equals`

---

## 3. Program Structure and Code Emission (`c_emitter.py`)

### 3.1. Program Boilerplate
`CEmitter.emit_program()` emits a standalone C99 compilation unit containing:
1. Preamble include: `#include "quest_runtime.h"`
2. Entry point: `int main(int argc, char **argv)`
3. Runtime initialization: `quest_gc_init()` (initializes Boehm GC or no-op if `-DQUEST_NOGC`)
4. Sequential emission of all top-level phrases.
5. Exit: `return 0;`

```c
/* Emitted by Quest Bootstrap C Transpiler */
#include "quest_runtime.h"

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    quest_gc_init();

    /* Top-level phrases */
    ...

    return 0;
}
```

### 3.2. Let Bindings and Variables
- **Immutable Bindings (`TypedLetValue` with `is_var=False`):**
  Emitted directly as a typed C local variable:
  ```c
  /* let x = 42; */
  QInt qv_x = (42LL);
  ```
- **Mutable Bindings (`TypedLetValue` with `is_var=True`):**
  Emitted as a standard C variable:
  ```c
  /* let var count = 0; */
  QInt qv_count = (0LL);
  ```
- **Assignment Mutation (`TypedAssign`):**
  ```c
  /* count := count + 1; */
  qv_count = ((qv_count) + (1LL));
  ```

### 3.3. Cardelli Non-Overloaded Operators
In Quest, operators are strictly non-overloaded (§4.2). The transpiler emits direct C99 expressions:

- **Integer Arithmetic:** `+`, `-`, `*` map to C `+`, `-`, `*`.
- **Integer Division & Modulo:** `/` and `%` call inline runtime functions with zero-divisor checks:
  ```c
  /* 42 / x */
  quest_int_div(42LL, qv_x)
  /* 42 % x */
  quest_int_mod(42LL, qv_x)
  ```
- **Real Arithmetic (Doubled Symbols):**
  - `++` $\rightarrow$ `(l) + (r)`
  - `--` $\rightarrow$ `(l) - (r)`
  - `**` $\rightarrow$ `(l) * (r)`
  - `//` $\rightarrow$ `(l) / (r)`
  - `^^` (exponentiation) $\rightarrow$ `quest_real_pow((l), (r))`
- **Relational Comparisons:**
  - Integer: `<`, `<=`, `>`, `>=`
  - Real: `<<` $\rightarrow$ `<`, `<<=` $\rightarrow$ `<=`, `>>` $\rightarrow$ `>`, `>>=` $\rightarrow$ `>=`
- **Identity and Equality:**
  - `is` and `==` map to C `==` (for scalars) or `quest_string_equal` (for strings).
  - `isnot` maps to C `!=` (or `!quest_string_equal`).
- **String Concatenation:**
  - `<>` calls `quest_string_concat(s1, s2)`.

---

## 4. Control Flow and Standard C99 Lowering

Because Quest is an expression-oriented language, constructs like `if`, `begin ... end`, and loops can appear in
arbitrary expression positions (e.g. `let x = if c then 1 else 2 end;`).

To lower these into strict, portable **standard ISO C99** without relying on non-standard GCC/Clang statement
expressions (`({ ... })`), the transpiler employs destination-passing statement lowering:
- Expressions evaluating in statement context (e.g. bindings, returns, or phrase sequences) emit directly into their
  destination.
- Control constructs (`if`, loops, blocks) decompose into standard C99 statements and blocks (`{ ... }`).
- When a complex expression appears as a sub-expression (e.g. inside an arithmetic operation), temporary variables
  are hoisted and emitted as preparation statements immediately preceding the consumer.

### 4.1. Conditionals (`TypedIf`)
- **Value-Producing If Expression:**
  ```c
  /* let x = if a > 0 then 10 else 20 end; */
  if ((qv_a) > (0LL)) {
      qv_x = 10LL;
  } else {
      qv_x = 20LL;
  }
  ```
- **Statement / Ok-typed If:**
  ```c
  if (cond) {
      then_body;
  } else {
      else_body;
  }
  ```

### 4.2. Sequential Blocks (`TypedBlock`)
A block scopes local variable declarations and evaluates to its destination inside standard C braces:
```c
/* begin let a = 5; let b = 6; a * b end */
{
    QInt qv_a;
    qv_a = 5LL;
    QInt qv_b;
    qv_b = 6LL;
    dest = ((qv_a) * (qv_b));
}
```

### 4.3. While and Infinite Loops (`TypedWhile`, `TypedLoop`, `TypedExit`)
- **`while <cond> do <body> end`:**
  Emitted as standard C `while (1)` with condition checking and early break:
  ```c
  while (1) {
      if (!(cond)) break;
      body;
  }
  ```
- **`loop <body> end`:**
  ```c
  while (1) {
      body;
  }
  ```
- **`exit`:**
  Emitted directly as `break;`.

### 4.4. For Loops (`TypedFor`)
Quest provides both ascending (`upto`) and descending (`downto`) loops, emitted as standard C99 `for` loops:
- **`for i = 1 upto 5 do <body> end`:**
  ```c
  QInt _stop_1 = 5LL;
  for (QInt qv_i = 1LL; qv_i <= _stop_1; qv_i++) {
      body;
  }
  ```
- **`for i = 5 downto 1 do <body> end`:**
  ```c
  QInt _stop_1 = 1LL;
  for (QInt qv_i = 5LL; qv_i >= _stop_1; qv_i--) {
      body;
  }
  ```

---

---

## 5. Functions & Direct Calling Conventions (Phase 4.2a)

### 5.1. Function Declaration Hoisting & Static Scope
Top-level function definitions (`let f(...) = ...`, `let rec f(...) = ...`) are hoisted out of `main()` to C file scope:
- **Top-Level Variable Hoisting:** Non-function top-level variables (`let x = 10;`) are declared as file-scope static C
  variables (`static QInt qv_x;`) and initialized inside `main()` in program order, ensuring top-level functions can
  read and mutate them.
- **Prototypes & Forward Declarations:** Before emitting function definitions, the transpiler generates static forward
  declarations for all top-level functions:
  ```c
  static QInt qv_factorial(QInt qv_n);
  ```
  This allows recursive and mutually referenced functions to compile without order dependency.

### 5.2. Direct Calling Convention & Currying Flattening
- **Uncurried Signatures:** Functions defined with multi-parameter or curried syntax are flattened into direct,
  zero-overhead uncurried C function signatures:
  ```c
  /* let add(x: Int y: Int): Int = x + y; */
  static QInt qv_add(QInt qv_x, QInt qv_y) {
      return ((qv_x) + (qv_y));
  }
  ```
- **Application Flattening:** Fully applied call sites (`add(10 20)` or `add(10)(20)`) are flattened into direct
  C invocations `qv_add(10LL, 20LL)`.
- **`Ok` Return Types:** Functions returning `Ok` emit `void` return types and clean `return;` statements. At statement
  call sites, calls returning `Ok` are emitted directly as statement calls: `qv_proc(...);`.

---

## 6. Host Compiler Runner (`compiler_runner.py`)

The compiler runner manages external C compiler toolchain discovery, Boehm GC flags, and native executable generation:

### 6.1. Compiler Discovery
`find_c_compiler()` searches `PATH` in order:
1. `clang` (preferred on macOS/Linux for optimal diagnostic output and C99 statement expression support).
2. `gcc` (fallback).

### 6.2. Boehm GC Auto-Detection & `--nogc`
`detect_gc_flags(nogc: bool)` locates the Boehm Garbage Collector:
- Standard paths checked: `/opt/homebrew/opt/bdw-gc` (Apple Silicon), `/usr/local/opt/bdw-gc` (Intel macOS), `/usr`.
- If found: passes `-I<prefix>/include -L<prefix>/lib -lgc`.
- If not found or when `--nogc` flag is specified: passes `-DQUEST_NOGC`, using standard libc `calloc`/`malloc`.

### 6.3. Compilation Invocation
`compile_c_source(c_source, output_path, nogc)`:
1. Writes emitted C source to a temporary file (`.c`).
2. Constructs compilation command:
   ```bash
   clang -std=c99 -Wall -Wextra -O2 \
     -I <repo_root>/runtime <repo_root>/runtime/quest_runtime.c \
     <temp.c> -o <out_bin> [GC_FLAGS]
   ```
3. Executes command via `subprocess.run()`. On failure, captures `stderr` and raises `RuntimeError`.
4. Cleans up temporary C source file.

---

## 7. Testing & Verification

The C code generator is verified by comprehensive unit and integration tests:
- `tests/python/test_phase4_1_c_codegen.py`: Scalar operations, control flow, memory modes, and runtime panic tests.
- `tests/python/test_phase4_2a_functions.py`: Top-level and recursive functions, direct C calling conventions,
  curried application flattening, mutable top-level variables, and `--nogc` execution.
- `tests/source/02_expressions_control_flow.quest`: Verified end-to-end native compilation and execution.

---

## See Also
- [c-representation.md](c-representation.md): 64-bit `QVal` representation, ABI assertions, and aggregate layouts.
- [pipeline.md](pipeline.md): Pipeline passes and driver CLI commands.
- [runtime-design.md](runtime-design.md): Architectural design for Evidence Passing and runtime representations.
