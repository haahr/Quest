"""C Type mapping, identifier mangling, and operator dispatch for Quest C Transpiler."""

from __future__ import annotations

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QType,
)


def mangle_ident(name: str) -> str:
    """Mangles a Quest identifier into a C-safe identifier prefixed with qv_."""
    clean = name.replace(".", "_")
    return f"qv_{clean}"


def type_to_c_tag(t: QType) -> str:
    """Produces a deterministic, valid C identifier component for a QType."""
    if t == INT_TYPE:
        return "Int"
    if t == REAL_TYPE:
        return "Real"
    if t == BOOL_TYPE:
        return "Bool"
    if t == CHAR_TYPE:
        return "Char"
    if t == STRING_TYPE:
        return "String"
    if t == OK_TYPE:
        return "Ok"
    if isinstance(t, QTupleType):
        tags = [type_to_c_tag(f.type_val) for f in t.value_fields]
        return "QTuple_" + ("_".join(tags) if tags else "empty")
    if isinstance(t, QRecordType):
        sorted_fields = sorted(t.fields, key=lambda f: f.name)
        tags = [f"{f.name}_{type_to_c_tag(f.type_val)}" for f in sorted_fields]
        return "QRecord_" + ("_".join(tags) if tags else "empty")
    return "QVal"


def tuple_struct_name(t: QTupleType) -> str:
    """Returns the C struct tag name for a given QTupleType."""
    return type_to_c_tag(t)


def record_struct_name(t: QRecordType) -> str:
    """Returns the C struct tag name for a given QRecordType."""
    return type_to_c_tag(t)


def qtype_to_c_type(t: QType) -> str:
    """Maps a semantic Quest QType to its corresponding C scalar or pointer type representation."""
    if t == INT_TYPE:
        return "QInt"
    if t == REAL_TYPE:
        return "QReal"
    if t == BOOL_TYPE:
        return "QBool"
    if t == CHAR_TYPE:
        return "QChar"
    if t == STRING_TYPE:
        return "QString *"
    if t == OK_TYPE:
        return "void"
    if isinstance(t, QTupleType):
        return f"{tuple_struct_name(t)} *"
    if isinstance(t, QRecordType):
        return f"{record_struct_name(t)} *"
    return "QVal"


def qtype_to_name_str(t: QType) -> str:
    """Returns the human-readable Quest type name string for runtime diagnostics and printing."""
    if t == INT_TYPE:
        return "Int"
    if t == REAL_TYPE:
        return "Real"
    if t == BOOL_TYPE:
        return "Bool"
    if t == CHAR_TYPE:
        return "Char"
    if t == STRING_TYPE:
        return "String"
    if t == OK_TYPE:
        return "Ok"
    return str(t)
