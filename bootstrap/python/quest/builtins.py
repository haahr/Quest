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

from quest.env import Environment, Scope, TypeSymbol, ValueSymbol, allocate_symbol_id
from quest.interpreter import (
    ARRAY_OP_ERROR_EXC,
    DYNAMIC_ERROR_EXC,
    QuestException,
    QuestRuntimeError,
    _infer_qtype,
)
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
    QList,
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
    QAllKind,
    QAllType,
    QArrayType,
    QExternalType,
    QFunType,
    QParam,
    QQuantifier,
    QRecordField,
    QRecordType,
    QType,
    QTypeApp,
    QTypeVar,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
)
from quest.typed_ast import (
    TypedBinding,
    TypedLetType,
    TypedModule,
    TypedNativeBinding,
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


def qchecked(error_exc: Optional[QExceptionVal], *expected_types: type) -> Callable:
    """Decorator to validate that arguments passed to a builtin function match expected types.

    If error_exc is provided, raises QuestException(error_exc) on mismatch;
    otherwise, raises QuestRuntimeError with a descriptive message.
    """
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any) -> Any:
            if len(args) != len(expected_types):
                if error_exc is not None:
                    raise QuestException(error_exc)
                raise QuestRuntimeError(f"Expected {len(expected_types)} arguments, got {len(args)}")
            for arg, exp_type in zip(args, expected_types):
                if not isinstance(arg, exp_type):
                    if error_exc is not None:
                        raise QuestException(error_exc)
                    raise QuestRuntimeError(
                        f"Expected argument of type {exp_type.__name__}, got {type(arg).__name__}"
                    )
            return fn(*args)
        return wrapper
    return decorator


class ModuleBuilder:
    """Builder to declaratively construct a Quest standard library interface and module."""

    def __init__(
        self,
        mod_name: str,
        iface_name: str,
        registry: type[BuiltinModuleRegistry],
        c_init: Optional[str] = None,
    ):
        self.mod_name = mod_name
        self.iface_name = iface_name
        self.registry = registry
        self.c_init = c_init
        registry._ensure_initialized()
        self.scope = Scope(name=f"interface_{iface_name}")
        self.record_dict: dict[str, QValue] = {}
        self.typed_bindings: list[TypedBinding] = []

    def def_type(
        self,
        name: str,
        symbol_id: int,
        kind: Any,
        definition: Optional[QType] = None,
    ) -> TypeSymbol:
        sym = TypeSymbol(name=name, symbol_id=symbol_id, kind=kind, definition=definition)
        self.scope.declare_type(sym)
        self.typed_bindings.append(TypedLetType(name=name, symbol=sym))
        return sym

    def def_external_type(
        self,
        name: str,
        symbol_id: int,
        kind: Any,
        c_type: str,
    ) -> TypeSymbol:
        ext_t = QExternalType(name=f"{self.iface_name}.{name}", c_type=c_type)
        sym = TypeSymbol(name=name, symbol_id=symbol_id, kind=kind, definition=ext_t)
        self.scope.declare_type(sym)
        self.typed_bindings.append(TypedLetType(name=name, symbol=sym))
        return sym

    def def_const(
        self,
        name: str,
        type_val: QType,
        runtime_val: QValue,
        c_val: Optional[str] = None,
    ) -> None:
        sym = ValueSymbol(name=name, type_val=type_val)
        self.scope.declare_value(sym)
        self.record_dict[name] = runtime_val
        if c_val:
            self.registry._symbol_bridge[c_val] = runtime_val
            clean_c = c_val.strip("(&)").strip()
            self.registry._symbol_bridge[clean_c] = runtime_val
        self.typed_bindings.append(
            TypedNativeBinding(
                name=name,
                symbol="",
                inline_template=None,
                c_val=c_val,
                type_val=type_val,
            )
        )

    def def_scope_val(self, name: str, type_val: QType) -> None:
        """Declares a value in the interface scope only (omitted from runtime record)."""
        self.scope.declare_value(ValueSymbol(name=name, type_val=type_val))

    def def_native_fn(
        self,
        name: str,
        params: list[tuple[str, QType]],
        result_type: QType,
        fn: Callable,
        c_symbol: Optional[str] = None,
        inline_template: Optional[str] = None,
    ) -> None:
        fn_type = _make_fn_type(params, result_type)
        sym = ValueSymbol(name=name, type_val=fn_type)
        self.scope.declare_value(sym)
        self.record_dict[name] = QBuiltinFun(f"{self.mod_name}.{name}", fn)
        if c_symbol:
            self.registry._symbol_bridge[c_symbol] = fn
        self.typed_bindings.append(
            TypedNativeBinding(
                name=name,
                symbol=c_symbol or "",
                inline_template=inline_template,
                c_val=None,
                type_val=fn_type,
            )
        )

    def def_fn(
        self,
        name: str,
        params: list[tuple[str, QType]],
        result_type: QType,
        fn: Callable,
        c_symbol: Optional[str] = None,
        inline_template: Optional[str] = None,
    ) -> None:
        self.def_native_fn(
            name, params, result_type, fn, c_symbol=c_symbol, inline_template=inline_template
        )

    def def_poly_fn(
        self,
        name: str,
        type_param_name: str,
        type_param_id: int,
        params: list[tuple[str, QType]],
        result_type: QType,
        fn: Callable,
        c_symbol: Optional[str] = None,
        inline_template: Optional[str] = None,
    ) -> None:
        body_type: QType = _make_fn_type(params, result_type) if params else result_type
        poly_type = _make_poly_fn_type(type_param_name, type_param_id, body_type)
        sym = ValueSymbol(name=name, type_val=poly_type)
        self.scope.declare_value(sym)
        self.record_dict[name] = QBuiltinFun(f"{self.mod_name}.{name}", fn)
        self.typed_bindings.append(
            TypedNativeBinding(
                name=name,
                symbol=c_symbol or "",
                inline_template=inline_template,
                c_val=None,
                type_val=poly_type,
            )
        )

    def finish(self) -> QRecord:
        self.registry._interfaces[self.iface_name] = self.scope
        rec = QRecord(self.record_dict)
        self.registry._modules[self.mod_name] = rec
        self.registry._module_types[self.mod_name] = self.registry._build_record_type_from_scope(self.scope)
        self.registry._module_asts[self.mod_name] = TypedModule(
            name=self.mod_name,
            interface_name=self.iface_name,
            bindings=tuple(self.typed_bindings),
            scope=self.scope,
            c_init=self.c_init,
        )
        return rec


