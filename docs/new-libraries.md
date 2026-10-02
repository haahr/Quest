# Extended Standard Libraries

This document specifies the extended standard libraries for Quest that reside in hierarchical namespaces
(subdirectories of `lib/`) rather than the flat Cardelli standard library (`lib/*.{int,mod}.quest`).

These libraries provide optional values, string building, text manipulation, and core data structures
essential for writing complex applications and the self-hosted Quest compiler (`questc`).

---

## Namespace and Import Conventions

Hierarchical libraries are organized by domain under `lib/<category>/`:
- Source files: `lib/<category>/<module>.int.quest` (interface) and
  `lib/<category>/<module>.mod.quest` (implementation).
- Filenames are strictly lowercase (e.g. `opt.int.quest`, `stringbuilder.mod.quest`, `strutil.mod.quest`).
- Import syntax:
  ```quest
  import category/module : category/Interface;
  ```
  or aliased:
  ```quest
  import m = category/module : category/Interface;
  ```
- Compiled artifacts (`.qi`, `.h`, `.c`, `.o`) are placed mirror-wise under `.build/<category>/` or alongside source.
- Type functors follow Cardelli's convention: `Vector.T(A)`, `Opt.T(A)`, `StringBuilder.T`.

---

## 1. Utilities (`lib/util/`)

### 1.1. `util/maybe : util/Maybe`

Standalone polymorphic option type functor and constructors for optional values and non-throwing operations.

#### Interface Summary

```quest
interface Maybe export
    (* Polymorphic optional value type *)
    T::ALL(A::TYPE) TYPE

    (* Exception raised on invalid option unwrapping *)
    error: Exception

    (* Test if an option value is present *)
    isSome: All(A::TYPE) All(o: T(A)) Bool

    (* Test if an option value is absent *)
    isNone: All(A::TYPE) All(o: T(A)) Bool

    (* Extract the payload from an option, or raise error if none *)
    unwrap: All(A::TYPE) All(o: T(A)) A

    (* Extract the payload from an option, or return default if none *)
    unwrapOr: All(A::TYPE) All(o: T(A) default: A) A

    (* Construct a some option value *)
    some: All(A::TYPE) All(val: A) T(A)

    (* Construct a none option value *)
    none: All(A::TYPE) T(A)
end;
```

---

### 1.2. `util/stringBuilder : util/StringBuilder`

High-performance chunked string accumulator providing $O(N)$ string construction without quadratic reallocation.

#### Interface Summary

```quest
interface StringBuilder
    import word: Word
export
    (* Opaque growable string builder type *)
    T::TYPE

    (* Create a new empty string builder *)
    new(): T

    (* Create a new string builder with preallocated chunk capacity *)
    newWithCapacity(capacity: Int): T

    (* Append a string to the builder *)
    append(b: T s: String): Ok

    (* Append a single character to the builder *)
    appendChar(b: T c: Char): Ok

    (* Append an integer formatted in decimal to the builder *)
    appendInt(b: T n: Int): Ok

    (* Append a real number formatted as string to the builder *)
    appendReal(b: T r: Real): Ok

    (* Append a boolean ("true" or "false") to the builder *)
    appendBool(b: T val: Bool): Ok

    (* Append an unsigned 64-bit word formatted in decimal to the builder *)
    appendWord(b: T w: word.T): Ok

    (* Return the total accumulated character length of the builder *)
    length(b: T): Int

    (* Reset the builder to empty *)
    clear(b: T): Ok

    (* Materialize accumulated chunks into a single string in O(N) time *)
    toString(b: T): String
end;
```

---

### 1.3. `util/strutil : util/Strutil`

Comprehensive string utilities: text splitting, joining, pattern search, whitespace trimming, C escaping,
and numerical string parsing.

#### Interface Summary

```quest
interface Strutil
import
    util/maybe : util/Maybe
    collections/vector : collections/Vector
    word: Word
export
    error: Exception

    (* Splitting & Joining *)
    split(s: String delim: String): vector.T(String)
    splitlines(s: String): vector.T(String)
    join(delim: String items: vector.T(String)): String
    joinArray(delim: String items: Array(String)): String

    (* Searching & Predicates *)
    startsWith(s: String prefix: String): Bool
    endsWith(s: String suffix: String): Bool
    find(s: String sub: String): Int
    findFrom(s: String sub: String start: Int): Int
    rfind(s: String sub: String): Int
    contains(s: String sub: String): Bool
    strip(s: String): String
    stripLeading(s: String): String
    stripTrailing(s: String): String

    (* Replacement & Escaping *)
    replace(s: String oldSub: String newSub: String): String
    escapeC(s: String): String
    unescapeC(s: String): String

    (* Character Classification *)
    isDigit(c: Char): Bool
    isAlpha(c: Char): Bool
    isAlnum(c: Char): Bool
    isSpace(c: Char): Bool

    (* Parsing *)
    toInt(s: String): Int
    tryToInt(s: String): maybe.T(Int)
    toIntBase(s: String base: Int): Int
    tryToIntBase(s: String base: Int): maybe.T(Int)
    toWord(s: String): word.T
    tryToWord(s: String): maybe.T(word.T)
    toWordBase(s: String base: Int): word.T
    tryToWordBase(s: String base: Int): maybe.T(word.T)
    formatWord(w: word.T base: Int): String
    wordToString(w: word.T): String
    toReal(s: String): Real
    tryToReal(s: String): maybe.T(Real)
    toBool(s: String): Bool
    tryToBool(s: String): maybe.T(Bool)
end;
```

