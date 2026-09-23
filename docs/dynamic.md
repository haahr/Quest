# Quest Dynamic Types & Serialization (`dynamic.extern` / `dynamic.intern`)

This document specifies the design, runtime representation, and JSON/JSOG serialization format for Quest dynamic
types (`Dynamic.T`), implemented in `bootstrap/python/quest/dynamic_json.py` and `bootstrap/python/quest/builtins.py`.

---

## 1. Overview & Theoretical Foundation

In Cardelli's *Typeful Programming* (§9.1 and Appendix), dynamic types provide a type-sound mechanism for handling
heterogeneous data, persistence, and run-time metaprogramming. A dynamic value packages an arbitrary runtime value
together with its static/declared type:

```quest
interface Dynamic
export
    T :: TYPE
    new (A :: TYPE a : A) : T
    be (A :: TYPE d : T) : A
    copy (d : T) : T
    extern (wr : Writer.T d : T) : Ok
    intern (rd : Reader.T) : T
    error : Exception(Ok)
end;
```

- **`dynamic.new(:Type val)`**: Packages `val` and its static type `Type` into a dynamic value `d: Dynamic.T`.
- **`dynamic.be(:TargetType d)`**: Inspects `d`'s packaged type against `TargetType`.
  If `is_subtype(d.type, TargetType)` holds, returns the underlying value typed as `TargetType`;
  otherwise raises `dynamic.error`.
- **`dynamic.copy(d)`**: Produces a deep copy of `d`, preserving internal sharing and cycles.
- **`dynamic.extern(wr, d)`**: Serializes `d` into a stream in a cycle-safe, JSON-compatible representation.
- **`dynamic.intern(rd)`**: Deserializes a dynamic value from an input stream, reconstructing the object graph,
  resolving cyclic/shared references, and restoring the packaged type for subsequent `dynamic.be` checks.

---

## 2. Wire Format Specification: JSON/JSOG

The serialization format emitted by `dynamic.extern` and parsed by `dynamic.intern` is standard JSON extended with
JSOG (JavaScript Object Graph) conventions for cycle detection and sharing.

### 2.1. Top-Level Type Envelope
Every serialized dynamic value is wrapped in an explicit top-level envelope:
```json
{
  "@type": "<TypeString>",
  "@value": <ValuePayload>
}
```
- **`@type`**: A canonical string representation of the static type `d.type_val` (e.g. `"Int"`, `"Array(String)"`,
  `"Record x: Int y: Int end"`).
- **`@value`**: The JSON serialization of the underlying value `d.value`.

On `dynamic.intern`, the `@type` string is parsed and elaborated using the Quest lexer, parser, and type elaborator
with the standard prelude environment, reconstructing the `QType` descriptor needed for runtime subtyping in
`dynamic.be`.