class BuiltinModuleRegistry:
    """Central registry of Cardelli standard library interfaces and runtime modules."""

    _WRITER_ERROR_EXC = QExceptionVal("writer.error")
    _READER_ERROR_EXC = QExceptionVal("reader.error")
    _ASCII_ERROR_EXC = QExceptionVal("ascii.error")
    _INT_ERROR_EXC = QExceptionVal("int.error")
    _REAL_ERROR_EXC = QExceptionVal("real.error")
    _STRING_ERROR_EXC = QExceptionVal("string.error")
    _LIST_ERROR_EXC = QExceptionVal("list.error")
    _SYSTEM_ERROR_EXC = QExceptionVal("system.error")

    # Module instances cache
    _initialized: bool = False
    _modules: dict[str, QRecord] = {}
    _interfaces: dict[str, Scope] = {}
    _module_types: dict[str, QType] = {}
    _module_asts: dict[str, TypedModule] = {}
    _symbol_bridge: dict[str, Any] = {}

    @classmethod
    def resolve_external_symbol(cls, symbol: str) -> QValue:
        """Resolves an external C symbol into a Python QValue for interpreter evaluation."""
        cls._ensure_initialized()
        clean = symbol.strip("(&)").strip()
        val = cls._symbol_bridge.get(symbol) or cls._symbol_bridge.get(clean)
        if val is None:
            raise QuestRuntimeError(f"Undefined external symbol '{symbol}' in interpreter")
        if callable(val) and not isinstance(val, QValue):
            return QBuiltinFun(symbol, val)
        return val

    @classmethod
    def get_interface(cls, name: str, env: Optional[Environment] = None) -> Optional[Scope]:
        """Returns the Scope containing the type signatures for the requested interface."""
        cls._ensure_initialized(env)
        return cls._interfaces.get(name)

    @classmethod
    def set_system_args(cls, args: list[str]) -> None:
        """Updates system.args with the provided argument list."""
        cls._ensure_initialized()
        sys_args_elements = tuple(QString(a) for a in args)
        sys_args_val = QArray(sys_args_elements)
        if "system" in cls._modules:
            cls._modules["system"].fields["args"] = sys_args_val
        cls._symbol_bridge["quest_system_args"] = sys_args_val

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
    def get_module_ast(cls, name: str, env: Optional[Environment] = None) -> Optional[TypedModule]:
        """Returns the TypedModule AST representing the requested builtin module."""
        cls._ensure_initialized(env)
        return cls._module_asts.get(name)

    @classmethod
    def _ensure_initialized(cls, env: Optional[Environment] = None) -> None:
        if cls._initialized:
            return
        cls._initialized = True

        class _IdGen:
            @classmethod
            def fresh_symbol_id(cls) -> int:
                return allocate_symbol_id()

        e: Any = env if env is not None else _IdGen

        # --------------------------------------------------------------------
        # 1. Writer Interface & Module
        # --------------------------------------------------------------------
        writer_t_id = e.fresh_symbol_id()
        writer_t = QTypeVar(name="Writer.T", symbol_id=writer_t_id, bound=TYPE_KIND)
        w_b = ModuleBuilder("writer", "Writer", cls)
        w_b.def_external_type("T", writer_t_id, TYPE_KIND, "QWriter *")
        w_b.def_const("error", EXCEPTION_TYPE, cls._WRITER_ERROR_EXC, c_val="(&quest_exc_writer_error)")
        w_b.def_const("output", writer_t, QWriter(sys.stdout, is_file=False), c_val="quest_writer_output")
        w_b.def_const("err", writer_t, QWriter(sys.stderr, is_file=False), c_val="quest_writer_err")

        @qchecked(cls._WRITER_ERROR_EXC, QString)
        def _writer_file(name_val: QString) -> QWriter:
            try:
                f = open(name_val.value, "w", encoding="utf-8")
                return QWriter(stream=f, is_file=True, file_name=name_val.value)
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        @qchecked(cls._WRITER_ERROR_EXC, QWriter, QString)
        def _writer_put_string(w: QWriter, s: QString) -> QOk:
            if w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(s.value)
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        @qchecked(cls._WRITER_ERROR_EXC, QWriter, QChar)
        def _writer_put_char(w: QWriter, c: QChar) -> QOk:
            if w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(c.value)
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        @qchecked(cls._WRITER_ERROR_EXC, QWriter, QString, QInt, QInt)
        def _writer_put_sub_string(w: QWriter, s: QString, start: QInt, size: QInt) -> QOk:
            if w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.write(s.value[st : st + sz])
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        @qchecked(cls._WRITER_ERROR_EXC, QWriter)
        def _writer_flush(w: QWriter) -> QOk:
            if w.is_closed:
                raise QuestException(cls._WRITER_ERROR_EXC)
            try:
                w.stream.flush()
                return OK_VALUE
            except OSError:
                raise QuestException(cls._WRITER_ERROR_EXC)

        @qchecked(cls._WRITER_ERROR_EXC, QWriter)
        def _writer_close(w: QWriter) -> QOk:
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

        w_b.def_fn("file", [("name", STRING_TYPE)], writer_t, _writer_file, c_symbol="quest_writer_file")
        w_b.def_fn(
            "putString",
            [("writer", writer_t), ("string", STRING_TYPE)],
            OK_TYPE,
            _writer_put_string,
            c_symbol="quest_writer_put_string",
        )
        w_b.def_fn(
            "putChar",
            [("writer", writer_t), ("char", CHAR_TYPE)],
            OK_TYPE,
            _writer_put_char,
            c_symbol="quest_writer_put_char",
        )
        w_b.def_fn(
            "putSubString",
            [("writer", writer_t), ("string", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
            OK_TYPE,
            _writer_put_sub_string,
            c_symbol="quest_writer_put_substring",
        )
        w_b.def_fn("flush", [("writer", writer_t)], OK_TYPE, _writer_flush, c_symbol="quest_writer_flush")
        w_b.def_fn("close", [("writer", writer_t)], OK_TYPE, _writer_close, c_symbol="quest_writer_close")
        w_b.finish()

        # --------------------------------------------------------------------
        # 2. Reader Interface & Module
        # --------------------------------------------------------------------
        reader_t_id = e.fresh_symbol_id()
        reader_t = QTypeVar(name="Reader.T", symbol_id=reader_t_id, bound=TYPE_KIND)
        r_b = ModuleBuilder("reader", "Reader", cls)
        r_b.def_external_type("T", reader_t_id, TYPE_KIND, "QReader *")
        r_b.def_const("error", EXCEPTION_TYPE, cls._READER_ERROR_EXC, c_val="(&quest_exc_reader_error)")
        r_b.def_const("input", reader_t, QReader(sys.stdin, is_file=False), c_val="quest_reader_input")

        @qchecked(cls._READER_ERROR_EXC, QString)
        def _reader_file(name_val: QString) -> QReader:
            try:
                f = open(name_val.value, "r", encoding="utf-8")
                return QReader(stream=f, is_file=True, file_name=name_val.value)
            except OSError:
                raise QuestException(cls._READER_ERROR_EXC)

        def _reader_read_one(r: QReader) -> str:
            peek = getattr(r, "_peek_char", None)
            if peek is not None:
                r._peek_char = None
                return peek
            return r.stream.read(1)

        @qchecked(cls._READER_ERROR_EXC, QReader)
        def _reader_more(r: QReader) -> QBool:
            if r.is_closed:
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

        @qchecked(cls._READER_ERROR_EXC, QReader)
        def _reader_ready(r: QReader) -> QInt:
            if r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            return QInt(0)

        @qchecked(cls._READER_ERROR_EXC, QReader)
        def _reader_get_char(r: QReader) -> QChar:
            if r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            try:
                ch = _reader_read_one(r)
                if not ch:
                    raise QuestException(cls._READER_ERROR_EXC)
                return QChar(ch)
            except OSError:
                raise QuestException(cls._READER_ERROR_EXC)

        @qchecked(cls._READER_ERROR_EXC, QReader, QInt)
        def _reader_get_string(r: QReader, size: QInt) -> QString:
            if r.is_closed:
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

        @qchecked(cls._READER_ERROR_EXC, QReader, QString, QInt, QInt)
        def _reader_get_sub_string(r: QReader, s: QString, start: QInt, size: QInt) -> QOk:
            if r.is_closed:
                raise QuestException(cls._READER_ERROR_EXC)
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._READER_ERROR_EXC)
            read_str = _reader_get_string(r, size).value
            s.value = s.value[:st] + read_str + s.value[st + len(read_str) :]
            return OK_VALUE

        @qchecked(cls._READER_ERROR_EXC, QReader)
        def _reader_close(r: QReader) -> QOk:
            if not r.is_closed:
                try:
                    if r.is_file:
                        r.stream.close()
                    r.is_closed = True
                except OSError:
                    raise QuestException(cls._READER_ERROR_EXC)
            return OK_VALUE

        r_b.def_fn("file", [("name", STRING_TYPE)], reader_t, _reader_file, c_symbol="quest_reader_file")
        r_b.def_fn("more", [("reader", reader_t)], BOOL_TYPE, _reader_more, c_symbol="quest_reader_more")
        r_b.def_fn("ready", [("reader", reader_t)], INT_TYPE, _reader_ready, c_symbol="quest_reader_ready")
        r_b.def_fn("getChar", [("reader", reader_t)], CHAR_TYPE, _reader_get_char, c_symbol="quest_reader_get_char")
        r_b.def_fn(
            "getString",
            [("reader", reader_t), ("size", INT_TYPE)],
            STRING_TYPE,
            _reader_get_string,
            c_symbol="quest_reader_get_string",
        )
        r_b.def_fn(
            "getSubString",
            [("reader", reader_t), ("string", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
            OK_TYPE,
            _reader_get_sub_string,
            c_symbol="quest_reader_get_substring",
        )
        r_b.def_fn("close", [("reader", reader_t)], OK_TYPE, _reader_close, c_symbol="quest_reader_close")
        r_b.finish()

        # --------------------------------------------------------------------
        # 3. Conv Interface & Module (Tilde ~ for negative numbers)
        # --------------------------------------------------------------------
        conv_b = ModuleBuilder("conv", "Conv", cls)

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

        conv_b.def_fn("okay", [], STRING_TYPE, lambda: QString("ok"), c_symbol="quest_conv_okay")
        conv_b.def_fn(
            "bool",
            [("b", BOOL_TYPE)],
            STRING_TYPE,
            lambda b: QString("true" if getattr(b, "value", False) else "false"),
            c_symbol="quest_conv_bool",
        )
        conv_b.def_fn("int", [("n", INT_TYPE)], STRING_TYPE, _conv_int, c_symbol="quest_conv_int")
        conv_b.def_fn("real", [("r", REAL_TYPE)], STRING_TYPE, _conv_real, c_symbol="quest_conv_real")
        conv_b.def_fn(
            "char",
            [("c", CHAR_TYPE)],
            STRING_TYPE,
            lambda c: QString(c.to_str() if isinstance(c, QChar) else ""),
            c_symbol="quest_conv_char",
        )
        conv_b.def_fn(
            "string",
            [("s", STRING_TYPE)],
            STRING_TYPE,
            lambda s: QString(s.to_str() if isinstance(s, QString) else ""),
            c_symbol="quest_conv_string",
        )
        conv_b.finish()

        # --------------------------------------------------------------------
        # 4. Ascii Interface & Module
        # --------------------------------------------------------------------
        asc_b = ModuleBuilder("ascii", "Ascii", cls)
        asc_b.def_const("error", EXCEPTION_TYPE, cls._ASCII_ERROR_EXC, c_val="(&quest_exc_ascii_error)")

        @qchecked(cls._ASCII_ERROR_EXC, QInt)
        def _ascii_char(n: QInt) -> QChar:
            if n.value < 0 or n.value > 255:
                raise QuestException(cls._ASCII_ERROR_EXC)
            return QChar(chr(n.value))

        @qchecked(cls._ASCII_ERROR_EXC, QChar)
        def _ascii_val(c: QChar) -> QInt:
            return QInt(ord(c.value))

        asc_b.def_fn("char", [("n", INT_TYPE)], CHAR_TYPE, _ascii_char, c_symbol="quest_ascii_char")
        asc_b.def_fn("val", [("c", CHAR_TYPE)], INT_TYPE, _ascii_val, c_symbol="quest_ascii_val")
        asc_b.finish()

        # --------------------------------------------------------------------
        # 5. IntOp Interface & Module
        # --------------------------------------------------------------------
        int_b = ModuleBuilder("int", "IntOp", cls)
        int_b.def_const("error", EXCEPTION_TYPE, cls._INT_ERROR_EXC, c_val="(&quest_exc_int_error)")
        int_b.def_const("minInt", INT_TYPE, QInt(-9223372036854775808), c_val="QUEST_INT_MIN")
        int_b.def_const("maxInt", INT_TYPE, QInt(9223372036854775807), c_val="QUEST_INT_MAX")
        int_b.def_fn(
            "abs", [("n", INT_TYPE)], INT_TYPE, lambda n: QInt(abs(n.value)), c_symbol="quest_int_abs"
        )
        int_b.def_fn(
            "min",
            [("a", INT_TYPE), ("b", INT_TYPE)],
            INT_TYPE,
            lambda a, b: QInt(min(a.value, b.value)),
            c_symbol="quest_int_min",
        )
        int_b.def_fn(
            "max",
            [("a", INT_TYPE), ("b", INT_TYPE)],
            INT_TYPE,
            lambda a, b: QInt(max(a.value, b.value)),
            c_symbol="quest_int_max",
        )
        int_b.finish()

        # --------------------------------------------------------------------
        # 6. RealOp Interface & Module
        # --------------------------------------------------------------------
        real_b = ModuleBuilder("real", "RealOp", cls)
        real_b.def_const("error", EXCEPTION_TYPE, cls._REAL_ERROR_EXC, c_val="(&quest_exc_real_error)")
        real_b.def_const("minReal", REAL_TYPE, QReal(-sys.float_info.max), c_val="QUEST_REAL_MIN")
        real_b.def_const("maxReal", REAL_TYPE, QReal(sys.float_info.max), c_val="QUEST_REAL_MAX")
        real_b.def_const("posEpsilon", REAL_TYPE, QReal(sys.float_info.epsilon), c_val="QUEST_REAL_POS_EPSILON")
        real_b.def_const("negEpsilon", REAL_TYPE, QReal(-sys.float_info.epsilon), c_val="QUEST_REAL_NEG_EPSILON")
        real_b.def_const("e", REAL_TYPE, QReal(math.e), c_val="QUEST_REAL_E")

        @qchecked(cls._REAL_ERROR_EXC, QReal)
        def _real_log(r: QReal) -> QReal:
            if r.value <= 0.0:
                raise QuestException(cls._REAL_ERROR_EXC)
            return QReal(math.log(r.value))

        @qchecked(cls._REAL_ERROR_EXC, QReal, QReal)
        def _real_div(a: QReal, b: QReal) -> QReal:
            if b.value == 0.0:
                raise QuestException(cls._REAL_ERROR_EXC)
            return QReal(a.value / b.value)

        @qchecked(cls._REAL_ERROR_EXC, QReal, QReal)
        def _real_exp(a: QReal, b: QReal) -> QReal:
            try:
                return QReal(math.pow(a.value, b.value))
            except (ValueError, OverflowError):
                raise QuestException(cls._REAL_ERROR_EXC)

        real_b.def_fn(
            "int", [("n", INT_TYPE)], REAL_TYPE, lambda n: QReal(float(n.value)),
            inline_template="((double)({0}))",
        )
        real_b.def_fn(
            "floor", [("r", REAL_TYPE)], INT_TYPE, lambda r: QInt(math.floor(r.value)),
            c_symbol="quest_real_floor",
        )
        real_b.def_fn(
            "round", [("r", REAL_TYPE)], INT_TYPE, lambda r: QInt(round(r.value)),
            c_symbol="quest_real_round",
        )
        real_b.def_fn(
            "abs", [("r", REAL_TYPE)], REAL_TYPE, lambda r: QReal(abs(r.value)),
            c_symbol="quest_real_abs",
        )
        real_b.def_fn("log", [("r", REAL_TYPE)], REAL_TYPE, _real_log, c_symbol="quest_real_log")
        real_b.def_fn(
            "min",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            REAL_TYPE,
            lambda a, b: QReal(min(a.value, b.value)),
            c_symbol="quest_real_min",
        )
        real_b.def_fn(
            "max",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            REAL_TYPE,
            lambda a, b: QReal(max(a.value, b.value)),
            c_symbol="quest_real_max",
        )
        real_b.def_fn(
            "plus",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            REAL_TYPE,
            lambda a, b: QReal(a.value + b.value),
            inline_template="({0} + {1})",
        )
        real_b.def_fn(
            "diff",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            REAL_TYPE,
            lambda a, b: QReal(a.value - b.value),
            inline_template="({0} - {1})",
        )
        real_b.def_fn(
            "mul",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            REAL_TYPE,
            lambda a, b: QReal(a.value * b.value),
            inline_template="({0} * {1})",
        )
        real_b.def_fn("div", [("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE, _real_div, c_symbol="quest_real_div")
        real_b.def_fn("exp", [("a", REAL_TYPE), ("b", REAL_TYPE)], REAL_TYPE, _real_exp, c_symbol="quest_real_exp")
        real_b.def_fn(
            "smaller",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            BOOL_TYPE,
            lambda a, b: QBool(a.value < b.value),
            inline_template="({0} < {1})",
        )
        real_b.def_fn(
            "greater",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            BOOL_TYPE,
            lambda a, b: QBool(a.value > b.value),
            inline_template="({0} > {1})",
        )
        real_b.def_fn(
            "smallerEq",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            BOOL_TYPE,
            lambda a, b: QBool(a.value <= b.value),
            inline_template="({0} <= {1})",
        )
        real_b.def_fn(
            "greaterEq",
            [("a", REAL_TYPE), ("b", REAL_TYPE)],
            BOOL_TYPE,
            lambda a, b: QBool(a.value >= b.value),
            inline_template="({0} >= {1})",
        )
        real_b.finish()

        # --------------------------------------------------------------------
        # 7. StringOp Interface & Module
        # --------------------------------------------------------------------
        str_b = ModuleBuilder("string", "StringOp", cls)
        str_b.def_const("error", EXCEPTION_TYPE, cls._STRING_ERROR_EXC, c_val="(&quest_exc_string_error)")

        @qchecked(cls._STRING_ERROR_EXC, QInt, QChar)
        def _string_new(size: QInt, init: QChar) -> QString:
            if size.value < 0:
                raise QuestException(cls._STRING_ERROR_EXC)
            return QString(init.value * size.value)

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt)
        def _string_get_char(s: QString, index: QInt) -> QChar:
            idx = index.value
            if idx < 0 or idx >= len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            return QChar(s.value[idx])

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QChar)
        def _string_set_char(s: QString, index: QInt, char: QChar) -> QOk:
            idx = index.value
            if idx < 0 or idx >= len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            s.value = s.value[:idx] + char.value + s.value[idx + 1 :]
            return OK_VALUE

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QInt)
        def _string_get_sub(s: QString, start: QInt, size: QInt) -> QString:
            st, sz = start.value, size.value
            if st < 0 or sz < 0 or st + sz > len(s.value):
                raise QuestException(cls._STRING_ERROR_EXC)
            return QString(s.value[st : st + sz])

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QString, QInt, QInt)
        def _string_set_sub(dest: QString, d_st: QInt, src: QString, s_st: QInt, sz: QInt) -> QOk:
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

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QInt, QString, QInt, QInt)
        def _string_cat_sub(s1: QString, st1: QInt, sz1: QInt, s2: QString, st2: QInt, sz2: QInt) -> QString:
            sub1 = _string_get_sub(s1, st1, sz1).value
            sub2 = _string_get_sub(s2, st2, sz2).value
            return QString(sub1 + sub2)

        @qchecked(cls._STRING_ERROR_EXC, QArray)
        def _string_conc(arr: QArray) -> QString:
            parts: list[str] = []
            for elem in arr.elements:
                if not isinstance(elem, QString):
                    raise QuestException(cls._STRING_ERROR_EXC)
                parts.append(elem.value)
            return QString("".join(parts))

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QInt, QString, QInt, QInt)
        def _string_equal_sub(s1: QString, st1: QInt, sz1: QInt, s2: QString, st2: QInt, sz2: QInt) -> QBool:
            sub1 = _string_get_sub(s1, st1, sz1).value
            sub2 = _string_get_sub(s2, st2, sz2).value
            return QBool(sub1 == sub2)

        @qchecked(cls._STRING_ERROR_EXC, QString, QInt, QInt, QString, QInt, QInt)
        def _string_precedes_sub(
            s1: QString, st1: QInt, sz1: QInt, s2: QString, st2: QInt, sz2: QInt
        ) -> QBool:
            sub1 = _string_get_sub(s1, st1, sz1).value
            sub2 = _string_get_sub(s2, st2, sz2).value
            return QBool(sub1 <= sub2)

        str_b.def_fn(
            "new", [("size", INT_TYPE), ("init", CHAR_TYPE)], STRING_TYPE, _string_new,
            c_symbol="quest_string_alloc",
        )
        str_b.def_fn(
            "isEmpty", [("string", STRING_TYPE)], BOOL_TYPE, lambda s: QBool(len(s.value) == 0),
            c_symbol="quest_string_is_empty",
        )
        str_b.def_fn(
            "length", [("string", STRING_TYPE)], INT_TYPE, lambda s: QInt(len(s.value)),
            inline_template="({0}->length)",
        )
        str_b.def_fn(
            "getChar", [("string", STRING_TYPE), ("index", INT_TYPE)], CHAR_TYPE, _string_get_char,
            c_symbol="quest_string_get_char",
        )
        str_b.def_fn(
            "setChar",
            [("string", STRING_TYPE), ("index", INT_TYPE), ("char", CHAR_TYPE)],
            OK_TYPE,
            _string_set_char,
            c_symbol="quest_string_set_char",
        )
        str_b.def_fn(
            "getSub",
            [("source", STRING_TYPE), ("start", INT_TYPE), ("size", INT_TYPE)],
            STRING_TYPE,
            _string_get_sub,
            c_symbol="quest_string_get_sub",
        )
        str_b.def_fn(
            "setSub",
            [
                ("dest", STRING_TYPE),
                ("destStart", INT_TYPE),
                ("source", STRING_TYPE),
                ("sourceStart", INT_TYPE),
                ("sourceSize", INT_TYPE),
            ],
            OK_TYPE,
            _string_set_sub,
            c_symbol="quest_string_set_sub",
        )
        str_b.def_fn(
            "cat",
            [("s1", STRING_TYPE), ("s2", STRING_TYPE)],
            STRING_TYPE,
            lambda s1, s2: QString(s1.value + s2.value),
            c_symbol="quest_string_concat",
        )
        str_b.def_fn(
            "catSub",
            [
                ("s1", STRING_TYPE),
                ("start1", INT_TYPE),
                ("size1", INT_TYPE),
                ("s2", STRING_TYPE),
                ("start2", INT_TYPE),
                ("size2", INT_TYPE),
            ],
            STRING_TYPE,
            _string_cat_sub,
            c_symbol="quest_string_cat_sub",
        )
        str_b.def_fn(
            "conc", [("a", QArrayType(STRING_TYPE))], STRING_TYPE, _string_conc,
            c_symbol="quest_string_conc",
        )
        str_b.def_fn(
            "equal",
            [("s1", STRING_TYPE), ("s2", STRING_TYPE)],
            BOOL_TYPE,
            lambda s1, s2: QBool(s1.value == s2.value),
            c_symbol="quest_string_equal",
        )
        str_b.def_fn(
            "equalSub",
            [
                ("s1", STRING_TYPE),
                ("start1", INT_TYPE),
                ("size1", INT_TYPE),
                ("s2", STRING_TYPE),
                ("start2", INT_TYPE),
                ("size2", INT_TYPE),
            ],
            BOOL_TYPE,
            _string_equal_sub,
            c_symbol="quest_string_equal_sub",
        )
        str_b.def_fn(
            "precedes",
            [("s1", STRING_TYPE), ("s2", STRING_TYPE)],
            BOOL_TYPE,
            lambda s1, s2: QBool(s1.value <= s2.value),
            c_symbol="quest_string_precedes",
        )
        str_b.def_fn(
            "precedesSub",
            [
                ("s1", STRING_TYPE),
                ("start1", INT_TYPE),
                ("size1", INT_TYPE),
                ("s2", STRING_TYPE),
                ("start2", INT_TYPE),
                ("size2", INT_TYPE),
            ],
            BOOL_TYPE,
            _string_precedes_sub,
            c_symbol="quest_string_precedes_sub",
        )
        str_b.finish()

        # --------------------------------------------------------------------
        # 8. ArrayOp Interface & Module
        # --------------------------------------------------------------------
        arr_a_id = e.fresh_symbol_id()
        arr_a = QTypeVar(name="A", symbol_id=arr_a_id, bound=TYPE_KIND)
        arr_b = ModuleBuilder("arrayOp", "ArrayOp", cls)
        arr_b.def_const("error", EXCEPTION_TYPE, ARRAY_OP_ERROR_EXC, c_val="(&quest_exc_arrayOp_error)")

        @qchecked(ARRAY_OP_ERROR_EXC, QInt, QValue)
        def _array_new(size: QInt, init: QValue) -> QArray:
            if size.value < 0:
                raise QuestException(ARRAY_OP_ERROR_EXC)
            return QArray([init for _ in range(size.value)])

        @qchecked(ARRAY_OP_ERROR_EXC, QArray)
        def _array_size(arr: QArray) -> QInt:
            return QInt(arr.size())

        @qchecked(ARRAY_OP_ERROR_EXC, QArray, QInt)
        def _array_get(arr: QArray, idx: QInt) -> QValue:
            i = idx.value
            if i < 0 or i >= arr.size():
                raise QuestException(ARRAY_OP_ERROR_EXC)
            return arr.get(i)

        @qchecked(ARRAY_OP_ERROR_EXC, QArray, QInt, QValue)
        def _array_set(arr: QArray, idx: QInt, item: QValue) -> QOk:
            i = idx.value
            if i < 0 or i >= arr.size():
                raise QuestException(ARRAY_OP_ERROR_EXC)
            arr.set(i, item)
            return OK_VALUE

        arr_b.def_poly_fn(
            "new",
            "A",
            arr_a_id,
            [("size", INT_TYPE), ("init", arr_a)],
            QArrayType(arr_a),
            _array_new,
        )
        arr_b.def_poly_fn("size", "A", arr_a_id, [("array", QArrayType(arr_a))], INT_TYPE, _array_size)
        arr_b.def_poly_fn(
            "get",
            "A",
            arr_a_id,
            [("array", QArrayType(arr_a)), ("index", INT_TYPE)],
            arr_a,
            _array_get,
        )
        arr_b.def_poly_fn(
            "set",
            "A",
            arr_a_id,
            [("array", QArrayType(arr_a)), ("index", INT_TYPE), ("item", arr_a)],
            OK_TYPE,
            _array_set,
        )
        arr_b.finish()

        # --------------------------------------------------------------------
        # 9. Dynamic Interface & Module
        # --------------------------------------------------------------------
        dyn_t_id = e.fresh_symbol_id()
        dyn_t = QTypeVar(name="Dynamic.T", symbol_id=dyn_t_id, bound=TYPE_KIND)
        dyn_a_id = e.fresh_symbol_id()
        dyn_a = QTypeVar(name="A", symbol_id=dyn_a_id, bound=TYPE_KIND)
        dyn_b = ModuleBuilder("dynamic", "Dynamic", cls)
        dyn_b.def_type("T", dyn_t_id, TYPE_KIND, definition=DYNAMIC_TYPE)
        dyn_b.def_const("error", EXCEPTION_TYPE, DYNAMIC_ERROR_EXC, c_val="(&quest_exc_dynamic_error)")

        @qchecked(DYNAMIC_ERROR_EXC, QValue)
        def _dynamic_new(val: QValue) -> QDynamicVal:
            return QDynamicVal(value=val, type_val=_infer_qtype(val))

        @qchecked(DYNAMIC_ERROR_EXC, QDynamicVal)
        def _dynamic_be(d: QDynamicVal) -> QValue:
            return d.value

        @qchecked(DYNAMIC_ERROR_EXC, QDynamicVal)
        def _dynamic_copy(d: QDynamicVal) -> QDynamicVal:
            return QDynamicVal(value=d.value, type_val=d.type_val)

        @qchecked(DYNAMIC_ERROR_EXC, QWriter, QDynamicVal)
        def _dynamic_extern(wr: QWriter, d: QDynamicVal) -> QOk:
            if wr.is_closed:
                raise QuestException(DYNAMIC_ERROR_EXC)
            from quest.dynamic_json import jsog_encode
            json_text = jsog_encode(d)
            try:
                wr.stream.write(json_text)
                return OK_VALUE
            except OSError:
                raise QuestException(DYNAMIC_ERROR_EXC)

        @qchecked(DYNAMIC_ERROR_EXC, QReader)
        def _dynamic_intern(rd: QReader) -> QDynamicVal:
            if rd.is_closed:
                raise QuestException(DYNAMIC_ERROR_EXC)
            buf = []
            peek = getattr(rd, "_peek_char", None)
            if peek is not None:
                buf.append(peek)
                rd._peek_char = None
            try:
                rest = rd.stream.read()
                if rest:
                    buf.append(rest)
            except OSError:
                raise QuestException(DYNAMIC_ERROR_EXC)
            raw = "".join(buf).strip()
            if not raw:
                raise QuestException(DYNAMIC_ERROR_EXC)
            from quest.dynamic_json import jsog_decode
            return jsog_decode(raw)

        dyn_b.def_poly_fn("new", "A", dyn_a_id, [("a", dyn_a)], dyn_t, _dynamic_new)
        dyn_b.def_poly_fn("be", "A", dyn_a_id, [("d", dyn_t)], dyn_a, _dynamic_be)
        dyn_b.def_fn("copy", [("d", dyn_t)], dyn_t, _dynamic_copy)
        dyn_b.def_fn("intern", [("rd", reader_t)], dyn_t, _dynamic_intern)
        dyn_b.def_fn("extern", [("wr", writer_t), ("d", dyn_t)], OK_TYPE, _dynamic_extern)
        dyn_b.finish()

        # --------------------------------------------------------------------
        # 10. List Interface & Module
        # --------------------------------------------------------------------
        list_param_id = e.fresh_symbol_id()
        list_kind = QAllKind(
            param_name="A",
            param_id=list_param_id,
            param_kind=TYPE_KIND,
            result_kind=TYPE_KIND,
        )
        list_t_id = e.fresh_symbol_id()
        list_t = QTypeVar(name="List.T", symbol_id=list_t_id, bound=list_kind)
        list_a_id = e.fresh_symbol_id()
        list_a = QTypeVar(name="A", symbol_id=list_a_id, bound=TYPE_KIND)
        list_t_app = QTypeApp(constructor=list_t, arguments=(list_a,))

        list_b = ModuleBuilder("list", "List", cls)
        list_b.def_type("T", list_t_id, list_kind, definition=None)
        list_b.def_const("error", EXCEPTION_TYPE, cls._LIST_ERROR_EXC)

        def _list_nil(*args: Any) -> QList:
            return QList(())

        @qchecked(cls._LIST_ERROR_EXC, QValue, QList)
        def _list_cons(item: QValue, l: QList) -> QList:
            return QList((item,) + l.elements)

        @qchecked(cls._LIST_ERROR_EXC, QList)
        def _list_null(l: QList) -> QBool:
            return TRUE_VALUE if len(l.elements) == 0 else FALSE_VALUE

        @qchecked(cls._LIST_ERROR_EXC, QList)
        def _list_head(l: QList) -> QValue:
            if not l.elements:
                raise QuestException(cls._LIST_ERROR_EXC)
            return l.elements[0]

        @qchecked(cls._LIST_ERROR_EXC, QList)
        def _list_tail(l: QList) -> QList:
            if not l.elements:
                raise QuestException(cls._LIST_ERROR_EXC)
            return QList(l.elements[1:])

        @qchecked(cls._LIST_ERROR_EXC, QList)
        def _list_length(l: QList) -> QInt:
            return QInt(len(l.elements))

        @qchecked(cls._LIST_ERROR_EXC, QArray)
        def _list_enum(arr: QArray) -> QList:
            return QList(tuple(arr.elements))

        list_b.def_poly_fn("nil", "A", list_a_id, [], list_t_app, _list_nil)
        list_b.def_poly_fn(
            "cons",
            "A",
            list_a_id,
            [("item", list_a), ("list", list_t_app)],
            list_t_app,
            _list_cons,
        )
        list_b.def_poly_fn(
            "null",
            "A",
            list_a_id,
            [("list", list_t_app)],
            BOOL_TYPE,
            _list_null,
        )
        list_b.def_poly_fn(
            "head",
            "A",
            list_a_id,
            [("list", list_t_app)],
            list_a,
            _list_head,
        )
        list_b.def_poly_fn(
            "tail",
            "A",
            list_a_id,
            [("list", list_t_app)],
            list_t_app,
            _list_tail,
        )
        list_b.def_poly_fn(
            "length",
            "A",
            list_a_id,
            [("list", list_t_app)],
            INT_TYPE,
            _list_length,
        )
        list_b.def_poly_fn(
            "enum",
            "A",
            list_a_id,
            [("array", QArrayType(list_a))],
            list_t_app,
            _list_enum,
        )
        list_b.finish()

        # --------------------------------------------------------------------
        # 10. System Interface & Module (Necessary OS extensions)
        # --------------------------------------------------------------------
        import os

        sys_b = ModuleBuilder("system", "System", cls)
        sys_b.def_const("error", EXCEPTION_TYPE, cls._SYSTEM_ERROR_EXC, c_val="(&quest_exc_system_error)")

        sys_args_elements = tuple(QString(a) for a in sys.argv)
        sys_args_val = QArray(sys_args_elements)
        sys_b.def_const("args", QArrayType(STRING_TYPE), sys_args_val, c_val="quest_system_args")

        @qchecked(cls._SYSTEM_ERROR_EXC, QInt)
        def _system_exit(code: QInt) -> QOk:
            sys.exit(code.value)

        @qchecked(cls._SYSTEM_ERROR_EXC, QString)
        def _system_getenv(name_val: QString) -> QString:
            return QString(os.environ.get(name_val.value, ""))

        @qchecked(cls._SYSTEM_ERROR_EXC, QString)
        def _system_file_exists(path_val: QString) -> QBool:
            return TRUE_VALUE if os.path.exists(path_val.value) else FALSE_VALUE

        sys_b.def_fn(
            "sysexit", [("code", INT_TYPE)], OK_TYPE, _system_exit, c_symbol="quest_system_exit"
        )
        sys_b.def_fn(
            "sysExit", [("code", INT_TYPE)], OK_TYPE, _system_exit, c_symbol="quest_system_exit"
        )
        sys_b.def_fn(
            "getEnv", [("name", STRING_TYPE)], STRING_TYPE, _system_getenv, c_symbol="quest_system_getenv"
        )
        sys_b.def_fn(
            "fileExists", [("path", STRING_TYPE)], BOOL_TYPE, _system_file_exists,
            c_symbol="quest_system_file_exists",
        )
        sys_b.finish()
        cls._symbol_bridge.update({
            "QUEST_INT_MAX": QInt(9223372036854775807),
            "QUEST_INT_MIN": QInt(-9223372036854775808),
            "QUEST_REAL_MIN": QReal(2.2250738585072014e-308),
            "QUEST_REAL_MAX": QReal(1.7976931348623157e+308),
            "QUEST_REAL_EPSILON": QReal(2.220446049250313e-16),
            "QUEST_REAL_E": QReal(math.e),
            "QUEST_REAL_PI": QReal(math.pi),
            "sin": lambda r: QReal(math.sin(r.value)),
            "cos": lambda r: QReal(math.cos(r.value)),
            "tan": lambda r: QReal(math.tan(r.value)),
            "asin": lambda r: QReal(math.asin(r.value)),
            "acos": lambda r: QReal(math.acos(r.value)),
            "atan": lambda r: QReal(math.atan(r.value)),
            "atan2": lambda y, x: QReal(math.atan2(y.value, x.value)),
            "exp": lambda r: QReal(math.exp(r.value)),
            "log": lambda r: QReal(math.log(r.value)),
            "sqrt": lambda r: QReal(math.sqrt(r.value)),
            "pow": lambda x, y: QReal(math.pow(x.value, y.value)),
            "floor": lambda r: QReal(math.floor(r.value)),
            "ceil": lambda r: QReal(math.ceil(r.value)),
            "round": lambda r: QReal(round(r.value)),
            "trunc": lambda r: QReal(math.trunc(r.value)),
            "quest_array_size": lambda arr: QInt(len(arr.elements)),
            "quest_string_length": lambda s: QInt(len(s.value)),
            "quest_real_from_int": lambda n: QReal(float(n.value)),
        })

    @classmethod
    def _build_record_type_from_scope(cls, scope: Scope) -> QRecordType:
        """Constructs a QRecordType matching the values exposed by an interface scope."""
        fields = [
            QRecordField(name=name, type_val=sym.type_val)
            for name, sym in scope.values.items()
        ]
        return QRecordType(tuple(fields))
