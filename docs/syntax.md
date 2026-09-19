# Quest Syntactic Front-End: Lexer, Parser, and AST Architecture

This document specifies the lexical syntax, parsing mechanics, and abstract syntax tree (AST) data structures for the
Quest bootstrap compiler (implementing Step 1).

---

## 1. Overview of the Syntactic Front-End

The front-end pipeline translates raw UTF-8 Quest source text into an immutable Abstract Syntax Tree:

```
  Source Text
       │
       ▼
 [ Tokenizer ]    Lexical scanning with 0-indexed character offsets
       │          Emits stream of Token objects
       ▼
 [ PEG Parser ]   Recursive descent / PEG grammar rules (quest/grammar.py)
       │          Uniform right-associativity, phrase separation
       ▼
  [ AST Tree ]    Immutable dataclasses (quest/ast.py)
                  Emits canonical 2-space indented S-expressions (ast_dump)
```

The formal EBNF grammar specification is preserved in [grammar.txt](grammar.txt).

---

## 2. Lexical Architecture (`tokens.py` and `tokenizer.py`)

### 2.1. Coordinate Tracking via Character Offsets
Rather than eagerly tracking lines and columns during scanning, every `Token` and `ASTNode` records only a 0-indexed
integer `offset` representing its absolute character offset from the beginning of the file.

When human-readable error messages are needed, `SourceMap.locate(offset)` maps offsets to 1-indexed `(line, column)`
coordinates on demand:
- **`Token(kind, lexeme, offset, value)`**: Immutable token representation.
- **`SourceMap(source_text, file_name)`**: Precomputes line boundary offsets for $O(\log N)$ binary-search coordinate
  resolution.

### 2.2. Identifiers and Keyword Rules
1. **Alphanumeric Identifiers (`IDENT`):**
   - Start with a letter, followed only by letters and digits: `[A-Za-z][A-Za-z0-9]*`.
   - Underscores are NOT part of alphanumeric identifiers. The underscore `_` is a reserved punctuation symbol.
   - Idiomatic Quest style uses camelCase (e.g. `x`, `point2D`, `addFive`, `List`), never snake_case.
   - Case-sensitive: `val`, `Val`, and `VAL` are distinct identifiers.
2. **Keywords:**
   - Reserved keywords must be written in exact casing:
      - Level 0/Value/Phrase keywords are lowercase: `let`, `var`, `out`, `fun`, `if`, `then`, `else`, `try`,
        `raise`, `not`, `extent`, `ordinal`, `of`, `for`, `while`, `loop`, `exit`, `case`, `inspect`,
        `interface`, `module`, `import`, `export`, `unsound`, `external`.
     - Level 1/2 capital keywords are capitalized: `Let`, `Rec`, `All`, `Tuple`, `Record`, `Option`, `Variant`,
       `Array`, `Var`, `Out`, `TYPE`, `POWER`, `DEF`, `ALL`.
     - Note the distinction between parameter mode `out` (lowercase) and type operator `Out` (capitalized).
3. **Symbolic Identifiers & Operators (`SYMBOLIC_INFIX`):**
   - Composed of characters from `!@#$%&*_+=-|\`:<>/?^~`.
   - Reserved symbolic punctuation includes `:=`, `::`, `<:`, `=`, `:`, `?`, `!`, `@`, `_`.
   - All non-reserved symbolic character sequences are scanned as `SYMBOLIC_INFIX` tokens (e.g. `+`, `*`, `->`, `==`).
4. **Braced Operators:**
   - Stand-alone operator values must be enclosed in braces: `{+}`, `{-}`, `{++}`, `{#}`.
   - Operators can be applied in prefix notation with argument tuples: `+(1 2)`.

### 2.3. Literals and Escape Sequences
- **Integers (`INT_LIT`):** Decimal sequences (`0`, `42`, `1000`). Negative integers are prefixed with a tilde `~`
  (e.g. `~1`, `~42`).
- **Reals (`REAL_LIT`):** Decimal floats with fractional and/or exponential parts (`3.14`, `2.0e-5`, `1.0E+3`).
  Negative reals are prefixed with a tilde `~` (e.g. `~3.14`, `~2.0e-5`).
- **Strings (`STRING_LIT`):** Delimited by double quotes `"..."`. Supports escapes `\n`, `\t`, `\"`, `\\`, and
  embedded character hex codes `\xHH`.
