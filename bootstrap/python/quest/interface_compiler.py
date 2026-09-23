"""Quest Interface Compiler (Phase 4.16 Step 1).

Compiles interface files (.int.quest) to:
1. .qi: Portable, cycle-safe JSON/JSOG metadata encoded using shadow Quest record types
   compatible with dynamic.extern / dynamic.intern.
2. .h: C header file providing include guards, dependency includes, abstract type erasure
   to QVal, manifest type definitions, and function signature typedefs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import quest.ast as ast
from quest.codegen.c_types import qtype_to_c_type
from quest.diagnostics import QuestTypeError
from quest.dynamic_json import jsog_decode, jsog_encode, parse_type_string
from quest.elaborate_types import elaborate_kind, elaborate_type
from quest.env import Environment, Scope, TypeSymbol, ValueSymbol
from quest.grammar import parse_quest_program
from quest.modules import elaborate_interface
from quest.runtime import (
    FALSE_VALUE,
    TRUE_VALUE,
    QArray,
    QBool,
    QDynamicVal,
    QRecord,
    QString,
)
from quest.tokenizer import Tokenizer
from quest.tokens import SourceMap
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    QAbstractType,
    QAllType,
    QArrayType,
    QFunType,
    QOptionType,
    QParam,
    QPathType,
    QQuantifier,
    QRecordField,
    QRecordType,
    QTupleComponent,
    QTupleField,
    QTupleType,
    QType,
    QTypeVar,
    QVariantField,
    QVariantType,
)

QI_SCHEMA_TYPE_STR = (
    "Record "
    "imports: Array(String) "
    "name: String "
    "types: Array(Record isManifest: Bool kind: String manifestType: String name: String end) "
    "values: Array(Record isPoly: Bool name: String typeSig: String end) "
    "end"
)


def format_type_for_qi(t: QType) -> str:
    """Formats a semantic QType into canonical Quest type syntax for .qi metadata."""
    t = t.prune() if hasattr(t, "prune") else t
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
    if t == DYNAMIC_TYPE:
        return "Dynamic.T"

    if isinstance(t, QTypeVar):
        return t.name
    if isinstance(t, QAbstractType):
        return t.name
    if isinstance(t, QPathType):
        return f"{t.module_name}.{t.type_name}"

    if isinstance(t, QArrayType):
        return f"Array({format_type_for_qi(t.element_type)})"

    if isinstance(t, QRecordType):
        fields = " ".join(f"{f.name}: {format_type_for_qi(f.type_val)}" for f in t.fields)
        return f"Record {fields} end" if fields else "Record end"

    if isinstance(t, QTupleType):
        parts: list[str] = []
        for f in t.fields:
            if isinstance(f, QTupleField):
                if f.name:
                    parts.append(f"{f.name}: {format_type_for_qi(f.type_val)}")
                else:
                    parts.append(format_type_for_qi(f.type_val))
        return f"Tuple {' '.join(parts)} end" if parts else "Tuple end"

    if isinstance(t, QVariantType):
        variants = " ".join(
            f"{v.name}: {format_type_for_qi(v.type_val)}" if v.type_val != OK_TYPE else v.name
            for v in t.variants
        )
        return f"Variant {variants} end" if variants else "Variant end"

    if isinstance(t, QOptionType):
        opts = " ".join(
            f"{o.name}: {format_type_for_qi(o.type_val)}" if o.type_val != OK_TYPE else o.name
            for o in t.variants
        )
        return f"Option {opts} end" if opts else "Option end"

    if isinstance(t, QFunType):
        params_str = " ".join(
            f"{p.name}: {format_type_for_qi(p.type_val)}" if p.name else format_type_for_qi(p.type_val)
            for p in t.params
        )
        return f"All({params_str}) {format_type_for_qi(t.result_type)}"

    if isinstance(t, QAllType):
        quants_str = " ".join(f"{q.name}::{q.bound}" for q in t.quantifiers)
        if isinstance(t.body, QFunType):
            params_str = " ".join(
                f"{p.name}: {format_type_for_qi(p.type_val)}" if p.name else format_type_for_qi(p.type_val)
                for p in t.body.params
            )
            return f"All({quants_str} {params_str}) {format_type_for_qi(t.body.result_type)}"
        return f"All({quants_str}) {format_type_for_qi(t.body)}"

    return str(t)


def _parse_and_elaborate_type_in_env(type_str: str, env: Environment) -> QType:
    """Parses and elaborates a Quest type string within an existing environment/scope."""
    source_map = SourceMap(type_str, "<type>")
    tokens = Tokenizer(type_str, "<type>").tokenize_all()
    ast_t = parse_quest_program(tokens, source_map, target="Type")
    return elaborate_type(ast_t, env)


def compile_interface_to_qi(decl: ast.InterfaceDecl, iface_scope: Scope) -> str:
    """Serializes interface declarations to portable JSON/JSOG .qi format using shadow Quest records."""
    imports_elems = [QString(imp.interface_name) for imp in decl.imports]
    imports_arr = QArray(imports_elems)

    type_records: list[QRecord] = []
    value_records: list[QRecord] = []

    # Collect types
    for sig in decl.signatures:
        if isinstance(sig, ast.TypeFormal):
            kind_str = "TYPE" if sig.bound is None or isinstance(sig.bound, ast.KindType) else str(sig.bound)
            type_records.append(
                QRecord(
                    {
                        "name": QString(sig.name),
                        "kind": QString(kind_str),
                        "isManifest": FALSE_VALUE,
                        "manifestType": QString(""),
                    }
                )
            )
        elif isinstance(sig, ast.LetTypeBinding):
            type_sym = iface_scope.lookup_type_local(sig.name)
            concrete_t = type_sym.definition if type_sym and type_sym.definition else None
            m_type_str = format_type_for_qi(concrete_t) if concrete_t else str(sig.type_val)
            type_records.append(
                QRecord(
                    {
                        "name": QString(sig.name),
                        "kind": QString("TYPE"),
                        "isManifest": TRUE_VALUE,
                        "manifestType": QString(m_type_str),
                    }
                )
            )
        elif isinstance(sig, ast.FieldSig) and sig.name:
            val_sym = iface_scope.lookup_value_local(sig.name)
            val_t = val_sym.type_val if val_sym else None
            sig_str = format_type_for_qi(val_t) if val_t else ""
            is_poly = isinstance(val_t, QAllType)
            value_records.append(
                QRecord(
                    {
                        "name": QString(sig.name),
                        "typeSig": QString(sig_str),
                        "isPoly": TRUE_VALUE if is_poly else FALSE_VALUE,
                    }
                )
            )

    desc_record = QRecord(
        {
            "name": QString(decl.name),
            "imports": imports_arr,
            "types": QArray(type_records),
            "values": QArray(value_records),
        }
    )

    schema_type = parse_type_string(QI_SCHEMA_TYPE_STR)
    dyn = QDynamicVal(desc_record, schema_type)
    return jsog_encode(dyn)


def compile_interface_to_header(decl: ast.InterfaceDecl, iface_scope: Scope) -> str:
    """Generates the C header (.h) for an interface declaration."""
    guard_name = f"QUEST_INTF_{decl.name.upper()}_H"
    lines: list[str] = [
        f"/* Generated by Quest compiler for interface {decl.name} */",
        f"#ifndef {guard_name}",
        f"#define {guard_name}",
        "",
        '#include "quest_runtime.h"',
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
    ]

    # Imported interfaces
    if decl.imports:
        lines.append("/* --- Imported Interfaces --- */")
        for imp in decl.imports:
            lines.append(f'#include "{imp.interface_name.lower()}.h"')
        lines.append("")

    # Abstract types (erased to QVal in C)
    lines.append("/* --- Type Declarations --- */")
    has_types = False
    for sig in decl.signatures:
        if isinstance(sig, ast.TypeFormal):
            has_types = True
            kind_desc = (
                "TYPE"
                if sig.bound is None or isinstance(sig.bound, ast.KindType)
                else str(sig.bound)
            )
            lines.append(f"/* Abstract type {sig.name}::{kind_desc} */")
            lines.append(f"typedef QVal quest_type_{decl.name}_{sig.name};")
        elif isinstance(sig, ast.LetTypeBinding):
            has_types = True
            type_sym = iface_scope.lookup_type_local(sig.name)
            concrete_t = type_sym.definition if type_sym and type_sym.definition else None
            c_type_name = qtype_to_c_type(concrete_t) if concrete_t else "QVal"
            lines.append(f"/* Manifest type {sig.name} */")
            if isinstance(concrete_t, QRecordType):
                lines.append(f"typedef struct quest_rec_{decl.name}_{sig.name} {{")
                for f in concrete_t.fields:
                    f_c_type = qtype_to_c_type(f.type_val)
                    lines.append(f"    {f_c_type} {f.name};")
                lines.append(f"}} quest_rec_{decl.name}_{sig.name};")
                lines.append(f"typedef QRecordVal quest_type_{decl.name}_{sig.name};")
            else:
                lines.append(f"typedef {c_type_name} quest_type_{decl.name}_{sig.name};")
    if not has_types:
        lines.append("/* (No types declared) */")
    lines.append("")

    # Member signatures as function pointer typedefs
    lines.append(f"/* --- Member Signatures for Interface {decl.name} --- */")
    has_values = False
    for sig in decl.signatures:
        if isinstance(sig, ast.FieldSig) and sig.name:
            has_values = True
            val_sym = iface_scope.lookup_value_local(sig.name)
            val_t = val_sym.type_val if val_sym else None
            if isinstance(val_t, (QFunType, QAllType)):
                inner_fn = val_t.body if isinstance(val_t, QAllType) else val_t
                ret_c_type = qtype_to_c_type(inner_fn.result_type)
                param_c_types: list[str] = []
                if isinstance(val_t, QAllType):
                    for q in val_t.quantifiers:
                        param_c_types.append(f"const QTypeDescriptor *desc_{q.name}")
                if isinstance(inner_fn, QFunType):
                    for p in inner_fn.params:
                        param_c_types.append(f"{qtype_to_c_type(p.type_val)} {p.name or 'arg'}")
                params_decl = ", ".join(param_c_types) if param_c_types else "void"
                lines.append(f"/* {sig.name}: {format_type_for_qi(val_t)} */")
                lines.append(
                    f"typedef {ret_c_type} (*quest_sig_{decl.name}_{sig.name})({params_decl});"
                )
            else:
                c_val_type = qtype_to_c_type(val_t) if val_t else "QVal"
                lines.append(f"/* {sig.name}: {format_type_for_qi(val_t)} */")
                lines.append(f"typedef {c_val_type} quest_sig_{decl.name}_{sig.name};")
    if not has_values:
        lines.append("/* (No values declared) */")
    lines.append("")

    lines.extend([
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        f"#endif /* {guard_name} */",
        "",
    ])

    return "\n".join(lines)


def compile_interface_file(
    file_path: Path,
    output_dir: Optional[Path] = None,
    include_paths: Optional[list[Path]] = None,
) -> tuple[Path, Path]:
    """Compiles a .int.quest file to .h and .qi files."""
    try:
        source_text = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise QuestTypeError(f"Error reading interface file '{file_path}': {err}")

    source_map = SourceMap(source_text, str(file_path))
    tokens = Tokenizer(source_text, str(file_path)).tokenize_all()
    prog = parse_quest_program(tokens, source_map)

    if not isinstance(prog, ast.Program) or len(prog.phrases) != 1:
        raise QuestTypeError(
            f"Interface file '{file_path.name}' must contain exactly one interface declaration"
        )

    decl = prog.phrases[0]
    if not isinstance(decl, ast.InterfaceDecl):
        raise QuestTypeError(
            f"Expected interface declaration in '{file_path.name}', but found {type(decl).__name__}"
        )

    env = Environment()
    if include_paths:
        env.include_paths = list(include_paths)
    env.current_dir = file_path.parent
    typed_iface = elaborate_interface(decl, env)

    qi_content = compile_interface_to_qi(decl, typed_iface.scope)
    h_content = compile_interface_to_header(decl, typed_iface.scope)

    target_dir = output_dir if output_dir is not None else file_path.parent
    base_name = file_path.name
    if base_name.endswith(".int.quest"):
        stem = base_name[:-10]
    else:
        stem = file_path.stem

    qi_path = target_dir / f"{stem.lower()}.qi"
    h_path = target_dir / f"{stem.lower()}.h"

    qi_path.write_text(qi_content, encoding="utf-8")
    h_path.write_text(h_content, encoding="utf-8")

    return h_path, qi_path


def load_interface_from_qi_file(file_path: Path, env: Environment) -> Scope:
    """Loads and deserializes an interface Scope directly from a precompiled .qi file."""
    try:
        raw_json = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise QuestTypeError(f"Error reading .qi file '{file_path}': {err}")

    dyn = jsog_decode(raw_json)
    if not isinstance(dyn.value, QRecord):
        raise QuestTypeError(f"Malformed .qi metadata in '{file_path}'")

    rec = dyn.value
    name = str(rec.fields["name"].value) if "name" in rec.fields else file_path.stem
    iface_scope = Scope(name=f"interface_{name}", parent=env.current_scope)

    # 1. Resolve imported interfaces
    if "imports" in rec.fields and isinstance(rec.fields["imports"], QArray):
        from quest.module_loader import load_interface

        for imp_elem in rec.fields["imports"].elements:
            imp_name = str(imp_elem.value)
            imp_scope = env.lookup_interface(imp_name)
            if imp_scope is None:
                imp_scope = load_interface(imp_name, env)
            for t_name, t_sym in imp_scope.types.items():
                iface_scope.declare_type(t_sym)
            for k_name, k_sym in imp_scope.kinds.items():
                iface_scope.declare_kind(k_sym)

    # 2. Declare types
    saved_scope = env.current_scope
    env.current_scope = iface_scope
    try:
        if "types" in rec.fields and isinstance(rec.fields["types"], QArray):
            for t_item in rec.fields["types"].elements:
                if isinstance(t_item, QRecord):
                    t_name = str(t_item.fields["name"].value)
                    is_manifest = (
                        t_item.fields["isManifest"].value
                        if "isManifest" in t_item.fields
                        else False
                    )
                    kind_str = str(t_item.fields["kind"].value)
                    manifest_str = str(t_item.fields["manifestType"].value)

                    bound_kind = TYPE_KIND
                    if kind_str and kind_str != "TYPE":
                        try:
                            bound_kind = _parse_and_elaborate_type_in_env(kind_str, env)
                        except Exception:
                            bound_kind = TYPE_KIND

                    concrete_def = None
                    if is_manifest and manifest_str:
                        concrete_def = _parse_and_elaborate_type_in_env(manifest_str, env)

                    sym_id = env.fresh_symbol_id()
                    type_sym = TypeSymbol(
                        name=t_name,
                        symbol_id=sym_id,
                        kind=bound_kind,
                        definition=concrete_def,
                    )
                    iface_scope.declare_type(type_sym)

        # 3. Declare values
        if "values" in rec.fields and isinstance(rec.fields["values"], QArray):
            for v_item in rec.fields["values"].elements:
                if isinstance(v_item, QRecord):
                    v_name = str(v_item.fields["name"].value)
                    type_sig_str = str(v_item.fields["typeSig"].value)
                    val_type = _parse_and_elaborate_type_in_env(type_sig_str, env)
                    val_sym = ValueSymbol(name=v_name, type_val=val_type)
                    iface_scope.declare_value(val_sym)
    finally:
        env.current_scope = saved_scope

    env.register_interface(name, iface_scope)
    return iface_scope
