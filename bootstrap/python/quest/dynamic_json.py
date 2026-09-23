"""JSON and JSOG serialization and deserialization for Quest dynamic values.

Provides cycle-safe serialization (`jsog_encode`) and deserialization (`jsog_decode`)
for `dynamic.extern` and `dynamic.intern`, modeling enums/variants after Rust's Serde
(external tagging) and representing object graph cycles with JSOG @id and @ref annotations.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from quest.interpreter import DYNAMIC_ERROR_EXC, QuestException
from quest.runtime import (
    FALSE_VALUE,
    OK_VALUE,
    TRUE_VALUE,
    QArray,
    QBool,
    QBuiltinFun,
    QChar,
    QClosure,
    QDynamicVal,
    QInt,
    QOk,
    QOption,
    QReader,
    QReal,
    QRecord,
    QRef,
    QString,
    QTuple,
    QValue,
    QVariant,
    QWriter,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QArrayType,
    QCharType,
    QIntType,
    QOptionType,
    QRealType,
    QRecordType,
    QTupleType,
    QType,
    QVariantType,
    QVarType,
)


def parse_type_string(type_str: str) -> QType:
    """Parses a Quest type string into a semantic QType."""
    base_types: dict[str, QType] = {
        "Int": INT_TYPE,
        "Real": REAL_TYPE,
        "Bool": BOOL_TYPE,
        "Char": CHAR_TYPE,
        "String": STRING_TYPE,
        "Ok": OK_TYPE,
        "Dynamic": DYNAMIC_TYPE,
        "Dynamic.T": DYNAMIC_TYPE,
        "Exception": EXCEPTION_TYPE,
    }
    cleaned = type_str.strip()
    if cleaned in base_types:
        return base_types[cleaned]

    try:
        from quest.elaborate_types import elaborate_type
        from quest.env import Environment
        from quest.grammar import parse_quest_program
        from quest.tokenizer import Tokenizer
        from quest.tokens import SourceMap

        source_map = SourceMap(cleaned, "<type>")
        tokens = Tokenizer(cleaned, "<type>").tokenize_all()
        ast_type = parse_quest_program(tokens, source_map, target="Type")
        env = Environment()
        return elaborate_type(ast_type, env)
    except Exception:
        return DYNAMIC_TYPE


def jsog_encode(dyn: QDynamicVal) -> str:
    """Serializes a QDynamicVal to a JSON string using JSOG for cyclic references."""
    seen: set[int] = set()
    multi_ref: set[int] = set()

    def scan(val: QValue) -> None:
        if isinstance(val, (QReader, QWriter, QClosure, QBuiltinFun)):
            raise QuestException(DYNAMIC_ERROR_EXC)

        if isinstance(val, (QRecord, QArray, QTuple)):
            obj_id = id(val)
            if obj_id in seen:
                multi_ref.add(obj_id)
                return
            seen.add(obj_id)
            if isinstance(val, QRecord):
                for f_val in val.fields.values():
                    scan(f_val)
            elif isinstance(val, QArray):
                for elem in val.elements:
                    scan(elem)
            elif isinstance(val, QTuple):
                for elem in val.elements:
                    scan(elem)
        elif isinstance(val, QRef):
            scan(val.value)
        elif isinstance(val, QVariant):
            if val.payload is not None:
                scan(val.payload)
        elif isinstance(val, QOption):
            if val.payload is not None:
                scan(val.payload)
        elif isinstance(val, QDynamicVal):
            scan(val.value)

    scan(dyn.value)

    id_map: dict[int, str] = {}
    next_id = 1

    def encode_val(val: QValue) -> Any:
        if isinstance(val, (QReader, QWriter, QClosure, QBuiltinFun)):
            raise QuestException(DYNAMIC_ERROR_EXC)

        if isinstance(val, QInt):
            return val.value
        if isinstance(val, QReal):
            return val.value
        if isinstance(val, QBool):
            return val.value
        if isinstance(val, QString):
            return val.value
        if isinstance(val, QChar):
            return val.value
        if isinstance(val, QOk):
            return None

        if isinstance(val, (QRecord, QArray, QTuple)):
            nonlocal next_id
            obj_id = id(val)
            if obj_id in multi_ref:
                if obj_id in id_map:
                    return {"@ref": id_map[obj_id]}
                cur_id = str(next_id)
                next_id += 1
                id_map[obj_id] = cur_id
            else:
                cur_id = None

            if isinstance(val, QRecord):
                d: dict[str, Any] = {}
                if cur_id is not None:
                    d["@id"] = cur_id
                for k in sorted(val.fields.keys()):
                    d[k] = encode_val(val.fields[k])
                return d

            if isinstance(val, QArray):
                arr_elems = [encode_val(elem) for elem in val.elements]
                if cur_id is not None:
                    return {"@id": cur_id, "@array": arr_elems}
                return arr_elems

            if isinstance(val, QTuple):
                tuple_elems = [encode_val(elem) for elem in val.elements]
                if cur_id is not None:
                    return {"@id": cur_id, "@tuple": tuple_elems}
                return tuple_elems

        if isinstance(val, QRef):
            return encode_val(val.value)

        if isinstance(val, QVariant):
            if val.payload is None or isinstance(val.payload, QOk):
                return val.tag
            return {val.tag: encode_val(val.payload)}

        if isinstance(val, QOption):
            if val.payload is None or isinstance(val.payload, QOk):
                return val.tag
            return {val.tag: encode_val(val.payload)}

        if isinstance(val, QDynamicVal):
            return {
                "@type": str(val.type_val),
                "@value": encode_val(val.value),
            }

        raise QuestException(DYNAMIC_ERROR_EXC)

    envelope = {
        "@type": str(dyn.type_val),
        "@value": encode_val(dyn.value),
    }
    return json.dumps(envelope, separators=(",", ":"))


def jsog_decode(raw_json: str) -> QDynamicVal:
    """Deserializes a JSON string with JSOG references into a QDynamicVal."""
    try:
        data = json.loads(raw_json)
    except Exception:
        raise QuestException(DYNAMIC_ERROR_EXC)

    if not isinstance(data, dict) or "@type" not in data or "@value" not in data:
        raise QuestException(DYNAMIC_ERROR_EXC)

    target_type = parse_type_string(str(data["@type"]))
    root_value_data = data["@value"]

    id_map: dict[str, Any] = {}

    def pre_allocate(node: Any) -> None:
        if isinstance(node, dict):
            if "@id" in node:
                node_id = str(node["@id"])
                if "@array" in node:
                    id_map[node_id] = QArray([])
                elif "@tuple" in node:
                    id_map[node_id] = []
                else:
                    id_map[node_id] = QRecord({})
            for k, v in node.items():
                if k not in ("@id", "@ref"):
                    pre_allocate(v)
        elif isinstance(node, list):
            for item in node:
                pre_allocate(item)

    pre_allocate(root_value_data)

    def decode_node(node: Any, expected_type: Optional[QType] = None) -> QValue:
        if isinstance(node, dict) and "@ref" in node:
            ref_id = str(node["@ref"])
            if ref_id not in id_map:
                raise QuestException(DYNAMIC_ERROR_EXC)
            res = id_map[ref_id]
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], list):
                return QTuple(tuple(res[0]), labels=res[1])
            if isinstance(res, list):
                return QTuple(tuple(res))
            return res

        if isinstance(expected_type, QVarType):
            inner_val = decode_node(node, expected_type.element_type)
            return QRef(inner_val)

        if node is None:
            return OK_VALUE

        if isinstance(node, bool):
            return TRUE_VALUE if node else FALSE_VALUE

        if isinstance(node, int):
            if isinstance(expected_type, QRealType):
                return QReal(float(node))
            return QInt(node)

        if isinstance(node, float):
            return QReal(node)

        if isinstance(node, str):
            if isinstance(expected_type, QCharType) and len(node) == 1:
                return QChar(node)
            if isinstance(expected_type, QVariantType):
                for v_field in expected_type.variants:
                    if v_field.name == node:
                        return QVariant(node, OK_VALUE)
            if isinstance(expected_type, QOptionType):
                for o_field in expected_type.variants:
                    if o_field.name == node:
                        return QOption(node, OK_VALUE)
            if len(node) == 1 and isinstance(expected_type, QCharType):
                return QChar(node)
            return QString(node)

        is_tuple_dict = isinstance(node, dict) and "@tuple" in node
        is_tuple_list = isinstance(expected_type, QTupleType) and isinstance(node, list)
        if is_tuple_dict or is_tuple_list:
            if isinstance(node, dict):
                obj_id = str(node["@id"])
                raw_list = node["@tuple"]
            else:
                obj_id = None
                raw_list = node
            labels = None
            if isinstance(expected_type, QTupleType):
                labels = tuple(f.name for f in expected_type.value_fields)
                tuple_t = tuple(f.type_val for f in expected_type.value_fields)
            else:
                tuple_t = None
            elems: list[QValue] = []
            for i, item in enumerate(raw_list):
                cur_t = tuple_t[i] if tuple_t and i < len(tuple_t) else None
                elems.append(decode_node(item, cur_t))
            if obj_id is not None:
                id_map[obj_id] = (elems, labels)
            return QTuple(tuple(elems), labels=labels)

        if isinstance(node, list) or (isinstance(node, dict) and "@array" in node):
            if isinstance(node, dict):
                obj_id = str(node["@id"])
                raw_list = node["@array"]
                arr = id_map[obj_id]
            else:
                raw_list = node
                arr = QArray([])
            elem_t = expected_type.element_type if isinstance(expected_type, QArrayType) else None
            arr.elements = [decode_node(item, elem_t) for item in raw_list]
            return arr

        if isinstance(node, dict) and "@type" in node and "@value" in node and len(node) == 2:
            inner_t = parse_type_string(str(node["@type"]))
            inner_v = decode_node(node["@value"], inner_t)
            return QDynamicVal(inner_v, inner_t)

        if isinstance(node, dict):
            keys = [k for k in node.keys() if k != "@id"]

            if isinstance(expected_type, QVariantType) and len(keys) == 1:
                tag = keys[0]
                for v_field in expected_type.variants:
                    if v_field.name == tag:
                        payload = decode_node(node[tag], v_field.type_val)
                        return QVariant(tag, payload)

            if isinstance(expected_type, QOptionType) and len(keys) == 1:
                tag = keys[0]
                for o_field in expected_type.variants:
                    if o_field.name == tag:
                        payload = decode_node(node[tag], o_field.type_val)
                        return QOption(tag, payload)

            if "@id" in node:
                obj_id = str(node["@id"])
                rec = id_map[obj_id]
            else:
                rec = QRecord({})

            field_types: dict[str, QType] = {}
            if isinstance(expected_type, QRecordType):
                field_types = {f.name: f.type_val for f in expected_type.fields}

            for k, v in node.items():
                if k == "@id":
                    continue
                rec.fields[k] = decode_node(v, field_types.get(k))
            return rec

        raise QuestException(DYNAMIC_ERROR_EXC)

    root_val = decode_node(root_value_data, target_type)
    return QDynamicVal(root_val, target_type)
