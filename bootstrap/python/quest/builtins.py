"""Quest Cardelli Standard Library Modules & Builtin Registry.

Provides implementations of the 9 standard library interfaces and modules:
- Writer: character/string sink (output, err, file, putString, putChar, flush, close)
- Reader: character/string source (input, file, getString, getChar, more, ready, close)
- Conv: string conversions with Cardelli tilde (~) for negative numbers
- Ascii: character encoding conversions and bounds validation
- IntOp: 64-bit integer operations (minInt, maxInt, abs, min, max)
- RealOp: IEEE-754 floating-point operations (minReal, maxReal, epsilon, e, math funcs)
- StringOp: mutable string operations (length, getChar, setChar, getSub, setSub, cat, conc, equal)
- ArrayOp: array primitives (new, size, get, set) operating on QArray
- Dynamic: dynamic object packaging and introspection (new, be, copy, intern, extern)
"""

from __future__ import annotations

import math
import sys
from typing import Any, Callable, Optional

from quest.env import Environment, Scope, TypeSymbol, ValueSymbol
from quest.interpreter import ARRAY_OP_ERROR_EXC, DYNAMIC_ERROR_EXC, QuestException, _infer_qtype
from quest.runtime import (
    FALSE_VALUE,
    OK_VALUE,
    TRUE_VALUE,
    QArray,
    QBool,
    QBuiltinFun,
    QChar,
    QDynamicVal,
    QExceptionVal,
    QInt,
    QOk,
    QReader,
    QReal,
    QRecord,
    QString,
    QValue,
    QWriter,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QAllType,
    QArrayType,
    QFunType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QType,
    QTypeVar,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
)


def _make_fn_type(params: list[tuple[str, QType]], result_type: QType) -> QFunType:
    """Helper to construct a monomorphic QFunType from parameter pairs."""
    return QFunType(
        params=tuple(QParam(name=pname, type_val=ptype) for pname, ptype in params),
        result_type=result_type,
    )


def _make_poly_fn_type(type_param_name: str, symbol_id: int, fn_type: QFunType) -> QAllType:
    """Helper to construct a single-quantifier QAllType: All(X::TYPE) fn_type."""
    quant = QQuantifier(name=type_param_name, symbol_id=symbol_id, bound=TYPE_KIND)
    return QAllType(quantifiers=(quant,), body=fn_type)


