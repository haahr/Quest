# Quest Type System: Semantics, Subtyping, and Term Elaboration

This document specifies the higher-order type system (System $F_{<:}^\omega$), semantic type representations,
subtyping algorithms, recursive contractiveness rules, and bidirectional term typechecking for the Quest compiler.

---

## 1. Overview and Design Philosophy

Quest implements a higher-order type system with bounded quantification and structural subtyping:
- **Level 2 (Kinds):** Classify types. `TYPE` classifies proper types; `POWER(B)` classifies subtypes of $B$;
  `ALL(X::K1) K2` classifies type operators.
- **Level 1 (Types and Type Operators):** Semantic types (`QType`) representing values, tuples, records, variants,
  options, and functions. Compile-time type functions (`Fun(X::K) T`) evaluate via typed $\lambda$-calculus reduction.
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
  ├── Variables & Constants   QTypeVar, QAbstractType
  └── Metavariables           QTypeMeta (local bidirectional inference)
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

## 4. Environment and Scoping (`bootstrap/python/quest/env.py`)

Compilation state is maintained across lexical scopes:
- **`Scope`:** An ordered mapping of identifiers to `Symbol` instances. Ordered scope resolution ensures that
  dependent components (e.g. `Tuple X::TYPE init:X end`) are evaluated left-to-right.
- **`Symbol`:**
  - `ValueSymbol(name, symbol_id, type_val, is_var, is_out)`
  - `TypeSymbol(name, symbol_id, kind, definition)`
  - `KindSymbol(name, symbol_id, kind)`
- **Stateless Manifest vs. Abstract Types:**
  Type transparency is controlled structurally without ambient mode flags:
  - Inside an implementing module, `definition` points to concrete `QType` (transparent).
  - Outside in client scopes, `definition` is `None` (abstract, bounded by `kind`).

---

## 5. Term Elaboration and Typechecking (`elaborate_types.py` and `typechecker.py`)

Term typechecking translates syntactic AST expressions into decorated `TypedExpr` nodes:

### 5.1. Bidirectional Discipline
- **Checking Mode ($\Gamma \vdash e \Leftarrow T$):** Pushes expected type $T$ down into expression $e$. Enables
  local inference for numeric constants, record upcasts, and function bodies.
- **Synthesis Mode ($\Gamma \vdash e \Rightarrow T$):** Infers minimal type $T$ from $e$ upward.

### 5.2. Mutability and Assignment
Mutable locations are declared with `var`:
```quest
let var x: Int := 10;
x := x + 1;
```
- In value positions, mutable locations automatically coerce to their underlying value type.
- In assignment positions (`x := e`), the target must be an explicit mutable location (`is_var=True` or `QVarType`).

### 5.3. Numeric Non-Coercion
Quest disallows implicit numeric coercions: `Int` and `Real` are disjoint types. Arithmetic between differing numeric
types requires explicit conversion operations (`Real(n)`).

### 5.4. Function Signatures and Recursive Bindings (`let rec`)
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

## 6. Summary Complexity Matrix

| Complexity Area | Key Difficulty | Architectural Solution |
| :--- | :--- | :--- |
| **Recursive Subtyping** | Infinite expansion loops & polarity flips | Lazy eval + coinductive trail $\Sigma$ |
| **Dependent Signatures** | Fields depend on earlier type parameters | Ordered `Scope` incremental elaboration |
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
- [ASemanticBasisForQuest.md](ASemanticBasisForQuest.md): Cardelli & Longo (1991) formal semantics.
- [TypefulProgramming.md](TypefulProgramming.md): Cardelli (1989/1993) language specification.
