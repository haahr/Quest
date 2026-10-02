# Rules of Thumb: Converting Idiomatic Python to Idiomatic Quest

Quest is the illustrative language from Luca Cardelli's *Typeful Programming* (1989, revised 1993). Cardelli notes that
the language is partly speculative: only the features given syntax in the paper's appendix were implemented. The paper
also names several built-in modules (`string:StringOp`, `conv:Conv`, `real:RealOp`, `arrayOp:ArrayOp`,
`Reader`/`Writer`) without listing their operations. Where these rules call into those modules, the function names are
assumed and marked as such.

The rules target a Quest dialect with hierarchical module and interface names, using `/` as a separator when importing.
Only the last component of a name is exposed in the program: `import collections/vector : collections/Vector` makes the
value `vector` and the type `Vector` available.

## Libraries

### Built into the language

Quest itself provides `Ok`, `Bool`, `Char`, `String`, `Int`, `Real`, fixed-size `Array(A)`, exceptions, tuples and
records, options and variants, auto (dynamic) types, and recursive types.

### Provided libraries

```
import collections/vector : collections/Vector       (* Python list *)
import collections/hashMap : collections/HashMap     (* Python dict *)
import collections/hashSet : collections/HashSet     (* Python set *)
import util/maybe : util/Maybe                       (* Optional[T] *)
import util/stringBuilder : util/StringBuilder       (* Fast string accumulator *)
import util/strutil : util/Strutil                   (* String utilities and hashing *)
```

Each library's main type is called `T`, following Quest convention, so you write `vector.T(Int)`, `hashMap.T(String
Int)`, `hashSet.T(String)`, and `maybe.T(Int)`.

The actual operations in the Quest standard library have the following uncurried shapes:

```
vector.T(A)     new(:A)  newWithCapacity(:A cap)  length(:A v)  empty(:A v)
                get(:A v idx)  set(:A v idx val)  first(:A v)  last(:A v)
                append(:A v val)  pop(:A v)  delete(:A v idx)  clear(:A v)
                copy(:A v)  concat(:A v1 v2)  fromArray(:A arr)  toArray(:A v)
                forEach(:A v action)  map(:A :B v f)  filter(:A v pred)
                fold(:A :B v init f)  filterMap(:A :B v f)
                error:Exception(Ok)        (* raised on out-of-bounds access or pop on empty *)

hashMap.T(K V)  new(:K :V eq hash)  newWithCapacity(:K :V cap eq hash)
                size(:K :V m)  empty(:K :V m)  contains(:K :V m k)
                get(:K :V m k)             (* returns maybe.T(V): some(v) or none *)
                find(:K :V m k)            (* returns V or raises error *)
                insert(:K :V m k v)        (* returns Bool: true if newly inserted *)
                delete(:K :V m k)          (* returns maybe.T(V) *)
                clear(:K :V m)  keys(:K :V m)  values(:K :V m)  entries(:K :V m)
                forEach(:K :V m action)  map(:K :V :W m f)  filter(:K :V m pred)
                fold(:K :V :Acc m init f)  filterMap(:K :V :W m f)
                error:Exception(Ok)        (* raised by find on a missing key *)

hashSet.T(A)    new(:A eq hash)  newWithCapacity(:A cap eq hash)
                size(:A s)  empty(:A s)  contains(:A s elem)
                insert(:A s elem)  delete(:A s elem)  clear(:A s)
                elements(:A s)  copy(:A s)  union(:A s1 s2)  intersection(:A s1 s2)
                difference(:A s1 s2)  forEach(:A s action)  filter(:A s pred)
                fold(:A :Acc s init f)  map(:A :B s eq hash f)
                filterMap(:A :B s eq hash f)

maybe.T(A)      Option type with tags none, and some with val:A:
                isSome(:A o)  isNone(:A o)  unwrap(:A o)  unwrapOr(:A o default)
                some(:A val)  none(:A)
                error:Exception(Ok)        (* raised by unwrap on none *)

stringBuilder.T new()  newWithCapacity(cap)  append(b s)  appendChar(b c)
                appendInt(b n)  appendReal(b r)  appendBool(b val)  appendWord(b w)
                length(b)  clear(b)  toString(b)
