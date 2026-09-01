"""Quest Tokenizer (Lexical Analyzer)."""

from __future__ import annotations

from typing import Iterator, Optional
from quest.tokens import (
    DELIMITERS,
    KEYWORDS,
    RESERVED_PUNCTUATION,
    SYMBOLIC_CHARS,
    SourceLocation,
    SourceMap,
    Token,
    TokenKind,
)


class TokenizerError(Exception):
    """Raised on lexical errors (unterminated literals, invalid characters, etc.)."""

    def __init__(self, message: str, offset: int, length: int = 1):
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.length = length

    def format_with_source(self, source_map: SourceMap) -> str:
        return source_map.format_error(self.offset, self.length, self.message)


class IncompleteInputError(TokenizerError):
    """Raised by InteractiveTokenizer when input ends inside an unclosed comment or literal."""
    pass


class Tokenizer:
    """Batch tokenizer for strings and files."""

    def __init__(self, source_text: str, file_name: str = "<string>"):
        self.source_text = source_text
        self.file_name = file_name
        self.cursor = 0
        self.length = len(source_text)
        self.source_map = SourceMap(source_text, file_name)

    @classmethod
    def from_str(cls, text: str, file_name: str = "<string>") -> "Tokenizer":
        return cls(text, file_name)

    @classmethod
    def from_file(cls, path: str) -> "Tokenizer":
        with open(path, "r", encoding="utf-8") as f:
            return cls(f.read(), path)

    def _peek(self, offset: int = 0) -> str:
        index = self.cursor + offset
        if index < self.length:
            return self.source_text[index]
        return ""

    def _advance(self) -> str:
        if self.cursor < self.length:
            char = self.source_text[self.cursor]
            self.cursor += 1
            return char
        return ""

    def _match(self, expected: str) -> bool:
        if self.cursor < self.length and self.source_text[self.cursor] == expected:
            self.cursor += 1
            return True
        return False

    def _skip_whitespace_and_comments(self) -> None:
        while self.cursor < self.length:
            char = self.source_text[self.cursor]

            # Whitespace
            if char in " \t\r\n\f\v":
                self.cursor += 1
                continue

            # Nested Comments (* ... *)
            if char == "(" and self._peek(1) == "*":
                start_offset = self.cursor
                self.cursor += 2
                depth = 1
                while self.cursor < self.length and depth > 0:
                    if self.source_text[self.cursor] == "(" and self._peek(1) == "*":
                        depth += 1
                        self.cursor += 2
                    elif self.source_text[self.cursor] == "*" and self._peek(1) == ")":
                        depth -= 1
                        self.cursor += 2
                    else:
                        self.cursor += 1

                if depth > 0:
                    raise TokenizerError(
                        "Unclosed comment",
                        start_offset,
                        self.cursor - start_offset,
                    )
                continue

            break

    def _lex_number(self) -> Token:
        start = self.cursor
        while self.cursor < self.length and self.source_text[self.cursor].isdigit():
            self.cursor += 1

        # Check for decimal point followed by a digit: e.g. 2.0
        if (
            self.cursor < self.length
            and self.source_text[self.cursor] == "."
            and self._peek(1).isdigit()
        ):
            self.cursor += 1  # Consume '.'
            while self.cursor < self.length and self.source_text[self.cursor].isdigit():
                self.cursor += 1

            # Optional exponent: e.g. 2.0e-5, 3.14E+2
            if self.cursor < self.length and self.source_text[self.cursor] in "eE":
                exponent_start = self.cursor
                self.cursor += 1
                if self.cursor < self.length and self.source_text[self.cursor] in "+-":
                    self.cursor += 1
                if not (self.cursor < self.length and self.source_text[self.cursor].isdigit()):
                    raise TokenizerError(
                        "Malformed real exponent",
                        exponent_start,
                        self.cursor - exponent_start,
                    )
                while self.cursor < self.length and self.source_text[self.cursor].isdigit():
                    self.cursor += 1

            lexeme = self.source_text[start:self.cursor]
            try:
                number_value = float(lexeme)
            except ValueError:
                raise TokenizerError(f"Invalid real literal '{lexeme}'", start, len(lexeme))
            return Token(TokenKind.REAL_LIT, lexeme, number_value, start)

        lexeme = self.source_text[start:self.cursor]
        try:
            number_value = int(lexeme)
        except ValueError:
            raise TokenizerError(f"Invalid integer literal '{lexeme}'", start, len(lexeme))
        return Token(TokenKind.INT_LIT, lexeme, number_value, start)

    def _lex_escape_sequence(self, literal_start: int) -> tuple[str, int]:
        """Parses an escape sequence starting after backslash."""
        escape_start = self.cursor - 1
        if self.cursor >= self.length:
            raise TokenizerError("Unterminated escape sequence", escape_start, 1)

        char = self._advance()
        if char == "n":
            return "\n", self.cursor - escape_start
        elif char == "t":
            return "\t", self.cursor - escape_start
        elif char == "r":
            return "\r", self.cursor - escape_start
        elif char == "b":
            return "\b", self.cursor - escape_start
        elif char == "f":
            return "\f", self.cursor - escape_start
        elif char == "\\":
            return "\\", self.cursor - escape_start
        elif char == "'":
            return "'", self.cursor - escape_start
        elif char == '"':
            return '"', self.cursor - escape_start
        elif char == "x":
            # Hexadecimal escape \xhh
            hex_digits = ""
            for _ in range(2):
                if self.cursor < self.length and self.source_text[self.cursor] in "0123456789abcdefABCDEF":
                    hex_digits += self._advance()
                else:
                    break
            if not hex_digits:
                raise TokenizerError(
                    "Invalid hexadecimal escape sequence",
                    escape_start,
                    self.cursor - escape_start,
                )
            return chr(int(hex_digits, 16)), self.cursor - escape_start
        elif char.isdigit():
            # Decimal character code \ddd (up to 3 decimal digits)
            digits = char
            while len(digits) < 3 and self.cursor < self.length and self.source_text[self.cursor].isdigit():
                digits += self._advance()
            char_code = int(digits)
            if char_code > 255:
                raise TokenizerError(
                    f"Character code {char_code} out of byte range",
                    escape_start,
                    self.cursor - escape_start,
                )
            return chr(char_code), self.cursor - escape_start
        else:
            raise TokenizerError(f"Unknown escape sequence '\\{char}'", escape_start, 2)

    def _lex_char(self) -> Token:
        start = self.cursor
        self.cursor += 1  # Consume opening quote '
        if self.cursor >= self.length or self.source_text[self.cursor] == "'":
            raise TokenizerError("Empty character literal", start, self.cursor - start)

        if self.source_text[self.cursor] == "\\":
            self.cursor += 1
            char_value, _ = self._lex_escape_sequence(start)
        else:
            char_value = self._advance()

        if self.cursor >= self.length or self.source_text[self.cursor] != "'":
            raise TokenizerError("Unterminated character literal", start, self.cursor - start)

        self.cursor += 1  # Consume closing quote '
        lexeme = self.source_text[start:self.cursor]
        return Token(TokenKind.CHAR_LIT, lexeme, char_value, start)

    def _lex_string(self) -> Token:
        start = self.cursor
        self.cursor += 1  # Consume opening quote "
        chars: list[str] = []

        while self.cursor < self.length and self.source_text[self.cursor] != '"':
            if self.source_text[self.cursor] == "\\":
                self.cursor += 1
                escaped_char, _ = self._lex_escape_sequence(start)
                chars.append(escaped_char)
            else:
                chars.append(self._advance())

        if self.cursor >= self.length:
            raise TokenizerError("Unterminated string literal", start, self.cursor - start)

        self.cursor += 1  # Consume closing quote "
        lexeme = self.source_text[start:self.cursor]
        return Token(TokenKind.STRING_LIT, lexeme, "".join(chars), start)

    def _lex_ident_or_keyword(self) -> Token:
        start = self.cursor
        while self.cursor < self.length and self.source_text[self.cursor].isalnum():
            self.cursor += 1

        lexeme = self.source_text[start:self.cursor]
        if lexeme in KEYWORDS:
            return Token(KEYWORDS[lexeme], lexeme, None, start)
        return Token(TokenKind.IDENT, lexeme, None, start)

    def _lex_symbolic_or_punctuation(self) -> Token:
        start = self.cursor
        while self.cursor < self.length and self.source_text[self.cursor] in SYMBOLIC_CHARS:
            # Stop if we see (* which is comment opener
            if self.source_text[self.cursor] == "(" and self._peek(1) == "*":
                break
            self.cursor += 1

        lexeme = self.source_text[start:self.cursor]
        if lexeme in RESERVED_PUNCTUATION:
            return Token(RESERVED_PUNCTUATION[lexeme], lexeme, None, start)
        return Token(TokenKind.SYMBOLIC_INFIX, lexeme, None, start)

    def next_token(self) -> Token:
        """Returns the next Token from the input stream, returning EOF at end."""
        self._skip_whitespace_and_comments()

        if self.cursor >= self.length:
            return Token(TokenKind.EOF, "", None, self.cursor)

        start = self.cursor
        char = self.source_text[self.cursor]

        # 1. Delimiters (single characters)
        if char in DELIMITERS:
            # Special check for comment opener (* which starts with (
            if char == "(" and self._peek(1) == "*":
                self._skip_whitespace_and_comments()
                return self.next_token()
            self.cursor += 1
            return Token(DELIMITERS[char], char, None, start)

        # 2. Dot operator
        if char == ".":
            self.cursor += 1
            return Token(TokenKind.DOT, ".", None, start)

        # 3. Numeric literals (strictly unsigned)
        if char.isdigit():
            return self._lex_number()

        # 4. Character literal
        if char == "'":
            return self._lex_char()

        # 5. String literal
        if char == '"':
            return self._lex_string()

        # 6. Alphanumeric identifiers and keywords
        if char.isalpha():
            return self._lex_ident_or_keyword()

        # 7. Symbolic operators and reserved punctuation
        if char in SYMBOLIC_CHARS:
            return self._lex_symbolic_or_punctuation()

        # 8. Unrecognized character
        self.cursor += 1
        raise TokenizerError(f"Unexpected character {char!r}", start, 1)

    def tokenize_all(self) -> list[Token]:
        """Eagerly consumes and returns all tokens up to and including EOF."""
        tokens: list[Token] = []
        while True:
            token = self.next_token()
            tokens.append(token)
            if token.kind == TokenKind.EOF:
                break
        return tokens

    def __iter__(self) -> Iterator[Token]:
        while True:
            token = self.next_token()
            yield token
            if token.kind == TokenKind.EOF:
                break


