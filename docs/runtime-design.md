# Quest Runtime Architecture and Object Representation

This document details the object representation model, subtyping evidence mechanics, calling conventions, and garbage
collection strategy for compiled Quest code (targeting Step 4 C transpilation and Step 6 native AArch64 emission).

---

## 1. The Core Architectural Decision: Record & Subtyping Representation

Quest features structural subtyping with multiple inheritance on records:
```quest
let r: Record x:Int y:Real z:Bool end = record x=1 y=2.0 z=true end;
let p: Record x:Int end = r;  (* Subsumption: dropping y and z *)
```
Under single inheritance, fields share fixed offsets across subtypes. Under multiple inheritance and structural
subtyping, field offsets cannot be assigned globally without conflict.

### Uniform Fat Pointer Representation (`QRecordVal`)

```
+-----------------------------------------------------------------------------------------+
| Uniform Fat Pointer Representation (Plan of Record)                                     |
|                                                                                         |
|  Caller & Callee: Passes and returns 16-byte struct { void *val; const void *dict; }    |
|  Under AAPCS64: Mapped directly to register pair (x0, x1) without stack or heap alloc.  |
|                                                                                         |
|    QRecordVal (16 bytes: 2 words)   Static Dictionary (ROData)      Heap Record Payload |
|    +--------------------+          +-----------------------+       +-------------------+|
|    | val: void*         |--------->|                       |       | field 0: x = 1    ||
|    | dict: const void*  |--------->| offset of 'x' = 0     |       | field 1: y = 2.0  ||
|    +--------------------+          | offset of 'y' = 8     |       | field 2: z = true ||
|                                    +-----------------------+       +-------------------+|
|                                                                                         |
|  • Upcasting cost: Zero heap allocation (attaches pointer to static constant dict)     |
|  • Register ABI: 2 registers (x0, x1) under AAPCS64 for parameters and returns          |
|  • Tuples: Inlined 16-byte fields                                                       |
|  • Arrays: Boxed into 8-byte heap pointer (QRecordVal *) for uniform 1-word QVal slots  |
+-----------------------------------------------------------------------------------------+
```

### Variant Representation & Subtyping in Aggregates

Variants are represented uniformly as unboxed 16-byte value structures (`QVariantVal`):
```c
typedef struct QVariantVal {
    int64_t tag;        /* 0-based branch discriminant */
    QVal    payload;    /* Branch payload (or Q_OK_VAL) */
} QVariantVal;
```
- **Zero-Allocation Construction & Tag Remapping:** Variant creation, pattern matching (`case`), checks (`v?x`),
  and assertions (`v!x`) operate directly on `QVariantVal` with **zero heap allocations**. Upcasting across
  subtyped variant boundaries generates a static lookup table (`static const int64_t tagmap_<Target>_<Source>[]`)
  in `.rodata` and constructs an unboxed compound literal with remapped tag and copied payload.
- **Aggregate Storage:** When a subtyped variant is stored into an aggregate (`Array(SuperVariant)` or
  `Tuple ... SuperVariant ...`), the compiler coerces the variant at insertion time using the static tag table.
  Tuples store the 16-byte `QVariantVal` inline. Arrays box into `QVariantVal *` within the 8-byte `QVal.p` slot.
  Extracting from aggregates accesses values whose tags are pre-aligned to the supertype's tag space, allowing
  direct `switch (v.tag)` matching without runtime descriptor overhead.

---

## 2. Architecture & Design Tradeoffs

| Dimension | `QRecordVal` Fat Pointer | Raw Pointers + Side-Channel Dicts |
| :--- | :--- | :--- |
| **Record Values** | **Uniform 2 words (`val, dict`)** | Fragmented: 1 word in some places, 2 in others |
| **Function ABI** | Clean 1-to-1 parameter mapping (AAPCS64 `x0, x1`) | Companion synthetic dict parameters |
| **Collections** | Boxed in `QRecordVal *` for arrays; inline in tuples | Subtyped records in aggregates disallowed |
| **Subsumption** | **Zero Allocation:** Pairs data with static dict | Requires synthetic variables or thunks |
| **Garbage Collection** | `dict` points to `.rodata`; `val` traced | Traced as normal pointer |
| **Coercions** | Supported directly via attached dictionary | Fragile side-channel dictionary propagation |

---

## 3. Differences from the Original Paper (Inline Caching + Hash Fallback)

In *Typeful Programming* (Section 6.3), Luca Cardelli proposed:
1. Attempting fixed offsets for single-inheritance hierarchies.
2. An **inline cache** at field selection call-sites: caching the last observed offset.
3. On cache miss: falling back to dynamic hash-table lookup by field name string.

### Why Evidence Passing Was Chosen Over Inline Caching:
1. **Deterministic Execution:** Evidence dictionary lookup is $O(1)$ constant time (a single static offset load),
   completely immune to polymorphic cache trashing.
2. **Predictable Code Generation:** Avoids generating self-modifying inline cache code (which requires costly
   instruction cache flushes on modern AArch64 cores).
3. **Ahead-of-Time Type Erasure:** At compile time, the compiler knows the source record type and the target record
   type. It emits a static offset mapping table in `.rodata` once per upcast site.

---

## 4. Register Conventions and AAPCS64 ABI (Step 6)

For native AArch64 code generation, 16-byte structs like `QRecordVal` are passed and returned in consecutive argument
registers per AAPCS64:

```
AAPCS64 Register Assignment for Record Values:
  x0: Record payload pointer (void *val)
  x1: Evidence dictionary pointer (const void *dict -> static .rodata table)
  x2-x7: Subsequent parameters
  x19-x28: Callee-saved registers
  x29 (FP) / x30 (LR): Frame pointer and link register
```

Record return values are returned in `x0` and `x1` without stack-spill or hidden return buffer.

---

## 5. Memory Management and Garbage Collection

- **Boehm GC (`libgc`):** Used across Step 4 (C transpiler) and Step 6 (native AArch64).
- **Uniform 1-Word `QVal`:** Primitive words, pointers, closures, and boxed aggregates (`QRecordVal *`) fit into 8-byte
  slots, allowing simple GC scanning.
- **Tuples & Records:** Inlined multi-word slots in stack frames and aggregate structs are directly traversed.
- **Static Dictionaries:** Evidence dictionaries reside in read-only data sections (`.rodata`) and are never traced or
  collected by the GC.

---

## See Also
- [README.md](../README.md): Project overview.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [type-system.md](type-system.md): Semantic type system and subtyping rules.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
