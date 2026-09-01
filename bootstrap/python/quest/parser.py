"""Generic, Data-Driven PEG / Packrat Parser Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional as Opt, Union

from quest.tokens import SourceMap, Token, TokenKind


# ============================================================================
# 1. Grammar Constructs & Rules
# ============================================================================

class Construct:
    """Base class for all PEG grammar constructs."""
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        """Evaluates this construct against the parser at token position pos."""
        raise NotImplementedError


@dataclass(frozen=True)
class MatchToken(Construct):
    """Matches a specific terminal TokenKind."""
    kind: TokenKind
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        token = parser._peek(pos)
        if token.kind == self.kind:
            return token, pos + 1
        parser._record_failure(pos, self.kind.name)
        return None, pos


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

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        result, new_pos = parser.parse_target(self, pos)
        if result is None:
            parser._record_failure(pos, self.name)
            return None, pos
        return result, new_pos

    def __repr__(self) -> str:
        return f"SyntaxTarget({self.name!r})"


class Optional(Construct):
    """Matches inner construct(s) 0 or 1 times: [...] in EBNF."""
    can_match_empty: bool = True

    def __init__(self, *items: Construct):
        if len(items) == 1:
            self.inner = items[0]
        else:
            self.inner = Sequence(items)

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        result, new_pos = self.inner.evaluate(parser, pos)
        if result is not None:
            return result, new_pos
        return None, pos

    def __repr__(self) -> str:
        return f"Optional({self.inner!r})"


class Repeated(Construct):
    """Matches inner construct(s) 0 or more times: {...} in EBNF."""
    can_match_empty: bool = True

    def __init__(self, *items: Construct):
        if len(items) == 1:
            self.inner = items[0]
        else:
            self.inner = Sequence(items)

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        results: list[Any] = []
        current_pos = pos
        while True:
            result, new_pos = self.inner.evaluate(parser, current_pos)
            if result is None or new_pos <= current_pos:
                # Enforce progress assertion to prevent zero-width infinite loops
                break
            results.append(result)
            current_pos = new_pos
        return tuple(results), current_pos

    def __repr__(self) -> str:
        return f"Repeated({self.inner!r})"


@dataclass(frozen=True)
class Sequence(Construct):
    """Matches a sequence of constructs in order."""
    items: tuple[Construct, ...]
    can_match_empty: bool = False

    def evaluate(self, parser: Parser, pos: int) -> tuple[Opt[Any], int]:
        items: list[Any] = []
        current_pos = pos
        for item in self.items:
            result, current_pos = item.evaluate(parser, current_pos)
            if result is None and not item.can_match_empty:
                return None, pos
            items.append(result)
        return tuple(items), current_pos


@dataclass(frozen=True)
class Rule:
    """An alternative production rule with a callable semantic action builder."""
    constructs: tuple[Construct, ...]
    action: Callable[..., Any]


# ============================================================================
# 2. Parser Exception
# ============================================================================

class ParserError(Exception):
    """Raised when parsing fails, carrying location and message."""

    def __init__(self, message: str, offset: int, length: int = 1):
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.length = length

    def format_with_source(self, source_map: SourceMap) -> str:
        return source_map.format_error(self.offset, self.length, self.message)


# Sentinel for packrat recursion detection
_IN_PROGRESS = object()


# ============================================================================
# 3. Generic Packrat Parser Engine
# ============================================================================

class Parser:
    """Generic data-driven PEG / Packrat parser engine."""

    def __init__(
        self,
        tokens: list[Token],
        source_map: SourceMap,
    ):
        # Keep all non-EOF tokens followed by a single EOF token
        self.tokens = [token for token in tokens if token.kind != TokenKind.EOF] + [
            tokens[-1] if tokens else Token(TokenKind.EOF, "", None, 0)
        ]
        self.source_map = source_map
        self.cache: dict[tuple[Any, int], Any] = {}
        self.farthest_pos = 0
        self.expected_at_farthest: set[str] = set()

    def _peek(self, pos: int) -> Token:
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]

    def _record_failure(self, pos: int, expected: str) -> None:
        if pos > self.farthest_pos:
            self.farthest_pos = pos
            self.expected_at_farthest = {expected}
        elif pos == self.farthest_pos:
            self.expected_at_farthest.add(expected)

    def parse(self, start_target: SyntaxTarget) -> Any:
        """Parses the entire token stream starting from start_target."""
        self.cache.clear()
        self.farthest_pos = 0
        self.expected_at_farthest.clear()

        result, pos = self.parse_target(start_target, 0)

        # Ensure all tokens up to EOF were consumed
        if result is not None:
            token = self._peek(pos)
            if token.kind == TokenKind.EOF:
                return result

        # Format diagnostic error on failure
        farthest_token = self._peek(self.farthest_pos)
        expected_string = (
            ", ".join(sorted(self.expected_at_farthest))
            if self.expected_at_farthest
            else "valid syntax"
        )
        message = (
            f"Unexpected token {farthest_token.lexeme!r} ({farthest_token.kind.name}), "
            f"expected: {expected_string}"
        )
        raise ParserError(message, farthest_token.offset, max(1, farthest_token.length))

    def parse_target(self, target: SyntaxTarget, pos: int) -> tuple[Opt[Any], int]:
        """Evaluates a target at the given token position with packrat memoization."""
        key = (target, pos)
        if key in self.cache:
            cached = self.cache[key]
            if cached is _IN_PROGRESS:
                # Cycle / left-recursion detected: break cycle
                return None, pos
            return cached

        self.cache[key] = _IN_PROGRESS

        for rule in target.rules:
            result, new_pos = self._evaluate_rule(rule, pos)
            if result is not None or (result is not None and new_pos == pos):
                self.cache[key] = (result, new_pos)
                return result, new_pos

        self.cache[key] = (None, pos)
        return None, pos

    def _evaluate_rule(self, rule: Rule, pos: int) -> tuple[Opt[Any], int]:
        current_pos = pos
        matched_arguments: list[Any] = []

        for construct in rule.constructs:
            result, current_pos = construct.evaluate(self, current_pos)
            if result is None and not construct.can_match_empty:
                return None, pos
            matched_arguments.append(result)

        try:
            node = rule.action(*matched_arguments)
            return node, current_pos
        except Exception:
            return None, pos
