"""Quest Bootstrap Tree-Walking Interpreter & Core Evaluation.

Implements Phase 3.2 of the Quest compiler:
- Scoped runtime environment (RuntimeEnvironment)
- Core literal evaluations (Int, Real, Bool, Char, String, Ok)
- Variable lookup, assignment, and mutable cell dereferencing
- Arithmetic operators (+, -, *, /, mod) with C-style truncation and DivideByZero exception
- Relational comparisons (<, <=, >, >=) and equality (is, isnot, ==, <>)
- Short-circuit conditionals (TypedIf)
- Loops (TypedLoop, TypedWhile, TypedFor) and early exit (TypedExit via _LoopExit)
- Scoped block evaluation (TypedBlock)
- Top-level program evaluation (TypedProgram)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from quest.diagnostics import Diagnostic, DiagnosticLabel, QuestCompilerError, Severity
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
    QExceptionVal,
    QInt,
    QList,
    QOk,
    QOption,
    QReal,
    QRecord,
    QRef,
    QArrayElementRef,
    QTupleElementRef,
    QString,
    QTuple,
    QTypeValue,
    QValue,
    QVariant,
    qvalue_is,
    qvalue_to_str,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    DYNAMIC_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QOptionType,
    QTupleType,
    QTupleTypeFormal,
    QTupleTypeBinding,
    QTupleField,
    QPathType,
    QTypeVar,
    QType,
    REAL_TYPE,
    STRING_TYPE,
    is_subtype,
)
from quest.typed_ast import (
    TypedApp,
    TypedArray,
    TypedArrayRep,
    TypedAssign,
    TypedBinding,
    TypedBlock,
    TypedBool,
    TypedCase,
    TypedChar,
    TypedDefKind,
    TypedDerefCell,
    TypedException,
    TypedExit,
    TypedExpr,
    TypedExprStmt,
    TypedExternal,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedIndex,
    TypedIndexAssign,
    TypedIndexRef,
    TypedInfix,
    TypedImport,
    TypedInspect,
    TypedInspectBranch,
    TypedInterface,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedModule,
    TypedNode,
    TypedOk,
    TypedOption,
    TypedProgram,
    TypedRaise,
    TypedReal,
    TypedRecord,
    TypedSelect,
    TypedSelectRef,
    TypedTupleSelectRef,
    TypedString,
    TypedTry,
    TypedTryBranch,
    TypedTuple,
    TypedTypeApp,
    TypedTypeWitness,
    TypedVar,
    TypedVarCell,
    TypedVariant,
    TypedVariantAssert,
    TypedVariantCheck,
    TypedWhile,
)


# ============================================================================
# 1. Runtime Exceptions & Control Signals
# ============================================================================

class _LoopExit(Exception):
    """Internal control-flow signal raised by TypedExit to break out of loops."""
    pass


class QuestException(QuestCompilerError):
    """Language-level Quest exception (e.g. DivideByZero or user-raised exception)."""

    def __init__(
        self,
        exc_val: QExceptionVal,
        payload: Optional[QValue] = None,
        payload_type: Optional[QType] = None,
        offset: Optional[int] = None,
        length: int = 1,
    ):
        super().__init__(message=exc_val.to_str(), offset=offset, length=length)
        self.exc_val = exc_val
        self.payload = payload
        self.payload_type = payload_type

    def to_diagnostic(self, length: Optional[int] = None) -> Diagnostic:
        len_val = length if length is not None else self.length
        label = DiagnosticLabel(offset=self.offset, length=len_val) if self.offset is not None else None
        if self.payload is not None and not isinstance(self.payload, QOk):
            payload_str = qvalue_to_str(self.payload)
            type_str = f":{self.payload_type}" if self.payload_type is not None else ""
            msg = f"Exception: {self.exc_val.name} with {payload_str}{type_str}"
        else:
            msg = f"Exception: {self.exc_val.name}"
        return Diagnostic(
            severity=Severity.ERROR,
            message=msg,
            primary_label=label,
        )


class QuestRuntimeError(QuestCompilerError):
    """System-level runtime evaluation error (e.g. undefined symbol)."""

    def __init__(self, message: str, offset: Optional[int] = None, length: int = 1):
        super().__init__(message=message, offset=offset, length=length)

    def to_diagnostic(self, length: Optional[int] = None) -> Diagnostic:
        len_val = length if length is not None else self.length
        label = DiagnosticLabel(offset=self.offset, length=len_val) if self.offset is not None else None
        return Diagnostic(
            severity=Severity.ERROR,
            message=self.message,
            primary_label=label,
        )


DIVIDE_BY_ZERO_EXC = QExceptionVal("DivideByZero")
ARRAY_OP_ERROR_EXC = QExceptionVal("arrayOp.error")
DYNAMIC_ERROR_EXC = QExceptionVal("dynamic.error")
LIST_ERROR_EXC = QExceptionVal("list.error")


# ============================================================================
# 2. Scoped Runtime Environment
# ============================================================================

class RuntimeEnvironment:
    """Lexically scoped symbol table mapping variable names to QValue instances."""

    def __init__(self, parent: Optional[RuntimeEnvironment] = None):
        self.parent = parent
        self.bindings: dict[str, QValue] = {}
        if parent is not None:
            self.evaluated_modules: dict[str, Any] = parent.evaluated_modules
            self.include_paths: list[Path] = parent.include_paths
            self.current_dir: Optional[Path] = parent.current_dir
            self.loaded_modules_ast: dict[str, Any] = parent.loaded_modules_ast
        else:
            self.evaluated_modules: dict[str, Any] = {}
            self.include_paths: list[Path] = []
            self.current_dir: Optional[Path] = None
            self.loaded_modules_ast: dict[str, Any] = {}

    def push_scope(self) -> RuntimeEnvironment:
        """Pushes a new child scope inheriting from this environment."""
        return RuntimeEnvironment(parent=self)

    def pop_scope(self) -> RuntimeEnvironment:
        """Pops the current child scope, returning its parent."""
        if self.parent is None:
            raise QuestRuntimeError("Cannot pop root runtime scope")
        return self.parent

    def define(self, name: str, value: QValue) -> None:
        """Binds a variable in the current innermost scope frame."""
        self.bindings[name] = value

    def lookup(self, name: str, offset: Optional[int] = None) -> QValue:
        """Resolves a variable recursively outward from innermost to outermost scope."""
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.lookup(name, offset)
        raise QuestRuntimeError(f"Undefined runtime symbol '{name}'", offset=offset)

    def assign(self, name: str, new_value: QValue, offset: Optional[int] = None) -> None:
        """Mutates an existing binding or updates its mutable QRef cell in place."""
        if name in self.bindings:
            curr = self.bindings[name]
            if isinstance(curr, QRef):
                curr.assign(new_value)
            else:
                self.bindings[name] = new_value
            return
        if self.parent is not None:
            self.parent.assign(name, new_value, offset)
            return
        raise QuestRuntimeError(f"Cannot assign to undefined symbol '{name}'", offset=offset)

    def snapshot(self) -> dict[str, Any]:
        """Captures a shallow copy of the current bindings and parent pointer."""
        return {
            "bindings": dict(self.bindings),
            "parent": self.parent,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        """Restores bindings and parent from a previous snapshot."""
        self.bindings = dict(snap["bindings"])
        self.parent = snap["parent"]

    @classmethod
    def create_root_env(cls) -> RuntimeEnvironment:
        """Creates the global root environment with standard constants pre-populated."""
        env = cls()
        env.define("true", TRUE_VALUE)
        env.define("false", FALSE_VALUE)
        env.define("ok", OK_VALUE)
        env.define("DivideByZero", DIVIDE_BY_ZERO_EXC)
        env.define("arrayOp.error", ARRAY_OP_ERROR_EXC)
        env.define("dynamic.error", DYNAMIC_ERROR_EXC)
        env.define("list.error", LIST_ERROR_EXC)

        from quest.builtins import BuiltinModuleRegistry
        BuiltinModuleRegistry._ensure_initialized()
        for mod_name, mod_val in BuiltinModuleRegistry._modules.items():
            env.define(mod_name, mod_val)

        # Built-in operators as callable functions (Cardelli §4.2)
        for op in ("+", "-", "*", "/", "mod", "%"):
            env.define(
                op,
                QBuiltinFun(
                    op,
                    lambda a, b, op=op: QInt(
                        _eval_int_arithmetic(op, a.value, b.value, offset=0)
                    ),
                ),
            )
        for op in ("<", "<=", ">", ">="):
            env.define(
                op,
                QBuiltinFun(
                    op,
                    lambda a, b, op=op: (
                        TRUE_VALUE
                        if _eval_int_relational(op, a.value, b.value, offset=0)
                        else FALSE_VALUE
                    ),
                ),
            )
        for op in ("++", "--", "**", "//", "^^"):
            env.define(
                op,
                QBuiltinFun(
                    op,
                    lambda a, b, op=op: QReal(
                        _eval_real_arithmetic(op, a.value, b.value, offset=0)
                    ),
                ),
            )
        for op in ("<<", "<<=", ">>", ">>="):
            env.define(
                op,
                QBuiltinFun(
                    op,
                    lambda a, b, op=op: (
                        TRUE_VALUE
                        if _eval_real_relational(op, a.value, b.value, offset=0)
                        else FALSE_VALUE
                    ),
                ),
            )
        env.define("<>", QBuiltinFun("<>", lambda a, b: QString(a.value + b.value)))
        env.define(
            "/\\",
            QBuiltinFun("/\\", lambda a, b: TRUE_VALUE if (a.value and b.value) else FALSE_VALUE),
        )
        env.define(
            "\\/",
            QBuiltinFun("\\/", lambda a, b: TRUE_VALUE if (a.value or b.value) else FALSE_VALUE),
        )

        # Monadic Operators: not, extent, ordinal (Cardelli §4.2, §4.3, §4.5)
        env.define(
            "not",
            QBuiltinFun("not", lambda b: FALSE_VALUE if b.value else TRUE_VALUE),
        )
        env.define(
            "extent",
            QBuiltinFun("extent", lambda a: QInt(len(a.elements))),
        )
        env.define(
            "ordinal",
            QBuiltinFun(
                "ordinal",
                lambda o: (
                    QInt(o.ordinal)
                    if isinstance(o, QOption)
                    else (_ for _ in ()).throw(
                        QuestRuntimeError(f"ordinal expects Option, got {o.type_name}")
                    )
                ),
            ),
        )

        return env


def _infer_qtype(val: QValue) -> QType:
    """Infers a default QType for dynamic values if not explicitly provided."""
    match val:
        case QInt():
            return INT_TYPE
        case QReal():
            return REAL_TYPE
        case QBool():
            return BOOL_TYPE
        case QChar():
            return CHAR_TYPE
        case QString():
            return STRING_TYPE
        case QOk():
            return OK_TYPE
        case QExceptionVal():
            return EXCEPTION_TYPE
        case QDynamicVal():
            return DYNAMIC_TYPE
        case _:
            return OK_TYPE


# ============================================================================
# 3. Arithmetic & Infix Helper Functions
# ============================================================================

def _eval_int_arithmetic(op: str, a: int, b: int, offset: Optional[int] = None) -> int:
    """Evaluates integer arithmetic with C-style truncation and DivideByZero check."""
    match op:
        case "+":
            return a + b
        case "-":
            return a - b
        case "*":
            return a * b
        case "/":
            if b == 0:
                raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
            # C-style truncation toward zero
            return int(a / b)
        case "mod" | "%":
            if b == 0:
                raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
            # C-style modulo: a - trunc(a / b) * b
            return a - int(a / b) * b
        case _:
            raise QuestRuntimeError(f"Unknown integer arithmetic operator '{op}'", offset=offset)


def _eval_int_relational(op: str, a: int, b: int, offset: Optional[int] = None) -> bool:
    """Evaluates integer relational comparisons (<, <=, >, >=)."""
    match op:
        case "<":
            return a < b
        case "<=":
            return a <= b
        case ">":
            return a > b
        case ">=":
            return a >= b
        case _:
            raise QuestRuntimeError(f"Unknown integer relational operator '{op}'", offset=offset)


def _eval_real_arithmetic(op: str, a: float, b: float, offset: Optional[int] = None) -> float:
    """Evaluates real floating-point arithmetic (++, --, **, //, ^^)."""
    match op:
        case "++":
            return a + b
        case "--":
            return a - b
        case "**":
            return a * b
        case "//":
            if b == 0.0:
                raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
            return a / b
        case "^^":
            if a == 0.0 and b < 0.0:
                raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
            try:
                return math.pow(a, b)
            except (ValueError, OverflowError) as e:
                raise QuestRuntimeError(f"Real exponentiation error: {e}", offset=offset)
        case _:
            raise QuestRuntimeError(f"Unknown real arithmetic operator '{op}'", offset=offset)


def _eval_real_relational(op: str, a: float, b: float, offset: Optional[int] = None) -> bool:
    """Evaluates real relational comparisons (<<, <<=, >>, >>=)."""
    match op:
        case "<<":
            return a < b
        case "<<=":
            return a <= b
        case ">>":
            return a > b
        case ">>=":
            return a >= b
        case _:
            raise QuestRuntimeError(f"Unknown real relational operator '{op}'", offset=offset)


# ============================================================================
# 4. Expression Evaluator
# ============================================================================

def eval_expr(expr: TypedExpr, env: RuntimeEnvironment) -> QValue:
    """Evaluates a typed expression within the given runtime environment."""
    match expr:
        # 1. Literals
        case TypedInt(value=val):
            return QInt(val)
        case TypedReal(value=val):
            return QReal(val)
        case TypedBool(value=val):
            return TRUE_VALUE if val else FALSE_VALUE
        case TypedChar(value=val):
            return QChar(val)
        case TypedString(value=val):
            return QString(val)
        case TypedOk():
            return OK_VALUE
        case TypedExternal(symbol=symbol):
            from quest.builtins import BuiltinModuleRegistry
            return BuiltinModuleRegistry.resolve_external_symbol(symbol)

        # 2. Variables & Mutable References
        case TypedVar(name=name, offset=offset):
            return env.lookup(name, offset=offset)

        case TypedVarCell(value=val):
            return QRef(eval_expr(val, env))

        case TypedDerefCell(target=tgt):
            target_val = eval_expr(tgt, env)
            return target_val.deref() if isinstance(target_val, QRef) else target_val

        case TypedSelectRef(target=tgt, field=fld, offset=offset):
            rec_val = eval_expr(tgt, env)
            while isinstance(rec_val, QRef):
                rec_val = rec_val.deref()
            if not isinstance(rec_val, QRecord):
                raise QuestRuntimeError("Field selection target must be Record", offset=offset)
            field_cell = rec_val.get(fld)
            if isinstance(field_cell, QRef):
                return field_cell
            raise QuestRuntimeError(f"Field '{fld}' is not mutable", offset=offset)

        case TypedIndexRef(target=tgt, index=idx, offset=offset):
            arr_val = eval_expr(tgt, env)
            while isinstance(arr_val, QRef):
                arr_val = arr_val.deref()
            if not isinstance(arr_val, QArray):
                raise QuestRuntimeError(f"Index target must be Array, got {arr_val.type_name}", offset=offset)
            idx_val = eval_expr(idx, env)
            if not isinstance(idx_val, QInt):
                raise QuestRuntimeError(f"Array index must be Int, got {idx_val.type_name}", offset=offset)
            i = idx_val.value
            if i < 0 or i >= arr_val.size():
                raise QuestException(ARRAY_OP_ERROR_EXC, offset=offset)
            return QArrayElementRef(arr_val, i)

        case TypedTupleSelectRef(target=tgt, index=idx, field=fld, offset=offset):
            tup_val = eval_expr(tgt, env)
            while isinstance(tup_val, QRef):
                tup_val = tup_val.deref()
            if not isinstance(tup_val, QTuple):
                raise QuestRuntimeError(f"Tuple select target must be Tuple, got {tup_val.type_name}", offset=offset)
            val_idx = idx
            if val_idx < 0 and fld is not None:
                val_idx = tup_val._name_to_index.get(fld, -1)
            if val_idx < 0 or val_idx >= len(tup_val.elements):
                raise QuestRuntimeError("Tuple component out of bounds", offset=offset)
            elem = tup_val.get_by_index(val_idx)
            if isinstance(elem, QRef):
                return elem
            return QTupleElementRef(tup_val, val_idx)

        case TypedAssign(target=tgt, value=val, offset=offset):
            rhs_val = eval_expr(val, env)
            match tgt:
                case TypedVar(name=name):
                    cell = env.lookup(name, offset=offset)
                    if isinstance(cell, QRef):
                        cell.assign(rhs_val)
                    else:
                        env.assign(name, rhs_val, offset=offset)
                    return OK_VALUE
                case TypedSelect(target=rec_expr, field=field):
                    rec_val = eval_expr(rec_expr, env)
                    while isinstance(rec_val, QRef):
                        rec_val = rec_val.deref()
                    if not isinstance(rec_val, QRecord):
                        raise QuestRuntimeError("Field assignment target must be Record", offset=offset)
                    field_cell = rec_val.get(field)
                    if isinstance(field_cell, QRef):
                        field_cell.assign(rhs_val)
                    else:
                        rec_val.fields[field] = rhs_val
                    return OK_VALUE
                case _:
                    raise QuestRuntimeError("Unsupported assignment target in interpreter", offset=offset)

        # 3. Functions & Application
        case TypedFun(params=params, body=body):
            return QClosure(
                params=tuple(p.name for p in params),
                body=body,
                env=env,
            )

        case TypedTypeApp(func=func, type_args=type_args):
            callee = eval_expr(func, env)
            if isinstance(callee, QBuiltinFun):
                if callee.name == "list.nil":
                    return QList(())
                if callee.name == "dynamic.new" and type_args:
                    target_type = type_args[0]
                    return QBuiltinFun(
                        "dynamic.new",
                        fn=lambda val: QDynamicVal(val, target_type),
                    )
                if callee.name == "dynamic.be" and type_args:
                    target_type = type_args[0]

                    def _be_fn(d: QValue) -> QValue:
                        if not isinstance(d, QDynamicVal):
                            raise QuestException(DYNAMIC_ERROR_EXC)
                        if not is_subtype(d.type_val, target_type):
                            raise QuestException(DYNAMIC_ERROR_EXC)
                        return d.value

                    return QBuiltinFun("dynamic.be", fn=_be_fn)
            return callee

        case TypedApp(func=func, args=args, offset=offset):
            callee_val = eval_expr(func, env)
            arg_vals = [eval_expr(arg, env) for arg in args]

            match callee_val:
                case QBuiltinFun(fn=fn):
                    return fn(*arg_vals)
                case QClosure(params=callee_params, body=body, env=closure_env):
                    call_env = closure_env.push_scope()
                    for param_name, arg_val in zip(callee_params, arg_vals):
                        call_env.define(param_name, arg_val)
                    return eval_expr(body, call_env)
                case _:
                    raise QuestRuntimeError(
                        f"Cannot call non-function of type {callee_val.type_name}",
                        offset=offset,
                    )

        # 4. Infix Operations
        case TypedInfix(left=left, op=op, right=right, offset=offset):
            left_val = eval_expr(left, env)
            right_val = eval_expr(right, env)

            # Integer Arithmetic
            if op in ("+", "-", "*", "/", "mod", "%"):
                if isinstance(left_val, QInt) and isinstance(right_val, QInt):
                    return QInt(_eval_int_arithmetic(op, left_val.value, right_val.value, offset=offset))
                raise QuestRuntimeError(
                    f"Operator '{op}' requires Int operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # Integer Relational
            if op in ("<", "<=", ">", ">="):
                if isinstance(left_val, QInt) and isinstance(right_val, QInt):
                    res = _eval_int_relational(op, left_val.value, right_val.value, offset=offset)
                    return TRUE_VALUE if res else FALSE_VALUE
                raise QuestRuntimeError(
                    f"Operator '{op}' requires Int operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # Real Arithmetic
            if op in ("++", "--", "**", "//", "^^"):
                if isinstance(left_val, QReal) and isinstance(right_val, QReal):
                    return QReal(_eval_real_arithmetic(op, left_val.value, right_val.value, offset=offset))
                raise QuestRuntimeError(
                    f"Operator '{op}' requires Real operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # Real Relational
            if op in ("<<", "<<=", ">>", ">>="):
                if isinstance(left_val, QReal) and isinstance(right_val, QReal):
                    res = _eval_real_relational(op, left_val.value, right_val.value, offset=offset)
                    return TRUE_VALUE if res else FALSE_VALUE
                raise QuestRuntimeError(
                    f"Operator '{op}' requires Real operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # String Concatenation
            if op == "<>":
                if isinstance(left_val, QString) and isinstance(right_val, QString):
                    return QString(left_val.value + right_val.value)
                raise QuestRuntimeError(
                    f"Operator '<>' requires String operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # Boolean Eager Operations
            if op == "/\\":
                if isinstance(left_val, QBool) and isinstance(right_val, QBool):
                    return TRUE_VALUE if (left_val.value and right_val.value) else FALSE_VALUE
                raise QuestRuntimeError(
                    f"Operator '/\\' requires Bool operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )
            if op == "\\/":
                if isinstance(left_val, QBool) and isinstance(right_val, QBool):
                    return TRUE_VALUE if (left_val.value or right_val.value) else FALSE_VALUE
                raise QuestRuntimeError(
                    f"Operator '\\/' requires Bool operands, got {left_val.type_name} and {right_val.type_name}",
                    offset=offset,
                )

            # Equality & Identity
            if op in ("is", "=="):
                res = qvalue_is(left_val, right_val)
                return TRUE_VALUE if res else FALSE_VALUE
            if op == "isnot":
                res = not qvalue_is(left_val, right_val)
                return TRUE_VALUE if res else FALSE_VALUE

            raise QuestRuntimeError(f"Unsupported infix operator '{op}'", offset=offset)

        # 5. Conditionals
        case TypedIf(cond=cond, then_branch=then_b, else_branch=else_b, offset=offset):
            cond_val = eval_expr(cond, env)
            match cond_val:
                case QBool(value=True):
                    return eval_expr(then_b, env)
                case QBool(value=False):
                    return eval_expr(else_b, env)
                case _:
                    raise QuestRuntimeError("Conditional expression must evaluate to Bool", offset=offset)

        # 6. Scoped Blocks
        case TypedBlock(bindings=bindings, result=result):
            block_env = env.push_scope()
            try:
                for b in bindings:
                    eval_binding(b, block_env)
                return eval_expr(result, block_env)
            finally:
                env = block_env.pop_scope()

        # 7. Loops & Control Flow
        case TypedLoop(body=body):
            while True:
                try:
                    eval_expr(body, env)
                except _LoopExit:
                    break
            return OK_VALUE

        case TypedWhile(cond=cond, body=body, offset=offset):
            while True:
                cond_val = eval_expr(cond, env)
                match cond_val:
                    case QBool(value=True):
                        try:
                            eval_expr(body, env)
                        except _LoopExit:
                            break
                    case QBool(value=False):
                        break
                    case _:
                        raise QuestRuntimeError("While loop condition must evaluate to Bool", offset=offset)
            return OK_VALUE

        case TypedFor(start=start, stop=stop, body=body, is_downto=is_downto, var_name=var_name, offset=offset):
            start_val = eval_expr(start, env)
            stop_val = eval_expr(stop, env)
            match (start_val, stop_val):
                case (QInt(value=start_i), QInt(value=stop_i)):
                    loop_env = env.push_scope()
                    try:
                        step = -1 if is_downto else 1
                        cur = start_i
                        while (cur <= stop_i) if not is_downto else (cur >= stop_i):
                            loop_env.define(var_name, QInt(cur))
                            try:
                                eval_expr(body, loop_env)
                            except _LoopExit:
                                break
                            cur += step
                    finally:
                        env = loop_env.pop_scope()
                    return OK_VALUE
                case _:
                    raise QuestRuntimeError("For loop bounds must evaluate to Int", offset=offset)

        case TypedExit():
            raise _LoopExit()

        # 8. Aggregates: Records & Tuples
        case TypedRecord(fields=fields):
            rec_fields: dict[str, QValue] = {}
            for f in fields:
                val = eval_expr(f.value, env)
                rec_fields[f.name] = QRef(val) if f.is_var else val
            return QRecord(rec_fields)

        case TypedTypeWitness(name=name, witness_type=witness_type, bound=bound):
            return QTypeValue(type_val=witness_type, bound=bound, name=name)

        case TypedTuple(elements=elements, type_val=type_val):
            labels: Optional[tuple[Optional[str], ...]] = None
            if isinstance(type_val, QTupleType):
                labels = tuple(f.name for f in type_val.fields)
            tup_env = env.push_scope()
            elems: list[QValue] = []
            try:
                for idx, e in enumerate(elements):
                    val = eval_expr(e, tup_env)
                    elems.append(val)
                    lbl = labels[idx] if labels and idx < len(labels) else None
                    if lbl is not None:
                        tup_env.define(lbl, val)
            finally:
                tup_env.pop_scope()
            return QTuple(elements=tuple(elems), labels=labels)

        case TypedSelect(target=target, field=field, offset=offset):
            target_val = eval_expr(target, env)
            while isinstance(target_val, QRef):
                target_val = target_val.deref()
            match target_val:
                case QRecord():
                    field_val = target_val.get(field)
                    return field_val.deref() if isinstance(field_val, QRef) else field_val
                case QTuple():
                    return target_val.get_by_name(field)
                case _:
                    raise QuestRuntimeError(
                        f"Cannot select field '{field}' from {target_val.type_name}",
                        offset=offset,
                    )

        # 9. Arrays: Creation, Repetition, Indexing, and Assignment
        case TypedArray(elements=elements):
            return QArray(elements=[eval_expr(e, env) for e in elements])

        case TypedArrayRep(count=count, init_val=init_val, offset=offset):
            count_val = eval_expr(count, env)
            match count_val:
                case QInt(value=c) if c >= 0:
                    init_v = eval_expr(init_val, env)
                    return QArray(elements=[init_v for _ in range(c)])
                case QInt():
                    raise QuestException(ARRAY_OP_ERROR_EXC, offset=offset)
                case _:
                    raise QuestRuntimeError("Array count must evaluate to Int", offset=offset)

        case TypedIndex(target=target, index=index, offset=offset):
            target_val = eval_expr(target, env)
            idx_val = eval_expr(index, env)
            match (target_val, idx_val):
                case (QArray(), QInt(value=idx)):
                    if idx < 0 or idx >= target_val.size():
                        raise QuestException(ARRAY_OP_ERROR_EXC, offset=offset)
                    return target_val.get(idx)
                case (QArray(), _):
                    raise QuestRuntimeError(f"Array index must be Int, got {idx_val.type_name}", offset=offset)
                case _:
                    raise QuestRuntimeError(f"Index target must be Array, got {target_val.type_name}", offset=offset)

        case TypedIndexAssign(target=target, index=index, value=value, offset=offset):
            target_val = eval_expr(target, env)
            idx_val = eval_expr(index, env)
            rhs_val = eval_expr(value, env)
            match (target_val, idx_val):
                case (QArray(), QInt(value=idx)):
                    if idx < 0 or idx >= target_val.size():
                        raise QuestException(ARRAY_OP_ERROR_EXC, offset=offset)
                    target_val.set(idx, rhs_val)
                    return OK_VALUE
                case (QArray(), _):
                    raise QuestRuntimeError(f"Array index must be Int, got {idx_val.type_name}", offset=offset)
                case _:
                    raise QuestRuntimeError(f"Index target must be Array, got {target_val.type_name}", offset=offset)

        # 10. Variants, Options, and Pattern Matching
        case TypedVariant(tag=tag, payload=payload):
            p_val = eval_expr(payload, env) if payload is not None else None
            return QVariant(tag=tag, payload=p_val)

        case TypedOption(
            tag=tag, payload=payload, ordinal=ordinal, ordinal_expr=ordinal_expr, type_val=type_val, offset=offset
        ):
            p_val = eval_expr(payload, env) if payload is not None else None
            if ordinal_expr is not None:
                ord_val = eval_expr(ordinal_expr, env)
                if not isinstance(ord_val, QInt):
                    raise QuestRuntimeError(
                        f"Option ordinal must evaluate to Int, got {ord_val.type_name}",
                        offset=offset,
                    )
                n = ord_val.value
                opt_type = type_val.evaluate_lazily(env)
                if not isinstance(opt_type, QOptionType):
                    raise QuestRuntimeError(f"Expected Option type, got {opt_type}", offset=offset)
                if n < 0 or n >= len(opt_type.options):
                    raise QuestRuntimeError(
                        f"Option ordinal {n} out of bounds (0 <= ordinal < {len(opt_type.options)})",
                        offset=offset,
                    )
                branch_tag = opt_type.options[n].name
                return QOption(tag=branch_tag, payload=p_val, ordinal=n)
            return QOption(tag=tag, payload=p_val, ordinal=ordinal)

        case TypedVariantCheck(target=target, tag=tag, offset=offset):
            target_val = eval_expr(target, env)
            if not isinstance(target_val, (QVariant, QOption)):
                raise QuestRuntimeError(
                    f"Variant query target must be Variant or Option, got {target_val.type_name}",
                    offset=offset,
                )
            return QBool(target_val.tag == tag)

        case TypedVariantAssert(target=target, tag=tag, offset=offset):
            target_val = eval_expr(target, env)
            if not isinstance(target_val, (QVariant, QOption)):
                raise QuestRuntimeError(
                    f"Variant assert target must be Variant or Option, got {target_val.type_name}",
                    offset=offset,
                )
            if target_val.tag != tag:
                raise QuestRuntimeError(
                    f"Variant tag mismatch in '!': expected '{tag}', got '{target_val.tag}'",
                    offset=offset,
                )
            if isinstance(target_val, QOption):
                ord_val = QInt(target_val.ordinal)
                if target_val.payload is None:
                    return QTuple(elements=(ord_val,), labels=(None,))
                if isinstance(target_val.payload, QTuple):
                    return QTuple(
                        elements=(ord_val, *target_val.payload.elements),
                        labels=(None, *target_val.payload.labels),
                    )
                return QTuple(elements=(ord_val, target_val.payload), labels=(None, None))
            if target_val.payload is not None:
                return target_val.payload
            return QOk()

        case TypedCase(target=target, branches=branches, else_branch=else_branch, offset=offset):
            target_val = eval_expr(target, env)
            if not isinstance(target_val, (QVariant, QOption)):
                raise QuestRuntimeError(
                    f"Case target must be Variant or Option, got {target_val.type_name}",
                    offset=offset,
                )
            for branch in branches:
                if target_val.tag in branch.tags:
                    if branch.binder is not None:
                        child_env = env.push_scope()
                        child_env.define(
                            branch.binder.name,
                            target_val.payload if target_val.payload is not None else OK_VALUE,
                        )
                        try:
                            return eval_expr(branch.body, child_env)
                        finally:
                            env = child_env.pop_scope()
                    else:
                        return eval_expr(branch.body, env)
            if else_branch is not None:
                return eval_expr(else_branch, env)
            raise QuestRuntimeError(f"Unhandled case tag '{target_val.tag}'", offset=offset)

        # 11. Exceptions
        case TypedException(name=name):
            exc_val = QExceptionVal(name=name)
            if name:
                env.define(name, exc_val)
            return exc_val

        case TypedRaise(exc=exc, payload=payload, offset=offset):
            tag_val = eval_expr(exc, env)
            if not isinstance(tag_val, QExceptionVal):
                raise QuestRuntimeError(
                    f"Target of raise must be Exception, got {tag_val.type_name}",
                    offset=offset,
                )
            payload_val = eval_expr(payload, env) if payload is not None else None
            payload_type = payload.type_val if payload is not None else None
            raise QuestException(
                exc_val=tag_val,
                payload=payload_val,
                payload_type=payload_type,
                offset=offset,
            )

        case TypedTry(body=body, branches=branches, else_branch=else_branch, offset=offset):
            try:
                return eval_expr(body, env)
            except QuestException as raised_exc:
                for branch in branches:
                    pattern_val = eval_expr(branch.exc_pattern, env)
                    if (
                        raised_exc.exc_val is pattern_val
                        or raised_exc.exc_val.name == getattr(pattern_val, "name", None)
                    ):
                        if branch.binder is not None:
                            child_env = env.push_scope()
                            actual_payload = (
                                raised_exc.payload
                                if raised_exc.payload is not None
                                else OK_VALUE
                            )
                            child_env.define(branch.binder.name, actual_payload)
                            try:
                                return eval_expr(branch.body, child_env)
                            finally:
                                env = child_env.pop_scope()
                        else:
                            return eval_expr(branch.body, env)
                if else_branch is not None:
                    return eval_expr(else_branch, env)
                raise

        # 12. Dynamic Types & Type Inspection
        case TypedInspect(target=target, branches=branches, else_branch=else_branch, offset=offset):
            target_dyn = eval_expr(target, env)
            if not isinstance(target_dyn, QDynamicVal):
                raise QuestRuntimeError(
                    f"Inspect target must be Dynamic, got {target_dyn.type_name}",
                    offset=offset,
                )
            for branch in branches:
                if is_subtype(target_dyn.type_val, branch.match_type):
                    if branch.binders:
                        child_env = env.push_scope()
                        for b_sym in branch.binders:
                            child_env.define(b_sym.name, target_dyn.value)
                        try:
                            return eval_expr(branch.body, child_env)
                        finally:
                            env = child_env.pop_scope()
                    else:
                        return eval_expr(branch.body, env)
            if else_branch is not None:
                return eval_expr(else_branch, env)
            raise QuestException(DYNAMIC_ERROR_EXC, offset=offset)

        case _:
            raise QuestRuntimeError(
                f"Unhandled expression node: {expr.__class__.__name__}",
                offset=getattr(expr, "offset", 0),
            )


# ============================================================================
# 5. Binding & Program Evaluator
# ============================================================================

def eval_binding(binding: TypedBinding, env: RuntimeEnvironment) -> QValue:
    """Evaluates a declaration or binding inside a block or top-level program."""
    match binding:
        case TypedLetValue(name=name, value=value, is_rec=is_rec, symbol=symbol):
            if is_rec and isinstance(value, TypedFun):
                closure = QClosure(
                    params=tuple(p.name for p in value.params),
                    body=value.body,
                    env=env,
                    name=name,
                )
                env.define(name, closure)
                return closure
            val = eval_expr(value, env)
            if symbol.is_var:
                env.define(name, QRef(val))
            else:
                env.define(name, val)
            return val

        case TypedLetType() | TypedDefKind() | TypedInterface():
            # Types, kinds, and interface declarations are erased at runtime
            return OK_VALUE

        case TypedModule(name=mod_name, bindings=mod_bindings, scope=mod_scope):
            if mod_name in env.evaluated_modules:
                rec = env.evaluated_modules[mod_name]
                env.define(mod_name, rec)
                return rec
            mod_env = env.push_scope()
            for b in mod_bindings:
                eval_binding(b, mod_env)
            exported_fields: dict[str, QValue] = {}
            for val_name in mod_scope.values:
                exported_fields[val_name] = mod_env.lookup(val_name)
            rec = QRecord(exported_fields)
            env.evaluated_modules[mod_name] = rec
            env.define(mod_name, rec)
            return rec

        case TypedImport(items=items):
            from quest.builtins import BuiltinModuleRegistry

            for item in items:
                for name in item.names:
                    if name in env.evaluated_modules:
                        mod_val = env.evaluated_modules[name]
                    else:
                        mod_val = BuiltinModuleRegistry.get_runtime_module(name)
                        if mod_val is None:
                            try:
                                mod_val = env.lookup(name)
                            except QuestRuntimeError:
                                mod_val = None
                        if mod_val is None:
                            if name in env.loaded_modules_ast:
                                typed_mod = env.loaded_modules_ast[name]
                                mod_env = env.push_scope()
                                for b in typed_mod.bindings:
                                    eval_binding(b, mod_env)
                                exported_fields = {}
                                for val_name in typed_mod.scope.values:
                                    exported_fields[val_name] = mod_env.lookup(val_name)
                                mod_val = QRecord(exported_fields)
                                env.evaluated_modules[name] = mod_val
                            else:
                                from quest.module_loader import load_module_for_interpreter
                                mod_val = load_module_for_interpreter(name, item.interface_name, env)
                                if mod_val is not None:
                                    env.evaluated_modules[name] = mod_val
                    if mod_val is not None:
                        env.define(name, mod_val)
            return OK_VALUE

        case TypedExprStmt(expr=inner_expr):
            return eval_expr(inner_expr, env)

        case _:
            raise QuestRuntimeError(f"Unhandled binding node: {binding.__class__.__name__}")


def eval_program_phrases(
    program: TypedProgram,
    env: Optional[RuntimeEnvironment] = None,
) -> list[tuple[TypedBinding | TypedExpr, QValue]]:
    """Evaluates an entire typed program sequentially, returning (phrase, value) pairs."""
    if env is None:
        env = RuntimeEnvironment.create_root_env()

    results: list[tuple[TypedBinding | TypedExpr, QValue]] = []
    for phrase in program.phrases:
        match phrase:
            case TypedBinding():
                val = eval_binding(phrase, env)
                results.append((phrase, val))
            case TypedExpr():
                val = eval_expr(phrase, env)
                results.append((phrase, val))
            case _:
                raise QuestRuntimeError(f"Unknown top-level phrase: {phrase.__class__.__name__}")

    return results


def eval_program(program: TypedProgram, env: Optional[RuntimeEnvironment] = None) -> QValue:
    """Evaluates an entire typed program sequentially, returning the final phrase value."""
    results = eval_program_phrases(program, env)
    return results[-1][1] if results else OK_VALUE


def format_value_with_type(val: QValue, typ: Optional[QType] = None) -> str:
    """Formats a runtime value with respect to its static type (Cardelli §5.3)."""
    if typ is None:
        return qvalue_to_str(val)

    if isinstance(typ, QPathType):
        return "<hidden>"

    if isinstance(val, QTypeValue):
        if val.bound:
            return f"<Hidden>::{val.bound}"
        return "<Hidden>::TYPE"

    if isinstance(val, QTuple) and isinstance(typ, QTupleType):
        parts: list[str] = []
        elem_idx = 0
        for comp in typ.components:
            if isinstance(comp, QTupleTypeFormal):
                parts.append(f"<Hidden>::{comp.bound}")
                elem_idx += 1
            elif isinstance(comp, QTupleTypeBinding):
                parts.append(f"Let {comp.name} = {comp.type_val}")
                elem_idx += 1
            elif isinstance(comp, QTupleField):
                if elem_idx < len(val.elements):
                    elem = val.elements[elem_idx]
                    if isinstance(comp.type_val, (QPathType, QTypeVar)):
                        elem_str = "<hidden>"
                    else:
                        elem_str = format_value_with_type(elem, comp.type_val)
                    if comp.name:
                        parts.append(f"{comp.name}={elem_str}")
                    else:
                        parts.append(elem_str)
                    elem_idx += 1
        return f"tuple {' '.join(parts)} end" if parts else "tuple end"

    return qvalue_to_str(val)


def format_interactive_result(
    phrase: Optional[TypedNode],
    val: Optional[QValue],
) -> str:
    """Formats the result of evaluating a top-level phrase in Cardelli interactive style."""
    if phrase is None or val is None:
        return ""

    match phrase:
        case TypedLetValue(name=name, symbol=symbol):
            var_str = "var " if symbol.is_var else ""
            type_str = str(symbol.type_val)
            val_str = format_value_with_type(val, symbol.type_val)
            return f"let {var_str}{name}:{type_str} = {val_str}"

        case TypedLetType(name=name, symbol=symbol):
            kind_str = str(symbol.kind)
            if symbol.definition is not None:
                return f"Let {name}::{kind_str} = {symbol.definition}"
            return f"Let {name}::{kind_str}"

        case TypedDefKind(name=name, symbol=symbol):
            kind_str = str(symbol.kind)
            return f"DEF {name} = {kind_str}"

        case TypedImport() | TypedInterface() | TypedModule():
            return ""

        case TypedExprStmt(expr=TypedException(name=name)):
            return f"exception {name}"

        case TypedExprStmt(expr=inner_expr):
            if isinstance(val, QOk):
                return ""
            val_str = format_value_with_type(val, inner_expr.type_val)
            return f"{val_str} : {inner_expr.type_val}"

        case TypedException(name=name):
            return f"exception {name}"

        case TypedExpr():
            if isinstance(val, QOk):
                return ""
            val_str = format_value_with_type(val, phrase.type_val)
            return f"{val_str} : {phrase.type_val}"

        case _:
            return ""