### 2.2. Serde-Style External Tagging for Variants and Options
To match idiomatic serialization patterns (e.g., Rust's Serde external tagging):
- **Variants with a payload**: Serialized as a single-key object where the key is the variant tag:
  ```json
  {"error": 404}
  ```
- **Unit variants** (payload of type `Ok`): Serialized directly as a string containing the tag name:
  ```json
  "success"
  ```
- **Options**: Encoded using the same external tagging rules:
  - `option nil of T end` -> `"nil"`
  - `option cons with head: 1 tail: ... end` -> `{"cons": {"head": 1, ...}}`

### 2.3. Cycle and Sharing Resolution via JSOG (`@id` and `@ref`)
In memory, Quest data structures (such as mutable records or arrays) can form cycles (e.g., recursive nodes) or
directed acyclic graphs (DAGs) with shared subgraphs.

Cardelli's specification requires that `extern` and `intern` preserve sharing and circularities within a single
dynamic object. This is achieved via JSOG annotations:

1. **`@id` Definition:**
   The first time an object that is referenced more than once (or participates in a cycle) is encountered during
   serialization, an `@id` property is added to its JSON representation:
   ```json
   {
     "@id": "1",
     "id": 1,
     "next": { ... }
   }
   ```
2. **`@ref` Reference:**
   On all subsequent encounters of the identical object, a reference stub is emitted instead of re-serializing the
   object:
   ```json
   {
     "@ref": "1"
   }
   ```
3. **Cyclic Arrays (`QArray`):**
   Plain JSON arrays `[...]` cannot carry object properties like `@id`. If a `QArray` participates in a cycle or has
   multiple incoming references, it is wrapped in an object container:
   ```json
   {
     "@id": "2",
     "@array": [1, 2, {"@ref": "2"}]
   }
   ```
   Non-cyclic, unshared arrays are emitted as standard JSON lists: `[1, 2, 3]`.
4. **Tuples (`QTuple`):**
   Tuples with shared references or cycles are wrapped in `{"@id": "...", "@tuple": [...]}`.

### 2.4. Mapping of Quest Values to JSON

| Quest Type / Value | Serialized JSON Format | Notes |
| :--- | :--- | :--- |
| `Ok` (`ok`) | `"ok"` | Represented as constant string `"ok"`. |
| `Bool` (`true` / `false`) | `true` / `false` | Native JSON booleans. |
| `Int` (`123`, `~45`) | `123`, `-45` | Standard JSON integer numbers. |
| `Real` (`3.14`, `~0.5`) | `3.14`, `-0.5` | Standard JSON float numbers. |
| `Char` (`'a'`) | `"a"` | Single-character string; type envelope specifies `"Char"`. |
| `String` (`"hello"`) | `"hello"` | Standard JSON string with standard escaping. |
| `Record` (`record ... end`) | `{"field": val, ...}` | Object with sorted field keys; adds `@id` if cyclic/shared. |
| `Tuple` (`tuple ... end`) | `{"@tuple": [val1, ...]}` | Emitted under `@tuple` key to distinguish from records. |
| `Array` (`array ... end`) | `[elem1, ...]` | Plain list if unshared; `{"@id": "...", "@array": [...]}` if cyclic. |
| `Variant` (`variant tag ...`) | `{"tag": val}` or `"tag"` | Serde external tagging convention. |
| `Option` (`option tag ...`) | `{"tag": val}` or `"tag"` | Serde external tagging convention. |
| `Dynamic.T` (`dynamic.new(...)`) | `{"@type": "...", "@value": ...}` | Nested dynamic envelope. |
| `Var(T)` / `QRef` | `<value>` | Transparently dereferenced and serialized as inner value. |

### 2.5. Non-Externable Types & Error Semantics
According to Cardelli (§9.1), objects bound to input/output devices or containing native runtime state cannot be
externed:
- **Prohibited Types:**
  - Readers (`QReader` / `Reader.T`)
  - Writers (`QWriter` / `Writer.T`)
  - Closures (`QClosure`, `QBuiltinFun`)
- **Error Behavior:**
  - Invoking `dynamic.extern` on a dynamic value containing any non-externable object immediately raises
    `dynamic.error` (`QuestException(DYNAMIC_ERROR_EXC)`).
  - Calling `dynamic.intern` on corrupt JSON, missing envelope keys (`@type`, `@value`), unresolvable `@ref` IDs,
    or schema mismatches cleanly raises `dynamic.error`.

### 2.6. Whitespace & Formatting
The default output generated by `dynamic.extern` is compact single-line JSON using minimal separators
(`separators=(',', ':')`). This ensures deterministic output across platforms and optimal streaming performance.

---

## 3. Implementation Architecture

### 3.1. Two-Pass Encoding (`jsog_encode`)
Located in `bootstrap/python/quest/dynamic_json.py`:
- **Pass 1 (Analysis):** Recursively traverses the value graph starting at `dyn.value`, tracking object identities via
  Python `id()`. Tracks reference counts for composite objects (`QRecord`, `QArray`, `QTuple`).
- **Pass 2 (Emission):** Assigns sequential string identifiers (`"1"`, `"2"`, ...) to objects with reference count
  greater than 1. Emits the full object definition with `@id` on the first encounter, and `{"@ref": id}` on all
  subsequent encounters.

### 3.2. Two-Pass Decoding (`jsog_decode`)
- **Pass 1 (Pre-allocation):** Recursively scans the parsed JSON dictionary/list tree for any object containing an
  `@id` attribute. Allocates an empty `QRecord`, `QArray`, or `QTuple` instance and stores it in an `id_map`.
- **Pass 2 (Linking):** Traverses the JSON tree again, populating fields and array elements. Whenever an object
  containing `{"@ref": id}` is encountered, it is replaced with the pre-allocated instance from `id_map`. This
  guarantees that self-referential cycles and mutual loops of any depth are restored correctly.

### 3.3. Type Parsing (`parse_type_string`)
Converts the textual type representation in `@type` back into a `QType` object:
- Primitive type names (`Int`, `Real`, `Bool`, `Char`, `String`, `Ok`, `Dynamic`) are resolved via a static table.
- Complex types (`Record ... end`, `Array(...)`, `Variant ... end`, `Option ... end`, `Tuple ... end`) are tokenized
  with `Tokenizer`, parsed using `parse_quest_program(tokens, symbol_map, target="Type")`, and elaborated in a base
  type environment.

### 3.4. Native C Runtime Implementation (`runtime/quest_serialization.c`)
The native C implementation provides full format parity with the Python reference:
- **`quest_dynamic_extern`:** Traverses the pointer graph, identifies cycles and multi-references with an address hash
  table, and emits JSON/JSOG text using canonical alphabetical record field ordering.
- **`quest_dynamic_intern`:** Reads characters from a `QReader` using a streaming lexer/parser, consuming exactly one
  top-level JSON value while preserving unread stream characters in `peek_char`.
- **Type Descriptor Resolution:** Checks registered static program types (`quest_lookup_type_descriptor_by_name`),
  falling back to a recursive-descent type expression parser (`quest_parse_type_descriptor`) for dynamically
  synthesized types.
- **Two-Pass Deserialization:** Pre-allocates heap memory for all `@id` nodes (`quest_jsog_preallocate`) using natural
  C struct alignment, and links fields and `@ref` pointers (`quest_jsog_decode_value`).

---

## 4. Example Serialization

### Cyclic Record in Quest
```quest
Let Node = Record id: Int var next: Dynamic.T end;
let n1 = record id = 1 var next = dynamic.new(:Ok ok) end;
let n2 = record id = 2 var next = dynamic.new(:Node n1) end;
n1.next := dynamic.new(:Node n2);

let d = dynamic.new(:Node n1);
dynamic.extern(writer.output d);
```

**Serialized JSON Output (compact on wire, formatted here for clarity):**
```json
{
  "@type": "Record id: Int var next: Dynamic end",
  "@value": {
    "@id": "1",
    "id": 1,
    "next": {
      "@type": "Record id: Int var next: Dynamic end",
      "@value": {
        "id": 2,
        "next": {
          "@type": "Record id: Int var next: Dynamic end",
          "@value": {
            "@ref": "1"
          }
        }
      }
    }
  }
}
```

When decoded with `dynamic.intern(reader.input)`, `n1.next.next` resolves identically to `n1` in memory, and
`dynamic.be(:Node d)` succeeds.
