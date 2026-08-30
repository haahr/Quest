"""Quest Token definitions, Source Maps, and Position tracking."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional


@dataclass(frozen=True)
class SourceLocation:
    """A human-readable source position computed from an offset."""
    file_name: str
    offset: int
    line: int        # 1-indexed
    column: int      # 1-indexed

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


class SourceMap:
    """Maintains source text and computes line/column coordinates from offsets."""

    def __init__(self, source_text: str, file_name: str = "<string>"):
        self.source_text = source_text
        self.file_name = file_name
        self.line_starts: list[int] = [0]
        for idx, ch in enumerate(source_text):
            if ch == "\n":
                self.line_starts.append(idx + 1)

    def locate(self, offset: int) -> SourceLocation:
        """Maps a 0-indexed character offset to (line, column)."""
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


class TokenKind(Enum):
    # --- Literals ---
    INT_LIT = auto()        # e.g. 0, 42, 1000
    REAL_LIT = auto()       # e.g. 3.14, 2.0e-5, 1.0E+3
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

    def __repr__(self) -> str:
        if self.value is not None:
            return f"Token({self.kind.name}, {self.lexeme!r}, value={self.value!r}, offset={self.offset})"
        return f"Token({self.kind.name}, {self.lexeme!r}, offset={self.offset})"


# Map of exact reserved keywords
KEYWORDS: dict[str, TokenKind] = {
    # Kind level
    "TYPE": TokenKind.KW_TYPE,
    "POWER": TokenKind.KW_POWER,
    "ALL": TokenKind.KW_ALL_KIND,
    "DEF": TokenKind.KW_DEF_KIND,

    # Type level
    "All": TokenKind.KW_ALL,
    "Array": TokenKind.KW_ARRAY_TYPE,
    "Auto": TokenKind.KW_AUTO_TYPE,
    "Def": TokenKind.KW_DEF,
    "Exception": TokenKind.KW_EXCEPTION_TYPE,
    "Fun": TokenKind.KW_FUN_TYPE,
    "Let": TokenKind.KW_LET_TYPE,
    "Option": TokenKind.KW_OPTION_TYPE,
    "Out": TokenKind.KW_OUT,
    "Rec": TokenKind.KW_REC_TYPE,
    "Record": TokenKind.KW_RECORD_TYPE,
    "Tuple": TokenKind.KW_TUPLE_TYPE,
    "Var": TokenKind.KW_VAR_TYPE,
    "Variant": TokenKind.KW_VARIANT_TYPE,

    # Value level
    "and": TokenKind.KW_AND,
    "andif": TokenKind.KW_ANDIF,
    "array": TokenKind.KW_ARRAY,
    "as": TokenKind.KW_AS,
    "auto": TokenKind.KW_AUTO,
    "begin": TokenKind.KW_BEGIN,
    "case": TokenKind.KW_CASE,
    "do": TokenKind.KW_DO,
    "downto": TokenKind.KW_DOWNTO,
    "else": TokenKind.KW_ELSE,
    "elsif": TokenKind.KW_ELSIF,
    "end": TokenKind.KW_END,
    "exception": TokenKind.KW_EXCEPTION,
    "exit": TokenKind.KW_EXIT,
    "export": TokenKind.KW_EXPORT,
    "false": TokenKind.KW_FALSE,
    "for": TokenKind.KW_FOR,
    "fun": TokenKind.KW_FUN,
    "if": TokenKind.KW_IF,
    "import": TokenKind.KW_IMPORT,
    "inspect": TokenKind.KW_INSPECT,
    "interface": TokenKind.KW_INTERFACE,
    "is": TokenKind.KW_IS,
    "isnot": TokenKind.KW_ISNOT,
    "let": TokenKind.KW_LET,
    "loop": TokenKind.KW_LOOP,
    "module": TokenKind.KW_MODULE,
    "of": TokenKind.KW_OF,
    "ok": TokenKind.KW_OK,
    "option": TokenKind.KW_OPTION,
    "orif": TokenKind.KW_ORIF,
    "raise": TokenKind.KW_RAISE,
    "rec": TokenKind.KW_REC,
    "record": TokenKind.KW_RECORD,
    "then": TokenKind.KW_THEN,
    "true": TokenKind.KW_TRUE,
    "try": TokenKind.KW_TRY,
    "tuple": TokenKind.KW_TUPLE,
    "unsound": TokenKind.KW_UNSOUND,
    "upto": TokenKind.KW_UPTO,
    "var": TokenKind.KW_VAR,
    "variant": TokenKind.KW_VARIANT,
    "when": TokenKind.KW_WHEN,
    "while": TokenKind.KW_WHILE,
    "with": TokenKind.KW_WITH,
}

# Map of reserved punctuation operators
RESERVED_PUNCTUATION: dict[str, TokenKind] = {
    ":=": TokenKind.ASSIGN,
    "::": TokenKind.COLON_COLON,
    "<:": TokenKind.SUBTYPE,
    "=": TokenKind.EQUAL,
    ":": TokenKind.COLON,
    "?": TokenKind.QUESTION,
    "!": TokenKind.BANG,
    "@": TokenKind.AT,
    "_": TokenKind.UNDERSCORE,
}

# Single-character punctuation tokens that are not part of symbolic operator characters
DELIMITERS: dict[str, TokenKind] = {
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    ",": TokenKind.COMMA,
    ";": TokenKind.SEMICOLON,
}

# Symbolic operator character set
SYMBOLIC_CHARS: frozenset[str] = frozenset("!@#$%&*_+=-|\\`:<>/?^~")
