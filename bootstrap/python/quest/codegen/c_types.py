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
    resolve_record_bound,
    resolve_variant_bound,
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
        return f"QArray_{type_to_c_tag(t.element_type)}"
    if isinstance(t, QVariantType):
        tags = []
        for v in t.variants:
            if v.type_val:
                tags.append(f"{v.name}_{type_to_c_tag(v.type_val)}")
            else:
                tags.append(v.name)
        return "QVariant_" + ("_".join(tags) if tags else "empty")
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
    if isinstance(t, QRecordType) or resolve_record_bound(t) is not None:
        return "QRecordVal"
    if isinstance(t, (QFunType, QAllType)):
        return "QClosure *"
    if isinstance(t, QArrayType):
        elem = t.element_type
        if isinstance(elem, QRecordType) or resolve_record_bound(elem) is not None:
            return "QArrayWideRecord *"
        if isinstance(elem, QVariantType) or resolve_variant_bound(elem) is not None:
            return "QArrayWideVariant *"
        return "QArray *"
    if isinstance(t, QVariantType) or resolve_variant_bound(t) is not None:
        return "QVariantVal"
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


def c_string_literal(s: str) -> str:
    """Escapes a Python string into a safe C string literal."""
    parts = []
    for ch in s:
        if ch == "\"":
            parts.append("\\\"")
        elif ch == "\\":
            parts.append("\\\\")
        elif ch == "\n":
            parts.append("\\n")
        elif ch == "\t":
            parts.append("\\t")
        elif ch == "\r":
            parts.append("\\r")
        elif 32 <= ord(ch) < 127:
            parts.append(ch)
        else:
            parts.append(f"\\x{ord(ch):02x}")
    return "\"" + "".join(parts) + "\""


def c_char_literal(ch: str) -> str:
    """Escapes a single character into a safe C character literal."""
    if ch == "'":
        return "'\\''"
    if ch == "\\":
        return "'\\\\'"
    if ch == "\n":
        return "'\\n'"
    if ch == "\t":
        return "'\\t'"
    if ch == "\r":
        return "'\\r'"
    if 32 <= ord(ch) < 127:
        return f"'{ch}'"
    return f"'\\x{ord(ch):02x}'"


def qval_wrap(expr_str: str, t: QType) -> str:
    """Wraps a scalar or pointer expression into a QVal union initializer."""
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    if resolve_record_bound(t) is not None:
        return f"((QVal){{ .p = (void *)quest_record_box({expr_str}) }})"
    if resolve_variant_bound(t) is not None:
        return f"((QVal){{ .p = (void *)quest_variant_box({expr_str}) }})"
    if isinstance(t, QTypeVar):
        return expr_str
    if t == INT_TYPE or t == BOOL_TYPE or t == CHAR_TYPE:
        return f"((QVal){{ .i = (int64_t)({expr_str}) }})"
    if t == REAL_TYPE:
        return f"((QVal){{ .r = (double)({expr_str}) }})"
    if t == STRING_TYPE or isinstance(
        t, (QTupleType, QFunType, QAllType, QArrayType, QOptionType, QExceptionType)
    ):
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    return f"((QVal){{ .u = 0 }})"


def qval_unwrap(qval_expr: str, t: QType, ctx: Optional[RecordNamingContext] = None) -> str:
    """Extracts the underlying concrete scalar or pointer from a QVal expression."""
    if t == DYNAMIC_TYPE or (isinstance(t, QTypeVar) and t.name == "Dynamic.T"):
        return f"((QDynamic *)({qval_expr}.p))"
    if resolve_record_bound(t) is not None:
        return f"(*((QRecordVal *)({qval_expr}.p)))"
    if resolve_variant_bound(t) is not None:
        return f"(*((QVariantVal *)({qval_expr}.p)))"
    if isinstance(t, QTypeVar):
        return qval_expr
    if t in (INT_TYPE, BOOL_TYPE, CHAR_TYPE):
        return f"({qval_expr}.i)"
    if t == REAL_TYPE:
        return f"({qval_expr}.r)"
    if t == OK_TYPE:
        return "((void)0)"
    c_t = qtype_to_c_type(t, ctx)
    return f"(({c_t})({qval_expr}.p))"


def closure_fn_ptr_type(fun_type: QType, ctx: Optional[RecordNamingContext] = None) -> str:
    """Constructs the C function pointer cast type for invoking a closure."""
    quantifiers: tuple[Any, ...] = ()
    cur_type = fun_type
    while isinstance(cur_type, QAllType):
        quantifiers = quantifiers + cur_type.quantifiers
        cur_type = cur_type.body

    if isinstance(cur_type, QFunType):
        if cur_type.result_type == OK_TYPE:
            ret_c = "void"
        elif isinstance(cur_type.result_type, QRecordType):
            ret_c = "QRecordVal"
        else:
            ret_c = qtype_to_c_type(cur_type.result_type, ctx)
        param_types = ["void *"]
        # Quantifier descriptors appear immediately after env
        for _ in quantifiers:
            param_types.append("const QTypeDescriptor *")
        for p in cur_type.params:
            param_types.append(qtype_to_c_type(p.type_val, ctx))
        sig = ", ".join(param_types)
        return f"{ret_c} (*)({sig})"
    return "void * (*)(void *, ...)"


def is_record_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QRecordType) or not isinstance(t, QRecordType):
        return False
    s_fields = {f.name: f.type_val for f in s.fields}
    for f in t.fields:
        if f.name not in s_fields or s_fields[f.name] != f.type_val:
            return False
    return True


def is_tuple_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QTupleType) or not isinstance(t, QTupleType):
        return False
    if len(s.value_fields) < len(t.value_fields):
        return False
    for i in range(len(t.value_fields)):
        if s.value_fields[i].type_val != t.value_fields[i].type_val:
            return False
    return True


def is_variant_subtype(s: QType, t: QType) -> bool:
    if not isinstance(s, QVariantType) or not isinstance(t, QVariantType):
        return False
    t_map = {v.name: v.type_val for v in t.variants}
    for v in s.variants:
        if v.name not in t_map or v.type_val != t_map[v.name]:
            return False
    return True
