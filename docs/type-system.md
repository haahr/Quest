# Quest Type System: Semantics, Subtyping, and Term Elaboration

This document specifies the higher-order type system (System $F_{<:}^\omega$), semantic type representations,
subtyping algorithms, recursive contractiveness rules, iterated existential tuples (weak sums / packages),
path-dependent types, and bidirectional term typechecking for the Quest compiler.

---

## 1. Overview and Design Philosophy

Quest implements a higher-order type system with bounded quantification, structural subtyping, and iterated weak sums:
- **Level 2 (Kinds):** Classify types. `TYPE` classifies proper types; `POWER(B)` classifies subtypes of $B$;
  `ALL(X::K1) K2` classifies type operators.
- **Level 1 (Types and Type Operators):** Semantic types (`QType`) representing values, tuples, records, variants,
  options, functions, and path-dependent types (`QPathType`). Compile-time type functions (`Fun(X::K) T`) evaluate
  via typed $\lambda$-calculus reduction.
- **Level 0 (Values):** Runtime expressions evaluated against typing contexts.

The compiler avoids global ML-style constraint unification. Instead, it uses **local bidirectional typing**
(Dunfield & Krishnaswami) where types propagate from annotations downward (checking mode) or are computed from
constructs upward (synthesis mode).

---

## 2. Semantic Hierarchy (`bootstrap/python/quest/types.py`)

Semantic entities use a `Q` prefix to avoid name collisions with Python host primitives:

```
QKind (Level 2)
  ├── QTypeKind               TYPE (proper types)
  ├── QPowerKind              POWER(B) (subtypes of B)
  ├── QAllKind                ALL(X::K1) K2 (operator kinds)
  └── QKindVar                Named kind variable

QType (Level 1)
  ├── Base Types              QIntType, QRealType, QBoolType, QCharType, QStringType, QOkType
  ├── Dynamic & Exceptions    QDynamicType, QExceptionType
  ├── Aggregates              QTupleType, QRecordType, QVariantType, QOptionType
  ├── Functions & References  QFunType, QVarType, QArrayType, QOutType
  ├── Polymorphic & Operators QAllType, QAutoType, QTypeFun, QTypeApp
  ├── Recursive Types         QRecType, QRecGroupType
  ├── Variables & Paths       QTypeVar, QPathType, QAbstractType
  └── Metavariables           QTypeMeta (local bidirectional inference)

QTupleComponent (Tuple Components)
  ├── QTupleField             Value field: name (optional), type_val
  ├── QTupleTypeFormal        Existential type formal: name, symbol_id, bound
  └── QTupleTypeBinding       Manifest type binding: name, type_val, bound
```

---

## 3. Subtyping and Kind Theory

