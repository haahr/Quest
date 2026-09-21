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

## 6. Tuples & Concrete Records (Phase 4.2b)

Phase 4.2b introduces standard C99 code generation for tuples and concrete records with heap allocation, uniform 64-bit
slot layout, and direct pointer-based field access.

### 6.1. C Struct Layout & Tag Generation
- **Positional Tuple Structs:** Tuple types map to positional members `_0`, `_1`, ... based on their component value
  fields (`t.value_fields`). Struct names are deterministic and reflect component types:
  ```c
  /* Tuple x: Int y: Real end */
  typedef struct QTuple_Int_Real QTuple_Int_Real;

  struct QTuple_Int_Real {
      QInt _0;
      QReal _1;
  };
  ```
- **Canonical Alphabetized Record Structs:** Records are unordered product types with structural equivalence. To ensure
  structurally identical record types share the same C struct definition, record struct members are sorted
  alphabetically by field name, prefixed with `qf_` (to avoid C keyword collisions):
  ```c
  /* record x = 10, y = 20.0 end */
  typedef struct QRecord_x_Int_y_Real QRecord_x_Int_y_Real;

  struct QRecord_x_Int_y_Real {
      QInt qf_x;
      QReal qf_y;
  };
  ```
- **Forward Typedef Hoisting:** The transpiler recursively discovers all `QTupleType` and `QRecordType` instances
  across the AST and emits forward declarations (`typedef struct Tag Tag;`) before any struct bodies, static variables,
  or function prototypes. This guarantees that mutually referencing or nested aggregate types compile cleanly without
  ordering dependencies.

### 6.2. Heap Allocation & Member Initialization
Tuples and records are heap-allocated via `quest_alloc(sizeof(StructTag))` (managed by Boehm GC or standard `calloc`
in `--nogc` mode):
```c
/* origin = tuple let x = 0 let y = 0.0 end */
qv_origin = (QTuple_Int_Real *)quest_alloc(sizeof(QTuple_Int_Real));
qv_origin->_0 = 0LL;
qv_origin->_1 = 0.0;
```
When an aggregate expression appears in a value context (e.g. passed directly to a function call or returned from an
expression), a local temporary pointer is allocated and returned.

### 6.3. Field Selection & Mutable Field Assignment
- **Selection (`TypedSelect`):**
  - For tuples: Named fields are mapped to their 0-based value component index at compile-time (`p.x` -> `qv_p->_0`).
    Unnamed fields accessed by index also map directly (`t._0` -> `qv_t->_0`).
  - For records: Field accesses map directly to the mangled field name (`r.x` -> `qv_r->qf_x`).
- **Mutable Assignment (`TypedAssign`):**
  - When the target of `TypedAssign` is a `TypedSelect` expression on a mutable record field (`var y = ...`), the
    target expression is evaluated as an lvalue pointer dereference, storing the value directly into the heap struct:
  ```c
  /* r.y := 42; */
  qv_r->qf_y = 42LL;
  ```

---

## 7. Closures, Function Values & Lambda Lifting (Phase 4.2c)

In Quest, functions are first-class values that can be passed to higher-order functions, returned from functions,
and capture variables from enclosing lexical scopes.

### 7.1. Closure Representation (`QClosure`)
First-class function values use the uniform 16-byte `QClosure` struct defined in `runtime/quest_runtime.h`:
```c
typedef struct QClosure {
    void *fn;   /* C function pointer: RetType (*)(void *env, ...) */
    void *env;  /* Captured environment struct pointer or NULL */
} QClosure;

static_assert(sizeof(QClosure) == 16, qclosure_must_be_16_bytes);
static_assert(offsetof(QClosure, env) == 8, qclosure_env_at_offset_8);
```

### 7.2. Direct Top-Level Calls vs. Trampoline Adapters
1. **Direct Top-Level Calls:** Direct calls to statically known top-level functions remain zero-overhead standard C
   function calls (`qv_f(args...)`) without passing an unused `env` pointer.
