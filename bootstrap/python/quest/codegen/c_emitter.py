"""C Code Generator for Quest AST (Emitting Standard ISO C99)."""

from __future__ import annotations

from typing import Any, Optional

from quest.codegen.c_types import (
    mangle_ident,
    qtype_to_c_type,
    qtype_to_name_str,
    record_struct_name,
    tuple_struct_name,
)
from quest.typed_ast import (
    TypedApp,
    TypedAssign,
    TypedBinding,
    TypedBlock,
    TypedBool,
    TypedChar,
    TypedDerefCell,
    TypedExit,
    TypedExpr,
    TypedExprStmt,
    TypedFor,
    TypedFun,
    TypedIf,
    TypedInfix,
    TypedInt,
    TypedLetType,
    TypedLetValue,
    TypedLoop,
    TypedNode,
    TypedOk,
    TypedParam,
    TypedProgram,
    TypedReal,
    TypedRecord,
    TypedRecordField,
    TypedSelect,
    TypedSelectRef,
    TypedString,
    TypedTuple,
    TypedTypeWitness,
    TypedVar,
    TypedVarCell,
    TypedWhile,
)
from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    INT_TYPE,
    OK_TYPE,
    REAL_TYPE,
    STRING_TYPE,
    QRecordField,
    QRecordType,
    QTupleField,
    QTupleType,
    QType,
)


def _c_string_literal(s: str) -> str:
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


def _c_char_literal(ch: str) -> str:
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


def _indent(text: str, spaces: int = 4) -> str:
    """Indents non-empty lines of text by the given number of spaces."""
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


def _qval_wrap(expr_str: str, t: QType) -> str:
    """Wraps a scalar or pointer expression into a QVal union initializer."""
    if t == INT_TYPE or t == BOOL_TYPE or t == CHAR_TYPE:
        return f"((QVal){{ .i = (int64_t)({expr_str}) }})"
    if t == REAL_TYPE:
        return f"((QVal){{ .r = (double)({expr_str}) }})"
    if t == STRING_TYPE or isinstance(t, (QTupleType, QRecordType)):
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    return f"((QVal){{ .u = 0 }})"


def _collect_aggregate_types(prog: TypedProgram) -> list[tuple[str, QType]]:
    """Traverses the program to find all unique QTupleType and QRecordType definitions."""
    visited_names: set[str] = set()
    result: list[tuple[str, QType]] = []

    def visit_type(t: Optional[QType]) -> None:
        if t is None:
            return
        if isinstance(t, QTupleType):
            for f in t.value_fields:
                visit_type(f.type_val)
            name = tuple_struct_name(t)
            if name not in visited_names:
                visited_names.add(name)
                result.append((name, t))
        elif isinstance(t, QRecordType):
            for f in t.fields:
                visit_type(f.type_val)
            name = record_struct_name(t)
            if name not in visited_names:
                visited_names.add(name)
                result.append((name, t))
        elif hasattr(t, "params") and hasattr(t, "result_type"):
            for p in getattr(t, "params", ()):
                visit_type(getattr(p, "type_val", None))
            visit_type(getattr(t, "result_type", None))
        elif hasattr(t, "element_type"):
            visit_type(getattr(t, "element_type", None))
        elif hasattr(t, "inner_type"):
            visit_type(getattr(t, "inner_type", None))
        elif hasattr(t, "variants"):
            for v in getattr(t, "variants", ()):
                visit_type(getattr(v, "type_val", None))

    def visit_node(node: Any) -> None:
        if node is None:
            return
        if hasattr(node, "type_val") and isinstance(getattr(node, "type_val"), QType):
            visit_type(getattr(node, "type_val"))
        if hasattr(node, "symbol"):
            sym = getattr(node, "symbol")
            if hasattr(sym, "type_val") and isinstance(getattr(sym, "type_val"), QType):
                visit_type(getattr(sym, "type_val"))
            if hasattr(sym, "definition") and isinstance(getattr(sym, "definition"), QType):
                visit_type(getattr(sym, "definition"))
        if hasattr(node, "definition") and isinstance(getattr(node, "definition"), QType):
            visit_type(getattr(node, "definition"))

        if isinstance(node, (list, tuple)):
            for item in node:
                visit_node(item)
            return

        if hasattr(node, "__dataclass_fields__"):
            for field_name in node.__dataclass_fields__:
                visit_node(getattr(node, field_name))

    visit_node(prog)
    return result