---

## 2. Collections (`lib/collections/`)

### 2.1. `collections/vector : collections/Vector`

Growable, dynamically-resizing array collection parameterized over element type `A`.

#### Interface Summary

```quest
interface Vector export
    (* The polymorphic growable vector type constructor *)
    T::ALL(A::TYPE) TYPE

    (* Exception raised on out-of-bounds access or empty vector operations *)
    error: Exception

    (* Create a new empty vector *)
    new: All(A::TYPE) T(A)

    (* Create a new empty vector with preallocated capacity hint *)
    newWithCapacity: All(A::TYPE) All(capacity: Int) T(A)

    (* Return the number of elements in a vector *)
    length: All(A::TYPE) All(v: T(A)) Int

    (* Test whether a vector is empty *)
    empty: All(A::TYPE) All(v: T(A)) Bool

    (* Return the element at the specified index, or raise error *)
    get: All(A::TYPE) All(v: T(A) index: Int) A

    (* Update the element at the specified index, or raise error *)
    set: All(A::TYPE) All(v: T(A) index: Int value: A) Ok

    (* Return the first element of a vector, or raise error if empty *)
    first: All(A::TYPE) All(v: T(A)) A

    (* Return the last element of a vector, or raise error if empty *)
    last: All(A::TYPE) All(v: T(A)) A

    (* Append a new element to the end of a vector *)
    append: All(A::TYPE) All(v: T(A) value: A) Ok

    (* Remove and return the last element of a vector, or raise error if empty *)
    pop: All(A::TYPE) All(v: T(A)) A

    (* Delete element at index and shift subsequent elements left; linear time *)
    delete: All(A::TYPE) All(v: T(A) index: Int) Ok

    (* Remove all elements from a vector *)
    clear: All(A::TYPE) All(v: T(A)) Ok

    (* Create a shallow copy of a vector *)
    copy: All(A::TYPE) All(v: T(A)) T(A)

    (* Concatenate two vectors into a new vector *)
    concat: All(A::TYPE) All(v1: T(A) v2: T(A)) T(A)

    (* Create a new vector containing the elements of an array *)
    fromArray: All(A::TYPE) All(arr: Array(A)) T(A)

    (* Create an array containing the elements of a vector *)
    toArray: All(A::TYPE) All(v: T(A)) Array(A)

    (* Iterate over all elements of a vector *)
    forEach: All(A::TYPE) All(v: T(A) action: All(elem: A) Ok) Ok
end;
```

#### Memory and Growth Strategy

- **Initial Floor**: When appending to an empty vector, initial capacity is allocated to 6 elements.
- **Growth Factor**: When capacity is exceeded, storage grows by $1.5\times$ (`cap + cap / 2`),
  ensuring $O(1)$ amortized append time.
- **Shrinking**: When utilization drops to 25% or below (`length * 4 <= capacity`), the backing array shrinks by 50%
  (bounded below by the floor of 6).
- **GC Safety**: Vacated slots on `pop` and `delete` are overwritten to prevent reference leaks. Emptying a vector
  via `clear` resets the backing array to zero elements.

---

### 2.2. `collections/hashMap : collections/HashMap`

Compact, insertion-order preserving polymorphic hash table parameterized over key type `K` and value type `V`.
Uses the Python 3.6+ / PyPy architecture (sparse power-of-two index array with dense parallel vectors)
with secondary perturbation probing and periodic tombstone compaction.

#### Interface Summary

