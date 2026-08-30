# Quest Front-End Design Document

This document specifies the architecture, data structures, and APIs for the **Quest Front-End** (Step 1 of the Quest implementation plan), encompassing the Tokenizer, Source Position Mapping, Diagnostic Formatting, Parser, and Abstract Syntax Tree (AST).

---

## 1. Overview and Design Principles

The front-end is responsible for converting raw Quest source text (`.quest`) into an immutable, strongly-typed Abstract Syntax Tree (AST). In accordance with the project plan:

- **Mostly-Functional Style:** The Python bootstrap implementation (in `bootstrap/python/quest/`) uses pure functions, immutable data structures (`@dataclass(frozen=True)`), and pattern matching (`match ... case`) to facilitate a direct subsequent port to Quest (in `src/`).
- **Dedicated AST Namespace:** All AST nodes live in a dedicated module (`quest.ast`) to prevent name collisions with standard Python built-ins or compiler passes.
- **Zero External Dependencies:** Built entirely with standard library facilities to ensure immediate portability.
- **Precision Diagnostics:** Retains full source fidelity with character-offset tracking, enabling formatted error messages with line numbers, column numbers, and underlined source context.
- **Canonical S-Expression Serialization:** Provides an `ast_dump()` utility emitting deterministic, 2-space indented S-expressions for golden test verification (`tests/golden/parse/<name>.out`).
- **Dual Execution Modes:** Supports batch compilation (strings and files) and incremental streaming for the interactive REPL.

---

## 2. Tokenizer (Lexical Analyzer)

### 2.1. Source Position and Offset Tracking

To keep token and AST representations lightweight and avoid per-token line-counting overhead:

1. **Offset-Only Tokens:** Each token records only its 0-indexed starting character offset (`offset: int`) from the beginning of the input string.
2. **Computed Token Bounds:** The token's end offset is computed on demand as `offset + len(lexeme)`.
3. **In-Memory Source Text:** The compiler retains the entire input string in memory. A utility function maps any character offset to its 1-indexed `(line, column)` coordinates on demand when formatting diagnostic messages.

#### Diagnostic Formatter / Source Map API
```python
@dataclass(frozen=True)
class SourceLocation:
    """A human-readable source position computed from an offset."""
    file_name: str
    offset: int
    line: int        # 1-indexed
    column: int      # 1-indexed

class SourceMap:
    """Maintains source text and computes line/column coordinates from offsets."""
    def __init__(self, source_text: str, file_name: str = "<string>"):
        self.source_text = source_text
        self.file_name = file_name
        # Precompute line start offsets for fast binary search
        self.line_starts: list[int] = [0]
        for idx, ch in enumerate(source_text):
            if ch == "\n":
                self.line_starts.append(idx + 1)

    def locate(self, offset: int) -> SourceLocation:
        """Maps a 0-indexed character offset to (line, column)."""
        import bisect
        offset = max(0, min(offset, len(self.source_text)))
        line_idx = bisect.bisect_right(self.line_starts, offset) - 1
        line = line_idx + 1
        col = offset - self.line_starts[line_idx] + 1
        return SourceLocation(self.file_name, offset, line, col)

    def format_error(self, offset: int, length: int, message: str) -> str:
        """Renders a diagnostic message with underlined source context."""
        loc = self.locate(offset)
        header = f"{loc.file_name}:{loc.line}:{loc.column}: error: {message}"
        lines = self.source_text.splitlines()
        if 1 <= loc.line <= len(lines):
            source_line = lines[loc.line - 1]
            caret_pad = " " * (loc.column - 1)
            underline = "^" * max(1, length)
            return f"{header}\n    {source_line}\n    {caret_pad}{underline}"
        return header
```

---

### 2.2. Token Kinds (`TokenKind`)

Quest tokens are classified into literals, identifiers, symbolic operators, punctuation/delimiters, and case-sensitive keywords:

```python
from enum import Enum, auto

class TokenKind(Enum):
    # --- Literals ---
    INT_LIT = auto()        # e.g. 0, 42, 1000 (strictly unsigned digits)
    REAL_LIT = auto()       # e.g. 3.14, 2.0e-5, 1.0E+3 (strictly unsigned digits + dot + digits)
    CHAR_LIT = auto()       # e.g. 'a', '\n', '\\'
    STRING_LIT = auto()     # e.g. "hello world", "escaped \" quotes"
    
    # --- Identifiers and Symbolic Operators ---
    IDENT = auto()          # Alphanumeric: [A-Za-z][A-Za-z0-9_]*
    SYMBOLIC_INFIX = auto() # Custom symbolic operator: ++, --, **, <>, +, -, *, /, etc.
    
    # --- Delimiters & Punctuation ---
    LPAREN = auto()         # (
    RPAREN = auto()         # )
    LBRACKET = auto()       # [
    RBRACKET = auto()       # ]
    LBRACE = auto()         # {
    RBRACE = auto()         # }
    COMMA = auto()          # ,
    SEMICOLON = auto()      # ;
    DOT = auto()            # .
    COLON = auto()          # :
    COLON_COLON = auto()    # ::
    SUBTYPE = auto()        # <:
    ASSIGN = auto()         # :=
    EQUAL = auto()          # =
    QUESTION = auto()       # ?
    BANG = auto()           # !
    AT = auto()             # @
    UNDERSCORE = auto()     # _
    
    # --- Kind-Level Keywords (ALL CAPS) ---
    KW_TYPE = auto()        # TYPE
    KW_POWER = auto()       # POWER
    KW_ALL_KIND = auto()    # ALL
    KW_DEF_KIND = auto()    # DEF
    
    # --- Type-Level Keywords (Initial Capital) ---
    KW_ALL = auto()         # All
    KW_ARRAY_TYPE = auto()  # Array
    KW_AUTO_TYPE = auto()   # Auto
    KW_DEF = auto()         # Def
    KW_EXCEPTION_TYPE = auto() # Exception
    KW_FUN_TYPE = auto()    # Fun
    KW_LET_TYPE = auto()    # Let
    KW_OPTION_TYPE = auto() # Option
    KW_OUT = auto()         # Out
    KW_REC_TYPE = auto()    # Rec
    KW_RECORD_TYPE = auto() # Record
    KW_TUPLE_TYPE = auto()  # Tuple
    KW_VAR_TYPE = auto()    # Var
    KW_VARIANT_TYPE = auto()# Variant
    
    # --- Value-Level Keywords (Lowercase) ---
    KW_AND = auto()         # and
    KW_ANDIF = auto()       # andif
    KW_ARRAY = auto()       # array
    KW_AS = auto()          # as
    KW_AUTO = auto()        # auto
    KW_BEGIN = auto()       # begin
    KW_CASE = auto()        # case
    KW_DO = auto()          # do
    KW_DOWNTO = auto()      # downto
    KW_ELSE = auto()        # else
    KW_ELSIF = auto()       # elsif
    KW_END = auto()         # end
    KW_EXCEPTION = auto()   # exception
    KW_EXIT = auto()        # exit
    KW_EXPORT = auto()      # export
    KW_FALSE = auto()       # false
    KW_FOR = auto()         # for
    KW_FUN = auto()         # fun
    KW_IF = auto()          # if
    KW_IMPORT = auto()      # import
    KW_INSPECT = auto()     # inspect
    KW_INTERFACE = auto()   # interface
    KW_IS = auto()          # is
    KW_ISNOT = auto()       # isnot
    KW_LET = auto()         # let
    KW_LOOP = auto()        # loop
    KW_MODULE = auto()      # module
    KW_OF = auto()          # of
    KW_OK = auto()          # ok
    KW_OPTION = auto()      # option
    KW_ORIF = auto()        # orif
    KW_RAISE = auto()       # raise
    KW_REC = auto()         # rec
    KW_RECORD = auto()      # record
    KW_THEN = auto()        # then
    KW_TRUE = auto()        # true
    KW_TRY = auto()         # try
    KW_TUPLE = auto()       # tuple
    KW_UNSOUND = auto()     # unsound
    KW_UPTO = auto()        # upto
    KW_VAR = auto()         # var
    KW_VARIANT = auto()     # variant
    KW_WHEN = auto()        # when
    KW_WHILE = auto()       # while
    KW_WITH = auto()        # with
    
    # --- End of Stream ---
    EOF = auto()
```

