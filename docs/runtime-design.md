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

### Two Competing Approaches

```
+-----------------------------------------------------------------------------------------+
| APPROACH A: Evidence Passing (Plan of Record)                                           |
|                                                                                         |
|  Caller: Passes object pointer (x0) + static dictionary pointer (x1)                     |
|                                                                                         |
|    Value Pointer (1 word)          Static Dictionary (ROData)      Heap Record Payload  |
|    +--------------------+          +-----------------------+       +-------------------+|
|    | Ptr to Record Data |--------->| offset of 'x' = 0     |       | field 0: x = 1    ||
|    +--------------------+          | offset of 'y' = 8     |       | field 1: y = 2.0  ||
|                                    +-----------------------+       | field 2: z = true ||
|                                                                    +-------------------+|
|  • Upcasting cost: Zero heap allocation (passes pointer to a static constant dictionary) |
|  • Value size: Exactly 1 word (uint64_t) everywhere                                     |
+-----------------------------------------------------------------------------------------+
| APPROACH B: Fat Pointers / Coercions (Considered Alternative)                           |
|                                                                                         |
|  Values are 2-word structs: struct FatPtr { void* data; void* dict; };                  |
|  • Upcasting cost: Allocates a 2-word struct on stack, or a heap box when stored in     |
|    generic structures like Array(T).                                                    |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Comparison Matrix

| Dimension | Evidence Passing (Plan of Record) | Fat Pointers / Coercions |
| :--- | :--- | :--- |
| **Values** | **Uniform 1 word (`uint64_t`)**; raw pointers | 2 words `(data, dict)` or heap boxes |
| **Collections** | **Trivial & Uniform:** 1-word elements | Requires heap boxing for generic array slots |
| **Subsumption** | **Zero Allocation:** Passes static dictionary | Allocates stack/heap struct on upcast |
| **Garbage Collection** | **Zero GC Overhead:** Dictionaries are static | Traces boxed fat-pointer nodes |
| **Coercions** | Object headers and adapter thunks when needed | Supported directly via attached dictionary |
| **Registers & ABI** | Standard AAPCS64; extra dictionary in register | Passes 2-word structs in register pairs |

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

For native AArch64 code generation, functions accepting subtyped record arguments receive the dictionary pointer in an
explicit argument register:

```
AAPCS64 Register Assignment:
  x0: Object data pointer (heap record payload)
  x1: Evidence dictionary pointer (static .rodata table)
  x2-x7: Subsequent parameters
  x19-x28: Callee-saved registers
  x29 (FP) / x30 (LR): Frame pointer and link register
```

When a record's concrete type is statically known (e.g. within a module or private function where no subsumption
occurred), the dictionary parameter is completely eliminated by the compiler via interprocedural specialization.

---

## 5. Memory Management and Garbage Collection

- **Boehm GC (`libgc`):** Used across Step 4 (C transpiler) and Step 6 (native AArch64).
- **Uniform Pointer Tracing:** Because all values in variables, arrays, and tuples are 1 word (`uint64_t`), the GC
  scans frames and heap allocations without needing runtime tag discrimination for primitive words vs. pointers.
- **Static Dictionaries:** Evidence dictionaries reside in read-only data sections (`.rodata`) and are never traced or
  collected by the GC.

---

## See Also
- [README.md](../README.md): Project overview.
- [roadmap.md](roadmap.md): 7-stage implementation roadmap.
- [type-system.md](type-system.md): Semantic type system and subtyping rules.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
