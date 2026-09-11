"""C Code Generator for Quest AST (Emitting Standard ISO C99)."""

from __future__ import annotations

from typing import Any, Optional

from quest.codegen.c_types import mangle_ident, qtype_to_c_type, qtype_to_name_str
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
    TypedLetValue,
    TypedLoop,
    TypedNode,
    TypedOk,
    TypedParam,
    TypedProgram,
    TypedReal,
    TypedString,
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
    """Wraps a scalar expression into a QVal union initializer."""
    if t == INT_TYPE or t == BOOL_TYPE or t == CHAR_TYPE:
        return f"((QVal){{ .i = (int64_t)({expr_str}) }})"
    if t == REAL_TYPE:
        return f"((QVal){{ .r = (double)({expr_str}) }})"
    if t == STRING_TYPE:
        return f"((QVal){{ .p = (void *)({expr_str}) }})"
    return f"((QVal){{ .u = 0 }})"


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
                c_val = self.emit_val(val, lines)
                lines.append(f"{c_tgt} = {c_val};")
                return "((void)0)"

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
                    f"C code generation for {expr.__class__.__name__} not implemented in Phase 4.2a"
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