```

`hashMap.new` and `hashSet.new` take an equality function `All(a,b:K) Bool` and a hash function `All(k:K) word.T`. Quest
has no overloading, and its `is` on strings and structured values compares memory locations, so a hash table cannot
discover key equality by itself. For strings, pass `stringOp.equal` and `strutil.hash`.

### Still missing

- **Iterators.** No generator or iterator protocol exists. The rules assume a type you define yourself:
  `Let Iter(A::TYPE)::TYPE = Tuple next():maybe.T(A) end`
- **Output and formatting helpers.** `Writer` is available for output (`writer.write(writer.output str)`), while
  conversions live in `Conv` (`conv.int`, `conv.real`, `conv.bool`) and `util/strutil` (`strutil.hash`, `strutil.split`,
  `strutil.join`, `strutil.strip`, etc.).

## Lexical and expression-level rules

**1. Brace every compound subexpression.** All infix operators in Quest have the same precedence and are
right-associative. So `a*b + c` must be written `{a*b}+c`. A bare `x - y - z` parses as `x-{y-z}`, so write `{x-y}-z`.
Curly braces group expressions; parentheses are only for parameter lists.

**2. Remap arithmetic operators by type, and watch the false friends.** Quest has no overloading. Integer and real
operators are different symbols, and several Python spellings mean something else in Quest:

| Python | Quest (Int) | Quest (Real) |
|---|---|---|
| `a + b`, `a - b`, `a * b` | `a+b`, `a-b`, `a*b` | `a++b`, `a--b`, `a**b` |
| `a // b` (int floor div) | `a/b` | — |
| `a / b` (true division) | — | `a//b` |
| `a ** b` (power) | — | `a^^b` |
| `a < b` etc. | `<` `>` `<=` `>=` | `<<` `>>` `<<=` `>>=` |
| `-3`, `-x` | `~3`, `{0-x}` | `~3.0` |
| `a == b`, `a != b` | `a is b`, `a isnot b` | same |

Python mixes ints and floats freely. In Quest you convert explicitly, for example `real.fromInt(n) // 2.0`. Also note
that Python's `int` is arbitrary-precision and Quest's `Int` is not.

Note on equality syntax: *Typeful Programming* specifies only `is` and `isnot` for identity and scalar equality; it does
not define `==` or `!=`. While some bootstrap compiler phases historically permitted `==` and `!=` as synonyms, Quest
code should strictly use `is` and `isnot`.

**3. Only use `is` for scalar equality.** `is`/`isnot` mean value equality for `Ok`, `Bool`, `Char`, `Int`, and `Real`.
For strings and every other reference type they mean "same memory location." Python `s == "yes"` becomes
`stringOp.equal(s "yes")`. For the same reason, hash tables are built with explicit equality and hash functions:
`hashMap.new(:String :Int stringOp.equal strutil.hash)`. For your own types, export `equal` and `hash` from the
interface, the Quest equivalent of `__eq__`/`__hash__`.

**4. Use the short-circuiting connectives.** Python `and`/`or` short-circuit. Quest's `/\` and `\/` evaluate both sides,
so the faithful translations are `andif` and `orif`: `{n isnot 0} andif {{m/n} > 0}`. `not` is a function: `not(done)`.

**5. Replace truthiness with explicit tests.** `if xs:` becomes `if {vector.length(:Int xs) isnot 0} then ...` or `if
not(vector.empty(:Int xs)) then ...`. There is no implicit conversion to `Bool`.

**6. Build strings by concatenation or stringBuilder.** For simple combinations, `f"{name} is {age}"` becomes `name <> "
is " <> conv.int(age)`. Characters use single quotes and strings use double quotes. Comments are `(* ... *)` and can
nest.

When building strings inside loops or accumulating large outputs (such as code generators or pretty-printers), repeated
`<>` creates $O(N^2)$ copying allocations. Use `util/stringBuilder` instead:

```quest
let sb = stringBuilder.new();
stringBuilder.append(sb "header\n");
stringBuilder.appendInt(sb 42);
let result = stringBuilder.toString(sb);
```

**7. Rename to Quest's case conventions.** Values and functions use lowerCamel (`word_count` becomes `wordCount`). Types
and interfaces are Capitalized. Kinds are ALL CAPS. `let` binds values, `Let` binds types, and `DEF` binds kinds.

## Functions and types