2. **First-Class Value Passing:** When a top-level function is referenced as a value (e.g., passed to an argument
   expecting `QFunType`), the transpiler synthesizes a static trampoline adapter and a file-scope static `QClosure`:
   ```c
   static QInt qv_add1_trampoline(void *env, QInt qv_x) {
       (void)env;
       return qv_add1(qv_x);
   }
   static QClosure qv_add1_closure = { (void *)qv_add1_trampoline, NULL };
   ```
   Passing `add1` in expression context emits `(&qv_add1_closure)` directly without heap allocation.

### 7.3. Lambda Lifting & Flat Environment Frames
Inner `TypedFun` expressions undergo free variable analysis (`_find_free_vars`):
1. **Capturing Lambdas:**
   - A dedicated flat environment struct `struct QEnv_<lid> { ... }` is generated containing the captured types.
   - The lambda body is lifted to file scope as `static RetType qv_<lid>(void *_raw_env, Params...)`.
   - At the instantiation site, the environment and a `QClosure` are allocated on the heap via `quest_alloc`:
     ```c
     struct QEnv_lambda_1 *_env = (struct QEnv_lambda_1 *)quest_alloc(sizeof(struct QEnv_lambda_1));
     _env->qv_x = qv_x;
     QClosure *_clos = (QClosure *)quest_alloc(sizeof(QClosure));
     _clos->fn = (void *)qv_lambda_1;
     _clos->env = (void *)_env;
     ```
2. **Non-Capturing Lambdas:**
   - Lifted to file scope with `(void)_raw_env;`.
   - Emits a static singleton closure `static QClosure qv_<lid>_closure = { (void *)qv_<lid>, NULL };` and passes
     `&qv_<lid>_closure`, avoiding heap allocations entirely.

### 7.4. Indirect Closure Invocations
When calling an indirect target (such as a closure parameter or returned function), the call site casts `fn` to the
expected C function pointer signature and passes `env` as the first argument:
```c
((QInt (*)(void *, QInt))(qv_f->fn))(qv_f->env, qv_x)
```

---

## 8. Arrays and Strings (Phase 4.3)

### 8.1. Array Representation (`QArray`)
Arrays are mutable buffers of 64-bit `QVal` words with an explicit length prefix:
```c
typedef struct QArray {
    int64_t length;
    QVal    data[];
} QArray;

static_assert(offsetof(QArray, data) == 8, qarray_data_at_offset_8);
```

### 8.2. Allocation and Construction
- **Explicit Element Lists (`TypedArray`):**
  Allocates the structure and populates each element wrapped as a `QVal`:
  ```c
  QArray *qv_arr = (QArray *)quest_alloc(sizeof(QArray) + (size_t)(4LL) * sizeof(QVal));
  qv_arr->length = 4LL;
  qv_arr->data[0LL] = ((QVal){ .i = (int64_t)(10LL) });
  ...
  ```
- **Repetition (`TypedArrayRep`):**
  Invokes `quest_array_new(length, init_val)` which verifies $N \ge 0$ and initializes all elements.

### 8.3. Indexing and Mutation
Array indexing (`a[i]`) and mutation (`a[i] := v`) emit inline bounds checking followed by direct access into `data[]`:
```c
quest_check_array_bounds(qv_arr, qv_i);
QInt elem = qv_arr->data[qv_i].i;

quest_check_array_bounds(qv_arr, qv_i);
qv_arr->data[qv_i] = ((QVal){ .i = (int64_t)(99LL) });
```
Out-of-bounds indices and negative sizes trigger `quest_raise_array_error()`, printing `Exception: arrayOp.error\n`
and terminating with exit code 1.

---

## 9. Options and Variants (Sums) (Phase 4.4)

### 9.1. Option Types
Option types are ordered sums with inline union payloads. Each unique `QOptionType` synthesizes:
- A tag enumeration: `QTAG_<Option>_<branch> = <index>`.
- A C struct containing `int64_t tag` and an inline union of branch structs for branches carrying components:
  ```c
  typedef struct QOption_... {
      int64_t tag;
      union {
          struct { QInt _0; } branch1;
          ...
      } u;
  } QOption_...;
  ```