class CEmitter:
    """Translates typed Quest AST nodes into standard C99 source code."""

    def __init__(self, echo: bool = False):
        self.echo = echo
        self._tmp_id = 0

    def fresh_tmp(self, prefix: str = "_tmp") -> str:
        """Generates a unique temporary C identifier."""
        self._tmp_id += 1
        return f"{prefix}_{self._tmp_id}"

    def _collect_fun_params(self, fun: TypedFun) -> tuple[list[TypedParam], TypedExpr, QType]:
        """Flattens nested curried TypedFun nodes into uncurried parameter list and final body."""
        params = list(fun.params)
        body = fun.body
        ret_type = fun.type_val.result_type
        while isinstance(body, TypedFun):
            params.extend(body.params)
            ret_type = body.type_val.result_type
            body = body.body
        return params, body, ret_type

    def _collect_app_args(self, app: TypedApp) -> tuple[TypedExpr, list[TypedExpr]]:
        """Flattens nested curried TypedApp nodes into target function and argument list."""
        args = list(app.args)
        curr = app.func
        while isinstance(curr, TypedApp):
            args = list(curr.args) + args
            curr = curr.func
        return curr, args

    def emit_program(self, prog: TypedProgram) -> str:
        """Translates a TypedProgram into a full standard C99 source file string."""
        top_funs: list[tuple[str, TypedFun, Any]] = []
        top_vars: list[tuple[str, TypedExpr, Any]] = []

        for phrase in prog.phrases:
            match phrase:
                case TypedLetValue(name=name, value=val, symbol=symbol):
                    if isinstance(val, TypedFun):
                        top_funs.append((name, val, symbol))
                    else:
                        top_vars.append((name, val, symbol))
                case _:
                    pass

        lines: list[str] = [
            "/* Emitted by Quest Bootstrap C Transpiler */",
            "#include \"quest_runtime.h\"",
            "",
        ]

        # 0. Aggregate types (forward declarations and struct definitions)
        agg_types = _collect_aggregate_types(prog)
        if agg_types:
            lines.append("/* Forward declarations for aggregate types */")
            for tag_name, _ in agg_types:
                lines.append(f"typedef struct {tag_name} {tag_name};")
            lines.append("")
            lines.append("/* Aggregate struct definitions */")
            for tag_name, t in agg_types:
                lines.append(f"struct {tag_name} {{")
                if isinstance(t, QTupleType):
                    if not t.value_fields:
                        lines.append("    char _unused;")
                    else:
                        for i, f in enumerate(t.value_fields):
                            c_type = qtype_to_c_type(f.type_val)
                            lines.append(f"    {c_type} _{i};")
                elif isinstance(t, QRecordType):
                    if not t.fields:
                        lines.append("    char _unused;")
                    else:
                        for f in sorted(t.fields, key=lambda fld: fld.name):
                            c_type = qtype_to_c_type(f.type_val)
                            lines.append(f"    {c_type} qf_{f.name};")
                lines.append("};")
                lines.append("")

        # 1. Static declarations for top-level non-void variables
        if top_vars:
            for name, _val, symbol in top_vars:
                if symbol.type_val != OK_TYPE:
                    c_type = qtype_to_c_type(symbol.type_val)
                    c_ident = mangle_ident(name)
                    lines.append(f"static {c_type} {c_ident};")
            lines.append("")

        # 2. Forward declarations for all top-level functions
        if top_funs:
            for name, fun, _sym in top_funs:
                params, _body, ret_type = self._collect_fun_params(fun)
                c_name = mangle_ident(name)
                ret_c = "void" if ret_type == OK_TYPE else qtype_to_c_type(ret_type)
                if not params:
                    param_sig = "void"
                else:
                    param_sig = ", ".join(
                        f"{qtype_to_c_type(p.type_val)} {mangle_ident(p.name)}"
                        for p in params
                    )
                lines.append(f"static {ret_c} {c_name}({param_sig});")
            lines.append("")

        # 3. Function definitions
        for name, fun, _sym in top_funs:
            params, body, ret_type = self._collect_fun_params(fun)
            c_name = mangle_ident(name)
            ret_c = "void" if ret_type == OK_TYPE else qtype_to_c_type(ret_type)
            if not params:
                param_sig = "void"
            else:
                param_sig = ", ".join(
                    f"{qtype_to_c_type(p.type_val)} {mangle_ident(p.name)}"
                    for p in params
                )
            lines.append(f"static {ret_c} {c_name}({param_sig}) {{")
            fn_lines: list[str] = []
            if ret_type == OK_TYPE:
                self.emit_to(body, None, fn_lines)
                fn_lines.append("return;")
            else:
                ret_val = self.emit_val(body, fn_lines)
                fn_lines.append(f"return {ret_val};")
            for f_line in fn_lines:
                lines.append(f"    {f_line}" if f_line.strip() else f_line)
            lines.append("}")
            lines.append("")

        # 4. Main entrypoint
        lines.extend([
            "int main(int argc, char **argv) {",
            "    (void)argc; (void)argv;",
            "    quest_gc_init();",
            "",
        ])

        total_phrases = len(prog.phrases)
        for i, phrase in enumerate(prog.phrases):
            is_last = (i == total_phrases - 1)
            self._emit_phrase(phrase, lines, is_last=is_last)

        lines.extend([
            "",
            "    return 0;",
            "}",
            "",
        ])
        return "\n".join(lines)

    def _emit_phrase(self, phrase: TypedNode, lines: list[str], is_last: bool = False) -> None:
        """Translates a top-level binding or expression phrase."""
        match phrase:
            case TypedLetValue(name=name, value=val, symbol=symbol):
                if isinstance(val, TypedFun):
                    if self.echo:
                        type_str = _c_string_literal(qtype_to_name_str(symbol.type_val))
                        lines.append(f"    quest_print_val(((QVal){{ .u = 0 }}), {type_str});")
                    return

                c_ident = mangle_ident(name)
                if symbol.type_val == OK_TYPE:
                    lines.append(f"    // inlined {name}")
                    phrase_lines: list[str] = []
                    self.emit_to(val, None, phrase_lines)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                else:
                    phrase_lines = []
                    self.emit_to(val, c_ident, phrase_lines)
                    for s in phrase_lines:
                        lines.append(f"    {s}" if s.strip() else s)
                if self.echo:
                    wrap = _qval_wrap(c_ident, symbol.type_val)
                    type_str = _c_string_literal(qtype_to_name_str(symbol.type_val))
                    lines.append(f"    quest_print_val({wrap}, {type_str});")

            case TypedExprStmt(expr=inner):
                self._emit_expr_phrase(inner, lines, is_last=is_last)

            case TypedExpr():
                self._emit_expr_phrase(phrase, lines, is_last=is_last)

            case _:
                # Type / Kind declarations are erased at runtime
                pass

    def _emit_expr_phrase(self, expr: TypedExpr, lines: list[str], is_last: bool = False) -> None:
        expr_type = expr.type_val
        phrase_lines: list[str] = []
        if expr_type == OK_TYPE:
            self.emit_to(expr, None, phrase_lines)
            for s in phrase_lines:
                lines.append(f"    {s}" if s.strip() else s)
            return

        c_type = qtype_to_c_type(expr_type)
        tmp = self.fresh_tmp("_res")
        phrase_lines.append(f"{c_type} {tmp};")
        self.emit_to(expr, tmp, phrase_lines)
        for s in phrase_lines:
            lines.append(f"    {s}" if s.strip() else s)
        if self.echo or is_last:
            wrap = _qval_wrap(tmp, expr_type)
            type_str = _c_string_literal(qtype_to_name_str(expr_type))
            lines.append(f"    quest_print_val({wrap}, {type_str});")

    def emit_val(self, expr: TypedExpr, lines: list[str]) -> str:
        """Emits any preparatory statements into lines and returns a C99 expression value."""
        match expr:
            case TypedInt(value=val):
                return f"{val}LL" if val >= 0 else f"({val}LL)"

            case TypedReal(value=val):
                s = repr(val)
                if "e" not in s and "." not in s:
                    s += ".0"
                return s

            case TypedBool(value=val):
                return "true" if val else "false"

            case TypedChar(value=val):
                return _c_char_literal(val)

            case TypedString(value=val):
                lit = _c_string_literal(val)
                return f"quest_string_new({lit}, {len(val)}LL)"

            case TypedOk():
                return "((void)0)"

            case TypedVar(name=name):
                return mangle_ident(name)

            case TypedDerefCell(target=tgt):
                return self.emit_val(tgt, lines)

            case TypedVarCell(value=val):
                return self.emit_val(val, lines)

            case TypedAssign(target=tgt, value=val):
                c_tgt = self.emit_val(tgt, lines)
                self.emit_to(val, c_tgt, lines)
                return "((void)0)"

            case TypedTuple() | TypedRecord():
                tmp = self.fresh_tmp("_alloc")
                c_type = qtype_to_c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case TypedSelect(target=tgt, field=fld):
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QTupleType):
                    val_idx = None
                    for i, vf in enumerate(tgt.type_val.value_fields):
                        if vf.name == fld:
                            val_idx = i
                            break
                    if val_idx is None:
                        if fld.startswith("_"):
                            val_idx = int(fld[1:])
                        elif fld.isdigit():
                            val_idx = int(fld)
                        else:
                            raise ValueError(f"Cannot resolve tuple field '{fld}' in {tgt.type_val}")
                    return f"{c_tgt}->_{val_idx}"
                elif isinstance(tgt.type_val, QRecordType):
                    return f"{c_tgt}->qf_{fld}"
                else:
                    return f"{c_tgt}->qf_{fld}"

            case TypedSelectRef(target=tgt, field=fld):
                c_tgt = self.emit_val(tgt, lines)
                if isinstance(tgt.type_val, QTupleType):
                    val_idx = None
                    for i, vf in enumerate(tgt.type_val.value_fields):
                        if vf.name == fld:
                            val_idx = i
                            break
                    if val_idx is None:
                        if fld.startswith("_"):
                            val_idx = int(fld[1:])
                        elif fld.isdigit():
                            val_idx = int(fld)
                        else:
                            raise ValueError(f"Cannot resolve tuple field '{fld}' in {tgt.type_val}")
                    return f"(&({c_tgt}->_{val_idx}))"
                else:
                    return f"(&({c_tgt}->qf_{fld}))"

            case TypedInfix(left=left, op=op, right=right):
                c_left = self.emit_val(left, lines)
                c_right = self.emit_val(right, lines)
                return self._emit_infix(c_left, op, c_right)

            case TypedApp():
                func_target, args = self._collect_app_args(expr)
                c_func = self.emit_val(func_target, lines)
                c_args = [self.emit_val(a, lines) for a in args]
                args_str = ", ".join(c_args)
                call_str = f"{c_func}({args_str})"
                if expr.type_val == OK_TYPE:
                    lines.append(f"{call_str};")
                    return "((void)0)"
                return call_str

            case TypedExit():
                lines.append("break;")
                return "((void)0)"

            case TypedIf() | TypedBlock() | TypedWhile() | TypedLoop() | TypedFor():
                if expr.type_val == OK_TYPE:
                    self.emit_to(expr, None, lines)
                    return "((void)0)"
                tmp = self.fresh_tmp("_val")
                c_type = qtype_to_c_type(expr.type_val)
                lines.append(f"{c_type} {tmp};")
                self.emit_to(expr, tmp, lines)
                return tmp

            case _:
                raise NotImplementedError(
                    f"C code generation for {expr.__class__.__name__} not implemented in Phase 4.2b"
                )

    def emit_to(self, expr: TypedExpr, dest: Optional[str], lines: list[str]) -> None:
        """Lowers expr into lines, storing the result into dest (if dest is not None)."""
        match expr:
            case TypedIf(cond=cond, then_branch=then_b, else_branch=else_b, type_val=t):
                c_cond = self.emit_val(cond, lines)
                lines.append(f"if ({c_cond}) {{")
                then_lines: list[str] = []
                self.emit_to(then_b, dest, then_lines)
                for line in then_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                if else_b is not None:
                    lines.append("} else {")
                    else_lines: list[str] = []
                    self.emit_to(else_b, dest, else_lines)
                    for line in else_lines:
                        lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedBlock(bindings=bindings, result=result):
                lines.append("{")
                block_lines: list[str] = []
                for b in bindings:
                    match b:
                        case TypedLetValue(name=name, value=val, symbol=symbol):
                            c_ident = mangle_ident(name)
                            if symbol.type_val == OK_TYPE:
                                self.emit_to(val, None, block_lines)
                            else:
                                c_type = qtype_to_c_type(symbol.type_val)
                                block_lines.append(f"{c_type} {c_ident};")
                                self.emit_to(val, c_ident, block_lines)
                        case TypedExprStmt(expr=inner):
                            self.emit_to(inner, None, block_lines)
                        case _:
                            pass
                self.emit_to(result, dest, block_lines)
                for line in block_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedWhile(cond=cond, body=body):
                lines.append("while (1) {")
                loop_lines: list[str] = []
                c_cond = self.emit_val(cond, loop_lines)
                loop_lines.append(f"if (!({c_cond})) break;")
                self.emit_to(body, None, loop_lines)
                for line in loop_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedLoop(body=body):
                lines.append("while (1) {")
                loop_lines = []
                self.emit_to(body, None, loop_lines)
                for line in loop_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedFor(start=start, stop=stop, body=body, is_downto=is_downto, var_name=var_name):
                c_start = self.emit_val(start, lines)
                c_stop = self.emit_val(stop, lines)
                v = mangle_ident(var_name)
                stop_tmp = self.fresh_tmp("_stop")
                cmp_op = ">=" if is_downto else "<="
                step_op = "--" if is_downto else "++"
                lines.append(f"QInt {stop_tmp} = {c_stop};")
                lines.append(f"for (QInt {v} = {c_start}; {v} {cmp_op} {stop_tmp}; {v}{step_op}) {{")
                for_lines: list[str] = []
                self.emit_to(body, None, for_lines)
                for line in for_lines:
                    lines.append(f"    {line}" if line.strip() else line)
                lines.append("}")

            case TypedExit():
                lines.append("break;")

            case TypedTuple(elements=elems, type_val=t):
                struct_name = tuple_struct_name(t)
                alloc_expr = f"({struct_name} *)quest_alloc(sizeof({struct_name}))"
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_tuple")
                    lines.append(f"{struct_name} *{target_dest} = {alloc_expr};")
                else:
                    lines.append(f"{target_dest} = {alloc_expr};")
                val_idx = 0
                for elem in elems:
                    if isinstance(elem, TypedTypeWitness):
                        continue
                    self.emit_to(elem, f"{target_dest}->_{val_idx}", lines)
                    val_idx += 1

            case TypedRecord(fields=flds, type_val=t):
                struct_name = record_struct_name(t)
                alloc_expr = f"({struct_name} *)quest_alloc(sizeof({struct_name}))"
                target_dest = dest
                if target_dest is None:
                    target_dest = self.fresh_tmp("_record")
                    lines.append(f"{struct_name} *{target_dest} = {alloc_expr};")
                else:
                    lines.append(f"{target_dest} = {alloc_expr};")
                for fld in flds:
                    self.emit_to(fld.value, f"{target_dest}->qf_{fld.name}", lines)

            case _:
                val = self.emit_val(expr, lines)
                if dest is not None and expr.type_val != OK_TYPE:
                    lines.append(f"{dest} = {val};")
                elif val != "((void)0)":
                    lines.append(f"{val};")

    def _emit_infix(self, c_left: str, op: str, c_right: str) -> str:
        # 1. Integer division and modulo via C99 inline runtime functions
        if op == "/":
            return f"quest_int_div({c_left}, {c_right})"
        if op in ("%", "mod"):
            return f"quest_int_mod({c_left}, {c_right})"

        # 2. Real exponentiation
        if op == "^^":
            return f"quest_real_pow({c_left}, {c_right})"

        # 3. String concatenation
        if op == "<>":
            return f"quest_string_concat({c_left}, {c_right})"

        # 4. Standard arithmetic & relations mapping directly
        op_map = {
            "+": "+", "-": "-", "*": "*",
            "++": "+", "--": "-", "**": "*", "//": "/",
            "<": "<", "<=": "<=", ">": ">", ">=": ">=",
            "<<": "<", "<<=": "<=", ">>": ">", ">>=": ">=",
            "/\\": "&&", "\\/": "||",
            "is": "==", "isnot": "!=", "==": "==",
        }
        if op in op_map:
            c_op = op_map[op]
            return f"(({c_left}) {c_op} ({c_right}))"

        raise NotImplementedError(f"Unsupported infix operator '{op}' in C codegen")
