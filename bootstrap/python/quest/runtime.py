"""Quest Runtime Values, Memory Model, Identity, and Structural Equality.

Implements the runtime value hierarchy (QValue) and operational semantics for
Step 3 (Tree-Walking Interpreter & REPL), including:
- Primitive values (Ok, Bool, Int, Real, Char, String)
- Compound aggregates (Record, Tuple, Array)
- Sum types (Variant, Option)
- First-class functions and closures (QClosure, QBuiltinFun)
- Mutable heap cells (QRef)
- Dynamic and Exception envelopes (QDynamicVal, QExceptionVal)
- Cardelli 'is'/'isnot' identity predicate and recursive structural equality.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Optional


# ============================================================================
# 1. Base Runtime Value
# ============================================================================

class QValue(ABC):
    """Abstract base class for all runtime Quest values."""

    @property
    @abstractmethod
    def type_name(self) -> str:
        """Returns the human-readable Quest type name of this value."""
        pass

    @abstractmethod
    def to_str(self, visited: Optional[set[int]] = None) -> str:
        """Formats the value into canonical Quest text with cycle detection."""
        pass

    def __str__(self) -> str:
        return self.to_str()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_str()})"


# ============================================================================
# 2. Primitive Values
# ============================================================================

class QOk(QValue):
    """Singleton unit value of type Ok."""

    _instance: Optional[QOk] = None

    def __new__(cls) -> QOk:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def type_name(self) -> str:
        return "Ok"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        return "ok"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, QOk)

    def __hash__(self) -> int:
        return hash("QOk")


OK_VALUE = QOk()


class QBool(QValue):
    """Boolean value (true or false)."""

    _true_instance: Optional[QBool] = None
    _false_instance: Optional[QBool] = None

    def __new__(cls, value: bool) -> QBool:
        if value:
            if cls._true_instance is None:
                inst = super().__new__(cls)
                inst._value = True
                cls._true_instance = inst
            return cls._true_instance
        else:
            if cls._false_instance is None:
                inst = super().__new__(cls)
                inst._value = False
                cls._false_instance = inst
            return cls._false_instance

    @property
    def value(self) -> bool:
        return self._value

    @property
    def type_name(self) -> str:
        return "Bool"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        return "true" if self._value else "false"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QBool):
            return self._value == other._value
        return False

    def __hash__(self) -> int:
        return hash(self._value)


TRUE_VALUE = QBool(True)
FALSE_VALUE = QBool(False)


class QInt(QValue):
    """Signed 64-bit integer value."""

    def __init__(self, value: int):
        self.value = int(value)

    @property
    def type_name(self) -> str:
        return "Int"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        return str(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QInt):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


class QReal(QValue):
    """64-bit floating point real number."""

    def __init__(self, value: float):
        self.value = float(value)

    @property
    def type_name(self) -> str:
        return "Real"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        res = str(self.value)
        if "e" not in res and "." not in res:
            res += ".0"
        return res

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QReal):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


class QChar(QValue):
    """Single ASCII character value."""

    def __init__(self, value: str):
        if len(value) != 1:
            raise ValueError(f"QChar must be a single character, got: {value!r}")
        self.value = value

    @property
    def type_name(self) -> str:
        return "Char"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        char = self.value
        if char == "\n":
            escaped = "\\n"
        elif char == "\t":
            escaped = "\\t"
        elif char == "\r":
            escaped = "\\r"
        elif char == "\\":
            escaped = "\\\\"
        elif char == "'":
            escaped = "\\'"
        elif 32 <= ord(char) <= 126:
            escaped = char
        else:
            escaped = f"\\x{ord(char):02x}"
        return f"'{escaped}'"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QChar):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


class QString(QValue):
    """String literal value."""

    def __init__(self, value: str):
        self.value = str(value)

    @property
    def type_name(self) -> str:
        return "String"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        escaped_parts: list[str] = []
        for char in self.value:
            if char == "\n":
                escaped_parts.append("\\n")
            elif char == "\t":
                escaped_parts.append("\\t")
            elif char == "\r":
                escaped_parts.append("\\r")
            elif char == "\\":
                escaped_parts.append("\\\\")
            elif char == '"':
                escaped_parts.append('\\"')
            elif 32 <= ord(char) <= 126:
                escaped_parts.append(char)
            else:
                escaped_parts.append(f"\\x{ord(char):02x}")
        return f'"{"".join(escaped_parts)}"'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QString):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


# ============================================================================
# 3. Compound Aggregates
# ============================================================================

class QRecord(QValue):
    """Unordered collection of labeled fields."""

    def __init__(self, fields: Optional[dict[str, QValue]] = None):
        self.fields: dict[str, QValue] = dict(fields) if fields is not None else {}

    @property
    def type_name(self) -> str:
        return "Record"

    def get(self, field_name: str) -> QValue:
        if field_name not in self.fields:
            raise KeyError(f"Record has no field '{field_name}'")
        return self.fields[field_name]

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if visited is None:
            visited = set()
        if id(self) in visited:
            return "record ... end"
        visited.add(id(self))

        try:
            if not self.fields:
                return "record end"
            sorted_items = sorted(self.fields.items(), key=lambda kv: kv[0])
            fields_str = " ".join(f"{name}={val.to_str(visited)}" for name, val in sorted_items)
            return f"record {fields_str} end"
        finally:
            visited.remove(id(self))


class QTuple(QValue):
    """Ordered sequence of values, with optional field labels."""

    def __init__(
        self,
        elements: tuple[QValue, ...],
        labels: Optional[tuple[Optional[str], ...]] = None,
    ):
        self.elements = tuple(elements)
        if labels is not None:
            if len(labels) != len(elements):
                raise ValueError("labels length must match elements length")
            self.labels: Optional[tuple[Optional[str], ...]] = tuple(labels)
            self._name_to_index: dict[str, int] = {
                name: idx for idx, name in enumerate(labels) if name is not None
            }
        else:
            self.labels = None
            self._name_to_index = {}

    @property
    def type_name(self) -> str:
        return "Tuple"

    def get_by_index(self, index: int) -> QValue:
        if index < 0 or index >= len(self.elements):
            raise IndexError(f"Tuple index {index} out of bounds [0, {len(self.elements)})")
        return self.elements[index]

    def get_by_name(self, name: str) -> QValue:
        if name not in self._name_to_index:
            raise KeyError(f"Tuple has no labeled component '{name}'")
        return self.elements[self._name_to_index[name]]

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if visited is None:
            visited = set()
        if id(self) in visited:
            return "tuple ... end"
        visited.add(id(self))

        try:
            if not self.elements:
                return "tuple end"
            parts: list[str] = []
            for idx, elem in enumerate(self.elements):
                label = self.labels[idx] if self.labels and idx < len(self.labels) else None
                elem_str = elem.to_str(visited)
                if label:
                    parts.append(f"{label}={elem_str}")
                else:
                    parts.append(elem_str)
            return f"tuple {' '.join(parts)} end"
        finally:
            visited.remove(id(self))


class QArray(QValue):
    """Mutable fixed-size array of Quest values."""

    def __init__(self, elements: list[QValue]):
        self.elements: list[QValue] = list(elements)

    @property
    def type_name(self) -> str:
        return "Array"

    def size(self) -> int:
        return len(self.elements)

    def get(self, index: int) -> QValue:
        if index < 0 or index >= len(self.elements):
            raise IndexError(f"Array index {index} out of bounds [0, {len(self.elements)})")
        return self.elements[index]

    def set(self, index: int, value: QValue) -> None:
        if index < 0 or index >= len(self.elements):
            raise IndexError(f"Array index {index} out of bounds [0, {len(self.elements)})")
        self.elements[index] = value

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if visited is None:
            visited = set()
        if id(self) in visited:
            return "array of ... end"
        visited.add(id(self))

        try:
            if not self.elements:
                return "array of end"
            elems_str = " ".join(e.to_str(visited) for e in self.elements)
            return f"array of {elems_str} end"
        finally:
            visited.remove(id(self))


# ============================================================================
# 4. Sum / Disjoint Union Values
# ============================================================================

class QVariant(QValue):
    """Unordered tagged variant value with optional payload."""

    def __init__(self, tag: str, payload: Optional[QValue] = None):
        self.tag = tag
        self.payload = payload

    @property
    def type_name(self) -> str:
        return "Variant"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if self.payload is not None:
            return f"variant {self.tag} with {self.payload.to_str(visited)} end"
        return f"variant {self.tag} end"


class QOption(QValue):
    """Ordered tagged option value with optional payload."""

    def __init__(self, tag: str, payload: Optional[QValue] = None):
        self.tag = tag
        self.payload = payload

    @property
    def type_name(self) -> str:
        return "Option"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if self.payload is not None:
            return f"option {self.tag} with {self.payload.to_str(visited)} end"
        return f"option {self.tag} end"


# ============================================================================
# 5. Functions & Closures
# ============================================================================

class QClosure(QValue):
    """First-class function closure capturing its lexical environment."""

    def __init__(
        self,
        params: tuple[str, ...],
        body: Any,
        env: Any,
        name: Optional[str] = None,
    ):
        self.params = tuple(params)
        self.body = body
        self.env = env
        self.name = name

    @property
    def type_name(self) -> str:
        return "Function"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if self.name:
            return f"<fun:{self.name}>"
        return "<fun>"


class QBuiltinFun(QValue):
    """Built-in host function wrapper."""

    def __init__(
        self,
        name: str,
        fn: Callable[..., QValue],
        doc: Optional[str] = None,
    ):
        self.name = name
        self.fn = fn
        self.doc = doc

    @property
    def type_name(self) -> str:
        return "BuiltinFunction"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        return f"<builtin:{self.name}>"


# ============================================================================
# 6. Mutable Heap Cells
# ============================================================================

class QRef(QValue):
    """Mutable heap reference cell for 'var' variables and assignable fields."""

    def __init__(self, value: QValue):
        self.value = value

    @property
    def type_name(self) -> str:
        return f"Ref({self.value.type_name})"

    def deref(self) -> QValue:
        return self.value

    def assign(self, new_value: QValue) -> None:
        self.value = new_value

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if visited is None:
            visited = set()
        if id(self) in visited:
            return "ref(...)"
        visited.add(id(self))
        try:
            return f"ref({self.value.to_str(visited)})"
        finally:
            visited.remove(id(self))


# ============================================================================
# 7. Dynamic & Exception Envelopes
# ============================================================================

class QDynamicVal(QValue):
    """Dynamically typed value packaging a value together with its type."""

    def __init__(self, value: QValue, type_val: Any):
        self.value = value
        self.type_val = type_val

    @property
    def type_name(self) -> str:
        return "Dynamic"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        val_str = self.value.to_str(visited)
        return f"dynamic({val_str} : {self.type_val})"


class QExceptionVal(QValue):
    """Runtime exception value with tag name and optional payload."""

    def __init__(self, name: str, payload: Optional[QValue] = None):
        self.name = name
        self.payload = payload

    @property
    def type_name(self) -> str:
        return "Exception"

    def to_str(self, visited: Optional[set[int]] = None) -> str:
        if self.payload is not None:
            return f"exception {self.name} with {self.payload.to_str(visited)}"
        return f"exception {self.name}"


# ============================================================================
# 8. Predicates: Identity & Structural Equality
# ============================================================================

def qvalue_is(v1: QValue, v2: QValue) -> bool:
    """Implements Quest's 'is' equality predicate (Cardelli Section 3.1).

    Value equality for primitives (Ok, Bool, Char, Int, Real);
    object identity (same memory location) for all other types (String, Array,
    Record, Tuple, Variant, Option, Closure, Ref, Dynamic, Exception).
    """
    if type(v1) is not type(v2):
        return False

    if isinstance(v1, QOk):
        return isinstance(v2, QOk)
    if isinstance(v1, QBool):
        return v1.value is v2.value  # type: ignore[attr-defined]
    if isinstance(v1, (QInt, QReal, QChar)):
        return v1.value == v2.value  # type: ignore[attr-defined]

    # For all other types: pointer identity
    return v1 is v2


def qvalue_structural_eq(
    v1: QValue,
    v2: QValue,
    visited: Optional[set[tuple[int, int]]] = None,
) -> bool:
    """Deep recursive structural equality with cycle detection (for testing)."""
    if v1 is v2:
        return True

    if type(v1) is not type(v2):
        return False

    if visited is None:
        visited = set()

    pair = (id(v1), id(v2))
    if pair in visited:
        return True
    visited.add(pair)

    if isinstance(v1, QOk):
        return isinstance(v2, QOk)

    if isinstance(v1, (QBool, QInt, QReal, QChar, QString)):
        return v1.value == v2.value  # type: ignore[attr-defined]

    if isinstance(v1, QRecord):
        assert isinstance(v2, QRecord)
        if set(v1.fields.keys()) != set(v2.fields.keys()):
            return False
        for k in v1.fields:
            if not qvalue_structural_eq(v1.fields[k], v2.fields[k], visited):
                return False
        return True

    if isinstance(v1, QTuple):
        assert isinstance(v2, QTuple)
        if len(v1.elements) != len(v2.elements):
            return False
        if v1.labels != v2.labels:
            return False
        for e1, e2 in zip(v1.elements, v2.elements):
            if not qvalue_structural_eq(e1, e2, visited):
                return False
        return True

    if isinstance(v1, QArray):
        assert isinstance(v2, QArray)
        if len(v1.elements) != len(v2.elements):
            return False
        for e1, e2 in zip(v1.elements, v2.elements):
            if not qvalue_structural_eq(e1, e2, visited):
                return False
        return True

    if isinstance(v1, (QVariant, QOption)):
        assert isinstance(v2, (QVariant, QOption))
        if v1.tag != v2.tag:
            return False
        if (v1.payload is None) != (v2.payload is None):
            return False
        if v1.payload is not None and v2.payload is not None:
            return qvalue_structural_eq(v1.payload, v2.payload, visited)
        return True

    if isinstance(v1, QRef):
        assert isinstance(v2, QRef)
        return qvalue_structural_eq(v1.value, v2.value, visited)

    if isinstance(v1, QDynamicVal):
        assert isinstance(v2, QDynamicVal)
        if v1.type_val != v2.type_val:
            return False
        return qvalue_structural_eq(v1.value, v2.value, visited)

    if isinstance(v1, QExceptionVal):
        assert isinstance(v2, QExceptionVal)
        if v1.name != v2.name:
            return False
        if (v1.payload is None) != (v2.payload is None):
            return False
        if v1.payload is not None and v2.payload is not None:
            return qvalue_structural_eq(v1.payload, v2.payload, visited)
        return True

    # Closures and Builtins fallback to pointer identity
    return v1 is v2


def qvalue_to_str(val: QValue) -> str:
    """Canonical string formatter for any Quest runtime value."""
    return val.to_str()