### 9.2. Variant Types
Variant types are unordered sums with a single 64-bit payload word, represented as first-class 16-byte values:
```c
typedef struct QVariantVal {
    int64_t tag;
    QVal    payload;
} QVariantVal;

static_assert(sizeof(QVariantVal) == 16, qvariantval_must_be_16_bytes);
static_assert(offsetof(QVariantVal, tag) == 0, qvariantval_tag_at_offset_0);
static_assert(offsetof(QVariantVal, payload) == 8, qvariantval_payload_at_offset_8);
```

### 9.3. Injections, Tag Queries, Extractions, and Pattern Matching
- **Injection:** `option b of T with payload end` allocates and populates the union branch; `variant b of T with v end`
  constructs an unboxed `QVariantVal` compound literal directly with zero heap allocations.
- **Tag Query (`target?tag`):** Checks `target.tag == EXPECTED_TAG` on variants (or `target->tag == EXPECTED_TAG`
  on options).
- **Tag Assertion (`target!tag`):** Asserts tag match (panics with `Exception: variant.tagMismatch\n` on failure).
  Returns `payload` for variants, or a `QTuple` prepending the ordinal for options.
- **Pattern Matching (`case`):** Lowers to standard C `switch (target.tag)` (or `target->tag` for options) with
  branch payload binders.

---

## 10. Structural Subtyping & Dynamic Dispatch (Phase 4.5)

Phase 4.5 implements Cardelli's structural subtyping across tuples, records, and variants:

### 10.1. Prefix Tuple Subtyping
- **Direct Pointer Coercion:** A wider tuple pointer `QT_Triple *` is cast directly to a prefix tuple `(QT_Pair *)`.
- **Memoized Compile-Time Layout Verification:**
  ```c
  static_assert(offsetof(QT_Triple, _0) == offsetof(QT_Pair, _0), tuple_subtyping_offset_match_0);
  static_assert(offsetof(QT_Triple, _1) == offsetof(QT_Pair, _1), tuple_subtyping_offset_match_1);
  ```

### 10.2. Evidence-Passing Record Subtyping
- **Object Header:** Every concrete record structure begins with `QRecordHeader header;` at offset 0
  (`header.descriptor = NULL;`).
- **First-Class Fat Pointers (`QRecordVal`):** All records are represented uniformly as a 16-byte struct:
  ```c
  typedef struct QRecordVal {
      void       *val;   /* Pointer to heap-allocated QT_<Record> payload */
      const void *dict;  /* Pointer to static OffsetDict_<Record> */
  } QRecordVal;
  ```
- **Function Parameters & Returns:** Functions take `QRecordVal` directly and return `QRecordVal` directly
  (passed in `x0, x1` under AAPCS64), eliminating companion dictionary arguments.
- **Dictionary Naming:** Uses alias name when available (`OffsetDict_<Alias>`), or sequential per-module identifier
  `OffsetDict_<Module>_record<N>` / `OffsetDict_record<N>`.
- **Field Selection:** Dynamic dispatch reads fields via byte offsets from embedded dictionaries:
  ```c
  (*((QInt *)((char *)qv_pt.val + ((const OffsetDict_Point2D *)qv_pt.dict)->offset_x)))
  ```
- **Aggregate Storage:** Records and variants in tuples are stored inline as 16-byte values (`QRecordVal` and
  `QVariantVal`). In arrays (`QArray`), they are boxed into 8-byte heap pointers (`QRecordVal *`, `QVariantVal *`)
  via `quest_record_box` and `quest_variant_box`, setting the stage for future unboxed multi-stride arrays.
  Subtyped variants in aggregates apply static tag remapping (`tagmap_<Target>_<Source>`) at insertion time.

