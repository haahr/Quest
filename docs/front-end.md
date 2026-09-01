# Quest Front-End Design Document

This document specifies the architecture, data structures, and APIs for the **Quest Front-End** (Step 1 of the Quest implementation plan), encompassing the Tokenizer, Source Position Mapping, Diagnostic Formatting, Data-Driven PEG Parser, and Abstract Syntax Tree (AST).

---

## 1. Overview and Design Principles

The front-end is responsible for converting raw Quest source text (`.quest`) into an immutable, strongly-typed Abstract Syntax Tree (AST). In accordance with the project plan:

- **Target Runtime:** Python 3.10+ (using Python 3.11 at `/opt/homebrew/opt/python@3.11/libexec/bin/python`), enabling native pattern matching (`match ... case`) and `dataclasses.KW_ONLY`.
- **Data-Driven PEG / Packrat Architecture:** The grammar is declaratively defined as a set of rules for non-terminal `SyntaxTarget`s composed of algebraic `Construct` elements (`MatchToken`, `MatchTarget`, `Optional`, `Repeated`, `Sequence`).
- **Mostly-Functional Style:** Pure functions, immutable data structures (`@dataclass(frozen=True)`), and algebraic type decompositions to facilitate a direct subsequent port to Quest (in `src/`).
- **Dedicated AST Namespace:** All AST nodes live in a dedicated module (`quest.ast`) to prevent name collisions with standard Python built-ins or compiler passes.
- **Zero External Dependencies:** Built entirely with standard library facilities to ensure immediate portability.
- **Precision Diagnostics:** Retains full source fidelity with character-offset tracking, enabling formatted error messages with line numbers, column numbers, and underlined source context.
- **Root `offset` via `KW_ONLY`:** The root `ASTNode` declares `offset: int = 0` with `KW_ONLY`, allowing subclasses to define purely positional semantic fields while automatically inheriting optional keyword `offset` tracking and clean `__match_args__`.
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
    IDENT = auto()          # Alphanumeric: [A-Za-z][A-Za-z0-9]* (no underscores)
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
   Alphanumeric identifiers are scanned with `[A-Za-z][A-Za-z0-9]*` (underscores are not part of identifiers). The resulting string is looked up in a case-sensitive keyword dictionary. If found, the corresponding `KW_*` token is emitted; otherwise, `IDENT` is emitted.

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

## 3. Data-Driven PEG / Packrat Parser Architecture

The front-end separates parsing into two decoupled modules:
1. **`quest.parser` (`bootstrap/python/quest/parser.py`):** A domain-agnostic, reusable PEG/Packrat engine implementing algebraic grammar constructs, packrat memoization, `_IN_PROGRESS` cycle detection, loop progress assertions, and farthest-failure diagnostics.
2. **`quest.grammar` (`bootstrap/python/quest/grammar.py`):** The Quest language grammar specification, mapping `SyntaxTarget` non-terminals to production `Rule`s paired with typed AST builder callables.

### 3.1. Syntax Targets and Grammar Constructs

Non-terminals are first-class `SyntaxTarget` instances that inherit directly from `Construct`. Each syntax target encapsulates its human-readable capitalized name, its list of production `Rule`s, and an `add_rule` registration method.

```python
class Construct:
    """Base class for all grammar constructs."""
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]:
        """Evaluates this construct against the parser at token position pos."""
        raise NotImplementedError

@dataclass(frozen=True)
class MatchToken(Construct):
    """Matches a specific terminal TokenKind."""
    kind: TokenKind
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]: ...

class SyntaxTarget(Construct):
    """A grammar non-terminal syntax target owning its production rules."""
    can_match_empty: bool = False

    def __init__(self, name: str):
        self.name = name
        self.rules: list[Rule] = []

    def add_rule(self, constructs: tuple[Construct, ...], action: Callable[..., Any]) -> Rule:
        rule = Rule(constructs, action)
        self.rules.append(rule)
        return rule

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]: ...

class Optional(Construct):
    """Matches inner construct(s) 0 or 1 times: [...] in EBNF."""
    can_match_empty: bool = True

    def __init__(self, *items: Construct):
        self.inner = items[0] if len(items) == 1 else Sequence(items)

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]: ...

class Repeated(Construct):
    """Matches inner construct(s) 0 or more times: {...} in EBNF."""
    can_match_empty: bool = True

    def __init__(self, *items: Construct):
        self.inner = items[0] if len(items) == 1 else Sequence(items)

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]: ...

@dataclass(frozen=True)
class Sequence(Construct):
    """Matches a sequence of constructs in order."""
    items: tuple[Construct, ...]
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Optional[Any], int]: ...

@dataclass(frozen=True)
class Rule:
    """An alternative production rule with a callable semantic action builder."""
    constructs: tuple[Construct, ...]
    action: Callable[..., Any]
```