class InteractiveTokenizer:
    """Incremental tokenizer for REPL sessions, maintaining continuous offsets."""

    def __init__(self, file_name: str = "<stdin>"):
        self.file_name = file_name
        self.buffer = ""
        self.cursor = 0
        self.comment_depth = 0
        self.source_map = SourceMap("", file_name)

    def feed(self, line: str) -> list[Token]:
        """Appends a new input line and yields all fully completed tokens."""
        self.buffer += line + "\n"
        self.source_map = SourceMap(self.buffer, self.file_name)
        tokenizer = Tokenizer(self.buffer, self.file_name)
        tokenizer.cursor = self.cursor

        tokens: list[Token] = []
        try:
            while True:
                # Save position before attempting next token
                pos_before = tokenizer.cursor
                tokenizer._skip_whitespace_and_comments()
                if tokenizer.cursor >= len(self.buffer):
                    # Reached end of buffer without trailing partial tokens
                    self.cursor = tokenizer.cursor
                    break

                token = tokenizer.next_token()
                if token.kind == TokenKind.EOF:
                    self.cursor = tokenizer.cursor
                    break
                tokens.append(token)
                self.cursor = tokenizer.cursor
        except TokenizerError:
            # If error is due to unclosed literal/comment at end of buffer, wait for more input
            pass

        return tokens

    def is_complete(self) -> bool:
        """Returns True if no comments or literals are pending completion."""
        tokenizer = Tokenizer(self.buffer, self.file_name)
        try:
            tokenizer.tokenize_all()
            return True
        except TokenizerError:
            return False
