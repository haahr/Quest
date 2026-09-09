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
    QOk,
    QOption,
    QReal,
    QRecord,
    QRef,
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
    TypedFor,
    TypedFun,
    TypedIf,
    TypedIndex,
    TypedIndexAssign,
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


# ============================================================================
# 2. Scoped Runtime Environment
# ============================================================================

class RuntimeEnvironment:
    """Lexically scoped symbol table mapping variable names to QValue instances."""

    def __init__(self, parent: Optional[RuntimeEnvironment] = None):
        self.parent = parent
        self.bindings: dict[str, QValue] = {}

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

        def make_dynamic(*args: QValue) -> QDynamicVal:
            if len(args) == 1:
                return QDynamicVal(value=args[0], type_val=_infer_qtype(args[0]))
            if len(args) == 2 and isinstance(args[1], QType):
                return QDynamicVal(value=args[0], type_val=args[1])
            raise QuestRuntimeError("dynamic expects 1 argument")

        env.define("dynamic", QBuiltinFun("dynamic", fn=make_dynamic))
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


def _eval_real_arithmetic(op: str, a: float, b: float, offset: Optional[int] = None) -> float:
    """Evaluates real floating-point arithmetic."""
    match op:
        case "+":
            return a + b
        case "-":
            return a - b
        case "*":
            return a * b
        case "/":
            if b == 0.0:
                raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
            return a / b
        case _:
            raise QuestRuntimeError(f"Unknown real arithmetic operator '{op}'", offset=offset)


def _eval_relational(op: str, left: QValue, right: QValue, offset: Optional[int] = None) -> bool:
    """Evaluates relational comparisons (<, <=, >, >=) for Int, Real, Char, String."""
    match (left, right):
        case (QInt(value=l_val), QInt(value=r_val)):
            pass
        case (QReal(value=l_val), QReal(value=r_val)):
            pass
        case (QChar(value=l_val), QChar(value=r_val)):
            pass
        case (QString(value=l_val), QString(value=r_val)):
            pass
        case _:
            raise QuestRuntimeError(
                f"Relational operator '{op}' cannot compare types {left.type_name} and {right.type_name}",
                offset=offset,
            )

    match op:
        case "<":
            return l_val < r_val
        case "<=":
            return l_val <= r_val
        case ">":
            return l_val > r_val
        case ">=":
            return l_val >= r_val
        case _:
            raise QuestRuntimeError(f"Unknown relational operator '{op}'", offset=offset)


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

        # 2. Variables & Mutable References
        case TypedVar(name=name, offset=offset):
            return env.lookup(name, offset=offset)

        case TypedVarCell(value=val):
            return QRef(eval_expr(val, env))

        case TypedDerefCell(target=tgt):
            target_val = eval_expr(tgt, env)
            return target_val.deref() if isinstance(target_val, QRef) else target_val

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
            if isinstance(callee, QBuiltinFun) and callee.name == "dynamic" and type_args:
                target_type = type_args[0]
                return QBuiltinFun("dynamic", fn=lambda *args: QDynamicVal(args[0], target_type))
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

            # Arithmetic
            if op in ("+", "-", "*", "/", "mod", "%"):
                match (left_val, right_val):
                    case (QInt(value=l), QInt(value=r)):
                        return QInt(_eval_int_arithmetic(op, l, r, offset=offset))
                    case (QReal(value=l), QReal(value=r)):
                        return QReal(_eval_real_arithmetic(op, l, r, offset=offset))
                    case _:
                        raise QuestRuntimeError(
                            f"Arithmetic operator '{op}' requires Int or Real operands, got {left_val.type_name}",
                            offset=offset,
                        )

            # Relational
            if op in ("<", "<=", ">", ">="):
                res = _eval_relational(op, left_val, right_val, offset=offset)
                return TRUE_VALUE if res else FALSE_VALUE

            # Equality & Identity
            if op in ("is", "=="):
                res = qvalue_is(left_val, right_val)
                return TRUE_VALUE if res else FALSE_VALUE
            if op in ("isnot", "<>"):
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

        case TypedOption(tag=tag, payload=payload):
            p_val = eval_expr(payload, env) if payload is not None else None
            return QOption(tag=tag, payload=p_val)

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

        case TypedLetType() | TypedDefKind() | TypedInterface() | TypedModule():
            # Types, kinds, and interface/module compile-time declarations are erased at runtime
            return OK_VALUE

        case TypedImport(items=items):
            from quest.builtins import BuiltinModuleRegistry

            for item in items:
                for name in item.names:
                    mod_val = BuiltinModuleRegistry.get_runtime_module(name)
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
