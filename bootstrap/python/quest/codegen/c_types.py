"""C Type mapping, identifier mangling, and operator dispatch for Quest C Transpiler."""

from __future__ import annotations

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QType,
)


def mangle_ident(name: str) -> str:
    """Mangles a Quest identifier into a C-safe identifier prefixed with qv_."""
    clean = name.replace(".", "_")
    return f"qv_{clean}"


def qtype_to_c_type(t: QType) -> str:
    """Maps a semantic Quest QType to its corresponding C scalar type representation."""
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
