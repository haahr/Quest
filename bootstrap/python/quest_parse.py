#!/usr/bin/env python3
"""Standalone CLI to parse Quest source code and output canonical S-expression ASTs."""

import argparse
import os
import sys

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quest.tokens import SourceMap
from quest.tokenizer import Tokenizer, TokenizerError
from quest.parser import ParserError
from quest.grammar import parse_quest_program
import quest.ast as ast


def parse_stream(source_text: str, file_name: str = "<stdin>", show_offsets: bool = False) -> int:
    source_map = SourceMap(source_text, file_name)
    tokenizer = Tokenizer(source_text, file_name)

    try:
        tokens = tokenizer.tokenize_all()
    except TokenizerError as error:
        sys.stderr.write(error.format_with_source(source_map) + "\n")
        return 1

    try:
        tree = parse_quest_program(tokens, source_map)
        print(ast.ast_dump(tree, show_offsets=show_offsets))
        return 0
    except ParserError as error:
        sys.stderr.write(error.format_with_source(source_map) + "\n")
        return 1


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Parse Quest source code into S-expression AST.")
    arg_parser.add_argument(
        "file", nargs="?", default=None, help="Path to Quest source file (.quest), or '-' for stdin."
    )
    arg_parser.add_argument("-c", "--code", help="Inline Quest code string to parse.")
    arg_parser.add_argument("--show-offsets", action="store_true", help="Include token offsets in AST dump.")

    args = arg_parser.parse_args()

    if args.code is not None:
        return parse_stream(args.code, "<string>", args.show_offsets)

    if args.file is None or args.file == "-":
        source_text = sys.stdin.read()
        return parse_stream(source_text, "<stdin>", args.show_offsets)

    try:
        with open(args.file, "r", encoding="utf-8") as file:
            source_text = file.read()
        return parse_stream(source_text, args.file, args.show_offsets)
    except OSError as error:
        sys.stderr.write(f"Error opening file '{args.file}': {error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