### 3.1. Subkinding ($K_1 \le K_2$)
Subkinding allows type operators and power kinds to be used wherever broader kind bounds are expected:
- *Reflexivity:* $K \le K$.
- *Power to Type:* $\text{POWER}(T) \le \text{TYPE}$ for any valid type $T$.
- *Power to Power:* $\text{POWER}(S) \le \text{POWER}(T) \iff S \le T$ (delegates to equi-recursive `is_subtype`).
- *Operator Kinds:* $\text{ALL}(X::K_1) K_2 \le \text{ALL}(Y::K_1') K_2'$
  $\iff K_1' \le K_1 \land K_2 \le K_2'[Y \mapsto X]$
  (contravariant in parameter kind, covariant in result kind).

### 3.2. Equi-Recursive Subtyping and the Coinductive Trail ($\Sigma$)
In Quest, recursive types are equi-recursive: $\text{Rec}(X::K) T \equiv T[\text{Rec}(X::K) T / X]$.
No explicit user `fold` or `unfold` operations are required.

To prevent infinite loops when checking subtyping between recursive types ($S \le T$), the subtyping engine:
1. Evaluates types **lazily**.
2. Records visited symbol pairs in an **active assumption trail** $\Sigma \vdash (S, T)$.
3. If the pair $(S, T)$ is encountered again under the same polarity, it is treated as coinductively valid.
4. Correctly handles polarity flips during function parameter contravariance.

### 3.3. Recursive Contractiveness ($C \succ X$)
To guarantee that recursive type definitions have unique solutions and do not produce infinite loops or degenerate
empty types, definitions must be **contractive** in their recursive variables (Cardelli & Longo 1991, Section 2.4/2.9,
rule `[T µ]`).

A type $C$ is contractive in $X$ ($C \succ X$) iff the recursive variable $X$ occurs exclusively behind a guarding
type constructor (`Record`, `Tuple`, `Option`, `Variant`, `Fun`, `Array`, `Var`, `Out`).
- **Bare occurrences are rejected:**
  ```quest
  Let Rec Bad::TYPE = Bad;              (* REJECTED: bare self-recursion *)
  Let Rec A = B and B = A;              (* REJECTED: mutual bare cycle *)
  Rec(X)X                               (* REJECTED: inline bare recursion *)
  ```
- **Guarded occurrences are accepted:**
  ```quest
  Let Rec List = Tuple head:Int tail:List end;   (* ACCEPTED: guarded by Tuple *)
  Let Rec Tree = Option empty, node with t:Tree end; (* ACCEPTED: guarded by Option *)
  ```

---

## 4. Iterated Existential Tuples and Weak Sums

Quest represents abstract data types, packages, and modules through **iterated weak sums** (existential tuples),
following Cardelli (*The Quest Language and System* §4.4, §5.3, §7.1, §10, and *A Semantic Basis for Quest* §1.2, §2).

### 4.1. Dependent Signatures and Type Formals
Tuples in Quest can interleave type formals (`X::K`), value fields (`x: T`), and manifest type bindings (`Let X = T`):
```quest
Let PointPackage = Tuple
  Point::TYPE
  origin: Point
  distance(p1: Point, p2: Point): Real
end;
```
Signature elaboration (`bootstrap/python/quest/elaborate_types.py`) proceeds sequentially in an ordered dependent
scope. Each type formal `X::K` introduces a `TypeSymbol` into the local scope so subsequent fields can refer to `X`.
Anonymous type formals (`::TYPE`) are prohibited; type formals must specify an identifier.

### 4.2. Extended Subsignatures (`is_subtype`)
Subtyping between tuple types implements Cardelli's extended subsignature rules (§7.1, §10.2):
1. **Prefix Subtyping:** A tuple type with extra trailing fields is a subtype of any prefix signature:
   $$\text{len}(S.\text{fields}) \ge \text{len}(T.\text{fields})$$
   For example, `Tuple age:Int speed:Int end <: Tuple age:Int end`.
2. **Exact Component Name Matching (No $\alpha$-Conversion):**
   Components must match identically in name and position:
   - `Tuple A::TYPE a:A end` is **not** a subtype of `Tuple B::TYPE a:B end`.
   - Matching names keeps path-dependent dot notation unambiguous and avoids accidental structural matches
     across distinct interfaces.
3. **Type Formal Subkinding & Variable Remapping:**
   For matching type formals (`A::K` in $S$ vs `A::L` in $T$), subtyping requires $K <:: L$. The formal's internal
   symbol ID in $T$ is remapped to the corresponding symbol ID in $S$ for checking subsequent components in $T$.
4. **Manifest Type Binding Subsumption:**
   A tuple with a concrete manifest binding is a subtype of a tuple with an abstract type formal:
   `Tuple Def A::TYPE = Int a:A end <: Tuple A::TYPE a:A end`.
   The manifest type definition is substituted into remaining components of the supertype signature.

### 4.3. Existential Packing and Witness Checking
Existential packages are constructed using tuple expressions with type witness bindings:
```quest
let p: PointPackage = tuple
  Let Point::TYPE = Tuple x: Real y: Real end
  let origin: Point = tuple 0.0 0.0 end
  let distance(p1: Point, p2: Point): Real = ...
end;
```
- **Explicit Ascription Required:**
  Existential packages require explicit type ascription (e.g. `let p: PointPackage = tuple ... end`).
  Unannotated tuple constructors synthesize transparent tuples containing `QTupleTypeBinding`, which coerce
  to existential signatures via subtyping.
- **Witness Checking (`_check_tuple_expr`):**
  When checking a tuple against an existential tuple type:
  1. Witness type bindings (`Let X::K = W`) are matched against expected type formals (`X::K`).
  2. Witness kinds are validated: $\Gamma \vdash W :: K$.
  3. Witnesses are substituted into subsequent component signatures before checking value fields.
  4. Mismatched witness bounds, names, or arities produce informative compile-time diagnostics.

### 4.4. Path-Dependent Types (`QPathType`)
When an existential tuple is bound to an immutable identifier $x$, its type components can be accessed via
**path-dependent types** ($x.A$):
```quest
let origin: p.Point = p.origin;
```
- **Representation:** `QPathType(root_name, root_symbol_id, field_name, bound)`.
- **Immutable Path Roots Only:**
  Path-dependent types can only be rooted at **immutable value bindings** (`let` bindings or immutable function
  parameters). Projecting type components from mutable variables (`let var x: T`) is rejected with a compile-time
  error to prevent unsoundness under variable reassignment.
- **Path Subtyping Rules:**
  1. *Reflexivity:* $x.A \le x.A$ holds when both path types share the same `root_symbol_id` and `field_name`.
     Distinct packages $t_1$ and $t_2$ have incompatible abstract types ($t_1.A \not\le t_2.A$).
  2. *Bounded Subtyping:* When a type formal is bounded by a power kind ($A :: \text{POWER}(B)$), its path type
     inherits that bound: $x.A \le B$. This allows abstract types with bounds to participate in operations of their
     supertype (e.g., arithmetic on bounded integers).
- **Member Selection Restrictions (`_synth_select_expr`):**
  - Type components cannot be evaluated as values: `p.Point` in a value expression produces a type error.
  - Type-dependent value members (`x.a`) cannot be selected from anonymous or compound tuple expressions;
    the package must be bound to an immutable variable first.

### 4.5. Scope Escape Prevention (Scope Extrusion)
Abstract path types cannot escape the lexical scope of their root variable:
```quest
let getOrigin(pkg: PointPackage) = pkg.origin;       (* REJECTED: pkg.Point escapes *)
let getOrigin(pkg: PointPackage): pkg.Point = ...;   (* REJECTED: dependent return type *)
```
- **Checking Rule (`check_no_escaping_path_types`):**
  The typechecker inspects types exiting local scopes (function return types, block results, pattern-matching branches,
  and inspect expressions). If a synthesized type contains a `QPathType` rooted at a locally bound `symbol_id`,
  typechecking aborts with:
  `TypeError: Abstract type 'pkg.Point' cannot escape the scope of 'pkg'`.
- Function return types in Quest cannot depend on value parameters (no value-dependent $\Pi$-types).

### 4.6. REPL Presentation
Following Cardelli §5.3:
- Existential packages print in the REPL with hidden representations:
  `p = tuple <Hidden>::TYPE origin=<hidden> distance=<fun> end : PointPackage`.
- Values whose static type is an abstract path type print as `<hidden>`:
  `origin = <hidden> : p.Point`.

---

## 5. Environment and Scoping (`bootstrap/python/quest/env.py`)

Compilation state is maintained across lexical scopes:
- **`Scope`:** An ordered mapping of identifiers to `Symbol` instances. Ordered scope resolution ensures that
  dependent components (e.g. `Tuple X::TYPE init:X end`) are evaluated left-to-right.
- **`Symbol`:**
  - `ValueSymbol(name, symbol_id, type_val, is_var, is_out)`: Every value symbol has a unique auto-incrementing
    integer `symbol_id` used for path-dependent root identity and scope escape tracking.
  - `TypeSymbol(name, symbol_id, kind, definition)`
  - `KindSymbol(name, symbol_id, kind)`
- **Stateless Manifest vs. Abstract Types:**
  Type transparency is controlled structurally without ambient mode flags:
  - Inside an implementing module, `definition` points to concrete `QType` (transparent).
  - Outside in client scopes, `definition` is `None` (abstract, bounded by `kind`).

---

## 6. Term Elaboration and Typechecking (`elaborate_types.py` and `typechecker.py`)

Term typechecking translates syntactic AST expressions into decorated `TypedExpr` nodes:

### 6.1. Bidirectional Discipline
- **Checking Mode ($\Gamma \vdash e \Leftarrow T$):** Pushes expected type $T$ down into expression $e$. Enables
  local inference for numeric constants, record upcasts, existential tuple packing, and function bodies.
- **Synthesis Mode ($\Gamma \vdash e \Rightarrow T$):** Infers minimal type $T$ from $e$ upward.

### 6.2. Mutability and Assignment
Mutable locations are declared with `var`:
```quest
let var x: Int := 10;
x := x + 1;
```
- In value positions, mutable locations automatically coerce to their underlying value type.
- In assignment positions (`x := e`), the target must be an explicit mutable location (`is_var=True` or `QVarType`).
- Path-dependent types cannot be rooted at mutable locations.

### 6.3. Numeric Non-Coercion
Quest disallows implicit numeric coercions: `Int` and `Real` are disjoint types. Arithmetic between differing numeric
types requires explicit conversion operations (`Real(n)`).

### 6.4. Function Signatures and Recursive Bindings (`let rec`)
- **Explicit Parameter Types:** Function parameters are syntactically signatures ($S$). In Quest, every value
  parameter in a signature must provide an explicit type annotation (`x: Int` or `: Int`); parameter types are
  not inferred from usage (Cardelli, *The Quest Language and System* §4).
- **Explicit Return Types on Recursive Functions:**
  While non-recursive functions allow omitting return types (`let f(S) = b` or `fun(S) b`) by synthesizing the
  return type from the body, **recursive functions (`let rec`) require an explicit return type annotation**
  (`let rec f(S): Ret = ...`).
- **Typing Discipline & Context:**
  Quest uses local bidirectional typechecking rather than global Hindley-Milner type inference. In a recursive
  binding, the function identifier $f$ must be introduced into the typing context $\Gamma$ before typechecking
  recursive calls within the function body:
  $$\frac{\Gamma, f: \text{All}(S) \text{Ret} \vdash \text{fun}(S): \text{Ret } b \Leftarrow \text{All}(S) \text{Ret}}
  {\Gamma \vdash \text{let rec } f(S): \text{Ret} = b}$$
  Without an explicit return type annotation, $f$'s signature cannot be formed prior to checking the body.
  Omitting return types or parameter types on recursive definitions triggers a compilation error.
- **Recursive Value Bindings:**
  Any recursive value binding without parameters (`let rec x: T = e`) similarly requires an explicit type
  annotation, and its right-hand side entity must syntactically be a constructor or abstraction (Cardelli,
  *Typeful Programming* §4.3).

---

## 7. Summary Complexity Matrix

| Complexity Area | Key Difficulty | Architectural Solution |
| :--- | :--- | :--- |
| **Recursive Subtyping** | Infinite expansion loops & polarity flips | Lazy eval + coinductive trail $\Sigma$ |
| **Dependent Signatures** | Fields depend on earlier type parameters | Ordered `Scope` incremental elaboration |
| **Extended Subsignatures** | Prefix & name matching, manifest types | Subsignature rule in `is_subtype` |
| **Existential Packing** | Witness kind checking & field substitution | Bidirectional `_check_tuple_expr` |
| **Path-Dependent Types** | Abstract identity tied to bindings | `QPathType` with `root_symbol_id` |
| **Scope Extrusion** | Local package types escaping scope | Escape checker in `typechecker.py` |
| **Type $\lambda$-Calculus** | $\beta$-reduction & variable capture | Lazy eval + `QTypeVar` symbol IDs |
| **Module Manifest Types** | Concrete inside, abstract outside | Structural `TypeSymbol(kind, definition)` |
| **Diamond Imports** | Disparate paths for same interface | Canonical symbol interning in `Environment` |
| **Contractiveness** | Non-terminating or degenerate recursion | Contractiveness validator ($C \succ X$) |

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [syntax.md](syntax.md): Lexer, parser, and untyped AST.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
- [testing.md](testing.md): Testing framework and golden outputs.
- [TheQuestLanguageAndSystem.md](TheQuestLanguageAndSystem.md): Cardelli (1990) language manual.
- [ASemanticBasisForQuest.md](ASemanticBasisForQuest.md): Cardelli & Longo (1991) formal semantics.
- [TypefulProgramming.md](TypefulProgramming.md): Cardelli (1989/1993) language specification.
- [c-representation.md](c-representation.md): C runtime representations and type erasure design.