- **Characters (`CHAR_LIT`):** Delimited by single quotes `'a'`.

### 2.4. Nested Block Comments
Quest comments nest to arbitrary depth using `(*` and `*)`:
```quest
(* Outer comment
   (* Nested comment *)
   still inside outer comment *)
```
Unclosed block comments at EOF trigger an `Unclosed comment` diagnostic.

---

## 3. Parsing Mechanics (`grammar.py` and `parser.py`)

### 3.1. Parsing Expression Grammar (PEG) Framework
The parser is constructed using composable PEG combinators defined in `bootstrap/python/quest/parser.py`:
- `MatchToken(kind)`: Matches a single token kind.
- `Sequence(*targets)`: Evaluates elements sequentially, rolling back on failure.
- `Choice(*alternatives)`: Ordered choice with short-circuiting.
- `Repeat(target, min_count)`: Evaluates target repeatedly.
- `OptionalTarget(target)`: Matches 0 or 1 occurrences.

### 3.2. Uniform Right-Associativity & Non-Overloaded Operators
In Quest, all infix operators share uniform precedence and are strictly **right-associative**:
```quest
a + b * c    ==>   a + (b * c)
2 * x + y    ==>   2 * (x + y)
```
To enforce explicit order of operations, sub-expressions must be grouped with parentheses: `(2 * x) + y`.

