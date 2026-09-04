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
from typing import Optional

from quest.diagnostics import Diagnostic, DiagnosticLabel, Severity
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
    TypedInspect,
    TypedInspectBranch,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
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
    TypedVar,
    TypedVarCell,
    TypedVariant,
    TypedWhile,
)


# ============================================================================
# 1. Runtime Exceptions & Control Signals
# ============================================================================

class _LoopExit(Exception):
    """Internal control-flow signal raised by TypedExit to break out of loops."""
    pass


class QuestException(Exception):
    """Language-level Quest exception (e.g. DivideByZero or user-raised exception)."""

    def __init__(
        self,
        exc_val: QExceptionVal,
        payload: Optional[QValue] = None,
        payload_type: Optional[QType] = None,
        offset: Optional[int] = None,
    ):
        super().__init__(exc_val.to_str())
        self.exc_val = exc_val
        self.payload = payload
        self.payload_type = payload_type
        self.offset = offset

    def to_diagnostic(self, length: int = 1) -> Diagnostic:
        label = DiagnosticLabel(offset=self.offset, length=length) if self.offset is not None else None
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


class QuestRuntimeError(Exception):
    """System-level runtime evaluation error (e.g. undefined symbol)."""

    def __init__(self, message: str, offset: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.offset = offset

    def to_diagnostic(self, length: int = 1) -> Diagnostic:
        label = DiagnosticLabel(offset=self.offset, length=length) if self.offset is not None else None
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
    if isinstance(val, QInt):
        return INT_TYPE
    if isinstance(val, QReal):
        return REAL_TYPE
    if isinstance(val, QBool):
        return BOOL_TYPE
    if isinstance(val, QChar):
        return CHAR_TYPE
    if isinstance(val, QString):
        return STRING_TYPE
    if isinstance(val, QOk):
        return OK_TYPE
    if isinstance(val, QExceptionVal):
        return EXCEPTION_TYPE
    if isinstance(val, QDynamicVal):
        return DYNAMIC_TYPE
    return OK_TYPE


# ============================================================================
# 3. Arithmetic & Infix Helper Functions
# ============================================================================

def _eval_int_arithmetic(op: str, a: int, b: int, offset: Optional[int] = None) -> int:
    """Evaluates integer arithmetic with C-style truncation and DivideByZero check."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
        # C-style truncation toward zero
        return int(a / b)
    if op in ("mod", "%"):
        if b == 0:
            raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
        # C-style modulo: a - trunc(a / b) * b
        return a - int(a / b) * b
    raise QuestRuntimeError(f"Unknown integer arithmetic operator '{op}'", offset=offset)


def _eval_real_arithmetic(op: str, a: float, b: float, offset: Optional[int] = None) -> float:
    """Evaluates real floating-point arithmetic."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0.0:
            raise QuestException(DIVIDE_BY_ZERO_EXC, offset=offset)
        return a / b
    raise QuestRuntimeError(f"Unknown real arithmetic operator '{op}'", offset=offset)


def _eval_relational(op: str, left: QValue, right: QValue, offset: Optional[int] = None) -> bool:
    """Evaluates relational comparisons (<, <=, >, >=) for Int, Real, Char, String."""
    if isinstance(left, QInt) and isinstance(right, QInt):
        l_val, r_val = left.value, right.value
    elif isinstance(left, QReal) and isinstance(right, QReal):
        l_val, r_val = left.value, right.value
    elif isinstance(left, QChar) and isinstance(right, QChar):
        l_val, r_val = left.value, right.value
    elif isinstance(left, QString) and isinstance(right, QString):
        l_val, r_val = left.value, right.value
    else:
        raise QuestRuntimeError(
            f"Relational operator '{op}' cannot compare types {left.type_name} and {right.type_name}",
            offset=offset,
        )

    if op == "<":
        return l_val < r_val
    if op == "<=":
        return l_val <= r_val
    if op == ">":
        return l_val > r_val
    if op == ">=":
        return l_val >= r_val
    raise QuestRuntimeError(f"Unknown relational operator '{op}'", offset=offset)


# ============================================================================
# 4. Expression Evaluator
# ============================================================================

def eval_expr(expr: TypedExpr, env: RuntimeEnvironment) -> QValue:
    """Evaluates a typed expression within the given runtime environment."""

    # 1. Literals
    if isinstance(expr, TypedInt):
        return QInt(expr.value)
    if isinstance(expr, TypedReal):
        return QReal(expr.value)
    if isinstance(expr, TypedBool):
        return TRUE_VALUE if expr.value else FALSE_VALUE
    if isinstance(expr, TypedChar):
        return QChar(expr.value)
    if isinstance(expr, TypedString):
        return QString(expr.value)
    if isinstance(expr, TypedOk):
        return OK_VALUE

    # 2. Variables & Mutable References
    if isinstance(expr, TypedVar):
        return env.lookup(expr.name, offset=expr.offset)

    if isinstance(expr, TypedVarCell):
        inner_val = eval_expr(expr.value, env)
        return QRef(inner_val)

    if isinstance(expr, TypedDerefCell):
        target_val = eval_expr(expr.target, env)
        if isinstance(target_val, QRef):
            return target_val.deref()
        return target_val

    if isinstance(expr, TypedAssign):
        rhs_val = eval_expr(expr.value, env)
        if isinstance(expr.target, TypedVar):
            cell = env.lookup(expr.target.name, offset=expr.offset)
            if isinstance(cell, QRef):
                cell.assign(rhs_val)
            else:
                env.assign(expr.target.name, rhs_val, offset=expr.offset)
            return OK_VALUE
        if isinstance(expr.target, TypedSelect):
            rec_val = eval_expr(expr.target.target, env)
            if not isinstance(rec_val, QRecord):
                raise QuestRuntimeError("Field assignment target must be Record", offset=expr.offset)
            field_cell = rec_val.get(expr.target.field)
            if isinstance(field_cell, QRef):
                field_cell.assign(rhs_val)
            else:
                rec_val.fields[expr.target.field] = rhs_val
            return OK_VALUE
        raise QuestRuntimeError("Unsupported assignment target in interpreter", offset=expr.offset)

    # 3. Functions & Application
    if isinstance(expr, TypedFun):
        return QClosure(
            params=tuple(p.name for p in expr.params),
            body=expr.body,
            env=env,
        )

    if isinstance(expr, TypedTypeApp):
        callee = eval_expr(expr.func, env)
        if isinstance(callee, QBuiltinFun) and callee.name == "dynamic" and expr.type_args:
            target_type = expr.type_args[0]
            return QBuiltinFun("dynamic", fn=lambda *args: QDynamicVal(args[0], target_type))
        return callee

    if isinstance(expr, TypedApp):
        callee_val = eval_expr(expr.func, env)
        arg_vals = [eval_expr(arg, env) for arg in expr.args]

        if isinstance(callee_val, QBuiltinFun):
            return callee_val.fn(*arg_vals)

        if isinstance(callee_val, QClosure):
            call_env = callee_val.env.push_scope()
            for param_name, arg_val in zip(callee_val.params, arg_vals):
                call_env.define(param_name, arg_val)
            return eval_expr(callee_val.body, call_env)

        raise QuestRuntimeError(
            f"Cannot call non-function of type {callee_val.type_name}",
            offset=expr.offset,
        )

    # 4. Infix Operations
    if isinstance(expr, TypedInfix):
        left_val = eval_expr(expr.left, env)
        right_val = eval_expr(expr.right, env)

        # Arithmetic
        if expr.op in ("+", "-", "*", "/", "mod", "%"):
            if isinstance(left_val, QInt) and isinstance(right_val, QInt):
                return QInt(_eval_int_arithmetic(expr.op, left_val.value, right_val.value, offset=expr.offset))
            if isinstance(left_val, QReal) and isinstance(right_val, QReal):
                return QReal(_eval_real_arithmetic(expr.op, left_val.value, right_val.value, offset=expr.offset))
            raise QuestRuntimeError(
                f"Arithmetic operator '{expr.op}' requires Int or Real operands, got {left_val.type_name}",
                offset=expr.offset,
            )

        # Relational
        if expr.op in ("<", "<=", ">", ">="):
            res = _eval_relational(expr.op, left_val, right_val, offset=expr.offset)
            return TRUE_VALUE if res else FALSE_VALUE

        # Equality & Identity
        if expr.op in ("is", "=="):
            res = qvalue_is(left_val, right_val)
            return TRUE_VALUE if res else FALSE_VALUE
        if expr.op in ("isnot", "<>"):
            res = not qvalue_is(left_val, right_val)
            return TRUE_VALUE if res else FALSE_VALUE

        raise QuestRuntimeError(f"Unsupported infix operator '{expr.op}'", offset=expr.offset)

    # 4. Conditionals (TypedIf)
    if isinstance(expr, TypedIf):
        cond_val = eval_expr(expr.cond, env)
        if not isinstance(cond_val, QBool):
            raise QuestRuntimeError("Conditional expression must evaluate to Bool", offset=expr.offset)
        if cond_val.value:
            return eval_expr(expr.then_branch, env)
        else:
            return eval_expr(expr.else_branch, env)

    # 5. Scoped Blocks (TypedBlock)
    if isinstance(expr, TypedBlock):
        block_env = env.push_scope()
        try:
            for b in expr.bindings:
                eval_binding(b, block_env)
            return eval_expr(expr.result, block_env)
        finally:
            env = block_env.pop_scope()

    # 6. Loops & Control Flow
    if isinstance(expr, TypedLoop):
        while True:
            try:
                eval_expr(expr.body, env)
            except _LoopExit:
                break
        return OK_VALUE

    if isinstance(expr, TypedWhile):
        while True:
            cond_val = eval_expr(expr.cond, env)
            if not isinstance(cond_val, QBool):
                raise QuestRuntimeError("While loop condition must evaluate to Bool", offset=expr.offset)
            if not cond_val.value:
                break
            try:
                eval_expr(expr.body, env)
            except _LoopExit:
                break
        return OK_VALUE

    if isinstance(expr, TypedFor):
        start_val = eval_expr(expr.start, env)
        stop_val = eval_expr(expr.stop, env)
        if not isinstance(start_val, QInt) or not isinstance(stop_val, QInt):
            raise QuestRuntimeError("For loop bounds must evaluate to Int", offset=expr.offset)

        start_i = start_val.value
        stop_i = stop_val.value
        loop_env = env.push_scope()
        try:
            if not expr.is_downto:
                cur = start_i
                while cur <= stop_i:
                    loop_env.define(expr.var_name, QInt(cur))
                    try:
                        eval_expr(expr.body, loop_env)
                    except _LoopExit:
                        break
                    cur += 1
            else:
                cur = start_i
                while cur >= stop_i:
                    loop_env.define(expr.var_name, QInt(cur))
                    try:
                        eval_expr(expr.body, loop_env)
                    except _LoopExit:
                        break
                    cur -= 1
        finally:
            env = loop_env.pop_scope()
        return OK_VALUE

    # 7. Aggregates: Records & Tuples
    if isinstance(expr, TypedRecord):
        rec_fields: dict[str, QValue] = {}
        for f in expr.fields:
            val = eval_expr(f.value, env)
            if f.is_var:
                rec_fields[f.name] = QRef(val)
            else:
                rec_fields[f.name] = val
        return QRecord(rec_fields)

    if isinstance(expr, TypedTuple):
        elems = tuple(eval_expr(e, env) for e in expr.elements)
        labels: Optional[tuple[Optional[str], ...]] = None
        if isinstance(expr.type_val, QTupleType):
            labels = tuple(f.name for f in expr.type_val.fields)
        return QTuple(elements=elems, labels=labels)

    if isinstance(expr, TypedSelect):
        target_val = eval_expr(expr.target, env)
        if isinstance(target_val, QRecord):
            field_val = target_val.get(expr.field)
            if isinstance(field_val, QRef):
                return field_val.deref()
            return field_val
        if isinstance(target_val, QTuple):
            return target_val.get_by_name(expr.field)
        raise QuestRuntimeError(
            f"Cannot select field '{expr.field}' from {target_val.type_name}",
            offset=expr.offset,
        )

    # 8. Arrays: Creation, Repetition, Indexing, and Assignment
    if isinstance(expr, TypedArray):
        elems_list = [eval_expr(e, env) for e in expr.elements]
        return QArray(elements=elems_list)

    if isinstance(expr, TypedArrayRep):
        count_val = eval_expr(expr.count, env)
        if not isinstance(count_val, QInt):
            raise QuestRuntimeError("Array count must evaluate to Int", offset=expr.offset)
        if count_val.value < 0:
            raise QuestException(ARRAY_OP_ERROR_EXC, offset=expr.offset)
        init_val = eval_expr(expr.init_val, env)
        return QArray(elements=[init_val for _ in range(count_val.value)])

    if isinstance(expr, TypedIndex):
        target_val = eval_expr(expr.target, env)
        idx_val = eval_expr(expr.index, env)
        if not isinstance(target_val, QArray):
            raise QuestRuntimeError(f"Index target must be Array, got {target_val.type_name}", offset=expr.offset)
        if not isinstance(idx_val, QInt):
            raise QuestRuntimeError(f"Array index must be Int, got {idx_val.type_name}", offset=expr.offset)
        if idx_val.value < 0 or idx_val.value >= target_val.size():
            raise QuestException(ARRAY_OP_ERROR_EXC, offset=expr.offset)
        return target_val.get(idx_val.value)

    if isinstance(expr, TypedIndexAssign):
        target_val = eval_expr(expr.target, env)
        idx_val = eval_expr(expr.index, env)
        rhs_val = eval_expr(expr.value, env)
        if not isinstance(target_val, QArray):
            raise QuestRuntimeError(f"Index target must be Array, got {target_val.type_name}", offset=expr.offset)
        if not isinstance(idx_val, QInt):
            raise QuestRuntimeError(f"Array index must be Int, got {idx_val.type_name}", offset=expr.offset)
        if idx_val.value < 0 or idx_val.value >= target_val.size():
            raise QuestException(ARRAY_OP_ERROR_EXC, offset=expr.offset)
        target_val.set(idx_val.value, rhs_val)
        return OK_VALUE

    # 9. Variants, Options, and Pattern Matching
    if isinstance(expr, TypedVariant):
        payload = eval_expr(expr.payload, env) if expr.payload is not None else None
        return QVariant(tag=expr.tag, payload=payload)

    if isinstance(expr, TypedOption):
        payload = eval_expr(expr.payload, env) if expr.payload is not None else None
        return QOption(tag=expr.tag, payload=payload)

    if isinstance(expr, TypedCase):
        target_val = eval_expr(expr.target, env)
        if not isinstance(target_val, (QVariant, QOption)):
            raise QuestRuntimeError(
                f"Case target must be Variant or Option, got {target_val.type_name}",
                offset=expr.offset,
            )
        for branch in expr.branches:
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
        if expr.else_branch is not None:
            return eval_expr(expr.else_branch, env)
        raise QuestRuntimeError(f"Unhandled case tag '{target_val.tag}'", offset=expr.offset)

    # 10. Exceptions
    if isinstance(expr, TypedException):
        exc_val = QExceptionVal(name=expr.name)
        if expr.name:
            env.define(expr.name, exc_val)
        return exc_val

    if isinstance(expr, TypedRaise):
        tag_val = eval_expr(expr.exc, env)
        if not isinstance(tag_val, QExceptionVal):
            raise QuestRuntimeError(
                f"Target of raise must be Exception, got {tag_val.type_name}",
                offset=expr.offset,
            )
        payload_val = eval_expr(expr.payload, env) if expr.payload is not None else None
        payload_type = expr.payload.type_val if expr.payload is not None else None
        raise QuestException(
            exc_val=tag_val,
            payload=payload_val,
            payload_type=payload_type,
            offset=expr.offset,
        )

    if isinstance(expr, TypedTry):
        try:
            return eval_expr(expr.body, env)
        except QuestException as raised_exc:
            for branch in expr.branches:
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
            if expr.else_branch is not None:
                return eval_expr(expr.else_branch, env)
            raise

    # 11. Dynamic Types & Type Inspection
    if isinstance(expr, TypedInspect):
        target_dyn = eval_expr(expr.target, env)
        if not isinstance(target_dyn, QDynamicVal):
            raise QuestRuntimeError(
                f"Inspect target must be Dynamic, got {target_dyn.type_name}",
                offset=expr.offset,
            )
        for branch in expr.branches:
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
        if expr.else_branch is not None:
            return eval_expr(expr.else_branch, env)
        raise QuestException(DYNAMIC_ERROR_EXC, offset=expr.offset)

    if isinstance(expr, TypedExit):
        raise _LoopExit()

    raise QuestRuntimeError(
        f"Unhandled expression node: {expr.__class__.__name__}",
        offset=getattr(expr, "offset", 0),
    )


# ============================================================================
# 5. Binding & Program Evaluator
# ============================================================================

def eval_binding(binding: TypedBinding, env: RuntimeEnvironment) -> QValue:
    """Evaluates a declaration or binding inside a block or top-level program."""
    if isinstance(binding, TypedLetValue):
        if binding.is_rec and isinstance(binding.value, TypedFun):
            closure = QClosure(
                params=tuple(p.name for p in binding.value.params),
                body=binding.value.body,
                env=env,
                name=binding.name,
            )
            env.define(binding.name, closure)
            return closure
        val = eval_expr(binding.value, env)
        if binding.symbol.is_var:
            env.define(binding.name, QRef(val))
        else:
            env.define(binding.name, val)
        return val

    if isinstance(binding, (TypedLetType, TypedDefKind)):
        # Types and kinds are erased at runtime
        return OK_VALUE

    if isinstance(binding, TypedExprStmt):
        return eval_expr(binding.expr, env)

    raise QuestRuntimeError(f"Unhandled binding node: {binding.__class__.__name__}")


def eval_program(program: TypedProgram, env: Optional[RuntimeEnvironment] = None) -> QValue:
    """Evaluates an entire typed program sequentially, returning the final phrase value."""
    if env is None:
        env = RuntimeEnvironment.create_root_env()

    final_val: QValue = OK_VALUE
    for phrase in program.phrases:
        if isinstance(phrase, TypedBinding):
            final_val = eval_binding(phrase, env)
        elif isinstance(phrase, TypedExpr):
            final_val = eval_expr(phrase, env)
        else:
            raise QuestRuntimeError(f"Unknown top-level phrase: {phrase.__class__.__name__}")

    return final_val


def format_interactive_result(
    phrase: Optional[TypedNode],
    val: Optional[QValue],
) -> str:
    """Formats the result of evaluating a top-level phrase in Cardelli interactive style."""
    if phrase is None or val is None:
        return ""

    if isinstance(phrase, TypedLetValue):
        var_str = "var " if phrase.symbol.is_var else ""
        type_str = str(phrase.symbol.type_val)
        val_str = qvalue_to_str(val)
        return f"let {var_str}{phrase.name}:{type_str} = {val_str}"

    if isinstance(phrase, TypedLetType):
        kind_str = str(phrase.symbol.kind)
        if phrase.symbol.definition is not None:
            return f"Let {phrase.name}::{kind_str} = {phrase.symbol.definition}"
        return f"Let {phrase.name}::{kind_str}"

    if isinstance(phrase, TypedDefKind):
        kind_str = str(phrase.symbol.kind)
        return f"DEF {phrase.name} = {kind_str}"

    if isinstance(phrase, TypedExprStmt):
        if isinstance(val, QOk):
            return ""
        if isinstance(phrase.expr, TypedException):
            return f"exception {phrase.expr.name}"
        return f"{qvalue_to_str(val)} : {phrase.expr.type_val}"

    if isinstance(phrase, TypedExpr):
        if isinstance(val, QOk):
            return ""
        if isinstance(phrase, TypedException):
            return f"exception {phrase.name}"
        return f"{qvalue_to_str(val)} : {phrase.type_val}"

    return ""