#### Top-Level Non-Terminals
Top-level non-terminals are defined as global constants in `bootstrap/python/quest/grammar.py` with capitalized string names:

```python
PROGRAM = SyntaxTarget("Program")
PHRASE = SyntaxTarget("Phrase")
INTERFACE = SyntaxTarget("Interface")
MODULE = SyntaxTarget("Module")
IMPORT = SyntaxTarget("Import")
IDE_LIST = SyntaxTarget("IdeList")

KIND = SyntaxTarget("Kind")
PRIMARY_KIND = SyntaxTarget("PrimaryKind")

TYPE = SyntaxTarget("Type")
POSTFIX_TYPE = SyntaxTarget("PostfixType")
PRIMARY_TYPE = SyntaxTarget("PrimaryType")
SIGNATURE = SyntaxTarget("Signature")

VALUE = SyntaxTarget("Value")
POSTFIX_VALUE = SyntaxTarget("PostfixValue")
PRIMARY_VALUE = SyntaxTarget("PrimaryValue")
BINDING = SyntaxTarget("Binding")
```

#### Architectural Alternative: `QuestGrammar` Class Encapsulation
An alternative design considered was encapsulating all `SyntaxTarget` non-terminals as fields of a `QuestGrammar` class, with rules built in its constructor (`self._build_rules()`):

```python
class QuestGrammar:
    def __init__(self):
        self.PROGRAM = SyntaxTarget("Program")
        self.VALUE = SyntaxTarget("Value")
        ...
        self._build_rules()
```

- **Advantages:** Eliminates all module-level global variables and allows instantiating multiple isolated grammar instances (useful for testing dialect extensions).
- **Trade-offs / Why Deferred:** Adds `self.` / unpacking preamble boilerplate across ~80 production rules, and is redundant with Quest's native `interface` / `module` system where a grammar module is already a first-class record/namespace when self-hosting.

---

### 3.2. Left-Recursion Elimination via Factored EBNF

In standard PEG, left-recursive productions like `Value ::= Value infix Value` or `Value ::= Value "(" Binding ")"` cause infinite recursion. We factor these into non-left-recursive EBNF rules:

#### A. Factored Expressions (`Value` & `Infix`)
Quest's uniform right-associativity (`2 * x + y` $\to$ `2 * (x + y)`) is parsed cleanly by right-recursive infix chaining:

```bnf
Value         ::= PostfixValue [ InfixTail ]
PostfixValue  ::= PrimaryValue { PostfixOp }
PostfixOp     ::= ("." ide | "?" ide | "!" ide | "(" [Binding] ")" | "[" Value "]" | "_" ide)
```

In rule definitions:
```python
T = MatchToken
TK = TokenKind
Opt = Optional
Rep = Repeated

# Value ::= PostfixValue [ InfixTail ]
VALUE.add_rule(
    (POSTFIX_VALUE, Opt(T(TK.SYMBOLIC_INFIX), VALUE)),
    lambda left, tail: ExprInfix(left=left, op=tail[0].lexeme, right=tail[1], offset=left.offset) if tail else left,
)
```

#### B. Factored Types (`Type`)
```bnf
Type          ::= PostfixType [ InfixTypeTail ]
PostfixType   ::= PrimaryType { PostfixTypeOp }
PostfixTypeOp ::= ("." ide | "(" [TypeBinding] ")" | "_" ide)
```

---

### 3.3. Packrat Memoization Table & Zero-Width Loop Prevention

1. **Table Structure:**  
   The parser memoizes results strictly at the `SyntaxTarget` level:
   $$\text{cache}[(target, token\_pos)] \to (result\_node, next\_token\_pos) \text{ or } \text{None}$$
   Internal construct evaluations (`MatchToken`, `Optional`, `Repeated`) execute directly in a fast loop without cache allocation overhead.

