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
   - Start with a letter, followed by letters, digits, and underscores (e.g. `x`, `point_2d`, `List`).
   - Case-sensitive: `val`, `Val`, and `VAL` are distinct identifiers.
2. **Keywords:**
   - Reserved keywords must be written in exact casing:
     - Level 0/Value keywords are lowercase: `let`, `var`, `fun`, `if`, `then`, `else`, `try`, `raise`.
     - Level 1/2 capital keywords are capitalized: `Let`, `Rec`, `All`, `Tuple`, `Record`, `TYPE`, `POWER`.
3. **Symbolic Identifiers & Operators (`SYMBOLIC_INFIX`):**
   - Composed of characters from `!@#$%&*_+=-|\`:<>/?^~`.
   - Reserved symbolic punctuation includes `:=`, `::`, `<:`, `=`, `:`, `?`, `!`, `@`, `_`.
   - All non-reserved symbolic character sequences are scanned as `SYMBOLIC_INFIX` tokens (e.g. `+`, `*`, `->`, `==`).

### 2.3. Literals and Escape Sequences
- **Integers (`INT_LIT`):** Decimal sequences (`0`, `42`, `1000`).
- **Reals (`REAL_LIT`):** Decimal floats with fractional and/or exponential parts (`3.14`, `2.0e-5`, `1.0E+3`).
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

### 3.2. Uniform Right-Associativity
In Quest, all infix operators share uniform precedence and are strictly **right-associative**:
```quest
a + b * c    ==>   a + (b * c)
2 * x + y    ==>   2 * (x + y)
```
To enforce explicit order of operations, sub-expressions must be grouped with parentheses: `(2 * x) + y`.

### 3.3. Initial/Final Keyword Block Disambiguation
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
  ├── Phrase                  (Top-level statements & bindings)
  │     ├── LetValueBinding   (let [var] [rec] x [: T] = e)
  │     ├── LetTypeBinding    (Let [Rec] T [:: K] = Type)
  │     ├── DefKindBinding    (DEF K = Kind)
  │     ├── TopExpr           (Expression evaluated at top level)
  │     └── ImportDecl        (import M1, M2)
  ├── Expr                    (Level 0 term expressions)
  │     ├── ExprInt, ExprReal, ExprString, ExprChar, ExprBool
  │     ├── ExprIdent         (Variable lookup)
  │     ├── ExprFun           (fun(params) body)
  │     ├── ExprApp           (Function / operator call)
  │     ├── ExprIf, ExprWhile, ExprLoop, ExprTry, ExprRaise
  │     ├── ExprRecord        (record x = 1, y = 2 end)
  │     └── ExprTuple         (tuple 1, 2, 3 end)
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
