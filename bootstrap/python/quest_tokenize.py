#!/usr/bin/env python3
"""Standalone CLI to tokenize Quest source files or standard input."""

import argparse
import os
import sys

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quest.tokens import TokenKind, SourceMap
from quest.tokenizer import Tokenizer, TokenizerError


def tokenize_stream(source_text: str, file_name: str = "<stdin>", show_value: bool = False) -> int:
    source_map = SourceMap(source_text, file_name)
    tokenizer = Tokenizer(source_text, file_name)

    try:
        for token in tokenizer:
            loc = source_map.locate(token.offset)
            if token.kind == TokenKind.EOF:
                # Still output EOF token or terminate
                line_col = f"{loc.line}:{loc.column}"
                print(f"{line_col}\t{token.kind.name}")
                break

            line_col = f"{loc.line}:{loc.column}"
            if show_value and token.value is not None:
                print(f"{line_col}\t{token.kind.name}\t{token.lexeme}\t(value={token.value!r})")
            else:
                print(f"{line_col}\t{token.kind.name}\t{token.lexeme}")
        return 0

    except TokenizerError as err:
        sys.stderr.write(err.format_with_source(source_map) + "\n")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Tokenize Quest source code.")
    parser.add_argument("file", nargs="?", default=None, help="Path to Quest source file (.quest), or '-' for stdin.")
    parser.add_argument("-c", "--code", help="Inline Quest code string to tokenize.")
    parser.add_argument("--show-value", action="store_true", help="Include parsed literal values in output.")

    args = parser.parse_args()

    if args.code is not None:
        return tokenize_stream(args.code, "<string>", args.show_value)

    if args.file is None or args.file == "-":
        source_text = sys.stdin.read()
        return tokenize_stream(source_text, "<stdin>", args.show_value)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            source_text = f.read()
        return tokenize_stream(source_text, args.file, args.show_value)
    except OSError as e:
        sys.stderr.write(f"Error opening file '{args.file}': {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
