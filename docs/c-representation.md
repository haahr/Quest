# Quest C Representation and Runtime ABI Design

This document specifies the C representation of Quest values, types, aggregates, closures, environments, exceptions,
and identifier mappings for **Step 4: Bootstrap C Transpiler** and the shared runtime in `runtime/`.

These representations are designed to be shared directly with the **Step 6: Native AArch64 Backend** and future
64-bit architectures (such as x86-64).

---

## 1. Design Goals and Architectural Principles

1. **64-bit Word Uniformity:** Every Quest value in a generic variable, parameter, or aggregate field occupies
   exactly one 64-bit word (`QVal`). All pointers and integer/floating-point primitives are 64 bits.
2. **Recommended Synthesis for Aggregates:**
   - Specific, typed C `struct` definitions for concrete, statically-known types (enabling natural field access and
     seamless debugger inspection in `lldb` and `gdb`).
   - Binary layout compatibility with uniform generic representations (`QVal[]`, `QVariant`), ensuring zero-cost
     coercions for prefix tuple subtyping, evidence-passing record subtyping, and global variant tag dispatch.
3. **Clean Identifier Namespacing:** Use prefix tags (`qv_`, `QT_`, `QK_`) to prevent collisions with C keywords and
   standard library symbols.
4. **Human-Readable Operator Mangling:** Map symbolic operators to descriptive English names
   (e.g., `<-=` $\rightarrow$ `qv_sym_lessthan_minus_equals`).
5. **Portable C99 Compile-Time Layout Enforcement:** Enforce ABI assumptions (word sizes, alignments, struct field
   offsets) at compile time via portable static assertions.
6. **Shared Runtime ABI:** Place common runtime definitions in a top-level `runtime/` directory usable by both
   transpiled C and native assembly backends.

---

## 2. Compile-Time Layout Assertions in Portable C99

To guarantee that C compilers lay out memory identically to our ABI expectations across platforms, we enforce layout
properties at compile time via `static_assert`.

While C11 standardizes `<assert.h>` `static_assert` as `_Static_assert`, portable C99 achieves compile-time assertions
without language extensions via a standard negative-sized array in a typedef. This macro works uniformly with both
`sizeof` and `<stddef.h>`'s `offsetof(...)` constructs because both evaluate to compile-time integer constants:

```c
/* runtime/quest_runtime.h */

#include <stddef.h>

#define Q_ASSERT_CONCAT_(a, b) a##b
#define Q_ASSERT_CONCAT(a, b)  Q_ASSERT_CONCAT_(a, b)

#ifndef static_assert
#  if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
#    define static_assert(cond, msg) _Static_assert(cond, #msg)
#  else
#    define static_assert(cond, msg) \
       typedef char Q_ASSERT_CONCAT(q_assert_##msg##_, __LINE__)[(cond) ? 1 : -1]
#  endif
#endif
```

If `cond` evaluates to 0, the array dimension is `-1`, triggering an immediate compiler error pointing to the
declaration and printing the descriptive message token in the error output.

---

## 3. Primitives and the Universal Value Word (`QVal`)

All Quest values stored in registers, local variable slots, arrays, and tuple/record fields are 64-bit words:

```c
#include <stdint.h>
#include <stdbool.h>

typedef int64_t QInt;
typedef double  QReal;
typedef bool    QBool;
typedef char    QChar;

typedef union QVal {
    void    *p;   /* Heap pointers: records, tuples, arrays, strings, closures */
    QInt     i;   /* 64-bit signed two's complement integer */
    QReal    r;   /* 64-bit IEEE-754 double precision float */
    uint64_t u;   /* Raw 64-bit unsigned word for bitwise/identity checks */
} QVal;

/* ABI layout assertions */
static_assert(sizeof(QInt)     == 8, qint_must_be_8_bytes);
static_assert(sizeof(QReal)    == 8, qreal_must_be_8_bytes);
static_assert(sizeof(void *)   == 8, ptr_must_be_8_bytes);
static_assert(sizeof(QVal)     == 8, qval_must_be_8_bytes);
static_assert(sizeof(uint64_t) == 8, u64_must_be_8_bytes);
```