### 10.3. Variant Subtyping & Static Tag Remapping
- **First-Class Value Representation:** `QVariantVal` is a 16-byte value type (`int64_t tag; QVal payload;`).
  Variant creation, checks (`v?x`), assertions (`v!x`), and `case` pattern matching execute with zero heap allocations.
- **Static Tag Tables:** Static lookup tables in `.rodata` translate source tags to target tags:
  ```c
  static const int64_t tagmap_Large_Small[] = { 2LL, 1LL };
  ```
- **Zero-Allocation Upcast:** Coercion emits an unboxed compound literal:
  `((QVariantVal){ .tag = tagmap_Large_Small[src.tag], .payload = src.payload })`.

### 10.4. Bounded Specialization for Records and Variants (Phase 4.9b)
- **Runtime Descriptor Retention:** Bounded polymorphic functions retain `const QTypeDescriptor *descriptor_<T>`
  parameters in their C signatures to facilitate separate compilation and uniform reflection.
- **Bounded Record Parameters & Field Selection:** Functions expecting `A <: Record` receive `QRecordVal` directly.
  Field selection `p.x` dynamically indexes through the passed-in dictionary:
  `((const OffsetDict_Bound *)p.dict)->offset_x`.
- **Caller Dictionary Restoration on Return:** When returning a bounded type variable `A <: Record`, the caller
  restores the dictionary (`Option A: Caller Restores Dictionary`), attaching the identity dictionary `&offsetdict_T_T`
  of the concrete type argument `T` to the returned `.val`.
- **Bounded Variant Parameters & Call-Site Tag Alignment:** Callers align variant tags to the bound variant type using
  static `.rodata` tag tables into an unboxed compound literal, allowing callees to switch directly on `v.tag` without
  runtime translation or heap allocation.

### 10.5. Call-Site Specialization for Unbounded Quantifiers (Phase 4.9c)
When unbounded polymorphic functions (`All(A::TYPE)`) are invoked at call sites with concrete `Record` or `Variant`
arguments:
- **Specialization Analysis Pass (`c_analysis.py`):** Scans the AST worklist for call sites where type arguments
  require specialization (`is_specialization_needed`). Clones the `TypedFun` node with substituted types, synthesizes
  specialized identifier `qv_<name>_spec_<type_tags>`, and populates aggregate types from cloned bodies.
- **Direct Calling Convention & Zero-Boxing:** Specialized function clones take unboxed `QRecordVal` and `QVariantVal`
  parameters directly without descriptor parameters (unless uninstantiated quantifiers remain) and pass them in
  register pairs `(x0, x1)` without heap boxing.
- **Struct Layout Alignment:** Generic tuples within specialized clones instantiate concrete C structs
  (`struct QTuple_<TypeTags>`) with 16-byte inline slots matching caller expectations, eliminating pointer mismatches.
- **First-Class Fallback:** The canonical unspecialized `QVal` version is retained for indirect calls and closures.

### 10.6. Flat Stride Arrays (Phase 4.9d)
Arrays containing records or variants (`Array(Record)` and `Array(Variant)`) are lowered to specialized wide array
structures (`QArrayWideRecord` and `QArrayWideVariant`):
- **Flat 16-Byte Stride Buffers:** Elements are stored directly in contiguous memory buffers without individual
  heap boxing (`quest_record_box` / `quest_variant_box`).
- **In-Place Read and Write:** Indexing (`arr[i]`) and assignment (`arr[i] := val`) operate directly on 16-byte
  slots in-place, passing and returning values in register pairs `(x0, x1)` with zero heap allocation.
- **Subtyping Coercion at Insertion:** Inserting a subtyped record or variant into an array evaluates evidence
  dictionary attachment or static tag remapping at insertion time and stores the result flat in the array slot.
- **Interaction with Call-Site Specialization:** Generic functions operating on `Array(A)` where `A` is a record
  or variant specialize to concrete clones that access flat wide arrays directly.

