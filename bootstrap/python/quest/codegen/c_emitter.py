"""C Code Generator for Quest AST (Phase 4.1: Scalars, Expressions, and Control Flow)."""

from __future__ import annotations

from typing import Optional

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
        return "'\\\''"
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
    """Translates typed Quest AST nodes into C99 source code."""

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
        """Translates a TypedProgram into a full C99 source file string."""
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
            c_body = self.emit_expr(body)
            lines.append(f"static {ret_c} {c_name}({param_sig}) {{")
            if ret_type == OK_TYPE:
                for b_line in f"{c_body};".split("\n"):
                    lines.append(f"    {b_line}" if b_line.strip() else b_line)
                lines.append("    return;")
            else:
                for b_line in f"return {c_body};".split("\n"):
                    lines.append(f"    {b_line}" if b_line.strip() else b_line)
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
                val_c = self.emit_expr(val)
                if symbol.type_val == OK_TYPE:
                    stmt = f"{val_c};"
                else:
                    stmt = f"{c_ident} = {val_c};"
                for s_line in stmt.split("\n"):
                    lines.append(f"    {s_line}" if s_line.strip() else s_line)
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
        expr_c = self.emit_expr(expr)
        expr_type = expr.type_val
        if expr_type == OK_TYPE:
            for s_line in f"{expr_c};".split("\n"):
                lines.append(f"    {s_line}" if s_line.strip() else s_line)
            return

        c_type = qtype_to_c_type(expr_type)
        tmp = self.fresh_tmp("_res")
        for s_line in f"{c_type} {tmp} = {expr_c};".split("\n"):
            lines.append(f"    {s_line}" if s_line.strip() else s_line)
        if self.echo or is_last:
            wrap = _qval_wrap(tmp, expr_type)
            type_str = _c_string_literal(qtype_to_name_str(expr_type))
            lines.append(f"    quest_print_val({wrap}, {type_str});")

    def emit_expr(self, expr: TypedExpr) -> str:
        """Emits a C expression string for a TypedExpr node."""
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
                return self.emit_expr(tgt)

            case TypedVarCell(value=val):
                return self.emit_expr(val)

            case TypedAssign(target=tgt, value=val):
                c_tgt = self.emit_expr(tgt)
                c_val = self.emit_expr(val)
                return f"({c_tgt} = {c_val}, ((void)0))"

            case TypedInfix(left=left, op=op, right=right):
                return self._emit_infix(left, op, right)

            case TypedIf(cond=cond, then_branch=then_b, else_branch=else_b, type_val=t):
                c_cond = self.emit_expr(cond)
                c_then = self.emit_expr(then_b)
                if t == OK_TYPE:
                    if else_b is not None:
                        c_else = self.emit_expr(else_b)
                        inner = (
                            f"if ({c_cond}) {{\n"
                            f"{_indent(c_then + ';')}\n"
                            f"}} else {{\n"
                            f"{_indent(c_else + ';')}\n"
                            f"}}\n"
                            f"((void)0);"
                        )
                    else:
                        inner = (
                            f"if ({c_cond}) {{\n"
                            f"{_indent(c_then + ';')}\n"
                            f"}}\n"
                            f"((void)0);"
                        )
                    return f"({{\n{_indent(inner)}\n}})"
                else:
                    c_else = self.emit_expr(else_b)
                    tmp = self.fresh_tmp("_if_res")
                    c_type = qtype_to_c_type(t)
                    inner = (
                        f"{c_type} {tmp};\n"
                        f"if ({c_cond}) {{\n"
                        f"{_indent(f'{tmp} = {c_then};')}\n"
                        f"}} else {{\n"
                        f"{_indent(f'{tmp} = {c_else};')}\n"
                        f"}}\n"
                        f"{tmp};"
                    )
                    return f"({{\n{_indent(inner)}\n}})"

            case TypedBlock(bindings=bindings, result=result):
                return self._emit_block(bindings, result)

            case TypedWhile(cond=cond, body=body):
                c_cond = self.emit_expr(cond)
                c_body = self.emit_expr(body)
                inner = (
                    f"while ({c_cond}) {{\n"
                    f"{_indent(c_body + ';')}\n"
                    f"}}\n"
                    f"((void)0);"
                )
                return f"({{\n{_indent(inner)}\n}})"

            case TypedLoop(body=body):
                c_body = self.emit_expr(body)
                inner = (
                    f"while (1) {{\n"
                    f"{_indent(c_body + ';')}\n"
                    f"}}\n"
                    f"((void)0);"
                )
                return f"({{\n{_indent(inner)}\n}})"

            case TypedFor(start=start, stop=stop, body=body, is_downto=is_downto, var_name=var_name):
                c_start = self.emit_expr(start)
                c_stop = self.emit_expr(stop)
                c_body = self.emit_expr(body)
                v = mangle_ident(var_name)
                stop_tmp = self.fresh_tmp("_stop")
                cmp_op = ">=" if is_downto else "<="
                step_op = "--" if is_downto else "++"
                inner = (
                    f"QInt {stop_tmp} = {c_stop};\n"
                    f"for (QInt {v} = {c_start}; {v} {cmp_op} {stop_tmp}; {v}{step_op}) {{\n"
                    f"{_indent(c_body + ';')}\n"
                    f"}}\n"
                    f"((void)0);"
                )
                return f"({{\n{_indent(inner)}\n}})"

            case TypedExit():
                return "break"

            case TypedApp():
                func_target, args = self._collect_app_args(expr)
                c_func = self.emit_expr(func_target)
                c_args = [self.emit_expr(a) for a in args]
                args_str = ", ".join(c_args)
                call_str = f"{c_func}({args_str})"
                if expr.type_val == OK_TYPE:
                    return f"({{ {call_str}; ((void)0); }})"
                return call_str

            case _:
                raise NotImplementedError(
                    f"C code generation for {expr.__class__.__name__} not implemented in Phase 4.2a"
                )

    def _emit_infix(self, left: TypedExpr, op: str, right: TypedExpr) -> str:
        c_left = self.emit_expr(left)
        c_right = self.emit_expr(right)

        # 1. Integer division and modulo with divide-by-zero check
        if op in ("/", "%", "mod"):
            c_op = "/" if op == "/" else "%"
            r_tmp = self.fresh_tmp("_r")
            l_tmp = self.fresh_tmp("_l")
            return (
                f"({{ QInt {l_tmp} = {c_left}; QInt {r_tmp} = {c_right}; "
                f"if ({r_tmp} == 0LL) quest_raise_divide_by_zero(); "
                f"{l_tmp} {c_op} {r_tmp}; }})"
            )

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

    def _emit_block(self, bindings: tuple[TypedBinding, ...], result: TypedExpr) -> str:
        stmts: list[str] = []
        for b in bindings:
            match b:
                case TypedLetValue(name=name, value=val, symbol=symbol):
                    c_type = qtype_to_c_type(symbol.type_val)
                    c_ident = mangle_ident(name)
                    c_val = self.emit_expr(val)
                    stmts.append(f"{c_type} {c_ident} = {c_val};")
                case TypedExprStmt(expr=inner):
                    stmts.append(f"{self.emit_expr(inner)};")
                case _:
                    pass
        res_c = self.emit_expr(result)
        stmts.append(res_c + ";")
        inner = "\n".join(stmts)
        return f"({{\n{_indent(inner)}\n}})"
