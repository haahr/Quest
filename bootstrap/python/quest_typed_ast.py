#!/usr/bin/env python3
"""Standalone CLI to elaborate Quest source code into typed ASTs and output canonical S-expressions."""

import argparse
import os
import sys

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quest.tokens import SourceMap
from quest.tokenizer import Tokenizer, TokenizerError
from quest.parser import ParserError
from quest.grammar import parse_quest_program
from quest.typechecker import elaborate_program, TypeError as QuestTypeError
from quest.types import KindError
from quest.env import Environment


def elaborate_stream(source_text: str, file_name: str = "<stdin>") -> int:
    source_map = SourceMap(source_text, file_name)
    tokenizer = Tokenizer(source_text, file_name)

    try:
        tokens = tokenizer.tokenize_all()
    except TokenizerError as error:
        sys.stderr.write(error.format_with_source(source_map) + "\n")
        return 1

    try:
        tree = parse_quest_program(tokens, source_map)
    except ParserError as error:
        sys.stderr.write(error.format_with_source(source_map) + "\n")
        return 1

    try:
        env = Environment()
        typed_tree = elaborate_program(tree, env)
        print(typed_tree.dump())
        return 0
    except QuestTypeError as error:
        loc = source_map.locate(error.offset)
        sys.stderr.write(f"{loc.file_name}:{loc.line}:{loc.column}: Type error: {error.message}\n")
        return 1
    except KindError as error:
        sys.stderr.write(f"{file_name}: Kind error: {error}\n")
        return 1


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Elaborate Quest source code into typed S-expression AST.")
    arg_parser.add_argument(
        "file", nargs="?", default=None, help="Path to Quest source file (.quest), or '-' for stdin."
    )
    arg_parser.add_argument("-c", "--code", help="Inline Quest code string to elaborate.")

    args = arg_parser.parse_args()

    if args.code is not None:
        return elaborate_stream(args.code, "<string>")

    if args.file is None or args.file == "-":
        source_text = sys.stdin.read()
        return elaborate_stream(source_text, "<stdin>")

    try:
        with open(args.file, "r", encoding="utf-8") as file:
            source_text = file.read()
        return elaborate_stream(source_text, args.file)
    except OSError as error:
        sys.stderr.write(f"Error opening file '{args.file}': {error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