### 3.1. Standard Constant Definitions
Standard scalar constants are defined for `Ok` and boolean values:
```c
#define Q_OK_VAL    ((QVal){ .u = 0x0ULL })
#define Q_TRUE_VAL  ((QVal){ .i = 1LL })
#define Q_FALSE_VAL ((QVal){ .i = 0LL })
```

### 3.2. String Representation (`QString`)
Quest strings are immutable byte sequences with explicit length and trailing null byte:
```c
typedef struct QString {
    size_t length;
    char   chars[];
} QString;
```
- Strings are allocated via `quest_alloc_atomic(sizeof(QString) + length + 1)`.
- Runtime functions `quest_string_new(const char *data, size_t len)`, `quest_string_concat(s1, s2)`, and
  `quest_string_equal(s1, s2)` provide safe string manipulation.

### 3.3. Rationale for Uniform 64-Bit Representation vs. Non-64-Bit Alternatives
During C backend design, alternatives such as unboxed 8-bit integers/chars or unboxed heterogenous tuples were
evaluated:
1. **Generic Uniformity & Polymorphism:** In Quest, any polymorphic type variable `X <: Any` or higher-order quantifier
   can be instantiated with arbitrary types. Variable-width types (e.g. 1-byte chars or 2-byte ints) would necessitate:
   - Dynamic boxing/unboxing overhead on every generic parameter or aggregate field read.
   - Extensive monomorphization, which cannot handle polymorphic recursion, existential types, or dynamic typing.
   - Fat pointers or runtime layout descriptors.
2. **Predictable Stride and Alignment:** Uniform 64-bit words guarantee that all aggregate slots are multiples of 8
   bytes, enabling zero-cost prefix tuple subtyping and constant-stride array indexing without struct padding anomalies.
3. **Monomorphic Scalar Optimization:** While the universal representation is 64-bit `QVal`, the C transpiler emits
   native C scalar types (`QInt`, `QReal`, `QBool`, `QChar`, `QString*`) for statically-known local variables and
   non-generic functions. This preserves register allocation and zero-boxing overhead where types are known at compile
   time.

### 3.4. ABI and Calling Convention Properties
- Under **AAPCS64** (macOS and Linux AArch64), `QVal` is an 8-byte composite type containing integer/pointer members;
  it is passed in a single **64-bit general-purpose register** (`x0`–`x7`) and returned in `x0`.
- Under **System V AMD64** (x86-64), `QVal` is classified as `INTEGER` class and passed in `rdi`, `rsi`, `rdx`, etc.,
  and returned in `rax`.
- For non-generic, monomorphic Quest functions whose types are statically known, the transpiler generates native C
  signatures (e.g. `QReal qv_add(QReal qv_a, QReal qv_b)`), allowing floats to remain in floating-point registers
  (`d0`–`d7`) without `fmov` overhead.

---

## 4. Identifier Mapping and Operator Mangling

### 4.1. Namespace Prefixes
All Quest identifiers map to C identifiers using explicit namespace prefixes:
- **`qv_` for Quest Values and Functions:**
  - `fib` $\rightarrow$ `qv_fib`
  - `factorial` $\rightarrow$ `qv_factorial`
  - `x` $\rightarrow$ `qv_x`
  - `int` $\rightarrow$ `qv_int` *(safely avoids collision with C `int`)*
  - `default` $\rightarrow$ `qv_default` *(safely avoids collision with C `default`)*
- **`QT_` for Quest Types:**
  - `Int` $\rightarrow$ `QT_Int`
  - `Real` $\rightarrow$ `QT_Real`
  - `List` $\rightarrow$ `QT_List`
- **`QK_` for Quest Kinds:**
  - `TYPE` $\rightarrow$ `QK_TYPE`
  - `POWER` $\rightarrow$ `QK_POWER`

### 4.2. Operator and Symbol Name Mangling
Quest supports arbitrary symbolic operator names. Symbolic characters map to human-readable names prefixed by `qv_sym_`:

| Symbol | Mangle Segment | Symbol | Mangle Segment | Symbol | Mangle Segment |
| :---: | :--- | :---: | :--- | :---: | :--- |
| `+` | `plus` | `-` | `minus` | `*` | `star` |
| `/` | `slash` | `=` | `equals` | `<` | `lessthan` |
| `>` | `greaterthan` | `!` | `bang` | `?` | `question` |
| `:` | `colon` | `@` | `at` | `#` | `hash` |
| `$` | `dollar` | `%` | `percent` | `^` | `caret` |
| `&` | `amp` | `|` | `pipe` | `~` | `tilde` |
| `\` | `backslash` | `.` | `dot` | `'` | `prime` |

#### Examples:
- `+` $\rightarrow$ `qv_sym_plus`
- `++` $\rightarrow$ `qv_sym_plus_plus`
- `<-=` $\rightarrow$ `qv_sym_lessthan_minus_equals`
- `<>` $\rightarrow$ `qv_sym_lessthan_greaterthan`
- `:=` $\rightarrow$ `qv_sym_colon_equals`
- `>>=` $\rightarrow$ `qv_sym_greaterthan_greaterthan_equals`

---

## 5. Aggregate Representations

### 5.1. Tuples
Tuples are ordered collections of 64-bit values. In Quest, tuple components can have explicit names
(`Tuple a:Int b:Real end`) or be positional (`Tuple Int Real end`), or a mix of both.

- **Field Naming Conventions:**
  - **Tuple components** use 0-indexed numerical tags: `_<index>` (`_0`, `_1`, etc.).
  - Named components (e.g. `p.x`) are resolved at compile time to their corresponding positional slot (`p->_0`).
  ```c
  /* Quest: Tuple x:Int y:Real String end */
  typedef struct QTuple_Int_Real_String {
      QInt     _0;  /* Component 0 (named x in signature) */
      QReal    _1;  /* Component 1 (named y in signature) */
      QString *_2;  /* Component 2 */
  } QTuple_Int_Real_String;
  ```

- **Generic View:**
  Any tuple pointer can be treated as a sequence of `QVal` words:
  ```c
  typedef struct QTuple {
      QVal elements[];
  } QTuple;
  ```

- **Zero-Cost Prefix Subtyping & Memoized Cast Verification:**
  Because each field is 8 bytes at consecutive 8-byte offsets, a pointer to an extended tuple (e.g. 3 components) is
  physically identical in its first 16 bytes to its prefix tuple (2 components). Passing an extended tuple to a
  function expecting a prefix requires only a pointer cast in C:
  ```c
  QTuple_Int_Real *sub = (QTuple_Int_Real *)tuple_3;
  ```
  To guarantee that compiler layout and alignment assumptions hold true, the transpiler **memoizes every tuple
  coercion pair** `(SourceTuple, TargetTuple)` encountered during translation. For each unique pair, the transpiler
  emits compile-time `static_assert` statements verifying that the byte offset of each prefix field in `SourceTuple`
  exactly matches the corresponding field in `TargetTuple`:
  ```c
  /* Memoized Tuple Coercion Assertions for (QTuple_Int_Real_String -> QTuple_Int_Real) */
  static_assert(offsetof(QTuple_Int_Real_String, _0) == offsetof(QTuple_Int_Real, _0),
                tuple_cast_offset_match_0);
  static_assert(offsetof(QTuple_Int_Real_String, _1) == offsetof(QTuple_Int_Real, _1),
                tuple_cast_offset_match_1);
  ```
  If field padding or struct alignment ever differs between the two types, compilation fails immediately.

### 5.2. Records and Subtyping (Evidence Passing)
Under Cardelli's structural subtyping with multiple inheritance, field offsets cannot be assigned globally.
As established in `docs/runtime-design.md`, Quest uses the **Evidence Passing** model:

1. **Concrete Record Payload & Object Header:**
   A heap-allocated block of 64-bit words beginning with an 8-byte object header (`QRecordHeader`), followed by
   fields sorted alphabetically by field name and prefixed with `qf_` (named `QT_<Alias>` or sequential `QT_record<N>`):
   ```c
   /* Quest: Let Point = Record x: Int y: Real end */
   typedef struct QT_Point {
       QRecordHeader header;  /* { const void *descriptor; } (8 bytes, descriptor = NULL) */
       QInt          qf_x;
       QReal         qf_y;
   } QT_Point;
   ```
