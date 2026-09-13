"""C Type mapping, identifier mangling, and operator dispatch for Quest C Transpiler."""

from __future__ import annotations

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QAllType,
    QArrayType,
    QExceptionType,
    QFunType,
    QOptionField,
    QOptionType,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QType,
    QTypeVar,
    QVariantField,
    QVariantType,
)


def mangle_ident(name: str) -> str:
    """Mangles a Quest identifier into a C-safe identifier prefixed with qv_."""
    clean = name.replace(".", "_")
    return f"qv_{clean}"


def mangle_module_ident(module_name: str, name: str) -> str:
    """Mangles a module-scoped Quest identifier into a C-safe identifier prefixed with qv_<mod>_."""
    clean_mod = module_name.replace(".", "_")
    clean_name = name.replace(".", "_")
    return f"qv_{clean_mod}_{clean_name}"


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
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return "Dynamic"
    if isinstance(t, QTupleType):
        tags = [type_to_c_tag(f.type_val) for f in t.value_fields]
        return "QTuple_" + ("_".join(tags) if tags else "empty")
    if isinstance(t, QRecordType):
        sorted_fields = sorted(t.fields, key=lambda f: f.name)
        tags = [f"{f.name}_{type_to_c_tag(f.type_val)}" for f in sorted_fields]
        return "QRecord_" + ("_".join(tags) if tags else "empty")
    if isinstance(t, (QFunType, QAllType)):
        return "QClosure"
    if isinstance(t, QTypeVar):
        return "QVal"
    if isinstance(t, QArrayType):
        return "QArray"
    if isinstance(t, QVariantType):
        return "QVariant"
    if isinstance(t, QExceptionType):
        return "QException"
    if isinstance(t, QOptionType):
        tags = []
        for o in t.options:
            if o.payload_type:
                tags.append(f"{o.name}_{type_to_c_tag(o.payload_type)}")
            else:
                tags.append(o.name)
        return "QOption_" + ("_".join(tags) if tags else "empty")
    return "QVal"


def tuple_struct_name(t: QTupleType) -> str:
    """Returns the C struct tag name for a given QTupleType."""
    return type_to_c_tag(t)


def record_struct_name(t: QRecordType, ctx: Optional[RecordNamingContext] = None) -> str:
    """Returns the C struct tag name for a given QRecordType."""
    if ctx is not None:
        name = ctx.get_or_create_name(t)
        return f"QT_{name}"
    return type_to_c_tag(t)


def option_struct_name(t: QOptionType) -> str:
    """Returns the C struct tag name for a given QOptionType."""
    return type_to_c_tag(t)


class RecordNamingContext:
    """Maintains sequential and alias-based naming for record types and evidence dictionaries."""

    def __init__(self) -> None:
        self.alias_by_shape: dict[tuple[tuple[str, str], ...], str] = {}
        self.seq_by_shape: dict[tuple[tuple[str, str], ...], str] = {}
        self.shape_to_canonical_name: dict[tuple[tuple[str, str], ...], str] = {}
        self._record_counter = 0

    def _shape_key(self, t: QRecordType) -> tuple[tuple[str, str], ...]:
        sorted_fields = sorted(t.fields, key=lambda f: f.name)
        return tuple((f.name, type_to_c_tag(f.type_val)) for f in sorted_fields)

    def register_alias(self, alias_name: str, t: QRecordType) -> None:
        key = self._shape_key(t)
        if key not in self.alias_by_shape:
            self.alias_by_shape[key] = alias_name
            self.shape_to_canonical_name[key] = alias_name

    def get_or_create_name(self, t: QRecordType, module_name: Optional[str] = None) -> str:
        key = self._shape_key(t)
        if key in self.shape_to_canonical_name:
            return self.shape_to_canonical_name[key]
        self._record_counter += 1
        prefix = f"{module_name}_" if module_name else ""
        name = f"{prefix}record{self._record_counter}"
        self.seq_by_shape[key] = name
        self.shape_to_canonical_name[key] = name
        return name

    def record_struct_name(self, t: QRecordType) -> str:
        name = self.get_or_create_name(t)
        return f"QT_{name}"

    def offset_dict_struct_name(self, t: QRecordType) -> str:
        name = self.get_or_create_name(t)
        return f"OffsetDict_{name}"

    def offset_dict_instance_name(self, target: QRecordType, source: QRecordType) -> str:
        tgt_name = self.get_or_create_name(target)
        src_name = self.get_or_create_name(source)
        return f"offsetdict_{tgt_name}_{src_name}"


def qtype_to_c_type(t: QType, ctx: Optional[RecordNamingContext] = None) -> str:
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
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return "QDynamic *"
    if isinstance(t, QTupleType):
        return f"{tuple_struct_name(t)} *"
    if isinstance(t, QRecordType):
        return f"{record_struct_name(t, ctx)} *"
    if isinstance(t, (QFunType, QAllType)):
        return "QClosure *"
    if isinstance(t, QArrayType):
        return "QArray *"
    if isinstance(t, QVariantType):
        return "QVariant *"
    if isinstance(t, QExceptionType):
        return "const QException *"
    if isinstance(t, QOptionType):
        return f"{option_struct_name(t)} *"
    if isinstance(t, QTypeVar):
        return "QVal"
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