### 10.7. Unified Native Module Mechanism & Hybrid Modules (Phase 4.11)
All modules—whether pure Quest, standard library built-ins (`writer`, `reader`, `conv`, `ascii`, `int`, `real`,
`string`, `system`, `arrayOp`, `dynamic`), or user-defined hybrid modules—are compiled uniformly:
- **Unified Pipeline (Section 8b Emission):** Legacy Section 8c and ad-hoc string matching
  (`_builtin_call_c_expr` / `_builtin_val_c_expr`) are eliminated. All modules emit uniform declarations in
  `c_declarations.py` and module initializers/trampolines in Section 8b of `c_emitter.py`.
- **Topological Lazy Initializers (`qv_mod_<name>_init`):**
  - Each module emits an initialization function guarded by `qv_mod_<name>_initialized` for idempotent execution.
  - Recursively triggers initializers of dependency modules in topological order before executing local bindings.
  - Allocates the module payload struct (`QT_<Interface>`) and populates all exported fields with **concrete values**:
    - Native bindings (`TypedNativeBinding`) and pure Quest functions emit static trampolines
      (`qv_<mod>_<fn>_trampoline`) with `(void)arg_{i}` unused parameter suppression, wrapped in `QClosure *` objects.
    - Native constants (`TypedExternal`) and evaluated `let` bindings populate fields directly, wrapping in `QVal`
      (`_qval_wrap`) if the interface field is abstract.
- **Direct Native Call Lowering:** When selecting a function on a known module (e.g. `writer.putString(w s)`), the
  compiler resolves the native binding and directly emits `quest_writer_put_string(...)` or expands the inline
  template, bypassing closure allocation and indirect calls.
- **External C Types and Values:** `external "C_TYPE"` and `external "C_SYMBOL"` seamlessly bridge C runtime
  structures (e.g. `QWriter *`, `QReader *`) into Quest's type system without compiler special-casing.

### 10.8. Mutable Reference Parameters (`out` and `var`) and `@` Lvalues (Phase 4.12)
Phase 4.12 implements native pointer lowering for Cardelli's mutable reference parameters:
- **Native Pointer Parameters (`T *`):** Parameters marked `var p: T` or `out p: T` compile directly to
  `T *qv_p` in C declarations, definitions, and closure trampolines. Reads from `var` parameters dereference the
  pointer (`*qv_p`), and writes to `var`/`out` parameters assign through the pointer (`*qv_p = val;`).
- **Callsite Lvalue Emission (`@`):**
  - Variable references `@x` emit `&qv_x`.
  - Pointer parameter forwarding `g(@y)` directly passes `qv_y` without taking its address (`&`).
  - Record field references `@r.f` emit pointers into the heap record buffer
    (`(({fld_t} *)((char *)rec.val + offset))`).
  - Array element references `@a[i]` emit pointers into the flat array buffer (`&arr->data[i]`).
  - Tuple element references `@t.1` emit pointers to tuple components (`&tup->_1`).
  - Temporary cells `var(e)` evaluate `e` into a stack local and pass its address (`&_var_cell`).
- **Polymorphic Reference Invocations (Two-Tier Model):**
  - **Tier 1 (Specialization):** Direct calls in the compilation unit trigger AST specialization in `c_analysis.py`.
    The specialized function takes native `T *qv_p` parameters, passing lvalue pointers directly without overhead.
  - **Tier 2 (Shadow Cell Fallback):** When calling unspecialized polymorphic functions (`var p: A` where `qv_p` is
    `QVal *`), the caller generates a stack shadow cell `QVal _shadow_cell`. For `var` parameters, it performs copy-in
    via `_qval_wrap(*_loc_ptr, T)` (boxing 16-byte `QRecordVal` fat pointers and `QVariantVal`), passes `&_shadow_cell`
    to the callee, and performs copy-out writeback `*_loc_ptr = _qval_unwrap(_shadow_cell, T)` after return.
- **Closure Capture Restrictions:** Closure capture of `out`/`var` parameters or local stack mutable variables
  is prohibited at compile time, guaranteeing that pointers never outlive their stack frames.