2. **Evidence Dictionary (`OffsetDict_<Name>`):**
   A concrete C struct whose members are `size_t offset_<field>` corresponding to the expected fields of the target record type.
   Static instances in `.rodata` (`offsetdict_<Target>_<Source>`) initialize these offsets using `<stddef.h>`'s `offsetof`:
   ```c
   typedef struct OffsetDict_Point {
       size_t offset_x;
       size_t offset_y;
   } OffsetDict_Point;

   static const OffsetDict_Point offsetdict_Point_Point3D = {
       offsetof(QT_Point3D, qf_x),
       offsetof(QT_Point3D, qf_y)
   };
   ```
3. **Function Parameters & Record Returns:**
   - Record parameters in functions and closures receive companion dictionary pointers:
     `(void *qv_p, const OffsetDict_Point *_dict_qv_p)`.
   - Functions returning records return a fat result structure:
     ```c
     typedef struct QRecordResult_Point {
         void *val;
         const OffsetDict_Point *dict;
     } QRecordResult_Point;
     ```
4. **Field Access:**
   - *Direct (exact concrete type statically known):* `r->qf_x` (direct load at fixed struct offset).
   - *Subtyped (via companion dictionary):* `(*((QInt *)((char *)r + dict->offset_x)))`.
5. **Storage in Aggregates:**
   - Storing subtyped records into an aggregate (such as `QTuple` or `QArray`) produces a compile-time diagnostic
     requiring runtime descriptors: `"Subtyped record or variant storage in aggregates requires runtime descriptors"`.

### 5.3. Options and Variants (Sums)

Cardelli's *Typeful Programming* establishes a fundamental distinction between **ordered sums (`Option`)** and
**unordered sums (`Variant`)**. The C runtime reflects this exact distinction:

#### 1. Option Types (Ordered, Dense 0-Indexed Enums with Inline Union Payloads)
By language definition, `Option` types are strictly ordered collections of signatures (§4.5). Unlike variants, an
option branch carries a full signature, meaning a branch may contain **zero, one, or multiple components**:
```quest
Let T =
  Option
    a                     (* 0 components *)
    b with x:Bool end     (* 1 component:  x:Bool *)
    c with x,y:String end (* 2 components: x,y:String *)
  end;
```
Cardelli explicitly defines the `ordinal(o)` operator, which exposes the 0-based integer index of an option at
runtime, and the `!` extraction operator, which unpacks the branch signature:
```quest
• bOption!b;
» tuple 1 let x=true end : Tuple :Int x:Bool end
```

To support zero or multiple components without auxiliary heap allocations, each concrete `Option` type emits a C
`struct` containing the 0-based `tag` followed by an **inline `union` of branch structs**:
```c
/* Generated for Option type T */
typedef enum {
    QTAG_T_a = 0,
    QTAG_T_b = 1,
    QTAG_T_c = 2,
} QT_T_Tag;

typedef struct QT_T {
    int64_t tag; /* 0-based ordinal matching Cardelli's ordinal(o) */
    union {
        /* branch 'a' has 0 components */
        struct {
            QBool qv_x;
        } b;
        struct {
            QString *qv_x;
            QString *qv_y;
        } c;
    } u;
} QT_T;
```

- **Generic View (`QOptionHeader`):** Because all payload components are 64-bit aligned words, generic runtime routines
  (such as `ordinal(o)` or generic `!`) can inspect any option through a common header:
  ```c
  typedef struct QOptionHeader {
      int64_t tag;
      QVal    fields[]; /* Inline 64-bit payload fields */
  } QOptionHeader;

  static_assert(offsetof(QOptionHeader, fields) == 8, qoption_fields_at_offset_8);
  ```
- **Zero-Cost Prefix Subtyping:** Because every union branch in C begins at offset 0 of the union (offset 8 of the
  struct), branch fields in a subtype maintain identical offsets in any extended supertype.
- **Fast Pattern Matching:**
  ```c
  switch (opt->tag) {
      case QTAG_T_a: /* 0 fields */ break;
      case QTAG_T_b: use(opt->u.b.qv_x); break;
      case QTAG_T_c: use(opt->u.c.qv_x, opt->u.c.qv_y); break;
  }
  ```