**8. Annotate parameters, and drop the commas.** Parameters are a space-separated signature. Commas appear only in
identifier lists. `def plus(a: int, b: int) -> int` becomes `let plus(a:Int b:Int):Int = a+b`, and `def gcd(n, m)`
becomes `let gcd(n,m:Int):Int = ...`. Calls also use no commas: `plus(3 4)`. Local `let` bindings may omit types.

**9. Mark recursion explicitly.** A Python function that calls itself needs `let rec`. Mutually recursive functions use
`let rec f(...) = ... and g(...) = ...`.

**10. Translate keyword arguments to bindings.** Quest arguments can be a named binding: `f(a=3, b=4)` becomes `f(let
a=3 let b=4)`. Names must match the parameter names, in order. Default arguments don't exist, so provide a second
function (`newCounter()` / `newCounterFrom(n)`) or take a `maybe.T(A)`.

**11. Translate `*args` to an array parameter plus listfix calls.** `def total(*xs)` becomes `let
total(xs:Array(Int)):Int = ...`, and you call it with listfix syntax: `total of 1 2 3 end`.

**12. Translate lambdas directly.** `lambda x: x + 1` becomes `fun(x:Int):Int x+1`. Closures over non-mutable locals
work as in Python.

**13. Make generics explicit.** A duck-typed function that works on "anything" takes a type parameter, usually curried
first: `def first(xs): return xs[0]` becomes `let first(A::TYPE)(xs:Array(A)):A = xs[0]`, and the call is
`first(:Int)(a)`. The leading colon in `:Int` marks a type argument.

**14. Turn duck typing on attributes into structural records.** If a function only needs `.name`, declare `Let Named =
Record name:String end` and accept a `Named`. Any record with at least that field is automatically a subtype, with no
declaration needed. If the function must return the same type it received, use a bounded parameter:

```
let oldest(A<:Aged)(a,b:A):A = if a.age >= b.age then a else b end;
```

## Control flow

**15. Treat everything as an expression, and eliminate `return`.** Quest has no `return`. A function body is an
expression, and `begin ... end` blocks yield their last expression. Early-return chains become `if/elsif/else`:

```
let sign(x:Int):Int = if x<0 then ~1 elsif x is 0 then 0 else 1 end;
```

An early return from inside a loop becomes a loop condition plus a result variable, or a raised exception caught at the
function boundary.

**16. Map loops to `while`, `for ... upto`, and `loop ... exit`.** `for i in range(n)` becomes `for i = 0 upto n-1 do
... end`. `while` maps directly. `break` becomes `exit` inside `loop ... end`. `continue` has no equivalent, so wrap the
remainder of the body in an `if`. Loops have type `Ok`.

**17. Iterate with the operation that matches the collection.** For a vector, `for x in xs:` becomes either an index
loop with `vector.get` or `vector.forEach(:Int xs fun(x:Int):Ok ...)`. For a hash map, `for k, v in d.items():` becomes

```quest
hashMap.forEach(:String :Int d fun(k:String v:Int):Ok ...)
```

Iterating over just `d.keys()` or `d.values()` can use `vector.forEach(:String hashMap.keys(:String :Int d) ...)` or
`forEach` ignoring the unused parameter.

**18. Replace comprehensions and reductions with `map`, `filter`, `fold`, or `filterMap`.**
Transformations and filters can be chained:

```quest
vector.map(:Int :Int
    vector.filter(:Int xs fun(x: Int): Bool x > 0)
    fun(x: Int): Int x * x)
```

When combining filtering and transformation in a single pass without intermediate allocations, use `filterMap`:

```quest
vector.filterMap(:Int :Int xs fun(x: Int): maybe.T(Int)
    if x > 0 then maybe.some(:Int {x * x}) else maybe.none(:Int) end)
```

For reductions (such as `sum()`, `any()`, `all()`, or state accumulation), use `fold`:

```quest
let sum = vector.fold(:Int :Int xs 0 fun(acc: Int x: Int): Int acc + x);
```

All of `Vector`, `HashMap`, and `HashSet` provide `forEach`, `map`, `filter`, `fold`, and `filterMap`.
On `HashMap`, `map` and `filterMap` transform values while preserving keys, equality, and hashing.
On `HashSet`, creating a set of a new element type takes `equal` and `hash` functions for the target type.

