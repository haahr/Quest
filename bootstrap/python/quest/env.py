"""Quest Scoping, Symbol Tables, and Lexical Environments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QKind,
    QType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
)


# ============================================================================
# 1. Symbol Definitions
# ============================================================================

class Symbol:
    """Base class for all named compiler symbols."""
    name: str


@dataclass
class ValueSymbol(Symbol):
    """Value-level symbol: x : Type."""
    name: str
    type_val: QType
    is_var: bool = False
    is_out: bool = False

    def __str__(self) -> str:
        var_prefix = "var " if self.is_var else ("out " if self.is_out else "")
        return f"{var_prefix}{self.name}: {self.type_val}"


@dataclass
class TypeSymbol(Symbol):
    """Type-level symbol: X :: Kind [= Definition]."""
    name: str
    symbol_id: int
    kind: QKind
    definition: Optional[QType] = None

    @property
    def is_abstract(self) -> bool:
        return self.definition is None

    def __str__(self) -> str:
        if self.definition is not None:
            return f"{self.name} :: {self.kind} = {self.definition}"
        return f"{self.name} :: {self.kind}"


@dataclass
class KindSymbol(Symbol):
    """Kind-level symbol: K = Kind."""
    name: str
    symbol_id: int
    kind: QKind

    def __str__(self) -> str:
        return f"{self.name} = {self.kind}"


# ============================================================================
# 2. Lexical Scope
# ============================================================================

class Scope:
    """A single lexical scope frame maintaining ordered declarations."""

    def __init__(self, parent: Optional[Scope] = None, name: str = "local"):
        self.parent = parent
        self.name = name
        self._declarations: list[Symbol] = []
        self._values: dict[str, ValueSymbol] = {}
        self._types: dict[str, TypeSymbol] = {}
        self._types_by_id: dict[int, TypeSymbol] = {}
        self._kinds: dict[str, KindSymbol] = {}
        self._kinds_by_id: dict[int, KindSymbol] = {}

    @property
    def declarations(self) -> list[Symbol]:
        """Returns all symbols declared in this scope in strict declaration order."""
        return list(self._declarations)

    def declare_value(self, symbol: ValueSymbol) -> ValueSymbol:
        self._declarations.append(symbol)
        self._values[symbol.name] = symbol
        return symbol

    def declare_type(self, symbol: TypeSymbol) -> TypeSymbol:
        self._declarations.append(symbol)
        self._types[symbol.name] = symbol
        self._types_by_id[symbol.symbol_id] = symbol
        return symbol

    def declare_kind(self, symbol: KindSymbol) -> KindSymbol:
        self._declarations.append(symbol)
        self._kinds[symbol.name] = symbol
        self._kinds_by_id[symbol.symbol_id] = symbol
        return symbol

    # --- Local Lookups ---

    def lookup_value_local(self, name: str) -> Optional[ValueSymbol]:
        return self._values.get(name)

    def lookup_type_local(self, name: str) -> Optional[TypeSymbol]:
        return self._types.get(name)

    def lookup_type_by_id_local(self, symbol_id: int) -> Optional[TypeSymbol]:
        return self._types_by_id.get(symbol_id)

    def lookup_kind_local(self, name: str) -> Optional[KindSymbol]:
        return self._kinds.get(name)

    def lookup_kind_by_id_local(self, symbol_id: int) -> Optional[KindSymbol]:
        return self._kinds_by_id.get(symbol_id)

    # --- Lexical Chain Lookups ---

    def lookup_value(self, name: str) -> Optional[ValueSymbol]:
        if name in self._values:
            return self._values[name]
        return self.parent.lookup_value(name) if self.parent else None

    def lookup_type(self, name: str) -> Optional[TypeSymbol]:
        if name in self._types:
            return self._types[name]
        return self.parent.lookup_type(name) if self.parent else None

    def lookup_type_by_id(self, symbol_id: int) -> Optional[TypeSymbol]:
        if symbol_id in self._types_by_id:
            return self._types_by_id[symbol_id]
        return self.parent.lookup_type_by_id(symbol_id) if self.parent else None

    def lookup_kind(self, name: str) -> Optional[KindSymbol]:
        if name in self._kinds:
            return self._kinds[name]
        return self.parent.lookup_kind(name) if self.parent else None

    def lookup_kind_by_id(self, symbol_id: int) -> Optional[KindSymbol]:
        if symbol_id in self._kinds_by_id:
            return self._kinds_by_id[symbol_id]
        return self.parent.lookup_kind_by_id(symbol_id) if self.parent else None

    def __repr__(self) -> str:
        return f"Scope({self.name!r}, {len(self._declarations)} decls)"


# ============================================================================
# 3. Compiler Environment
# ============================================================================

class Environment:
    """Manages the active lexical scope stack, built-in definitions, and module linkages."""

    def __init__(self):
        self._symbol_counter: int = 0
        self.global_scope: Scope = Scope(parent=None, name="global")
        self.current_scope: Scope = self.global_scope
        self._interfaces: dict[str, Scope] = {}
        self._modules: dict[str, Scope] = {}
        self._init_builtins()

    def fresh_symbol_id(self) -> int:
        """Allocates a unique positive integer symbol ID."""
        self._symbol_counter += 1
        return self._symbol_counter

    def push_scope(self, name: str = "local") -> Scope:
        """Pushes a new child scope onto the active scope stack."""
        self.current_scope = Scope(parent=self.current_scope, name=name)
        return self.current_scope

    def pop_scope(self) -> Scope:
        """Pops the current scope from the stack and returns it."""
        if self.current_scope.parent is None:
            raise RuntimeError("Cannot pop root global scope from Environment")
        popped = self.current_scope
        self.current_scope = self.current_scope.parent
        return popped

    # --- Direct Delegation Lookups ---

    def lookup_value(self, name: str) -> Optional[ValueSymbol]:
        return self.current_scope.lookup_value(name)

    def lookup_type(self, name: str) -> Optional[TypeSymbol]:
        return self.current_scope.lookup_type(name)

    def lookup_type_by_id(self, symbol_id: int) -> Optional[TypeSymbol]:
        return self.current_scope.lookup_type_by_id(symbol_id)

    def lookup_kind(self, name: str) -> Optional[KindSymbol]:
        return self.current_scope.lookup_kind(name)

    def lookup_kind_by_id(self, symbol_id: int) -> Optional[KindSymbol]:
        return self.current_scope.lookup_kind_by_id(symbol_id)

    # --- Interface and Module Registries ---

    def register_interface(self, name: str, scope: Scope) -> None:
        self._interfaces[name] = scope

    def lookup_interface(self, name: str) -> Optional[Scope]:
        return self._interfaces.get(name)

    def register_module(self, name: str, scope: Scope) -> None:
        self._modules[name] = scope

    def lookup_module(self, name: str) -> Optional[Scope]:
        return self._modules.get(name)

    # --- Built-in Initialization ---

    def _init_builtins(self) -> None:
        """Populates the global root scope with standard Quest primitives and constants."""
        # Built-in Kinds
        self.global_scope.declare_kind(
            KindSymbol(name="TYPE", symbol_id=self.fresh_symbol_id(), kind=TYPE_KIND)
        )

        # Built-in Primitive Types
        builtin_types = [
            ("Int", INT_TYPE),
            ("Real", REAL_TYPE),
            ("Bool", BOOL_TYPE),
            ("Char", CHAR_TYPE),
            ("String", STRING_TYPE),
            ("Ok", OK_TYPE),
            ("Dynamic", DYNAMIC_TYPE),
            ("Exception", EXCEPTION_TYPE),
        ]
        for type_name, qtype_inst in builtin_types:
            self.global_scope.declare_type(
                TypeSymbol(
                    name=type_name,
                    symbol_id=self.fresh_symbol_id(),
                    kind=TYPE_KIND,
                    definition=qtype_inst,
                )
            )

        # Built-in Primitive Values
        self.global_scope.declare_value(ValueSymbol(name="true", type_val=BOOL_TYPE))
        self.global_scope.declare_value(ValueSymbol(name="false", type_val=BOOL_TYPE))
        self.global_scope.declare_value(ValueSymbol(name="ok", type_val=OK_TYPE))