```quest
interface HashMap
import
    util/maybe : util/Maybe
    collections/vector : collections/Vector
    word: Word
export
    (* The polymorphic hash map type constructor *)
    T::ALL(K::TYPE) ALL(V::TYPE) TYPE

    (* Key-value pair entry *)
    Entry::ALL(K::TYPE) ALL(V::TYPE) TYPE

    (* Exception raised on lookup failure when using unwrap-style access *)
    error: Exception

    (* Create a new empty hash map with custom equality and hash functions *)
    new: All(K::TYPE V::TYPE)
        All(equal: All(k1: K k2: K) Bool
            hash: All(k: K) word.T)
        T(K V)

    (* Create a new hash map with preallocated initial capacity *)
    newWithCapacity: All(K::TYPE V::TYPE)
        All(capacity: Int
            equal: All(k1: K k2: K) Bool
            hash: All(k: K) word.T)
        T(K V)

    (* Return the number of active key-value pairs stored in the map *)
    size: All(K::TYPE V::TYPE) All(m: T(K V)) Int

    (* Check if the map is empty *)
    empty: All(K::TYPE V::TYPE) All(m: T(K V)) Bool

    (* Retrieve value associated with key, returning maybe.some(v) or maybe.none *)
    get: All(K::TYPE V::TYPE) All(m: T(K V) key: K) maybe.T(V)

    (* Check if key exists in the map *)
    contains: All(K::TYPE V::TYPE) All(m: T(K V) key: K) Bool

    (* Retrieve value or raise error if key is not present *)
    find: All(K::TYPE V::TYPE) All(m: T(K V) key: K) V

    (* Insert or overwrite key-value pair. Returns true if key was newly inserted *)
    insert: All(K::TYPE V::TYPE) All(m: T(K V) key: K value: V) Bool

    (* Remove a key and its associated value. Returns maybe.some(v) if found, else none *)
    delete: All(K::TYPE V::TYPE) All(m: T(K V) key: K) maybe.T(V)

    (* Clear all key-value pairs in the map *)
    clear: All(K::TYPE V::TYPE) All(m: T(K V)) Ok

    (* Return all keys as a vector in insertion order *)
    keys: All(K::TYPE V::TYPE) All(m: T(K V)) vector.T(K)

    (* Return all values as a vector in insertion order *)
    values: All(K::TYPE V::TYPE) All(m: T(K V)) vector.T(V)

    (* Return all entries as a vector of (key, value) records in insertion order *)
    entries: All(K::TYPE V::TYPE) All(m: T(K V)) vector.T(Entry(K V))

    (* Iterate over all key-value pairs in insertion order *)
    forEach: All(K::TYPE V::TYPE)
        All(m: T(K V) action: All(k: K v: V) Ok)
        Ok
end;
```

---

### 2.3. `collections/hashSet : collections/HashSet`

Polymorphic hash set parameterized over element type `A`, implemented directly on top of `collections/hashMap(A, Ok)`.
Maintains insertion ordering and provides standard set membership, manipulation, and set algebra operations.

#### Interface Summary

```quest
interface HashSet
import
    collections/vector : collections/Vector
    word: Word
export
    (* The polymorphic hash set type constructor *)
    T::ALL(A::TYPE) TYPE

    (* Create a new empty hash set with custom equality and hash functions *)
    new: All(A::TYPE)
        All(equal: All(a1: A a2: A) Bool
            hash: All(a: A) word.T)
        T(A)

    (* Create a new hash set with preallocated initial capacity *)
    newWithCapacity: All(A::TYPE)
        All(capacity: Int
            equal: All(a1: A a2: A) Bool
            hash: All(a: A) word.T)
        T(A)

    (* Return the number of elements in the set *)
    size: All(A::TYPE) All(s: T(A)) Int

    (* Check if the set is empty *)
    empty: All(A::TYPE) All(s: T(A)) Bool

    (* Check if an element exists in the set *)
    contains: All(A::TYPE) All(s: T(A) elem: A) Bool

    (* Insert an element into the set. Returns true if newly added, false if already present *)
    insert: All(A::TYPE) All(s: T(A) elem: A) Bool

    (* Remove an element from the set. Returns true if element was found and removed *)
    delete: All(A::TYPE) All(s: T(A) elem: A) Bool

    (* Clear all elements from the set *)
    clear: All(A::TYPE) All(s: T(A)) Ok

    (* Return all elements as a vector in insertion order *)
    elements: All(A::TYPE) All(s: T(A)) vector.T(A)

    (* Iterate over all elements in insertion order *)
    forEach: All(A::TYPE)
        All(s: T(A) action: All(elem: A) Ok)
        Ok

    (* Create a shallow copy of the set *)
    copy: All(A::TYPE) All(s: T(A)) T(A)

    (* Return the union of s1 and s2 (elements in s1 or s2) *)
    union: All(A::TYPE) All(s1: T(A) s2: T(A)) T(A)

    (* Return the intersection of s1 and s2 (elements in both s1 and s2) *)
    intersection: All(A::TYPE) All(s1: T(A) s2: T(A)) T(A)

    (* Return the set difference s1 \ s2 (elements in s1 that are not in s2) *)
    difference: All(A::TYPE) All(s1: T(A) s2: T(A)) T(A)

    (* Check if s1 is a subset of s2 (every element in s1 is in s2) *)
    isSubset: All(A::TYPE) All(s1: T(A) s2: T(A)) Bool

    (* Check if s1 and s2 are equal (same size and every element of s1 is in s2) *)
    equal: All(A::TYPE) All(s1: T(A) s2: T(A)) Bool
end;
```