2. **Zero-Width Loop Prevention in `Repeated`:**  
   On every iteration of `Repeated(construct)`, the parser asserts progress:
   $$\text{new\_pos} > \text{old\_pos}$$
   If a construct matches the empty stream without advancing the token index, the loop terminates immediately, preventing infinite loops.

3. **Direct & Mutual Left-Recursion Cycle Detection (`IN_PROGRESS` Sentinel):**  
   If an accidental left-recursion or mutual cycle ($A \to B \to A$ at the same token index) is entered, `cache[(target, token_pos)]` is marked with an `IN_PROGRESS` sentinel upon entry. If a recursive call hits an `IN_PROGRESS` entry before completion, the parser immediately detects the cycle and fails that branch (`return None, pos`), guaranteeing that mutual left-recursions never trigger stack overflows.

4. **Interactive REPL Caching Policy:**  
   To prevent stale failure results recorded at EOF boundaries from poisoning future input, the cache is cleared at the start of each top-level interactive phrase parse attempt.

---

### 3.4. Diagnostic Error Reporting via Farthest-Failure Tracking

Backtracking PEG parsers can fail deep inside an invalid expression and backtrack out. The parser tracks:
- `farthest_pos: int`: The maximum token index reached across all evaluated branches.
- `expected_constructs: set[TokenKind | SyntaxTarget]`: The set of constructs expected at `farthest_pos`.

When the top-level parse fails, the parser reports the exact token at `farthest_pos` and formats a diagnostic message with line, column, and source underline via `SourceMap`.

---

### 3.5. Parser API

```python
class ParserError(Exception):
    """Raised when parsing fails, carrying location and message."""
    def __init__(self, message: str, offset: int, length: int = 1):
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.length = length

    def format_with_source(self, source_map: SourceMap) -> str:
        return source_map.format_error(self.offset, self.length, self.message)

class Parser:
    """Data-driven PEG / Packrat parser for Quest."""
    
    def __init__(self, tokens: list[Token], source_map: SourceMap):
        self.tokens = tokens
        self.source_map = source_map
        self.cache: dict[tuple[SyntaxTarget, int], Optional[tuple[Any, int]]] = {}
        self.farthest_pos = 0
        self.expected_at_farthest: set[str] = set()

    def parse_program(self) -> ast.Program:
        """Parses the entire token stream as a complete Quest Program."""
        ...

    def parse_target(self, target: SyntaxTarget, pos: int) -> tuple[Optional[Any], int]:
        """Evaluates a SyntaxTarget at the given token position, with packrat memoization."""
        ...
```

---

## 4. Abstract Syntax Tree (AST) Specification (`quest.ast`)

To avoid name collisions with Python built-ins (e.g. `type`, `tuple`, `eval`) or compiler pass symbols, all AST nodes reside in the dedicated namespace **`quest.ast`** (`bootstrap/python/quest/ast.py`).

### 4.1. Base Node and Parameter Structures

In Python 3.10+, `ASTNode` declares `_: KW_ONLY` and `offset: int = 0`. Subclasses define purely positional semantic fields, while automatically inheriting keyword-only `offset` tracking:

```python
from __future__ import annotations
from dataclasses import dataclass, KW_ONLY
from enum import Enum, auto
from typing import Optional, Union

@dataclass(frozen=True)
class ASTNode:
    """Base class for all AST nodes."""
    _: KW_ONLY
    offset: int = 0

class ParamMode(Enum):
    VALUE = auto()
    VAR = auto()
    OUT = auto()

@dataclass(frozen=True)
class FormalParam(ASTNode):
    """Value-level function parameter: [var | out] x : T"""
    name: str
    type_annot: Optional[Type] = None
    mode: ParamMode = ParamMode.VALUE

@dataclass(frozen=True)
class TypeFormal(ASTNode):
    """Type-level parameter: X <: B or X :: K"""
    name: str
    bound: Kind

@dataclass(frozen=True)
class Quantifier(ASTNode):
    """Universal/existential quantifier: X <: B or X :: K"""
    name: str
    bound: Kind
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
    pass

@dataclass(frozen=True)
class KindPower(Kind):
    """POWER(T) — the kind of all subtypes of type T."""
    bound: Type

@dataclass(frozen=True)
class KindAll(Kind):
    """ALL(X::K) K' — operator kind universal quantifier."""
    param_name: str
    param_kind: Kind
    body_kind: Kind

@dataclass(frozen=True)
class KindId(Kind):
    """User-defined or aliased kind identifier."""
    name: str

@dataclass(frozen=True)
class KindManifest(Kind):
    """Interface manifest kind path, e.g. I_K."""
    interface_name: str
    kind_name: str
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

@dataclass(frozen=True)
class TypeAll(Type):
    """All(X <: B, Y :: K) T — universal type quantifier."""
    quantifiers: tuple[Quantifier, ...]
    result_type: Type

@dataclass(frozen=True)
class FieldSig(ASTNode):
    """Field in a tuple or auto signature: [var | out] x : T"""
    name: str
    type_sig: Type
    mode: ParamMode = ParamMode.VALUE

@dataclass(frozen=True)
class TypeTuple(Type):
    """Tuple x:Int, y:Real end — ordered dependent tuple signature."""
    fields: tuple[FieldSig, ...]

@dataclass(frozen=True)
class RecordFieldSig(ASTNode):
    """Field in a record signature: [var] x : T"""
    name: str
    type_sig: Type
    is_var: bool = False

@dataclass(frozen=True)
class TypeRecord(Type):
    """Record x:Int, y:Real end — unordered record type."""
    fields: tuple[RecordFieldSig, ...]

@dataclass(frozen=True)
class OptionFieldSig(ASTNode):
    """Variant in an option signature: tag [with fields...]"""
    tag: str
    payload_sig: tuple[FieldSig, ...] = ()

@dataclass(frozen=True)
class TypeOption(Type):
    """Option red, green, blue with val:Int end — tagged union / option type."""
    variants: tuple[OptionFieldSig, ...]

@dataclass(frozen=True)
class VariantFieldSig(ASTNode):
    """Field in a variant signature: [var] tag : T"""
    tag: str
    type_sig: Type
    is_var: bool = False

@dataclass(frozen=True)
class TypeVariant(Type):
    """Variant ok:Int, err:String end — unordered variant type."""
    fields: tuple[VariantFieldSig, ...]

@dataclass(frozen=True)
class TypeAuto(Type):
    """Auto X::K with x:T end — existential / automorphic dynamic type."""
    type_param: Optional[str]
    kind_bound: Kind
    signature: tuple[FieldSig, ...]

@dataclass(frozen=True)
class TypeFun(Type):
    """Fun(X::K, Y<:B) T — higher-order compile-time type operator."""
    params: tuple[TypeFormal, ...]
    result_kind: Optional[Kind]
    body: Type

@dataclass(frozen=True)
class TypeRec(Type):
    """Rec(X <: B) T — recursive type constructor."""
    var_name: str
    bound: Kind
    body: Type

@dataclass(frozen=True)
class TypeApp(Type):
    """T(A, B) — type operator application."""
    constructor: Type
    arguments: tuple[Type, ...]

@dataclass(frozen=True)
class TypeInfix(Type):
    """T -> U, T /\ U — infix type operator."""
    left: Type
    op: str
    right: Type

@dataclass(frozen=True)
class TypeArray(Type):
    """Array(T) — built-in array type."""
    element_type: Type

@dataclass(frozen=True)
class TypeVar(Type):
    """Var(T) — mutable reference cell type."""
    element_type: Type

@dataclass(frozen=True)
class TypeOut(Type):
    """Out(T) — contravariant output parameter mode."""
    element_type: Type

@dataclass(frozen=True)
class TypeManifest(Type):
    """M_T — manifest type extraction across interfaces."""
    module_name: str
    type_name: str
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

@dataclass(frozen=True)
class ExprReal(Expr):
    value: float
    lexeme: str

@dataclass(frozen=True)
class ExprChar(Expr):
    value: str
    lexeme: str

@dataclass(frozen=True)
class ExprString(Expr):
    value: str
    lexeme: str

@dataclass(frozen=True)
class ExprBool(Expr):
    value: bool

@dataclass(frozen=True)
class ExprOk(Expr):
    pass

@dataclass(frozen=True)
class ExprId(Expr):
    name: str

# --- Blocks & Control Flow ---
@dataclass(frozen=True)
class ExprBlock(Expr):
    """begin ... end — sequence of bindings and statements."""
    bindings: tuple[BindingNode, ...]

@dataclass(frozen=True)
class ExprIf(Expr):
    """if cond then e1 elsif cond2 then e2 else e3 end"""
    cond: Expr
    then_branch: Expr
    elsifs: tuple[tuple[Expr, Expr], ...] = ()   # tuple of (cond, body)
    else_branch: Optional[Expr] = None

@dataclass(frozen=True)
class ExprWhile(Expr):
    cond: Expr
    body: Expr

@dataclass(frozen=True)
class ExprLoop(Expr):
    body: Expr

@dataclass(frozen=True)
class ExprExit(Expr):
    pass

@dataclass(frozen=True)
class ExprFor(Expr):
    var_name: str
    start: Expr
    is_downto: bool
    stop: Expr
    body: Expr

# --- Functions & Applications ---
@dataclass(frozen=True)
class ExprFun(Expr):
    """fun(x: Int): Int x + 1"""
    params: tuple[FormalParam, ...]
    return_type: Optional[Type]
    body: Expr

@dataclass(frozen=True)
class ExprApp(Expr):
    """f(a, b)"""
    func: Expr
    args: tuple[Expr, ...]

@dataclass(frozen=True)
class ExprInfix(Expr):
    """a + b, a := b, a andif b, a orif b, a is b"""
    left: Expr
    op: str
    right: Expr

# --- Aggregates & Constructors ---
@dataclass(frozen=True)
class TupleBinding(ASTNode):
    name: Optional[str]
    value: Expr

@dataclass(frozen=True)
class ExprTuple(Expr):
    fields: tuple[TupleBinding, ...]

@dataclass(frozen=True)
class RecordBinding(ASTNode):
    name: str
    value: Expr
    is_var: bool = False

@dataclass(frozen=True)
class ExprRecord(Expr):
    fields: tuple[RecordBinding, ...]

@dataclass(frozen=True)
class ExprOption(Expr):
    tag: str
    option_type: Type
    payload: Optional[Expr] = None

@dataclass(frozen=True)
class ExprVariant(Expr):
    tag: str
    variant_type: Type
    is_var: bool = False
    payload: Optional[Expr] = None

@dataclass(frozen=True)
class ExprArray(Expr):
    elements: tuple[Expr, ...]

@dataclass(frozen=True)
class ExprArrayRep(Expr):
    count: Expr
    init_val: Expr

@dataclass(frozen=True)
class ExprAuto(Expr):
    witness: Optional[tuple[str, Optional[Kind], Expr]]
    target_type: Type
    payload: Expr

# --- Selection, Indexing, and References ---
@dataclass(frozen=True)
class ExprSelect(Expr):
    target: Expr
    field: str

@dataclass(frozen=True)
class ExprIndex(Expr):
    target: Expr
    index: Expr

@dataclass(frozen=True)
class ExprIndexAssign(Expr):
    target: Expr
    index: Expr
    value: Expr

@dataclass(frozen=True)
class ExprVarCell(Expr):
    value: Expr

@dataclass(frozen=True)
class ExprDerefCell(Expr):
    target: Expr

@dataclass(frozen=True)
class ExprVariantCheck(Expr):
    target: Expr
    tag: str

@dataclass(frozen=True)
class ExprVariantAssert(Expr):
    target: Expr
    tag: str

# --- Pattern Matching & Discrimination ---
@dataclass(frozen=True)
class CaseBranch(ASTNode):
    tags: tuple[str, ...]
    binder: Optional[str] = None
    binder_type: Optional[Type] = None
    body: Expr = None

@dataclass(frozen=True)
class ExprCase(Expr):
    target: Expr
    branches: tuple[CaseBranch, ...]
    else_branch: Optional[Expr] = None

@dataclass(frozen=True)
class InspectBranch(ASTNode):
    match_type: Type
    binders: tuple[tuple[str, Optional[Type]], ...]
    body: Expr

@dataclass(frozen=True)
class ExprInspect(Expr):
    target: Expr
    branches: tuple[InspectBranch, ...]
    else_branch: Optional[Expr] = None

# --- Exceptions ---
@dataclass(frozen=True)
class ExprRaise(Expr):
    exc: Expr
    payload: Optional[Expr] = None
    as_type: Optional[Type] = None

@dataclass(frozen=True)
class TryBranch(ASTNode):
    exc_pattern: Expr
    binder: Optional[str] = None
    binder_type: Optional[Type] = None
    body: Expr = None

@dataclass(frozen=True)
class ExprTry(Expr):
    body: Expr
    branches: tuple[TryBranch, ...]
    else_branch: Optional[Expr] = None
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
    name: str
    value: Expr
    params: tuple[FormalParam, ...] = ()
    type_annot: Optional[Type] = None
    is_rec: bool = False
    is_var: bool = False

@dataclass(frozen=True)
class LetTypeBinding(BindingNode):
    """Let [Rec] T(X::K)::K' = Type and U = ..."""
    name: str
    type_val: Type
    params: tuple[TypeFormal, ...] = ()
    bound: Optional[Kind] = None
    is_rec: bool = False

@dataclass(frozen=True)
class DefTypeBinding(BindingNode):
    """Def [Rec] T = Type (in interface signature)"""
    name: str
    type_val: Type
    params: tuple[TypeFormal, ...] = ()
    bound: Optional[Kind] = None
    is_rec: bool = False

@dataclass(frozen=True)
class DefKindBinding(BindingNode):
    """DEF K = Kind"""
    name: str
    kind_val: Kind

@dataclass(frozen=True)
class ExprStmt(BindingNode):
    """Standalone expression statement."""
    expr: Expr

@dataclass(frozen=True)
class ImportItem(ASTNode):
    names: tuple[str, ...]
    interface_name: str

@dataclass(frozen=True)
class InterfaceDecl(ASTNode):
    name: str
    signatures: tuple[BindingNode, ...]
    imports: tuple[ImportItem, ...] = ()
    is_unsound: bool = False

@dataclass(frozen=True)
class ModuleDecl(ASTNode):
    name: str
    interface_name: str
    bindings: tuple[BindingNode, ...]
    imports: tuple[ImportItem, ...] = ()
    is_unsound: bool = False

@dataclass(frozen=True)
class Program(ASTNode):
    """A complete .quest compilation unit: top-level declarations, expressions, interfaces, modules."""
    phrases: tuple[ASTNode, ...]
```

