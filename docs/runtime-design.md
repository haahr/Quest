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

### Bounded Specialization for Records & Variants (`A <: Record`, `V <: Variant`)

- **Descriptor Retention:** Bounded polymorphic functions retain `const QTypeDescriptor *descriptor_<T>` parameters in
  their C signatures to support separate compilation and uniform reflection across translation units.
- **Bounded Records (`A <: Record`):** Functions take `QRecordVal` fat pointers directly. When passing a subtype
  $S <: T$, the caller pairs the payload with the subtyping offset dictionary (`&offsetdict_T_S`). Inside the callee,
  field accesses dynamically evaluate offsets from `p.dict`. When returning a bounded type variable $A$, the caller
  restores the dictionary (`Option A: Caller Restores Dictionary`), attaching the concrete subtype's identity dictionary
  `&offsetdict_S_S` to the returned `.val`.
- **Bounded Variants (`V <: Variant`):** Functions take unboxed `QVariantVal` directly. Callers perform call-site tag
  alignment to the bound variant type using static `.rodata` tag tables. Callees dispatch directly on `v.tag` without
  runtime translation or heap allocation.

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

## 6. Dynamic Subtyping & Runtime Type Descriptors

Dynamic values (`Dynamic`) wrap an arbitrary runtime value paired with a `const QTypeDescriptor *`:
```c
typedef struct QDynamic {
    const QTypeDescriptor *type_desc;
    QVal                   payload;
} QDynamic;
```

### 1. Hybrid Descriptor Architecture
- **Compile-time Static Descriptors (.rodata):** Closed types generated during compilation are emitted as
  `static const QTypeDescriptor quest_type_<tag> Q_UNUSED` with static payload structs (`qrec_desc_*`, `qtup_desc_*`,
  `qvar_desc_*`, `qarr_desc_*`). Forward declarations allow mutual and self-referential descriptor links without
  dynamic allocation.
- **Runtime Descriptors with Hash-Interning:** Dynamic constructor functions (`quest_make_record_descriptor`,
  `quest_make_tuple_descriptor`, `quest_make_variant_descriptor`, etc.) provide runtime type synthesis interned via
  hash table buckets to guarantee canonical pointer equality ($T_1 \equiv T_2 \iff \text{desc}_1 == \text{desc}_2$).

### 2. Structural Subtyping Algorithm (`quest_is_subtype`)
Subtyping checks are unified under `quest_is_subtype`:
- **Records:** Width subtyping (all supertype fields present in subtype), permutation subtyping (order independent),
  depth subtyping on immutable fields ($T_{\text{sub}} <: T_{\text{super}}$), and invariance on mutable `var` fields.
- **Tuples:** Prefix subtyping with covariant element types.
- **Variants:** Branch set inclusion with covariant immutable payloads.
- **Coinductive Cycle Detection:** Recursive type subtyping cycles are guarded using an active cycle trail
  (`quest_subtyping_trail`) to ensure terminating coinductive subtyping checks.

### 3. Dynamic Value Adaptation (`quest_record_adapt` & `quest_variant_adapt`)
When `dynamic.be` or `inspect` succeeds on a structural subtype:
- For records: `quest_record_adapt` synthesizes an offset dictionary mapping target fields (alphabetically ordered)
  to source record byte offsets, recursively adapting nested subtyped immutable fields. Results are cached in a
- For variants: `quest_variant_adapt` remaps source variant tags to target tag indices and adapts payloads via a
  memoized tag-mapping adapter cache.

### 4. Dynamic Graph Serialization (`dynamic.extern` & `dynamic.intern`)
- **JSON/JSOG Representation:** Dynamically serialized packages use a JSON/JSOG representation (`@id` and `@ref`)
  matching the interpreter's `dynamic_json.py`, handling arbitrary cyclic and DAG data structures.
- **Streaming Single-Value Parser:** Deserialization (`dynamic.intern`) parses exactly one JSON value from `QReader`,
  skipping leading whitespace and leaving trailing stream characters unread, allowing multiple objects to be read
  sequentially.
- **Auto-Registration & Dynamic Type Parsing Fallback:** When `main` initializes, the generated program automatically
  registers all compiled static `QTypeDescriptor` structures with the runtime intern table
  (`quest_register_static_type_descriptor`). Deserialization lookups for known types resolve in $O(1)$ without runtime
  descriptor allocation. For dynamically transmitted types unknown to the binary, a recursive-descent type parser
  (`quest_parse_type_descriptor`) dynamically synthesizes descriptors at runtime.
- **Two-Pass Deserialization with Pre-allocation:** JSOG cycles and shared subgraphs are resolved via a two-pass decode
  (`quest_jsog_preallocate` and `quest_jsog_decode_value`), pre-allocating record, array, and tuple nodes before
  populating fields and connecting `@ref` pointers.
- **Natural C ABI Packing:** Dynamically interned compound records allocate heap memory matching standard C ABI struct
  packing rules (8-byte aligned scalars and pointers, 16-byte aligned fat records and variants).

---

## See Also
- [README.md](../README.md): Project overview.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [type-system.md](type-system.md): Semantic type system and subtyping rules.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