**19. Replace generators with explicit iterators.** There are no coroutines. A generator becomes a function returning an
`Iter(A)`: a tuple whose `next()` closes over a private mutable state tuple (rule 23) and returns `maybe.T(A)`, with
`none` signalling exhaustion. Alternatively, build the whole `vector.T(A)` eagerly, or take a callback in the style of
`each`/`forEach`.

**20. Translate `match` and enum dispatch to `case`.** See rule 25.

## Data modeling

**21. Choose between tuples, records, and options for data modeling.** Python tuples and `NamedTuple`s map to `Tuple`
(ordered, positional or named, single-inheritance subtyping). Single dataclasses representing pure product types
(structs/records) map to `Record` (unordered, always named, multiple-inheritance subtyping) or `Tuple`. Fields are
immutable unless declared `var`: `record var count:Int = 0 end`.

However, when Python uses class hierarchies or dataclasses to represent sum types (such as AST nodes, tokens, command
envelopes, or variants), do not use class hierarchies, duck typing, or `Auto`. Map the entire hierarchy to an `Option`
type with payloads (Rule 25).

**22. Destructure explicitly.** `a, b = f()` becomes `let p = f()` followed by `p.fst`, `p.snd`. You can also have `f`
return a named tuple type like `Tuple quot:Int rem:Int end`, which is clearer than positional pairs.

**23. Put mutable state in data structures.** `x = 3; x += 1` becomes `let var x = 3` then `x := x+1`. However,
functions may not refer directly to global `var` variables. Python `global`/`nonlocal` patterns must put the state
inside a tuple, as Cardelli's "own variable" example does:

```
let acc = tuple let var total = 0 end;
let add(x:Int):Ok = acc.total := acc.total+x;
```

**24. Translate `None` and `Optional[T]` to `maybe.T(A)`.** Returning `None` from a procedure becomes returning `ok :
Ok`. `Optional[int]` becomes `maybe.T(Int)`:

```
let found:maybe.T(Int) = option some of maybe.T(Int) with 5 end;
let missing:maybe.T(Int) = option none of maybe.T(Int) end;

case found
when none then 0
when some with arm then arm.some
end
```

If `util/Maybe` exports its own constructors or uses different tag names, use those instead of the raw `option ... of`
form.

**25. Translate `Enum`s, tagged unions, and sum types to options or variants.**
Simple enums without payloads use tag-only options: `Let Day = Option mon tue wed thu fri sat sun end`, consumed with:

```quest
case d when sat,sun then "weekend" else "weekday" end
```

When variants carry data (sum types / algebraic data types), give each tag a payload type:

```quest
Let Node = Option
    leaf: Int
    branch: Tuple left: Node right: Node end
end
```

Construct variants using `option tag of TargetType with payload end` (or helper constructor functions), and consume them
using `case`:

```quest
let rec countLeaves(n: Node): Int =
    case n
    when leaf with val then 1
    when branch with arm then
        countLeaves(arm.left) + countLeaves(arm.right)
    end;
```

This pattern provides compile-time exhaustiveness checking and static type safety without needing dynamic `isinstance`
checks or `Auto` types.

**26. Replace `isinstance`, `Any`, and runtime type switches with auto types.** Use `Auto A<:Base with a:A end` and
`inspect ... when Car with arm then ... end`. Reach for this only when you truly need runtime dispatch. Most Python
`isinstance` checks are better expressed as options (rule 25) or as functions on records (rule 14).

## Classes and objects

**27. A class becomes an interface type plus a constructor function.** Methods become closures in a tuple, and private
attributes become a hidden mutable tuple:

```
Let Counter = Tuple incr():Int value():Int end;

let newCounter(start:Int):Counter =
  begin
    let state = tuple let var n = start end
    tuple
      let incr():Int = begin state.n := state.n+1 state.n end
      let value():Int = state.n
    end
  end;
```

There is no `self`. Methods reach state through the closure.

**28. Inheritance becomes signature extension plus manual code reuse.** A tuple type with extra trailing fields (or a
record with extra fields) is automatically a subtype. Inherited behavior is obtained by having the "subclass"
constructor build a base object and forward to its methods. The language shares signatures, not implementations.