#### 2. Variant Types (Unordered, Single 64-bit Payload, Evidence-Passing)
Unlike options, variants are unordered and each branch has **exactly one type** $A_i$ (§6.3):
```quest
Variant x1:A1 .. xn:An end
variant x of A with a end
```
If a branch requires no payload value, it uses the unit type `Ok` (`Variant mon,tue:Ok end`). Thus, every variant
payload is always **exactly one 64-bit word** (`QVal`):
```c
typedef struct QVariant {
    const void *descriptor; /* Object header / runtime type descriptor (8 bytes, descriptor = NULL) */
    int64_t     tag;        /* Local dense tag index (0, 1, ...) */
    QVal        payload;    /* Exactly one 64-bit word */
} QVariant;

static_assert(sizeof(QVariant) == 24, qvariant_must_be_24_bytes);
static_assert(offsetof(QVariant, payload) == 16, qvariant_payload_at_offset_16);
```
- **Static Tag Remapping Dictionaries (`.rodata`):** When a variant is upcast across an unordered subtyping boundary,
  the compiler emits a static lookup table `static const int64_t tagmap_<Target>_<Source>[]`:
  ```c
  QVariant *tmp = (QVariant *)quest_alloc(sizeof(QVariant));
  tmp->descriptor = NULL;
  tmp->tag = tagmap_Large_Small[src->tag];
  tmp->payload = src->payload;
  ```
- **Specialization:** Eliminated entirely when the variant type is statically known.

### 5.4. Arrays
Arrays are mutable, length-prefixed buffers of 64-bit words:
```c
typedef struct QArray {
    int64_t length;
    QVal    data[];
} QArray;

static_assert(offsetof(QArray, data) == 8, qarray_data_at_offset_8);
```