class BuiltinModuleRegistry:
    """Central registry of Cardelli standard library interfaces and runtime modules."""

    _WRITER_ERROR_EXC = QExceptionVal("writer.error")
    _READER_ERROR_EXC = QExceptionVal("reader.error")
    _ASCII_ERROR_EXC = QExceptionVal("ascii.error")
    _INT_ERROR_EXC = QExceptionVal("int.error")
    _REAL_ERROR_EXC = QExceptionVal("real.error")
    _STRING_ERROR_EXC = QExceptionVal("string.error")

    # Module instances cache
    _modules: dict[str, QRecord] = {}
    _interfaces: dict[str, Scope] = {}
    _module_types: dict[str, QType] = {}

    @classmethod
    def get_interface(cls, name: str, env: Optional[Environment] = None) -> Optional[Scope]:
        """Returns the Scope containing the type signatures for the requested interface."""
        cls._ensure_initialized(env)
        return cls._interfaces.get(name)

    @classmethod
    def get_runtime_module(cls, name: str) -> Optional[QRecord]:
        """Returns the runtime QRecord representing the requested module instance."""
        cls._ensure_initialized()
        return cls._modules.get(name)

    @classmethod
    def get_module_type(cls, name: str, env: Optional[Environment] = None) -> Optional[QType]:
        """Returns the QType (usually QRecordType) representing the module's signature."""
        cls._ensure_initialized(env)
        return cls._module_types.get(name)

    @classmethod
    def _ensure_initialized(cls, env: Optional[Environment] = None) -> None:
        if cls._modules:
            return

        e = env if env is not None else Environment()

        # --------------------------------------------------------------------
        # 1. Writer Interface & Module
        # --------------------------------------------------------------------
        writer_t_id = e.fresh_symbol_id()
        writer_t = QTypeVar(name="Writer.T", symbol_id=writer_t_id, bound=TYPE_KIND)
        writer_scope = Scope(name="interface_Writer")
        writer_scope.declare_type(TypeSymbol(name="T", symbol_id=writer_t_id, kind=TYPE_KIND, definition=None))
        writer_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        writer_scope.declare_value(ValueSymbol(name="output", type_val=writer_t))
        writer_scope.declare_value(ValueSymbol(name="err", type_val=writer_t))
        writer_scope.declare_value(ValueSymbol(name="file", type_val=_make_fn_type([("name", STRING_TYPE)], writer_t)))
        writer_scope.declare_value(
            ValueSymbol(
                name="putString",
                type_val=_make_fn_type([("writer", writer_t), ("string", STRING_TYPE)], OK_TYPE),
            )
        )
        writer_scope.declare_value(
            ValueSymbol(
                name="putChar",
                type_val=_make_fn_type([("writer", writer_t), ("char", CHAR_TYPE)], OK_TYPE),
            )
        )
        writer_scope.declare_value(
            ValueSymbol(
                name="putSubString",
                type_val=_make_fn_type(
                    [("writer", writer_t), ("string", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
                    OK_TYPE,
                ),
            )
        )
        writer_scope.declare_value(
            ValueSymbol(name="flush", type_val=_make_fn_type([("writer", writer_t)], OK_TYPE))
        )
        writer_scope.declare_value(
            ValueSymbol(name="close", type_val=_make_fn_type([("writer", writer_t)], OK_TYPE))
        )
        cls._interfaces["Writer"] = writer_scope

        def _writer_file(name_val: QValue) -> QWriter:
            if not isinstance(name_val, QString):
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                f = open(name_val.value, "w", encoding="utf-8")
                return QWriter(stream=f, is_file=True, file_name=name_val.value)
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        def _writer_put_string(w: QValue, s: QValue) -> QOk:
            if not isinstance(w, QWriter) or not isinstance(s, QString) or w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(s.value)
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        def _writer_put_char(w: QValue, c: QValue) -> QOk:
            if not isinstance(w, QWriter) or not isinstance(c, QChar) or w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(c.value)
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        def _writer_put_sub_string(w: QValue, s: QValue, start: QValue, size: QValue) -> QOk:
            if (
                not isinstance(w, QWriter)
                or not isinstance(s, QString)
                or not isinstance(start, QInt)
                or not isinstance(size, QInt)
                or w.is_closed
            ):
                raise QuestException(cls._WRITER_ERROR_EXC)
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(s.value[st : st + sz])
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        def _writer_flush(w: QValue) -> QOk:
            if not isinstance(w, QWriter) or w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.flush()
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        def _writer_close(w: QValue) -> QOk:
            if not isinstance(w, QWriter):
                raise QuestException(cls._WRITER_ERROR_EXC)
            if not w.is_closed:
                try:
                    if w.is_file:
                        w.stream.close()
                    else:
                        w.stream.flush()
                    w.is_closed = True
                except OSError:
                    raise QuestException(cls._WRITER_ERROR_EXC)
            return OK_VALUE

        writer_mod = QRecord({
            "error": cls._WRITER_ERROR_EXC,
            "output": QWriter(sys.stdout, is_file=False),
            "err": QWriter(sys.stderr, is_file=False),
            "file": QBuiltinFun("writer.file", _writer_file),
            "putString": QBuiltinFun("writer.putString", _writer_put_string),
            "putChar": QBuiltinFun("writer.putChar", _writer_put_char),
            "putSubString": QBuiltinFun("writer.putSubString", _writer_put_sub_string),
            "flush": QBuiltinFun("writer.flush", _writer_flush),
            "close": QBuiltinFun("writer.close", _writer_close),
        })
        cls._modules["writer"] = writer_mod
        cls._module_types["writer"] = cls._build_record_type_from_scope(writer_scope)

        # --------------------------------------------------------------------
        # 2. Reader Interface & Module
        # --------------------------------------------------------------------
        reader_t_id = e.fresh_symbol_id()
        reader_t = QTypeVar(name="Reader.T", symbol_id=reader_t_id, bound=TYPE_KIND)
        reader_scope = Scope(name="interface_Reader")
        reader_scope.declare_type(TypeSymbol(name="T", symbol_id=reader_t_id, kind=TYPE_KIND, definition=None))
        reader_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        reader_scope.declare_value(ValueSymbol(name="input", type_val=reader_t))
        reader_scope.declare_value(ValueSymbol(name="file", type_val=_make_fn_type([("name", STRING_TYPE)], reader_t)))
        reader_scope.declare_value(
            ValueSymbol(name="more", type_val=_make_fn_type([("reader", reader_t)], BOOL_TYPE))
        )
        reader_scope.declare_value(
            ValueSymbol(name="ready", type_val=_make_fn_type([("reader", reader_t)], INT_TYPE))
        )
        reader_scope.declare_value(
            ValueSymbol(name="getChar", type_val=_make_fn_type([("reader", reader_t)], CHAR_TYPE))
        )
        reader_scope.declare_value(
            ValueSymbol(
                name="getString",
                type_val=_make_fn_type([("reader", reader_t), ("size", INT_TYPE)], STRING_TYPE),
            )
        )
        reader_scope.declare_value(
            ValueSymbol(
                name="getSubString",
                type_val=_make_fn_type(
                    [("reader", reader_t), ("string", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
                    OK_TYPE,
                ),
            )
        )
        reader_scope.declare_value(
            ValueSymbol(name="close", type_val=_make_fn_type([("reader", reader_t)], OK_TYPE))
        )
        cls._interfaces["Reader"] = reader_scope

        def _reader_file(name_val: QValue) -> QReader:
            if not isinstance(name_val, QString):
                raise QuestException(cls._READER_ERROR_EXC)
            try:
                f = open(name_val.value, "r", encoding="utf-8")
                return QReader(stream=f, is_file=True, file_name=name_val.value)
            except OSError:
                raise QuestException(cls._READER_ERROR_EXC)

        def _reader_read_one(r: QReader) -> str:
            """Internal helper to read 1 char taking peek buffer into account."""
            peek = getattr(r, "_peek_char", None)
            if peek is not None:
                r._peek_char = None
                return peek
            return r.stream.read(1)

        def _reader_more(r: QValue) -> QBool:
            if not isinstance(r, QReader) or r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            peek = getattr(r, "_peek_char", None)
            if peek is not None:
                return TRUE_VALUE
            try:
                ch = r.stream.read(1)
                if not ch:
                    return FALSE_VALUE
                r._peek_char = ch
                return TRUE_VALUE
            except OSError:
                raise QuestException(cls._READER_ERROR_EXC)

        def _reader_ready(r: QValue) -> QInt:
            if not isinstance(r, QReader) or r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            # Trivially returns 0 as specified
            return QInt(0)

        def _reader_get_char(r: QValue) -> QChar:
            if not isinstance(r, QReader) or r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            try:
                ch = _reader_read_one(r)
                if not ch:
                    raise QuestException(cls._READER_ERROR_EXC)
                return QChar(ch)
            except OSError:
                raise QuestException(cls._READER_ERROR_EXC)

        def _reader_get_string(r: QValue, size: QValue) -> QString:
            if not isinstance(r, QReader) or not isinstance(size, QInt) or r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            sz = size.value
            if sz < 0:
                raise QuestException(cls._READER_ERROR_EXC)
            buf = []
            peek = getattr(r, "_peek_char", None)
            if peek is not None and sz > 0:
                buf.append(peek)
                r._peek_char = None
                sz -= 1
            if sz > 0:
                try:
                    chunk = r.stream.read(sz)
                    buf.append(chunk)
                except OSError:
                    raise QuestException(cls._READER_ERROR_EXC)
            return QString("".join(buf))

        def _reader_get_sub_string(r: QValue, s: QValue, start: QValue, size: QValue) -> QOk:
            if (
                not isinstance(r, QReader)
                or not isinstance(s, QString)
                or not isinstance(start, QInt)
                or not isinstance(size, QInt)
                or r.is_closed
            ):
                raise QuestException(cls._READER_ERROR_EXC)
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._READER_ERROR_EXC)
            read_str = _reader_get_string(r, size).value
            s.value = s.value[:st] + read_str + s.value[st + len(read_str) :]
            return OK_VALUE

        def _reader_close(r: QValue) -> QOk:
            if not isinstance(r, QReader):
                raise QuestException(cls._READER_ERROR_EXC)
            if not r.is_closed:
                try:
                    if r.is_file:
                        r.stream.close()
                    r.is_closed = True
                except OSError:
                    raise QuestException(cls._READER_ERROR_EXC)
            return OK_VALUE

        reader_mod = QRecord({
            "error": cls._READER_ERROR_EXC,
            "input": QReader(sys.stdin, is_file=False),
            "file": QBuiltinFun("reader.file", _reader_file),
            "more": QBuiltinFun("reader.more", _reader_more),
            "ready": QBuiltinFun("reader.ready", _reader_ready),
            "getChar": QBuiltinFun("reader.getChar", _reader_get_char),
            "getString": QBuiltinFun("reader.getString", _reader_get_string),
            "getSubString": QBuiltinFun("reader.getSubString", _reader_get_sub_string),
            "close": QBuiltinFun("reader.close", _reader_close),
        })
        cls._modules["reader"] = reader_mod
        cls._module_types["reader"] = cls._build_record_type_from_scope(reader_scope)

        # --------------------------------------------------------------------
        # 3. Conv Interface & Module (Tilde ~ for negative numbers)
        # --------------------------------------------------------------------
        conv_scope = Scope(name="interface_Conv")
        conv_scope.declare_value(ValueSymbol(name="okay", type_val=_make_fn_type([], STRING_TYPE)))
        conv_scope.declare_value(ValueSymbol(name="bool", type_val=_make_fn_type([("b", BOOL_TYPE)], STRING_TYPE)))
        conv_scope.declare_value(ValueSymbol(name="int", type_val=_make_fn_type([("n", INT_TYPE)], STRING_TYPE)))
        conv_scope.declare_value(ValueSymbol(name="real", type_val=_make_fn_type([("r", REAL_TYPE)], STRING_TYPE)))
        conv_scope.declare_value(ValueSymbol(name="char", type_val=_make_fn_type([("c", CHAR_TYPE)], STRING_TYPE)))
        conv_scope.declare_value(ValueSymbol(name="string", type_val=_make_fn_type([("s", STRING_TYPE)], STRING_TYPE)))
        cls._interfaces["Conv"] = conv_scope

        def _conv_int(n: QValue) -> QString:
            if not isinstance(n, QInt):
                return QString("")
            val = n.value
            return QString(f"~{-val}" if val < 0 else str(val))

        def _conv_real(r: QValue) -> QString:
            if not isinstance(r, QReal):
                return QString("")
            val = r.value
            is_neg = val < 0
            abs_val = -val if is_neg else val
            s = str(abs_val)
            if "." not in s and "e" not in s:
                s += ".0"
            return QString(f"~{s}" if is_neg else s)

        conv_mod = QRecord({
            "okay": QBuiltinFun("conv.okay", lambda: QString("ok")),
            "bool": QBuiltinFun("conv.bool", lambda b: QString("true" if getattr(b, "value", False) else "false")),
            "int": QBuiltinFun("conv.int", _conv_int),
            "real": QBuiltinFun("conv.real", _conv_real),
            "char": QBuiltinFun("conv.char", lambda c: QString(c.to_str() if isinstance(c, QChar) else "")),
            "string": QBuiltinFun("conv.string", lambda s: QString(s.to_str() if isinstance(s, QString) else "")),
        })
        cls._modules["conv"] = conv_mod
        cls._module_types["conv"] = cls._build_record_type_from_scope(conv_scope)

        # --------------------------------------------------------------------
        # 4. Ascii Interface & Module
        # --------------------------------------------------------------------
        ascii_scope = Scope(name="interface_Ascii")
        ascii_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        ascii_scope.declare_value(ValueSymbol(name="char", type_val=_make_fn_type([("n", INT_TYPE)], CHAR_TYPE)))
        ascii_scope.declare_value(ValueSymbol(name="val", type_val=_make_fn_type([("c", CHAR_TYPE)], INT_TYPE)))
        cls._interfaces["Ascii"] = ascii_scope

        def _ascii_char(n: QValue) -> QChar:
            if not isinstance(n, QInt) or n.value < 0 or n.value > 255:
                raise QuestException(cls._ASCII_ERROR_EXC)
            return QChar(chr(n.value))

        def _ascii_val(c: QValue) -> QInt:
            if not isinstance(c, QChar):
                raise QuestException(cls._ASCII_ERROR_EXC)
            return QInt(ord(c.value))

        ascii_mod = QRecord({
            "error": cls._ASCII_ERROR_EXC,
            "char": QBuiltinFun("ascii.char", _ascii_char),
            "val": QBuiltinFun("ascii.val", _ascii_val),
        })
        cls._modules["ascii"] = ascii_mod
        cls._module_types["ascii"] = cls._build_record_type_from_scope(ascii_scope)

        # --------------------------------------------------------------------
        # 5. IntOp Interface & Module
        # --------------------------------------------------------------------
        int_scope = Scope(name="interface_IntOp")
        int_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        int_scope.declare_value(ValueSymbol(name="minInt", type_val=INT_TYPE))
        int_scope.declare_value(ValueSymbol(name="maxInt", type_val=INT_TYPE))
        int_scope.declare_value(ValueSymbol(name="abs", type_val=_make_fn_type([("n", INT_TYPE)], INT_TYPE)))
        int_scope.declare_value(
            ValueSymbol(name="min", type_val=_make_fn_type([("a", INT_TYPE), ("b", INT_TYPE)], INT_TYPE))
        )
        int_scope.declare_value(
            ValueSymbol(name="max", type_val=_make_fn_type([("a", INT_TYPE), ("b", INT_TYPE)], INT_TYPE))
        )
        cls._interfaces["IntOp"] = int_scope

        int_mod = QRecord({
            "error": cls._INT_ERROR_EXC,
            "minInt": QInt(-9223372036854775808),
            "maxInt": QInt(9223372036854775807),
            "abs": QBuiltinFun("int.abs", lambda n: QInt(abs(n.value))),
            "min": QBuiltinFun("int.min", lambda a, b: QInt(min(a.value, b.value))),
            "max": QBuiltinFun("int.max", lambda a, b: QInt(max(a.value, b.value))),
        })
        cls._modules["int"] = int_mod
        cls._module_types["int"] = cls._build_record_type_from_scope(int_scope)

        # --------------------------------------------------------------------
        # 6. RealOp Interface & Module
        # --------------------------------------------------------------------
        real_scope = Scope(name="interface_RealOp")
        real_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        real_scope.declare_value(ValueSymbol(name="minReal", type_val=REAL_TYPE))
        real_scope.declare_value(ValueSymbol(name="maxReal", type_val=REAL_TYPE))
        real_scope.declare_value(ValueSymbol(name="posEpsilon", type_val=REAL_TYPE))
        real_scope.declare_value(ValueSymbol(name="negEpsilon", type_val=REAL_TYPE))
        real_scope.declare_value(ValueSymbol(name="e", type_val=REAL_TYPE))
        real_scope.declare_value(ValueSymbol(name="int", type_val=_make_fn_type([("n", INT_TYPE)], REAL_TYPE)))
        real_scope.declare_value(ValueSymbol(name="floor", type_val=_make_fn_type([("r", REAL_TYPE)], INT_TYPE)))
        real_scope.declare_value(ValueSymbol(name="round", type_val=_make_fn_type([("r", REAL_TYPE)], INT_TYPE)))
        real_scope.declare_value(ValueSymbol(name="abs", type_val=_make_fn_type([("r", REAL_TYPE)], REAL_TYPE)))
        real_scope.declare_value(ValueSymbol(name="log", type_val=_make_fn_type([("r", REAL_TYPE)], REAL_TYPE)))
        real_scope.declare_value(
            ValueSymbol(name="min", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="max", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="plus", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="diff", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="mul", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="div", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="exp", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="smaller", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], BOOL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="greater", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], BOOL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="smallerEq", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], BOOL_TYPE))
        )
        real_scope.declare_value(
            ValueSymbol(name="greaterEq", type_val=_make_fn_type([("a", REAL_TYPE), ("b", REAL_TYPE)], BOOL_TYPE))
        )
        cls._interfaces["RealOp"] = real_scope

        def _real_log(r: QValue) -> QReal:
            if not isinstance(r, QReal) or r.value <= 0.0:
                raise QuestException(cls._REAL_ERROR_EXC)
            return QReal(math.log(r.value))

        def _real_div(a: QValue, b: QValue) -> QReal:
            if not isinstance(a, QReal) or not isinstance(b, QReal) or b.value == 0.0:
                raise QuestException(cls._REAL_ERROR_EXC)
            return QReal(a.value / b.value)

        def _real_exp(a: QValue, b: QValue) -> QReal:
            if not isinstance(a, QReal) or not isinstance(b, QReal):
                raise QuestException(cls._REAL_ERROR_EXC)
            try:
                return QReal(math.pow(a.value, b.value))
            except (ValueError, OverflowError):
                raise QuestException(cls._REAL_ERROR_EXC)

        real_mod = QRecord({
            "error": cls._REAL_ERROR_EXC,
            "minReal": QReal(-sys.float_info.max),
            "maxReal": QReal(sys.float_info.max),
            "posEpsilon": QReal(sys.float_info.epsilon),
            "negEpsilon": QReal(-sys.float_info.epsilon),
            "e": QReal(math.e),
            "int": QBuiltinFun("real.int", lambda n: QReal(float(n.value))),
            "floor": QBuiltinFun("real.floor", lambda r: QInt(math.floor(r.value))),
            "round": QBuiltinFun("real.round", lambda r: QInt(round(r.value))),
            "abs": QBuiltinFun("real.abs", lambda r: QReal(abs(r.value))),
            "log": QBuiltinFun("real.log", _real_log),
            "min": QBuiltinFun("real.min", lambda a, b: QReal(min(a.value, b.value))),
            "max": QBuiltinFun("real.max", lambda a, b: QReal(max(a.value, b.value))),
            "plus": QBuiltinFun("real.plus", lambda a, b: QReal(a.value + b.value)),
            "diff": QBuiltinFun("real.diff", lambda a, b: QReal(a.value - b.value)),
            "mul": QBuiltinFun("real.mul", lambda a, b: QReal(a.value * b.value)),
            "div": QBuiltinFun("real.div", _real_div),
            "exp": QBuiltinFun("real.exp", _real_exp),
            "smaller": QBuiltinFun("real.smaller", lambda a, b: QBool(a.value < b.value)),
            "greater": QBuiltinFun("real.greater", lambda a, b: QBool(a.value > b.value)),
            "smallerEq": QBuiltinFun("real.smallerEq", lambda a, b: QBool(a.value <= b.value)),
            "greaterEq": QBuiltinFun("real.greaterEq", lambda a, b: QBool(a.value >= b.value)),
        })
        cls._modules["real"] = real_mod
        cls._module_types["real"] = cls._build_record_type_from_scope(real_scope)

        # --------------------------------------------------------------------
        # 7. StringOp Interface & Module
        # --------------------------------------------------------------------
        string_scope = Scope(name="interface_StringOp")
        string_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        string_scope.declare_value(
            ValueSymbol(name="new", type_val=_make_fn_type([("size", INT_TYPE), ("init", CHAR_TYPE)], STRING_TYPE))
        )
        string_scope.declare_value(
            ValueSymbol(name="isEmpty", type_val=_make_fn_type([("string", STRING_TYPE)], BOOL_TYPE))
        )
        string_scope.declare_value(
            ValueSymbol(name="length", type_val=_make_fn_type([("string", STRING_TYPE)], INT_TYPE))
        )
        string_scope.declare_value(
            ValueSymbol(
                name="getChar",
                type_val=_make_fn_type([("string", STRING_TYPE), ("index", INT_TYPE)], CHAR_TYPE),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="setChar",
                type_val=_make_fn_type(
                    [("string", STRING_TYPE), ("index", INT_TYPE), ("char", CHAR_TYPE)],
                    OK_TYPE,
                ),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="getSub",
                type_val=_make_fn_type(
                    [("source", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
                    STRING_TYPE,
                ),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="setSub",
                type_val=_make_fn_type(
                    [
                        ("dest", STRING_TYPE),
                        ("destStart", INT_TYPE),
                        ("source", STRING_TYPE),
                        ("sourceStart", INT_TYPE),
                        ("sourceSize", INT_TYPE),
                    ],
                    OK_TYPE,
                ),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="cat",
                type_val=_make_fn_type([("s1", STRING_TYPE), ("s2", STRING_TYPE)], STRING_TYPE),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="catSub",
                type_val=_make_fn_type(
                    [
                        ("s1", STRING_TYPE),
                        ("start1", INT_TYPE),
                        ("size1", INT_TYPE),
                        ("s2", STRING_TYPE),
                        ("start2", INT_TYPE),
                        ("size2", INT_TYPE),
                    ],
                    STRING_TYPE,
                ),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="conc",
                type_val=_make_fn_type([("a", QArrayType(STRING_TYPE))], STRING_TYPE),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="equal",
                type_val=_make_fn_type([("s1", STRING_TYPE), ("s2", STRING_TYPE)], BOOL_TYPE),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="equalSub",
                type_val=_make_fn_type(
                    [
                        ("s1", STRING_TYPE),
                        ("start1", INT_TYPE),
                        ("size1", INT_TYPE),
                        ("s2", STRING_TYPE),
                        ("start2", INT_TYPE),
                        ("size2", INT_TYPE),
                    ],
                    BOOL_TYPE,
                ),
            )
        )
        string_scope.declare_value(
            ValueSymbol(
                name="precedes",
                type_val=_make_fn_type([("s1", STRING_TYPE), ("s2", STRING_TYPE)], BOOL_TYPE),
            )
        )
        cls._interfaces["StringOp"] = string_scope

        def _string_new(size: QValue, init: QValue) -> QString:
            if not isinstance(size, QInt) or not isinstance(init, QChar) or size.value < 0:
                raise QuestException(cls._STRING_ERROR_EXC)
            return QString(init.value * size.value)

        def _string_get_char(s: QValue, index: QValue) -> QChar:
            if not isinstance(s, QString) or not isinstance(index, QInt):
                raise QuestException(cls._STRING_ERROR_EXC)
            idx = index.value
            if idx < 0 or idx >= len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            return QChar(s.value[idx])

        def _string_set_char(s: QValue, index: QValue, char: QValue) -> QOk:
            if not isinstance(s, QString) or not isinstance(index, QInt) or not isinstance(char, QChar):
                raise QuestException(cls._STRING_ERROR_EXC)
            idx = index.value
            if idx < 0 or idx >= len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            s.value = s.value[:idx] + char.value + s.value[idx + 1 :]
            return OK_VALUE

        def _string_get_sub(s: QValue, start: QValue, size: QValue) -> QString:
            if not isinstance(s, QString) or not isinstance(start, QInt) or not isinstance(size, QInt):
                raise QuestException(cls._STRING_ERROR_EXC)
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            return QString(s.value[st : st + sz])

        def _string_set_sub(dest: QValue, d_st: QValue, src: QValue, s_st: QValue, sz: QValue) -> QOk:
            if (
                not isinstance(dest, QString)
                or not isinstance(src, QString)
                or not isinstance(d_st, QInt)
                or not isinstance(s_st, QInt)
                or not isinstance(sz, QInt)
            ):
                raise QuestException(cls._STRING_ERROR_EXC)
            dst_idx, src_idx, count = d_st.value, s_st.value, sz.value
            if (
                dst_idx < 0
                or src_idx < 0
                or count < 0
                or dst_idx + count > len(dest.value)
                or src_idx + count > len(src.value)
            ):
                raise QuestException(cls._STRING_ERROR_EXC)
            chunk = src.value[src_idx : src_idx + count]
            dest.value = dest.value[:dst_idx] + chunk + dest.value[dst_idx + count :]
            return OK_VALUE

        def _string_cat_sub(s1: QValue, st1: QValue, sz1: QValue, s2: QValue, st2: QValue, sz2: QValue) -> QString:
            sub1 = _string_get_sub(s1, st1, sz1).value
            sub2 = _string_get_sub(s2, st2, sz2).value
            return QString(sub1 + sub2)

        def _string_conc(arr: QValue) -> QString:
            if not isinstance(arr, QArray):
                raise QuestException(cls._STRING_ERROR_EXC)
            parts: list[str] = []
            for elem in arr.elements:
                if not isinstance(elem, QString):
                    raise QuestException(cls._STRING_ERROR_EXC)
                parts.append(elem.value)
            return QString("".join(parts))

        def _string_equal_sub(s1: QValue, st1: QValue, sz1: QValue, s2: QValue, st2: QValue, sz2: QValue) -> QBool:
            sub1 = _string_get_sub(s1, st1, sz1).value
            sub2 = _string_get_sub(s2, st2, sz2).value
            return QBool(sub1 == sub2)

        string_mod = QRecord({
            "error": cls._STRING_ERROR_EXC,
            "new": QBuiltinFun("string.new", _string_new),
            "isEmpty": QBuiltinFun("string.isEmpty", lambda s: QBool(len(s.value) == 0)),
            "length": QBuiltinFun("string.length", lambda s: QInt(len(s.value))),
            "getChar": QBuiltinFun("string.getChar", _string_get_char),
            "setChar": QBuiltinFun("string.setChar", _string_set_char),
            "getSub": QBuiltinFun("string.getSub", _string_get_sub),
            "setSub": QBuiltinFun("string.setSub", _string_set_sub),
            "cat": QBuiltinFun("string.cat", lambda s1, s2: QString(s1.value + s2.value)),
            "catSub": QBuiltinFun("string.catSub", _string_cat_sub),
            "conc": QBuiltinFun("string.conc", _string_conc),
            "equal": QBuiltinFun("string.equal", lambda s1, s2: QBool(s1.value == s2.value)),
            "equalSub": QBuiltinFun("string.equalSub", _string_equal_sub),
            "precedes": QBuiltinFun("string.precedes", lambda s1, s2: QBool(s1.value <= s2.value)),
        })
        cls._modules["string"] = string_mod
        cls._module_types["string"] = cls._build_record_type_from_scope(string_scope)

        # --------------------------------------------------------------------
        # 8. ArrayOp Interface & Module
        # --------------------------------------------------------------------
        arr_a_id = e.fresh_symbol_id()
        arr_a = QTypeVar(name="A", symbol_id=arr_a_id, bound=TYPE_KIND)
        arrayop_scope = Scope(name="interface_ArrayOp")
        arrayop_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        arrayop_scope.declare_value(
            ValueSymbol(
                name="new",
                type_val=_make_poly_fn_type(
                    "A",
                    arr_a_id,
                    _make_fn_type([("size", INT_TYPE), ("init", arr_a)], QArrayType(arr_a)),
                ),
            )
        )
        arrayop_scope.declare_value(
            ValueSymbol(
                name="size",
                type_val=_make_poly_fn_type("A", arr_a_id, _make_fn_type([("array", QArrayType(arr_a))], INT_TYPE)),
            )
        )
        arrayop_scope.declare_value(
            ValueSymbol(
                name="get",
                type_val=_make_poly_fn_type(
                    "A",
                    arr_a_id,
                    _make_fn_type([("array", QArrayType(arr_a)), ("index", INT_TYPE)], arr_a),
                ),
            )
        )
        arrayop_scope.declare_value(
            ValueSymbol(
                name="set",
                type_val=_make_poly_fn_type(
                    "A",
                    arr_a_id,
                    _make_fn_type([("array", QArrayType(arr_a)), ("index", INT_TYPE), ("item", arr_a)], OK_TYPE),
                ),
            )
        )
        cls._interfaces["ArrayOp"] = arrayop_scope

        def _array_new(size: QValue, init: QValue) -> QArray:
            if not isinstance(size, QInt) or size.value < 0:
                raise QuestException(ARRAY_OP_ERROR_EXC)
            return QArray([init for _ in range(size.value)])

        def _array_size(arr: QValue) -> QInt:
            if not isinstance(arr, QArray):
                raise QuestException(ARRAY_OP_ERROR_EXC)
            return QInt(arr.size())

        def _array_get(arr: QValue, idx: QValue) -> QValue:
            if not isinstance(arr, QArray) or not isinstance(idx, QInt):
                raise QuestException(ARRAY_OP_ERROR_EXC)
            i = idx.value
            if i < 0 or i >= arr.size():
                raise QuestException(ARRAY_OP_ERROR_EXC)
            return arr.get(i)

        def _array_set(arr: QValue, idx: QValue, item: QValue) -> QOk:
            if not isinstance(arr, QArray) or not isinstance(idx, QInt):
                raise QuestException(ARRAY_OP_ERROR_EXC)
            i = idx.value
            if i < 0 or i >= arr.size():
                raise QuestException(ARRAY_OP_ERROR_EXC)
            arr.set(i, item)
            return OK_VALUE

        arrayop_mod = QRecord({
            "error": ARRAY_OP_ERROR_EXC,
            "new": QBuiltinFun("arrayOp.new", _array_new),
            "size": QBuiltinFun("arrayOp.size", _array_size),
            "get": QBuiltinFun("arrayOp.get", _array_get),
            "set": QBuiltinFun("arrayOp.set", _array_set),
        })
        cls._modules["arrayOp"] = arrayop_mod
        cls._module_types["arrayOp"] = cls._build_record_type_from_scope(arrayop_scope)

        # --------------------------------------------------------------------
        # 9. Dynamic Interface & Module
        # --------------------------------------------------------------------
        dyn_t_id = e.fresh_symbol_id()
        dyn_t = QTypeVar(name="Dynamic.T", symbol_id=dyn_t_id, bound=TYPE_KIND)
        dyn_a_id = e.fresh_symbol_id()
        dyn_a = QTypeVar(name="A", symbol_id=dyn_a_id, bound=TYPE_KIND)
        dynamic_scope = Scope(name="interface_Dynamic")
        dynamic_scope.declare_type(TypeSymbol(name="T", symbol_id=dyn_t_id, kind=TYPE_KIND, definition=DYNAMIC_TYPE))
        dynamic_scope.declare_value(ValueSymbol(name="error", type_val=EXCEPTION_TYPE))
        dynamic_scope.declare_value(
            ValueSymbol(
                name="new",
                type_val=_make_poly_fn_type("A", dyn_a_id, _make_fn_type([("a", dyn_a)], dyn_t)),
            )
        )
        dynamic_scope.declare_value(
            ValueSymbol(
                name="be",
                type_val=_make_poly_fn_type("A", dyn_a_id, _make_fn_type([("d", dyn_t)], dyn_a)),
            )
        )
        dynamic_scope.declare_value(
            ValueSymbol(name="copy", type_val=_make_fn_type([("d", dyn_t)], dyn_t))
        )
        dynamic_scope.declare_value(
            ValueSymbol(name="intern", type_val=_make_fn_type([("rd", reader_t)], dyn_t))
        )
        dynamic_scope.declare_value(
            ValueSymbol(name="extern", type_val=_make_fn_type([("wr", writer_t), ("d", dyn_t)], OK_TYPE))
        )
        cls._interfaces["Dynamic"] = dynamic_scope

        def _dynamic_new(val: QValue) -> QDynamicVal:
            return QDynamicVal(value=val, type_val=_infer_qtype(val))

        def _dynamic_be(d: QValue) -> QValue:
            if not isinstance(d, QDynamicVal):
                raise QuestException(DYNAMIC_ERROR_EXC)
            return d.value

        def _dynamic_copy(d: QValue) -> QDynamicVal:
            if not isinstance(d, QDynamicVal):
                raise QuestException(DYNAMIC_ERROR_EXC)
            return QDynamicVal(value=d.value, type_val=d.type_val)

        def _dynamic_extern(wr: QValue, d: QValue) -> QOk:
            if not isinstance(wr, QWriter) or not isinstance(d, QDynamicVal) or wr.is_closed:
                raise QuestException(DYNAMIC_ERROR_EXC)
            wr.stream.write(d.to_str())
            return OK_VALUE

        dynamic_mod = QRecord({
            "error": DYNAMIC_ERROR_EXC,
            "new": QBuiltinFun("dynamic.new", _dynamic_new),
            "be": QBuiltinFun("dynamic.be", _dynamic_be),
            "copy": QBuiltinFun("dynamic.copy", _dynamic_copy),
            "extern": QBuiltinFun("dynamic.extern", _dynamic_extern),
        })
        cls._modules["dynamic"] = dynamic_mod
        cls._module_types["dynamic"] = cls._build_record_type_from_scope(dynamic_scope)

    @classmethod
    def _build_record_type_from_scope(cls, scope: Scope) -> QRecordType:
        """Constructs a QRecordType matching the values exposed by an interface scope."""
        fields = [QRecordField(name=name, type_val=sym.type_val) for name, sym in scope.values.items()]
        return QRecordType(tuple(fields))