**29. Translate abstract base classes and encapsulated ADTs to abstract types.** Use a tuple type with a type component,
for example `Tuple A::TYPE new(x,y:Int):A x,y(p:A):Int end`, or an interface exporting `T::TYPE` plus operations.
Callers then can't see or forge the representation, which is stronger than Python's `_private` convention.

## Errors

**30. Exceptions are typed values you create.** `class NotFound(Exception)` becomes `let notFound:Exception(String) =
exception notFound:String end`. `raise NotFound(k)` becomes `raise notFound with k end`. The `except` handlers become:

```
try lookup(k)
when notFound with key then default
else fallback
end
```

Python's built-in collection errors map to the library exceptions. `IndexError` becomes `vector.error` (e.g. from
out-of-bounds `get` or empty `pop`), and `KeyError` corresponds to `hashMap.error` (from `find` on a missing key):

```quest
try hashMap.find(:String :Int counts w)
when hashMap.error then 0
end
```

Both library errors have type `Exception(Ok)`, so they carry no payload. If the Python code reads the missing key or
index from the exception, keep it in a local variable before the call instead. The two are still distinct values, so a
single `try` can handle them separately.

Prefer `hashMap.get` (which returns `maybe.none` if missing) and `maybe.unwrapOr`, or `hashMap.contains`, over catching
`hashMap.error` when the Python code uses `d.get(k, default)` or `k in d`:

```quest
maybe.unwrapOr(:Int hashMap.get(:String :Int counts w) 0)
```

The paper has no `finally` or `with` statement. Write cleanup in each handler path, or wrap the resource in a
higher-order function that does so.

## Modules and packages

**31. Each Python module becomes an interface plus a module, named by its package path.**

1. A Python module `myapp/geometry/shapes.py` becomes an interface `myapp/geometry/Shapes` and a module
`myapp/geometry/shapes`. The interface lists exactly what Python would put in `__all__`, and underscore-prefixed names
simply aren't exported. Types that clients need to see concretely go in the interface as manifest definitions (`Def T =
...`). Circular imports aren't allowed.

2. Convert dots to slashes and capitalize the last component of the interface. Python `import myapp.geometry.shapes`
becomes `import myapp/geometry/shapes : myapp/geometry/Shapes`. In code you then write `shapes.area(s)` and `shapes.T`,
never the full path, because only the last component is exposed by default.

3. Import the module, not individual names. `from myapp.geometry.shapes import area` becomes the same full import
followed by qualified use, `shapes.area`. If a short name really helps, add a local `let area = shapes.area`.

4. Resolve last-component collisions with import aliasing. Since only the final component becomes the identifier by
default, importing both `a/util` and `b/util` would cause a collision. In Quest, you can alias module imports using
`alias = path : Interface`:

```quest
import
    aUtil = a/util : a/Util
    bUtil = b/util : b/Util
    stringOp = string : StringOp
```

This binds `aUtil` and `bUtil` cleanly in the module environment.

5. Put library imports first. Any Python file that uses `list`, `dict`, `set`, or `Optional` needs the matching
`collections/vector`, `collections/hashMap`, `collections/hashSet`, or `util/maybe` import at the top of its module, and
in its interface if exported signatures mention those types. Inside a module, these go in the module heading's `import`
clause rather than as standalone `import ...;` statements.

## Worked example

Python:

```python
def word_counts(words: list[str]) -> dict[str, int]:
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return counts
```

Quest:

```quest
import
    collections/vector : collections/Vector
    collections/hashMap : collections/HashMap
    util/maybe : util/Maybe
    util/strutil : util/Strutil
    stringOp = string : StringOp
export
    let wordCounts(words: vector.T(String)): hashMap.T(String Int) =
        begin
            let counts = hashMap.new(:String :Int stringOp.equal strutil.hash);
            vector.forEach(:String words fun(w: String): Ok
                begin
                    let cur = maybe.unwrapOr(:Int hashMap.get(:String :Int counts w) 0);
                    hashMap.insert(:String :Int counts w {cur + 1});
                    ok
                end);
            counts
        end;
```

This example applies several rules at once: library imports by hierarchical name with aliasing (31), explicit type
arguments (13), equality and hash supplied to the map (3), iteration with `forEach` (17), braces around the compound
argument (1), and the block's last expression as the result instead of `return` (15).