### 5.5. Strings
In Quest, strings are mutable character sequences (supporting Cardelli's `StringOp` interface):
```c
typedef struct QString {
    int64_t length;
    int64_t capacity;
    char   *data;     /* Null-terminated UTF-8 / ASCII buffer */
} QString;
```

---

## 6. Closures and Calling Convention (Phase 4.2c)

In Quest, functions are first-class values and can capture lexical bindings:

### 6.1. Closure Representation (`QClosure`)
Every closure is a uniform 16-byte structure containing a C function pointer and an environment pointer:
```c
typedef struct QClosure {
    void *fn;   /* C function pointer */
    void *env;  /* Captured environment pointer or NULL */
} QClosure;

static_assert(sizeof(QClosure) == 16, qclosure_must_be_16_bytes);
static_assert(offsetof(QClosure, env) == 8, qclosure_env_at_offset_8);
```

### 6.2. Function Signatures and Calling Conventions
1. **Direct Top-Level Functions:** Keep clean standard C signatures without an unused environment parameter:
   `static QInt qv_square(QInt qv_x);`.
2. **First-Class Top-Level Functions:** When a top-level function is referenced as a value, the compiler generates a
   static trampoline adapter:
   ```c
   static QInt qv_square_trampoline(void *env, QInt qv_x) {
       (void)env;
       return qv_square(qv_x);
   }
   static QClosure qv_square_closure = { (void *)qv_square_trampoline, NULL };
   ```
   Referencing `square` emits `(&qv_square_closure)`.
3. **Lifted Lambdas:** Every non-top-level lambda is lifted to file scope with signature:
   `static RetType qv_lambda_<id>(void *_raw_env, Params...)`.
4. **Indirect Call Site:**
   ```c
   ((RetType (*)(void *, ParamTypes...))(c_func->fn))(c_func->env, args...);
   ```

### 6.3. Flat Environment Frames
Captured variables are grouped into flat environment structs allocated via `quest_alloc`:
```c
struct QEnv_lambda_1 {
    QInt qv_x;
    QReal qv_y;
};
```
Non-capturing lambdas omit the environment struct and use file-scope static singleton closures.

---

## 7. Exception Handling with `setjmp` and `longjmp`

Quest's `try...when...else` and `raise` are lowered using a thread-local exception handler stack:

```c
#include <setjmp.h>

typedef struct QException {
    const char *name;
} QException;

typedef struct QExceptionState {
    const QException *exc;
    QVal              payload;
} QExceptionState;

typedef struct QExceptionHandler {
    jmp_buf                     env_jmp;
    struct QExceptionHandler   *prev;
} QExceptionHandler;

/* Thread-local exception handler chain */
#if defined(_MSC_VER)
#  define Q_THREAD_LOCAL __declspec(thread)
#else
#  define Q_THREAD_LOCAL _Thread_local
#endif

extern Q_THREAD_LOCAL QExceptionHandler *quest_current_exception_handler;
extern Q_THREAD_LOCAL QExceptionState    quest_current_exception;
```

### 7.1. Generative Exception Values
Cardelli's Quest specification (§4.9) states:
> *"The `exception` construct generates a new unique exception value whenever it is evaluated..."*

Evaluating `exception name [: Type] end` invokes `quest_alloc_exception("name")`, returning a heap-allocated pointer `const QException *`. Because each allocation produces a distinct memory address, **pointer equality (`==`)** directly provides unique generative identity without requiring an integer exception ID.

Built-in exceptions (e.g. `quest_exc_DivideByZero`, `quest_exc_arrayOp_error`, `quest_exc_string_error`, `quest_exc_variant_error`) are pre-allocated global `QException` singletons whose static addresses provide their immutable identity.

### 7.2. Raising an Exception (`raise E [with payload] end`)
```c
void quest_raise(const QException *exc, QVal payload) {
    if (!quest_current_exception_handler) {
        /* Uncaught exception diagnostic */
        const char *name = (exc && exc->name) ? exc->name : "<unknown>";
        fprintf(stderr, "Exception: %s\n", name);
        exit(1);
    }
    quest_current_exception.exc = exc;
    quest_current_exception.payload = payload;
    longjmp(quest_current_exception_handler->env_jmp, 1);
}
```

### 7.3. Try-Handler Block (`try ... when ... else ... end`)
```c
QExceptionHandler q_handler;
q_handler.prev = quest_current_exception_handler;
quest_current_exception_handler = &q_handler;

if (setjmp(q_handler.env_jmp) == 0) {
    /* Protected body evaluated into destination */
    ...
    quest_current_exception_handler = q_handler.prev; /* Pop handler on normal completion */
} else {
    /* Pop handler before executing catch block so nested raises propagate outwards */
    quest_current_exception_handler = q_handler.prev;
    QExceptionState q_caught = quest_current_exception;
    
    if (q_caught.exc == qv_Exc1) {
        /* If branch has binder: bind q_caught.payload */
        /* Evaluate branch body into destination */
    } else if (q_caught.exc == qv_Exc2) {
        /* Handle branch 2 */
    } else {
        /* Else clause, or re-raise if no matching when */
        quest_raise(q_caught.exc, q_caught.payload);
    }
}
```

---

## 8. Dynamic Type Envelopes (`QDynamic`)

The `Dynamic` type encapsulates a value and its runtime type representation:
```c
typedef struct QTypeDesc {
    uint32_t    type_id;
    const char *name;
    /* Subtyping descriptor / structural descriptor */
} QTypeDesc;

typedef struct QDynamic {
    QVal              value;
    const QTypeDesc  *type_desc;
} QDynamic;

static_assert(sizeof(QDynamic) == 16, qdynamic_must_be_16_bytes);
```
`inspect d when T with x then ... end` checks `d->type_desc == &QT_Desc_T` (or subtyping against `QT_Desc_T`).

---

## 9. Memory Management Abstraction & `--nogc` Support

All heap allocations route through two runtime allocator functions:
- `quest_alloc(size_t bytes)`: Allocates memory that may contain pointers (scanned by GC).
- `quest_alloc_atomic(size_t bytes)`: Allocates memory guaranteed not to contain pointers (e.g., string buffers,
  atomic raw bytes).

```c
/* runtime/quest_runtime.h */

#ifdef QUEST_NOGC
#  include <stdlib.h>
   static inline void *quest_alloc(size_t sz)        { return calloc(1, sz); }
   static inline void *quest_alloc_atomic(size_t sz) { return malloc(sz); }
   static inline void  quest_gc_init(void)           { /* no-op */ }
#else
#  include <gc.h>
   static inline void *quest_alloc(size_t sz)        { return GC_MALLOC(sz); }
   static inline void *quest_alloc_atomic(size_t sz) { return GC_MALLOC_ATOMIC(sz); }
   static inline void  quest_gc_init(void)           { GC_INIT(); }
#endif
```

- When compiled without flags, Quest links with Boehm GC (`-lgc`).
- When invoked with `--nogc`, the compiler passes `-DQUEST_NOGC` and omits `-lgc`.

---

## 10. Shared `runtime/` Directory Structure & Implemented Functions

The runtime files are located at the repository root and shared with future native code backends:
```
runtime/
├── quest_runtime.h    /* Core ABI, QVal union, layout assertions, allocator macros */
├── quest_runtime.c    /* String primitives, math helpers, panic handlers, printing */
├── quest_io.c         /* Future: C implementation of Writer and Reader stream modules */
└── quest_conv.c       /* Future: C implementation of Conv, Ascii, IntOp, RealOp, StringOp */
```

### 10.1. Implemented Runtime Functions (`runtime/quest_runtime.c`)
- **String Primitives:**
  - `QString *quest_string_new(const char *data, size_t len)`: Allocates `QString` with trailing null byte.
  - `QString *quest_string_concat(const QString *s1, const QString *s2)`: Implements Quest `<>` string concatenation.
  - `bool quest_string_equal(const QString *s1, const QString *s2)`: Compares string length and characters.
  - `QChar quest_string_get_char(const QString *s, int64_t idx)`: Retrieves character at 0-based index.
  - `void quest_string_set_char(QString *s, int64_t idx, QChar ch)`: Mutates character at 0-based index.
  - `QString *quest_string_get_sub(const QString *s, int64_t start, int64_t len)`: Extracts substring slice.
  - `void quest_string_set_sub(QString *dest, int64_t d_start, const QString *src, int64_t s_start, int64_t len)`: Overwrites slice.
- **Array Primitives:**
  - `QArray *quest_array_new(int64_t len, QVal init_val)`: Allocates length-prefixed array with initial element values.
  - `void quest_check_array_bounds(const QArray *a, int64_t idx)`: Inline guard checking `idx >= 0 && idx < a->length`.
- **Floating-Point Math:**
  - `double quest_real_pow(double base, double exp)`: Implements Quest `^^` real exponentiation via `pow()`.
- **Runtime Panic / Exception Handlers:**
  - `void quest_raise_divide_by_zero(void)`: Triggered on division or modulo by zero. Prints
    `Exception: DivideByZero\n` to `stderr` and terminates the process with exit code 1.
  - `void quest_raise_array_error(void)`: Triggered on out-of-bounds array access or negative array sizes. Prints
    `Exception: arrayOp.error\n` to `stderr` and terminates the process with exit code 1.
  - `void quest_raise_string_error(void)`: Triggered on out-of-bounds string index or slice bounds. Prints
    `Exception: string.error\n` to `stderr` and terminates the process with exit code 1.
- **Debug & Value Printing:**
  - `void quest_raise_variant_error(void)`: Triggered on failed variant tag assertions (`!tag`). Prints
    `Exception: variant.tagMismatch\n` to `stderr` and terminates the process with exit code 1.
  - `void quest_print_val(QVal val, const char *type_name)`: Formats and prints interactive expression results
    matching Cardelli's typescript format (e.g., `42 : Int`, `15.75 : Real`, `true : Bool`, `"hello" : String`).

---

## See Also
- [codegen-c.md](codegen-c.md): C Code Generator architecture, AST lowering, and compiler runner.
- [pipeline.md](pipeline.md): Compiler pipeline passes and dual-pipeline CLI driver.
- [runtime-design.md](runtime-design.md): Evidence Passing vs. Fat Pointers and AAPCS64 register ABI.
- [roadmap.md](roadmap.md): 7-stage compiler implementation roadmap.
- [type-system.md](type-system.md): Quest higher-order subtyping and typing rules.
- [step3-interpreter.md](step3-interpreter.md): Python interpreter architecture and standard library modules.