### 10.9. Existential Tuples & Dot-Projections (Phase 4.13)
Phase 4.13 implements existential tuples (weak sums `Tuple A::TYPE ... end`), path-type projection (`p.T`),
and member projection (`p.v`):
- **Struct Layout & Type Formal Erasure:** In static compilation, type formal components (`A::TYPE`, `A <: T`) are
  erased from the physical C struct layout. Positional value indices (`_0`, `_1`, etc.) correspond strictly to the
  tuple's value components.
- **Bounded Path-Type Native Lowering (`resolve_type_bound`):**
  - Unbounded type variables and path-types (`A::TYPE`, `p.T`) map to uniform 64-bit `QVal`. Scalar values are boxed
    via `qval_wrap` and unboxed via `qval_unwrap`.
  - Bounded type variables and path-types (`A::POWER(T)`, `p.T <: T`) unbox directly to the bound's native C type
    (e.g., `QInt`, `QReal`), eliminating dynamic boxing and preserving full native performance.
- **Closure Adaptation Thunks (`_emit_closure_adaptation`):** When packaging or coercing a tuple containing closures
  whose concrete signatures differ from the abstract interface signature (e.g., `create(init: Int): Counter` where
  `Counter = Int` coerced to `create(init: Int): A`), the transpiler synthesizes static adaptation thunks
  (`qv_adapt_<id>`). The thunk unpacks/forwards the original closure's environment, unwraps any `QVal` arguments with
  `qval_unwrap`, invokes the underlying native function, and wraps any abstract return value with `qval_wrap`.
- **Tuple Structural Coercion & Generic Returns (`_coerce_tuple_val`):** Coercions between tuples whose field C types
  differ (e.g., concrete scalar to `QVal`, closure adaptation, nested tuple structural conversions, or generic tuple
  returns where `QVal` fields are unwrapped into concrete types) allocate a new target tuple and map each field.
  - **Fat Pointer & Variant Support:** Unwrapping `QVal` fields into concrete record fat pointers (`QRecordVal`) or
    variants (`QVariantVal`) invokes `quest_record_unbox` or `quest_variant_unbox`.
  - **Record Subtyping & Tag Remapping:** Coercions attach evidence dictionaries for subtyped records and apply static
    tag remapping arrays for variants across subtyping boundaries.
  - If all field C types match identically, zero-cost pointer casting is retained.
- **End-to-End Golden Verification:** Verified across all phases (`tokenize`, `parse`, `typecheck`, `interpret`,
  `run_c_compiled`) via `existential_packages.quest`, `existential_adt.quest`, `cardelli_syntax.quest`, and
  `polymorphic_refs_records.quest`.

---

## 11. Host Compiler Runner (`compiler_runner.py`)

The compiler runner manages external C compiler toolchain discovery, Boehm GC flags, and native executable generation:

### 11.1. Compiler Discovery
`find_c_compiler()` searches `PATH` in order:
1. `clang` (preferred on macOS/Linux for optimal diagnostic output and C99 statement expression support).
2. `gcc` (fallback).

### 11.2. Boehm GC Auto-Detection & `--nogc`
`detect_gc_flags(nogc: bool)` locates the Boehm Garbage Collector:
- Standard paths checked: `/opt/homebrew/opt/bdw-gc` (Apple Silicon), `/usr/local/opt/bdw-gc` (Intel macOS), `/usr`.
- If found: passes `-I<prefix>/include -L<prefix>/lib -lgc`.
- If not found or when `--nogc` flag is specified: passes `-DQUEST_NOGC`, using standard libc `calloc`/`malloc`.

### 11.3. Compilation Invocation
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

## 12. Verification & Test Suite

The C code generator is verified through comprehensive unit, integration, and end-to-end tests:
- `tests/python/test_phase4_1_runtime.py`: Runtime macros, tag operations, error exits, and `--nogc` execution.
- `tests/python/test_phase4_2a_functions.py`: Direct function calls, uncurrying, mutual recursion,
  curried application flattening, mutable top-level variables, and `--nogc` execution.