---

### 4.6. Canonical S-Expression Pretty-Printer (`ast_dump`)

To verify parser correctness with the golden test framework (`tests/golden/parse/<name>.out`), `ast_dump()` serializes ASTs to S-expressions using **two-space indentation per nesting level**:

```python
def ast_dump(node: ASTNode, indent: int = 0, show_offsets: bool = False) -> str:
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

---

## 5. Output Streams, Golden Testing, and Error Handling Discipline

### 5.1. Standard Compiler Output Streams
The compiler strictly distinguishes standard output and diagnostic error output:
- **Standard Output (`stdout`, exit code 0):** Used exclusively for valid compiler output (e.g. token streams from `quest_tokenize.py`, S-expression ASTs from `quest_parse.py`, and compiled code in later phases).
- **Standard Error (`stderr`, exit code 1):** Used exclusively for diagnostic messages, syntax errors, and compiler errors formatted with source location context.

### 5.2. Golden Test Framework Conventions (`.out` vs. `.error`)
The test runner (`run_tests.py`) enforces strict separation between positive success tests and negative error tests:
- **Positive Tests (`<test>.out`):** Valid Quest source files must succeed with exit code 0. Their `stdout` is captured and verified against `tests/golden/<phase>/<test>.out`.
- **Negative Tests (`<test>.error`):** Invalid Quest source files must fail with exit code $\ne 0$. Their `stderr` diagnostic is captured and verified against `tests/golden/<phase>/<test>.error`.
- `.out` files must never contain compiler error messages.

### 5.3. Future Error Handling Discipline
As the bootstrap compiler progresses into type checking and intermediate code generation, more formal discipline will be imposed on error handling:
1. **Structured Diagnostics:** Transitioning from unstructured error strings to structured diagnostic objects carrying severity (error/warning), error codes, primary and secondary labels, and compiler hints.
2. **Error Recovery & Cascading Suppression:** Implementing parser and typechecker synchronization strategies to report multiple non-cascading errors per compilation run.
3. **Explicit Negative Test Suites:** Organizing negative tests under dedicated subdirectories (e.g. `tests/source/errors/`) to systematically verify diagnostic reporting.