---

### 2.3. Token Data Structure

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Token:
    kind: TokenKind
    lexeme: str
    value: Any        # int, float, str, bool, or None
    offset: int       # 0-indexed character offset from input start

    @property
    def length(self) -> int:
        return len(self.lexeme)

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.lexeme)
```

---

### 2.4. Lexical Disambiguation and Tokenization Rules

1. **Unsigned Numeric Literals (No Leading Signs):**  
   `INT_LIT` and `REAL_LIT` are strictly unsigned sequences of decimal digits (e.g. `0`, `42`, `3.14`). The tokenizer **never** consumes a leading `+` or `-` as part of a numeric literal. Signs (`+`, `-`) are always emitted as `SYMBOLIC_INFIX` tokens, allowing the parser to resolve them as unary negation or binary subtraction without breaking infix expressions like `x-5`.

2. **Real Literal vs. Integer Projection (`.`):**  
   - If a sequence of digits is followed by `.` **and the character immediately following the `.` is a decimal digit** (`0..9`), it is consumed as a `REAL_LIT` (e.g. `2.0`, `3.14159`, `2.0e10`).
   - If a sequence of digits is followed by `.` and a **non-digit** character (e.g. `t.1`, `r.x`), the digits are emitted as `INT_LIT` (or `IDENT`), and the `.` is emitted separately as `DOT`.
   - Real numbers require at least one digit after the decimal point (`2.0`, not `2.`).

3. **Symbolic Operator Characters vs. String/Char Quotes:**  
   The set of characters that can form symbolic operators is:
   ```
   ! @ # $ % & * + - = | \ ` : < > / ? ^ ~
   ```
   Single quotes `'` (reserved for `CHAR_LIT`) and double quotes `"` (reserved for `STRING_LIT`) are **strictly excluded** from symbolic operator lexemes.
   
   **Maximal Munch & Punctuation Lookup:**  
   The tokenizer greedily accumulates the longest contiguous sequence of symbolic characters. It then checks this sequence against reserved punctuation tokens:
   - `:=` $\to$ `ASSIGN`
   - `::` $\to$ `COLON_COLON`
   - `<:` $\to$ `SUBTYPE`
   - `=`  $\to$ `EQUAL`
   - `:`  $\to$ `COLON`
   - `?`  $\to$ `QUESTION`
   - `!`  $\to$ `BANG`
   - `@`  $\to$ `AT`
   
   If the sequence matches a reserved punctuation token, that token is emitted. Otherwise, the full sequence is emitted as `SYMBOLIC_INFIX` (e.g. `+`, `-`, `*`, `/`, `<>`, `<=`, `>=`, `++`, `**`, `/\`, `\/`, `<::`).

4. **Comments vs. Parenthesized Operators (`(*` vs. `(`):**  
   - When the tokenizer encounters `(`, it performs a 1-character lookahead. If the next character is `*`, it immediately opens a comment (`comment_depth += 1`) and consumes characters until the matching `*)` returns `comment_depth` to 0.
   - If an expression contains `(*)`, the tokenizer interprets `(*` as the start of a comment. To parenthesize a lone `*` operator, whitespace or braces must be used: `( * )` or `{ * }`.

5. **Case-Sensitive Keyword Resolution:**  
   Alphanumeric identifiers are scanned with `[A-Za-z][A-Za-z0-9_]*`. The resulting string is looked up in a case-sensitive keyword dictionary. If found, the corresponding `KW_*` token is emitted; otherwise, `IDENT` is emitted.

6. **Escape Sequences:**  
   Both character literals (`'...'`) and string literals (`"..."`) support:
   - Standard escapes: `\n`, `\t`, `\r`, `\b`, `\f`, `\\`, `\'`, `\"`.
   - 3-digit decimal character codes: `\ddd` (e.g. `\065` $\to$ `'A'`).
   - Hexadecimal character codes: `\xhh` (e.g. `\x41` $\to$ `'A'`).

---

### 2.5. Tokenizer API

```python
class TokenizerError(Exception):
    """Raised on lexical errors (unterminated literal, invalid character, etc.)."""
    def __init__(self, message: str, offset: int, length: int = 1):
        super().__init__(message)
        self.offset = offset
        self.length = length

class IncompleteInputError(TokenizerError):
    """Raised by InteractiveTokenizer when input ends inside an unclosed comment or string literal."""
    pass

class Tokenizer:
    """Batch tokenizer for strings and files."""
    def __init__(self, source_text: str, file_name: str = "<string>"):
        self.source_text = source_text
        self.file_name = file_name
        self.cursor = 0
        self.source_map = SourceMap(source_text, file_name)

    @classmethod
    def from_str(cls, text: str, file_name: str = "<string>") -> "Tokenizer":
        return cls(text, file_name)

    @classmethod
    def from_file(cls, path: str) -> "Tokenizer":
        with open(path, "r", encoding="utf-8") as f:
            return cls(f.read(), path)

    def next_token(self) -> Token:
        """Returns the next Token from the input stream, returning EOF at the end."""
        ...

    def tokenize_all(self) -> list[Token]:
        """Eagerly consumes and returns all tokens up to and including EOF."""
        ...
```

---

## 3. Parser Architecture (Planned)

*(To be specified: recursive descent / Pratt parser handling Quest's uniform right-associative infix precedence, listfix syntax, and top-level phrase sequencing).*

---

## 4. Abstract Syntax Tree (AST) Specification (`quest.ast`)

To avoid name collisions with Python built-ins (e.g. `type`, `tuple`, `eval`) or compiler pass symbols, all AST nodes reside in the dedicated namespace **`quest.ast`** (`bootstrap/python/quest/ast.py`).

### 4.1. Base Node and Parameter Structures

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Union

@dataclass(frozen=True)
class ASTNode:
    """Base class for all AST nodes."""
    offset: int

class ParamMode(Enum):
    VALUE = auto()
    VAR = auto()
    OUT = auto()

@dataclass(frozen=True)
class FormalParam(ASTNode):
    """Value-level function parameter: [var | out] x : T"""
    name: str
    type_annot: Optional[Type]
    mode: ParamMode
    offset: int

@dataclass(frozen=True)
class TypeFormal(ASTNode):
    """Type-level parameter: X <: B or X :: K"""
    name: str
    bound: Kind
    offset: int

@dataclass(frozen=True)
class Quantifier(ASTNode):
    """Universal/existential quantifier: X <: B or X :: K"""
    name: str
    bound: Kind
    offset: int
```

---

### 4.2. Level 2: Kinds (`Kind`)

```python
@dataclass(frozen=True)
class Kind(ASTNode):
    """Base class for Level 2 kind terms."""
    pass

@dataclass(frozen=True)
class KindType(Kind):
    """TYPE — the base kind of all ground types."""
    offset: int

@dataclass(frozen=True)
class KindPower(Kind):
    """POWER(T) — the kind of all subtypes of type T."""
    bound: Type
    offset: int

@dataclass(frozen=True)
class KindAll(Kind):
    """ALL(X::K) K' — operator kind universal quantifier."""
    param_name: str
    param_kind: Kind
    body_kind: Kind
    offset: int

@dataclass(frozen=True)
class KindId(Kind):
    """User-defined or aliased kind identifier."""
    name: str
    offset: int

@dataclass(frozen=True)
class KindManifest(Kind):
    """Interface manifest kind path, e.g. I_K."""
    interface_name: str
    kind_name: str
    offset: int
```

---

### 4.3. Level 1: Types and Type Operators (`Type`)

```python
@dataclass(frozen=True)
class Type(ASTNode):
    """Base class for Level 1 type terms and type operators."""
    pass

@dataclass(frozen=True)
class TypePath(Type):
    """Named type or dot-projection path: e.g. 'Int', 'Point', 'Mod.T'."""
    path: tuple[str, ...]
    offset: int

@dataclass(frozen=True)
class TypeAll(Type):
    """All(X <: B, Y :: K) T — universal type quantifier."""
    quantifiers: tuple[Quantifier, ...]
    result_type: Type
    offset: int

@dataclass(frozen=True)
class FieldSig(ASTNode):
    """Field in a tuple or auto signature: [var | out] x : T"""
    name: str
    type_sig: Type
    mode: ParamMode
    offset: int

@dataclass(frozen=True)
class TypeTuple(Type):
    """Tuple x:Int, y:Real end — ordered dependent tuple signature."""
    fields: tuple[FieldSig, ...]
    offset: int

@dataclass(frozen=True)
class RecordFieldSig(ASTNode):
    """Field in a record signature: [var] x : T"""
    name: str
    type_sig: Type
    is_var: bool
    offset: int

@dataclass(frozen=True)
class TypeRecord(Type):
    """Record x:Int, y:Real end — unordered record type."""
    fields: tuple[RecordFieldSig, ...]
    offset: int

@dataclass(frozen=True)
class OptionFieldSig(ASTNode):
    """Variant in an option signature: tag [with fields...]"""
    tag: str
    payload_sig: tuple[FieldSig, ...]
    offset: int

@dataclass(frozen=True)
class TypeOption(Type):
    """Option red, green, blue with val:Int end — tagged union / option type."""
    variants: tuple[OptionFieldSig, ...]
    offset: int

@dataclass(frozen=True)
class VariantFieldSig(ASTNode):
    """Field in a variant signature: [var] tag : T"""
    tag: str
    type_sig: Type
    is_var: bool
    offset: int

@dataclass(frozen=True)
class TypeVariant(Type):
    """Variant ok:Int, err:String end — unordered variant type."""
    fields: tuple[VariantFieldSig, ...]
    offset: int

@dataclass(frozen=True)
class TypeAuto(Type):
    """Auto X::K with x:T end — existential / automorphic dynamic type."""
    type_param: Optional[str]
    kind_bound: Kind
    signature: tuple[FieldSig, ...]
    offset: int

@dataclass(frozen=True)
class TypeFun(Type):
    """Fun(X::K, Y<:B) T — higher-order compile-time type operator."""
    params: tuple[TypeFormal, ...]
    result_kind: Optional[Kind]
    body: Type
    offset: int

@dataclass(frozen=True)
class TypeRec(Type):
    """Rec(X <: B) T — recursive type constructor."""
    var_name: str
    bound: Kind
    body: Type
    offset: int

@dataclass(frozen=True)
class TypeApp(Type):
    """T(A, B) — type operator application."""
    constructor: Type
    arguments: tuple[Type, ...]
    offset: int

@dataclass(frozen=True)
class TypeInfix(Type):
    """T -> U, T /\ U — infix type operator."""
    left: Type
    op: str
    right: Type
    offset: int

@dataclass(frozen=True)
class TypeArray(Type):
    """Array(T) — built-in array type."""
    element_type: Type
    offset: int

@dataclass(frozen=True)
class TypeVar(Type):
    """Var(T) — mutable reference cell type."""
    element_type: Type
    offset: int

@dataclass(frozen=True)
class TypeOut(Type):
    """Out(T) — contravariant output parameter mode."""
    element_type: Type
    offset: int

@dataclass(frozen=True)
class TypeManifest(Type):
    """M_T — manifest type extraction across interfaces."""
    module_name: str
    type_name: str
    offset: int
```

---

### 4.4. Level 0: Values and Expressions (`Expr`)

```python
@dataclass(frozen=True)
class Expr(ASTNode):
    """Base class for Level 0 value expressions."""
    pass

# --- Literals ---
@dataclass(frozen=True)
class ExprInt(Expr):
    value: int
    lexeme: str
    offset: int

@dataclass(frozen=True)
class ExprReal(Expr):
    value: float
    lexeme: str
    offset: int

@dataclass(frozen=True)
class ExprChar(Expr):
    value: str
    lexeme: str
    offset: int

@dataclass(frozen=True)
class ExprString(Expr):
    value: str
    lexeme: str
    offset: int

@dataclass(frozen=True)
class ExprBool(Expr):
    value: bool
    offset: int

@dataclass(frozen=True)
class ExprOk(Expr):
    offset: int

@dataclass(frozen=True)
class ExprId(Expr):
    name: str
    offset: int

# --- Blocks & Control Flow ---
@dataclass(frozen=True)
class ExprBlock(Expr):
    """begin ... end — sequence of bindings and statements."""
    bindings: tuple[BindingNode, ...]
    offset: int

@dataclass(frozen=True)
class ExprIf(Expr):
    """if cond then e1 elsif cond2 then e2 else e3 end"""
    cond: Expr
    then_branch: Expr
    elsifs: tuple[tuple[Expr, Expr], ...]   # tuple of (cond, body)
    else_branch: Optional[Expr]
    offset: int

@dataclass(frozen=True)
class ExprWhile(Expr):
    cond: Expr
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprLoop(Expr):
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprExit(Expr):
    offset: int

@dataclass(frozen=True)
class ExprFor(Expr):
    var_name: str
    start: Expr
    is_downto: bool
    stop: Expr
    body: Expr
    offset: int

# --- Functions & Applications ---
@dataclass(frozen=True)
class ExprFun(Expr):
    """fun(x: Int): Int x + 1"""
    params: tuple[FormalParam, ...]
    return_type: Optional[Type]
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprApp(Expr):
    """f(a, b)"""
    func: Expr
    args: tuple[Expr, ...]
    offset: int

@dataclass(frozen=True)
class ExprInfix(Expr):
    """a + b, a := b, a andif b, a orif b, a is b"""
    left: Expr
    op: str
    right: Expr
    offset: int

# --- Aggregates & Constructors ---
@dataclass(frozen=True)
class TupleBinding(ASTNode):
    name: Optional[str]
    value: Expr
    offset: int

@dataclass(frozen=True)
class ExprTuple(Expr):
    fields: tuple[TupleBinding, ...]
    offset: int

@dataclass(frozen=True)
class RecordBinding(ASTNode):
    name: str
    value: Expr
    is_var: bool
    offset: int

@dataclass(frozen=True)
class ExprRecord(Expr):
    fields: tuple[RecordBinding, ...]
    offset: int

@dataclass(frozen=True)
class ExprOption(Expr):
    tag: str
    option_type: Type
    payload: Optional[Expr]
    offset: int

@dataclass(frozen=True)
class ExprVariant(Expr):
    tag: str
    variant_type: Type
    is_var: bool
    payload: Optional[Expr]
    offset: int

@dataclass(frozen=True)
class ExprArray(Expr):
    elements: tuple[Expr, ...]
    offset: int

@dataclass(frozen=True)
class ExprArrayRep(Expr):
    count: Expr
    init_val: Expr
    offset: int

@dataclass(frozen=True)
class ExprAuto(Expr):
    witness: Optional[tuple[str, Optional[Kind], Expr]]
    target_type: Type
    payload: Expr
    offset: int

# --- Selection, Indexing, and References ---
@dataclass(frozen=True)
class ExprSelect(Expr):
    target: Expr
    field: str
    offset: int

@dataclass(frozen=True)
class ExprIndex(Expr):
    target: Expr
    index: Expr
    offset: int

@dataclass(frozen=True)
class ExprIndexAssign(Expr):
    target: Expr
    index: Expr
    value: Expr
    offset: int

@dataclass(frozen=True)
class ExprVarCell(Expr):
    value: Expr
    offset: int

@dataclass(frozen=True)
class ExprDerefCell(Expr):
    target: Expr
    offset: int

@dataclass(frozen=True)
class ExprVariantCheck(Expr):
    target: Expr
    tag: str
    offset: int

@dataclass(frozen=True)
class ExprVariantAssert(Expr):
    target: Expr
    tag: str
    offset: int

# --- Pattern Matching & Discrimination ---
@dataclass(frozen=True)
class CaseBranch(ASTNode):
    tags: tuple[str, ...]
    binder: Optional[str]
    binder_type: Optional[Type]
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprCase(Expr):
    target: Expr
    branches: tuple[CaseBranch, ...]
    else_branch: Optional[Expr]
    offset: int

@dataclass(frozen=True)
class InspectBranch(ASTNode):
    match_type: Type
    binders: tuple[tuple[str, Optional[Type]], ...]
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprInspect(Expr):
    target: Expr
    branches: tuple[InspectBranch, ...]
    else_branch: Optional[Expr]
    offset: int

# --- Exceptions ---
@dataclass(frozen=True)
class ExprRaise(Expr):
    exc: Expr
    payload: Optional[Expr]
    as_type: Optional[Type]
    offset: int

@dataclass(frozen=True)
class TryBranch(ASTNode):
    exc_pattern: Expr
    binder: Optional[str]
    binder_type: Optional[Type]
    body: Expr
    offset: int

@dataclass(frozen=True)
class ExprTry(Expr):
    body: Expr
    branches: tuple[TryBranch, ...]
    else_branch: Optional[Expr]
    offset: int
```

---

### 4.5. Bindings, Declarations, and Programs

```python
@dataclass(frozen=True)
class BindingNode(ASTNode):
    """Base class for declarations and statements inside blocks/phrases."""
    pass

@dataclass(frozen=True)
class LetValueBinding(BindingNode):
    """let [rec] [var] x (params...) : T = expr and y = ..."""
    is_rec: bool
    is_var: bool
    name: str
    params: tuple[FormalParam, ...]
    type_annot: Optional[Type]
    value: Expr
    offset: int

@dataclass(frozen=True)
class LetTypeBinding(BindingNode):
    """Let [Rec] T(X::K)::K' = Type and U = ..."""
    is_rec: bool
    name: str
    params: tuple[TypeFormal, ...]
    bound: Optional[Kind]
    type_val: Type
    offset: int

@dataclass(frozen=True)
class DefTypeBinding(BindingNode):
    """Def [Rec] T = Type (in interface signature)"""
    is_rec: bool
    name: str
    params: tuple[TypeFormal, ...]
    bound: Optional[Kind]
    type_val: Type
    offset: int

@dataclass(frozen=True)
class DefKindBinding(BindingNode):
    """DEF K = Kind"""
    name: str
    kind_val: Kind
    offset: int

@dataclass(frozen=True)
class ExprStmt(BindingNode):
    """Standalone expression statement."""
    expr: Expr
    offset: int

@dataclass(frozen=True)
class ImportItem(ASTNode):
    names: tuple[str, ...]
    interface_name: str
    offset: int

@dataclass(frozen=True)
class InterfaceDecl(ASTNode):
    name: str
    is_unsound: bool
    imports: tuple[ImportItem, ...]
    signatures: tuple[BindingNode, ...]
    offset: int

@dataclass(frozen=True)
class ModuleDecl(ASTNode):
    name: str
    interface_name: str
    is_unsound: bool
    imports: tuple[ImportItem, ...]
    bindings: tuple[BindingNode, ...]
    offset: int

@dataclass(frozen=True)
class Program(ASTNode):
    """A complete .quest compilation unit: top-level declarations, expressions, interfaces, modules."""
    phrases: tuple[ASTNode, ...]
    offset: int
```

---

### 4.6. Canonical S-Expression Pretty-Printer (`ast_dump`)

To verify parser correctness with the golden test framework (`tests/golden/parse/<name>.out`), `ast_dump()` serializes ASTs to S-expressions using **two-space indentation per nesting level**:

```python
def ast_dump(node: ASTNode, indent: int = 0) -> str:
    """Recursively formats an AST node into a canonical 2-space indented S-expression string."""
    pad = "  " * indent
    # Example format:
    # (Program
    #   (LetValueBinding x (ExprInt 42))
    #   (ExprIf
    #     (ExprId cond)
    #     (ExprInt 1)
    #     (ExprInt 0)))
    ...
```

#### Canonical Serialization Rules:
1. **Node Headers:** `(<NodeName>` on the opening line.
2. **Atomic Leaves:** Inline representations for simple leaves: `(ExprInt 42)`, `(ExprId x)`, `(KindType)`.
3. **Complex Children:** Indented on subsequent lines with 2 additional spaces.
4. **Lists / Tuples:** Formatted with child nodes indented beneath their parent clause.