- `tests/python/test_phase4_2b_aggregates.py`: Tuples, concrete records, heap allocation via `quest_alloc`,
  named/indexed field selection, mutable field assignment, and nested aggregates.
- `tests/python/test_phase4_2c_closures.py`: First-class function values, trampolines, capturing closures,
  multi-level nested closures, and `--nogc` execution.
- `tests/python/test_phase4_3_arrays.py`: Mutable arrays, repetition, indexing, element mutation, Real/String elements,
  out-of-bounds error handling, and `--nogc` execution.
- `tests/python/test_phase4_4_options_variants.py`: Ordered options, tagged variants, tag checks (`?`),
  tag extractions (`!`), case discrimination, and `--nogc` execution.
- `tests/python/test_phase4_5_subtyping.py`: Prefix tuple subtyping with static assertions,
  record width/permutation subtyping, evidence dictionary passing through closures, uniform `QRecordVal` returns,
  and static variant tag remapping.
- `tests/python/test_phase4_6_exceptions.py`: Exception values, try-when exception handling, and stack unwinding.
- `tests/python/test_phase4_7_whole_program_modules.py`: Multi-file compilation, interface checking, and linking.
- `tests/python/test_phase4_8_quantifier_descriptors.py`: Quantifier calling convention and type descriptors.
- `tests/python/test_phase4_8_dynamic.py`: Dynamic module lowering, dynamic values, and generic wrappers.
- `tests/python/test_phase4_9a_aggregate_subtyping.py`: Arrays of subtyped records, array repetition, element mutation,
  tuples with subtyped records, and passing aggregate record elements to functions.
- `tests/python/test_phase4_9b_bounded_specialization.py`: Bounded specialization for records and variants,
  dynamic offset evaluation via evidence dictionaries, caller dictionary restoration, and call-site tag alignment.
- `tests/python/test_phase4_9c_callsite_specialization.py`: Call-site specialization for unbounded quantifiers,
  unboxed QRecordVal/QVariantVal parameters and returns, generic tuple layout alignment, and scalar coexistence.
- `tests/python/test_phase4_9d_flat_stride_arrays.py`: Flat stride arrays for Array(Record) and Array(Variant),
  in-place mutation, flat dictionary coercion, specialized generic functions, and wide array bounds checks.
- `tests/python/test_phase4_10_stdlib_c.py`: Cardelli standard library interfaces in C (Writer, Reader, Conv, Ascii,
  IntOp, RealOp, StringOp) and System OS extensions.
- `tests/python/test_phase4_11_native_modules.py`: Unified native module mechanism, external types and values, and
  hybrid Quest/C modules.
- `tests/python/test_stage2_cardelli.py` & `tests/source/language/lvalues_references.quest`: Mutable reference
  parameters (`out`, `var`), lvalue address-of generation, pointer forwarding, and compile-time error checks.
- `tests/python/test_existential_tuples.py` & `tests/source/language/existential_{packages,adt}.quest`: Existential
  tuples, package packing, signature adaptation thunks, bounded path-type unboxing, and dot-projections across
  interpreter and native C execution.
- `tests/source/01_lexer_basics.quest`: Verified end-to-end native compilation and execution of tuple operations.
- `tests/source/02_expressions_control_flow.quest`: Verified end-to-end native compilation and execution.
- `tests/source/03_functions_closures.quest`: Verified end-to-end native compilation and execution of closures.
- `tests/source/04_records_variants_options.quest`: Verified end-to-end native compilation and execution.

---

## See Also
- [c-representation.md](c-representation.md): 64-bit `QVal` representation, ABI assertions, and aggregate layouts.
- [pipeline.md](pipeline.md): Pipeline passes and driver CLI commands.
- [runtime-design.md](runtime-design.md): Architectural design for Evidence Passing and runtime representations.