Quest does not overload operators across types; distinct operators exist for different types (Cardelli §4.2):
- **Integer arithmetic:** `+`, `-`, `*`, `/`, `%` / `mod`
- **Integer relations:** `<`, `<=`, `>`, `>=`
- **Real arithmetic:** `++`, `--`, `**`, `//`, `^^`
- **Real relations:** `<<`, `<<=`, `>>`, `>>=`
- **String concatenation:** `<>`
- **Boolean logic:** `/\` (and), `\/` (or)
- **Identity / Equality:** `is`, `isnot`

### 3.3. Monadic Operators
The monadic operators `not`, `extent`, and `ordinal` are keyword operators that bind tighter than dyadic infix
operators:
- `not b`: Boolean negation.
- `extent a`: Array length (number of elements).
- `ordinal opt`: Zero-based tag index of an option value.

### 3.4. Actual Parameter Bindings & Call Syntax
Function applications evaluate space-separated phrases inside argument lists `f(...)`:
- **Value arguments:** `f(x)`
- **Explicit type arguments:** `f(:Int x)` or `id(:Int)(42)`
- **Out reference coercion (`@`):** `@x` or `@r.field` passes the underlying mutable location.
- **On-the-fly out allocation (`var`):** `var(0)` creates a mutable cell on the fly.

### 3.5. Listfix Postfix Syntax
Quest supports listfix syntax for functions consuming array arguments:
- `f of a1 ... an end` desugars to `f(array a1 ... an end)`
- `f of(count init)` desugars to `f(array of(count init))`
- Explicit element type: `array of :Int 1 2 3 end` records the target element type.
- List aggregates similarly use listfix syntax with the `list` constructor (`list of 1 2 3 end`, `list of end`).

### 3.6. Curried Signatures & Anonymous Tuple Fields
- **Curried Signatures:** Functions and function types support multiple parameter lists:
  `fun(x: Int)(y: Int): Int x + y` and `Fun(x: Int)(y: Int): Int`.
- **Anonymous Fields:** Tuple types and signatures allow anonymous fields:
  `Tuple :Int :Real end` or `Tuple x:Int :Var(Real) :Out(String) end`.

### 3.7. Option Construction and Extraction Syntax
Option types support both tag-based and ordinal-based operations (Cardelli §4.5):
- **Tag Construction:** `option tag of Type [with Binding] end`
- **Ordinal Construction:** `option ordinal(expr) of Type [with Binding] end`
  Allowed when all branches of the target option type share the same signature.
- **Tag Testing:** `opt?tag` returns `true` if `opt` carries tag `tag`, `false` otherwise.
- **Payload Extraction:** `opt!tag` extracts the payload as a tuple whose first component is the 0-based integer
  ordinal of the option (e.g. `tuple 1 let x=true end : Tuple :Int x:Bool end`).

### 3.8. External Types and Value Bindings
Quest provides `external` syntax for declaring opaque native C data structures and native C symbols:
- **External Types (`PRIMARY_TYPE`):** `type T = external "C_TYPE"` or `Let T = external "C_TYPE"`.
  Binds `T` to an opaque C data type (e.g. `external "QWriter *"`).
- **External Values (`PRIMARY_VALUE`):** `let x: Type = external "C_SYMBOL"`.
  Binds `x` to a C runtime symbol or constant (e.g. `let stdout: Handle = external "quest_writer_output"`).

### 3.9. Initial/Final Keyword Block Disambiguation
Complex expressions (conditionals, loops, records, tuples, options) employ explicit terminating keywords:
- `if ... then ... else ... end`
- `while ... do ... end`
- `try ... when ... else ... end`
- `record ... end`, `tuple ... end`, `option ... end`

This eliminates dangling-else ambiguities and allows whitespace to be freely used for aesthetic formatting.

---

## 4. Abstract Syntax Tree (AST) Hierarchy (`ast.py`)

All AST nodes are defined using Python immutable frozen dataclasses (`@dataclass(frozen=True)`), deriving from the base
class `ASTNode(offset: int)`:

```
ASTNode
  ├── Phrase                  (Top-level statements & declarations)
  │     ├── LetValueBinding   (let [var] [rec] x [: T] = e)
  │     ├── LetTypeBinding    (Let [Rec] T [:: K] = Type)
  │     ├── DefKindBinding    (DEF K = Kind)
  │     ├── InterfaceDecl     (interface I [import ...] export ... end)
  │     ├── ModuleDecl        (module M : I [import ...] export ... end)
  │     ├── ImportDecl        (import M1, M2 : I)
  │     └── TopExpr           (Expression evaluated at top level)
  ├── Expr                    (Level 0 term expressions)
  │     ├── ExprInt, ExprReal, ExprString, ExprChar, ExprBool
  │     ├── ExprIdent         (Variable lookup)
  │     ├── ExprFun           (fun(params) body)
  │     ├── ExprApp           (Function / operator call)
  │     ├── ExprIf, ExprWhile, ExprLoop, ExprTry, ExprRaise
  │     ├── ExprRecord        (record x = 1, y = 2 end)
  │     ├── ExprTuple         (tuple 1, 2, 3 end)
  │     ├── ExprArray         (array of [:T] a1 ... an end)
  │     ├── ExprArrayRep      (array of(n init))
  │     ├── ExprOption        (option (tag | ordinal(n)) of T [with Binding] end)
  │     ├── ExprVariant       (variant tag of T [with Value] end)
  │     ├── ExprVariantCheck  (target?tag)
  │     ├── ExprVariantAssert (target!tag)
  │     ├── ExprCase          (case target when ... else ... end)
  │     ├── ExprDerefCell     (@target)
  │     └── ExprVarCell       (var(e))
  ├── Type                    (Level 1 types and type operators)
  │     ├── TypePath          (Named type or projection: Int, M.T)
  │     ├── TypeTuple         (Tuple x:Int, y:Real end)
  │     ├── TypeRecord        (Record x:Int, y:Real end)
  │     ├── TypeOption        (Option red, green with v:Int end)
  │     ├── TypeAll           (All(X <: B) T)
  │     ├── TypeFun           (Fun(X::K) T)
  │     └── TypeRec           (Rec(X <: B) T)
  └── Kind                    (Level 2 kinds)
        ├── KindType          (TYPE)
        ├── KindPower         (POWER(T))
        └── KindAll           (ALL(X::K1) K2)
```

### 4.1. Canonical S-Expression Serialization (`ast_dump`)
The parser outputs deterministic S-expressions formatted with **2 spaces of indentation per nesting level**:

```lisp
(Program
  :phrases (
    (LetValueBinding
      :name 'x'
      :type_annot (TypePath 'Int')
      :value (ExprInt 10 '10')
    )
  )
)
```

---

## See Also
- [README.md](../README.md): Project overview and quickstart.
- [grammar.txt](grammar.txt): Canonical EBNF grammar.
- [type-system.md](type-system.md): Type system, kinds, and term elaboration.
- [pipeline.md](pipeline.md): Compiler pipeline framework and CLI driver.
- [testing.md](testing.md): Testing framework and golden outputs.
