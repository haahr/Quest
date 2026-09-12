"""Quest Language Grammar Specification and AST Builders."""

from __future__ import annotations

from typing import Any

from quest.tokens import SourceMap, Token, TokenKind
from quest.parser import (
    Construct,
    MatchToken,
    Optional,
    Parser,
    Repeated,
    Rule,
    SyntaxTarget,
)
import quest.ast as ast


# ============================================================================
# 1. Top-Level Quest Syntax Targets (Non-Terminals)
# ============================================================================

PROGRAM = SyntaxTarget("Program")
PHRASE = SyntaxTarget("Phrase")
INTERFACE = SyntaxTarget("Interface")
MODULE = SyntaxTarget("Module")
LINKAGE = SyntaxTarget("Linkage")
IMPORT = SyntaxTarget("Import")
IMPORT_ITEM = SyntaxTarget("ImportItem")
IDE = SyntaxTarget("Ide")
IDE_LIST = SyntaxTarget("IdeList")

KIND = SyntaxTarget("Kind")
PRIMARY_KIND = SyntaxTarget("PrimaryKind")

TYPE = SyntaxTarget("Type")
POSTFIX_TYPE = SyntaxTarget("PostfixType")
POSTFIX_TYPE_OP = SyntaxTarget("PostfixTypeOp")
PRIMARY_TYPE = SyntaxTarget("PrimaryType")
TYPE_SIGNATURE = SyntaxTarget("TypeSignature")
VALUE_SIGNATURE = SyntaxTarget("ValueSignature")
OPTION_SIGNATURE = SyntaxTarget("OptionSignature")
SIGNATURE = SyntaxTarget("Signature")

VALUE = SyntaxTarget("Value")
POSTFIX_VALUE = SyntaxTarget("PostfixValue")
POSTFIX_OP = SyntaxTarget("PostfixOp")
PRIMARY_VALUE = SyntaxTarget("PrimaryValue")
INFIX_OP = SyntaxTarget("InfixOp")
BINDING = SyntaxTarget("Binding")
TYPE_BINDING = SyntaxTarget("TypeBinding")
VALUE_BINDING = SyntaxTarget("ValueBinding")

KIND_DECL = SyntaxTarget("KindDecl")
TYPE_DECL = SyntaxTarget("TypeDecl")
VALUE_DECL = SyntaxTarget("ValueDecl")
FORMAL_PARAM = SyntaxTarget("FormalParam")
TYPE_FORMAL = SyntaxTarget("TypeFormal")
QUANTIFIER = SyntaxTarget("Quantifier")

CASE_BRANCHES = SyntaxTarget("CaseBranches")
CASE_BRANCH = SyntaxTarget("CaseBranch")
INSPECT_BRANCHES = SyntaxTarget("InspectBranches")
INSPECT_BRANCH = SyntaxTarget("InspectBranch")
TRY_BRANCHES = SyntaxTarget("TryBranches")
TRY_BRANCH = SyntaxTarget("TryBranch")

HAS_TYPE = SyntaxTarget("HasType")
HAS_MUT_TYPE = SyntaxTarget("HasMutType")
HAS_KIND = SyntaxTarget("HasKind")

ALL_SYNTAX_TARGETS: tuple[SyntaxTarget, ...] = (
    PROGRAM, PHRASE, INTERFACE, MODULE, LINKAGE, IMPORT, IMPORT_ITEM, IDE, IDE_LIST,
    KIND, PRIMARY_KIND,
    TYPE, POSTFIX_TYPE, POSTFIX_TYPE_OP, PRIMARY_TYPE, TYPE_SIGNATURE, VALUE_SIGNATURE, OPTION_SIGNATURE, SIGNATURE,
    VALUE, POSTFIX_VALUE, POSTFIX_OP, PRIMARY_VALUE, INFIX_OP, BINDING, TYPE_BINDING, VALUE_BINDING,
    KIND_DECL, TYPE_DECL, VALUE_DECL, FORMAL_PARAM, TYPE_FORMAL, QUANTIFIER,
    CASE_BRANCHES, CASE_BRANCH, INSPECT_BRANCHES, INSPECT_BRANCH, TRY_BRANCHES, TRY_BRANCH,
    HAS_TYPE, HAS_MUT_TYPE, HAS_KIND,
)


# ============================================================================
# 2. Postfix Folding Helpers
# ============================================================================

def fold_type_postfix(primary: ast.Type, operations: tuple[Any, ...]) -> ast.Type:
    current = primary
    for operation in operations:
        operation_kind = operation[0]
        if operation_kind == "dot":
            if isinstance(current, ast.TypePath):
                current = ast.TypePath(path=current.path + (operation[1],), offset=current.offset)
            else:
                current = ast.TypePath(path=(operation[1],), offset=current.offset)
        elif operation_kind == "manifest":
            current = ast.TypeManifest(
                module_name=getattr(current, "path", ("_",))[-1],
                type_name=operation[1],
                offset=current.offset,
            )
        elif operation_kind == "app":
            args = operation[1] if isinstance(operation[1], tuple) else ((operation[1],) if operation[1] else ())
            current = ast.TypeApp(constructor=current, arguments=args, offset=current.offset)
    return current


def fold_value_postfix(primary: ast.Expr, operations: tuple[Any, ...]) -> ast.Expr:
    current = primary
    for operation in operations:
        operation_kind = operation[0]
        if operation_kind == "dot":
            current = ast.ExprSelect(target=current, field=operation[1], offset=current.offset)
        elif operation_kind == "question":
            current = ast.ExprVariantCheck(target=current, tag=operation[1], offset=current.offset)
        elif operation_kind == "bang":
            current = ast.ExprVariantAssert(target=current, tag=operation[1], offset=current.offset)
        elif operation_kind == "app":
            arguments_payload = operation[1]
            argument_nodes = (
                arguments_payload
                if isinstance(arguments_payload, tuple)
                else ((arguments_payload,) if arguments_payload else ())
            )
            current = ast.ExprApp(
                func=current,
                args=tuple(
                    argument.expr if isinstance(argument, ast.ExprStmt) else argument
                    for argument in argument_nodes
                ),
                offset=current.offset,
            )
        elif operation_kind == "index":
            current = ast.ExprIndex(target=current, index=operation[1], offset=current.offset)
        elif operation_kind == "listfix_rep":
            current = ast.ExprApp(
                func=current,
                args=(
                    ast.ExprArrayRep(
                        count=operation[1],
                        init_val=operation[2],
                        offset=operation[3],
                    ),
                ),
                offset=current.offset,
            )
        elif operation_kind == "listfix_elements":
            arr = _build_array_expr(operation[2], operation[1])
            current = ast.ExprApp(
                func=current,
                args=(arr,),
                offset=current.offset,
            )
    return current


def _build_array_expr(offset: int, bindings: tuple[Any, ...]) -> ast.ExprArray:
    """Builds an ExprArray from bindings, extracting leading element type if present."""
    bindings_tuple = (
        bindings
        if isinstance(bindings, tuple)
        else ((bindings,) if bindings else ())
    )
    elem_type = None
    raw_elements = list(bindings_tuple)
    if raw_elements and isinstance(raw_elements[0], ast.TypeArgument):
        elem_type = raw_elements.pop(0).type_val
    elements = tuple(
        item.expr if isinstance(item, ast.ExprStmt) else item
        for item in raw_elements
    )
    return ast.ExprArray(elements=elements, element_type=elem_type, offset=offset)


def _process_tuple_bindings(bindings: tuple[Any, ...]) -> tuple[Any, ...]:
    """Processes phrases inside a tuple constructor into tuple components."""
    result: list[Any] = []
    for item in bindings:
        match item:
            case ast.LetTypeBinding() | ast.DefTypeBinding():
                result.append(item)
            case ast.LetValueBinding(params=params) if params:
                fn_expr = ast.ExprFun(
                    params=params,
                    return_type=item.type_annot,
                    body=item.value,
                    offset=item.offset,
                )
                result.append(
                    ast.TupleBinding(
                        name=item.name,
                        value=fn_expr,
                        offset=item.offset,
                    )
                )
            case ast.LetValueBinding():
                result.append(
                    ast.TupleBinding(
                        name=item.name,
                        value=item.value,
                        type_annot=item.type_annot,
                        offset=item.offset,
                    )
                )
            case ast.ExprStmt(expr=expr):
                result.append(
                    ast.TupleBinding(
                        name=None,
                        value=expr,
                        offset=item.offset,
                    )
                )
            case ast.TupleBinding():
                result.append(item)
            case ast.Expr():
                result.append(
                    ast.TupleBinding(
                        name=None,
                        value=item,
                        offset=item.offset,
                    )
                )
            case _:
                result.append(
                    ast.TupleBinding(
                        name=getattr(item, "name", None),
                        value=getattr(item, "value", getattr(item, "expr", item)),
                        offset=getattr(item, "offset", 0),
                    )
                )
    return tuple(result)


def _build_option_payload(with_binding: Any, offset: int) -> Optional[ast.Expr]:
    """Processes phrases inside an option with clause into an expression payload."""
    if not with_binding or len(with_binding) < 2 or not with_binding[1]:
        return None
    items = with_binding[1]
    if isinstance(items, tuple):
        if len(items) == 1 and isinstance(items[0], ast.ExprStmt) and isinstance(items[0].expr, ast.ExprTuple):
            return items[0].expr
        fields = _process_tuple_bindings(items)
        return ast.ExprTuple(fields=fields, offset=offset)
    if isinstance(items, ast.Expr):
        return items
    return None



def _build_curried_field_sig(
    var_token: Optional[Token],
    out_token: Optional[Token],
    identifiers: tuple[str, ...],
    param_groups: tuple[Any, ...],
    colon_token: Token,
    return_type: ast.Type,
) -> tuple[ast.FieldSig, ...]:
    current_type: ast.Type = return_type
    for i in range(len(param_groups) - 1, -1, -1):
        grp_sigs = param_groups[i][1]
        current_type = ast.TypeAll(
            quantifiers=tuple(
                ast.Quantifier(
                    name=getattr(sig, "name", "_") or "_",
                    bound=(
                        ast.KindPower(bound=sig.type_sig)
                        if hasattr(sig, "type_sig") and sig.type_sig is not None
                        else getattr(sig, "bound", ast.KindType(offset=colon_token.offset))
                    ),
                    mode=getattr(sig, "mode", ast.ParamMode.VALUE),
                    offset=getattr(sig, "offset", colon_token.offset),
                )
                for sig in grp_sigs
            ),
            result_type=current_type,
            offset=colon_token.offset,
        )
    mode = (
        ast.ParamMode.VAR
        if var_token
        else (ast.ParamMode.OUT if out_token else ast.ParamMode.VALUE)
    )
    return tuple(
        ast.FieldSig(
            name=name,
            type_sig=current_type,
            mode=mode,
            offset=colon_token.offset,
        )
        for name in identifiers
    )


def _build_curried_fun_expr(
    param_groups: tuple[Any, ...],
    ret_type: Optional[tuple[Token, ast.Type]],
    val_expr: ast.Expr,
    offset: int,
) -> ast.Expr:
    return_type_node = ret_type[1] if ret_type else None
    if not param_groups:
        return ast.ExprFun(
            params=(),
            return_type=return_type_node,
            body=val_expr,
            type_params=(),
            offset=offset,
        )
    current_body: ast.Expr = val_expr
    for i in range(len(param_groups) - 1, -1, -1):
        grp_sigs = param_groups[i][1]
        type_params = tuple(sig for sig in grp_sigs if isinstance(sig, ast.TypeFormal))
        value_params = tuple(
            ast.FormalParam(name=sig.name, type_annot=sig.type_sig, mode=sig.mode, offset=sig.offset)
            for sig in grp_sigs
            if isinstance(sig, ast.FieldSig) and sig.name is not None
        )
        g_ret_type = return_type_node if i == len(param_groups) - 1 else None
        current_body = ast.ExprFun(
            params=value_params,
            return_type=g_ret_type,
            body=current_body,
            type_params=type_params,
            offset=offset,
        )
    return current_body


def _build_curried_value_decl(
    var_token: Optional[Token],
    ident_token: Token,
    param_groups: tuple[Any, ...],
    ret_type: Optional[tuple[Token, ast.Type]],
    val_expr: ast.Expr,
) -> ast.LetValueBinding:
    return_type_node = ret_type[1] if ret_type else None
    if not param_groups:
        return ast.LetValueBinding(
            name=ident_token.lexeme,
            value=val_expr,
            params=(),
            type_annot=return_type_node,
            is_var=bool(var_token),
            offset=ident_token.offset,
        )

    full_type_annot: Optional[ast.Type] = None
    if return_type_node is not None:
        full_type_annot = return_type_node
        for i in range(len(param_groups) - 1, -1, -1):
            grp_sigs = param_groups[i][1]
            full_type_annot = ast.TypeAll(
                quantifiers=tuple(
                    ast.Quantifier(
                        name=getattr(sig, "name", "_") or "_",
                        bound=(
                            ast.KindPower(bound=sig.type_sig)
                            if hasattr(sig, "type_sig") and sig.type_sig is not None
                            else getattr(sig, "bound", ast.KindType(offset=ident_token.offset))
                        ),
                        mode=getattr(sig, "mode", ast.ParamMode.VALUE),
                        offset=getattr(sig, "offset", ident_token.offset),
                    )
                    for sig in grp_sigs
                ),
                result_type=full_type_annot,
                offset=ident_token.offset,
            )

    current_body: ast.Expr = val_expr
    for i in range(len(param_groups) - 1, -1, -1):
        grp_sigs = param_groups[i][1]
        type_params = tuple(sig for sig in grp_sigs if isinstance(sig, ast.TypeFormal))
        value_params = tuple(
            ast.FormalParam(name=sig.name, type_annot=sig.type_sig, mode=sig.mode, offset=sig.offset)
            for sig in grp_sigs
            if isinstance(sig, ast.FieldSig) and sig.name is not None
        )
        g_ret_type = return_type_node if i == len(param_groups) - 1 else None

        if i == 0 and len(param_groups) == 1 and not type_params:
            return ast.LetValueBinding(
                name=ident_token.lexeme,
                value=current_body,
                params=value_params,
                type_annot=g_ret_type,
                is_var=bool(var_token),
                offset=ident_token.offset,
            )

        current_body = ast.ExprFun(
            params=value_params,
            return_type=g_ret_type,
            body=current_body,
            type_params=type_params,
            offset=ident_token.offset,
        )

    return ast.LetValueBinding(
        name=ident_token.lexeme,
        value=current_body,
        params=(),
        type_annot=full_type_annot,
        is_var=bool(var_token),
        offset=ident_token.offset,
    )



def _build_type_decl(
    ident_token: Token,
    param_groups: tuple[Any, ...],
    kind_bound: Optional[ast.Kind],
    type_node: ast.Type,
) -> ast.LetTypeBinding:
    all_formals: list[ast.TypeFormal] = []
    for grp in param_groups:
        sigs = grp[1]
        for sig in sigs:
            if isinstance(sig, ast.TypeFormal):
                all_formals.append(sig)
            elif isinstance(sig, ast.FieldSig):
                all_formals.append(
                    ast.TypeFormal(
                        name=sig.name or "_",
                        bound=ast.KindType(offset=sig.offset),
                        offset=sig.offset,
                    )
                )
    type_fun = ast.TypeFun(
        params=tuple(all_formals),
        result_kind=kind_bound,
        body=type_node,
        offset=ident_token.offset,
    )
    return ast.LetTypeBinding(
        name=ident_token.lexeme,
        type_val=type_fun,
        bound=None,
        offset=ident_token.offset,
    )


# ============================================================================
# 3. Quest Grammar Definition Builder
# ============================================================================

def build_quest_grammar() -> None:
    for target in ALL_SYNTAX_TARGETS:
        target.rules.clear()

    T = MatchToken
    TK = TokenKind
    Opt = Optional
    Rep = Repeated

    # ------------------------------------------------------------------------
    # Helper: Identifiers & Lists
    # ------------------------------------------------------------------------
    IDE.add_rule((T(TK.IDENT),), lambda ident_token: ident_token)
    IDE.add_rule((T(TK.SYMBOLIC_INFIX),), lambda token: token)

    # ide , IdeList
    IDE_LIST.add_rule(
        (IDE, T(TK.COMMA), IDE_LIST),
        lambda ident_token, comma_token, rest: (ident_token.lexeme,) + rest,
    )
    # ide
    IDE_LIST.add_rule((IDE,), lambda ident_token: (ident_token.lexeme,))

    # ------------------------------------------------------------------------
    # Kinds (Level 2)
    # ------------------------------------------------------------------------
    # ALL ( TypeSignature ) Kind
    KIND.add_rule(
        (T(TK.KW_ALL_KIND), T(TK.LPAREN), TYPE_SIGNATURE, T(TK.RPAREN), KIND),
        lambda all_token, left_paren, signature, right_paren, kind_body: ast.KindAll(
            param_name=getattr(
                signature[0] if isinstance(signature, tuple) and signature else signature,
                "name",
                "_",
            ),
            param_kind=getattr(
                signature[0] if isinstance(signature, tuple) and signature else signature,
                "bound",
                ast.KindType(offset=left_paren.offset),
            ),
            body_kind=kind_body,
            offset=all_token.offset,
        ),
    )
    # PRIMARY_KIND
    KIND.add_rule((PRIMARY_KIND,), lambda primary_kind: primary_kind)

    # TYPE
    PRIMARY_KIND.add_rule((T(TK.KW_TYPE),), lambda type_token: ast.KindType(offset=type_token.offset))
    # POWER ( Type )
    PRIMARY_KIND.add_rule(
        (T(TK.KW_POWER), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda power_token, left_paren, bound_type, right_paren: ast.KindPower(
            bound=bound_type, offset=power_token.offset
        ),
    )
    # ide _ ide (Manifest kind)
    PRIMARY_KIND.add_rule(
        (T(TK.IDENT), T(TK.UNDERSCORE), T(TK.IDENT)),
        lambda interface_ident, underscore, kind_ident: ast.KindManifest(
            interface_name=interface_ident.lexeme,
            kind_name=kind_ident.lexeme,
            offset=interface_ident.offset,
        ),
    )
    # ide (Kind identifier)
    PRIMARY_KIND.add_rule(
        (T(TK.IDENT),),
        lambda ident_token: ast.KindId(name=ident_token.lexeme, offset=ident_token.offset),
    )
    # { Kind }
    PRIMARY_KIND.add_rule(
        (T(TK.LBRACE), KIND, T(TK.RBRACE)),
        lambda left_brace, inner_kind, right_brace: inner_kind,
    )

    # ------------------------------------------------------------------------
    # Types (Level 1)
    # ------------------------------------------------------------------------
    # POSTFIX_TYPE [ InfixTail ]
    TYPE.add_rule(
        (POSTFIX_TYPE, Opt(T(TK.SYMBOLIC_INFIX), TYPE)),
        lambda left, tail: (
            ast.TypeInfix(left=left, op=tail[0].lexeme, right=tail[1], offset=left.offset)
            if tail
            else left
        ),
    )

    POSTFIX_TYPE.add_rule(
        (PRIMARY_TYPE, Rep(POSTFIX_TYPE_OP)),
        lambda primary_type, operations: fold_type_postfix(primary_type, operations),
    )

    POSTFIX_TYPE_OP.add_rule(
        (T(TK.DOT), T(TK.IDENT)),
        lambda dot_token, ident_token: ("dot", ident_token.lexeme),
    )
    POSTFIX_TYPE_OP.add_rule(
        (T(TK.LPAREN), Opt(TYPE_BINDING), T(TK.RPAREN)),
        lambda left_paren, binding_payload, right_paren: ("app", binding_payload),
    )
    POSTFIX_TYPE_OP.add_rule(
        (T(TK.UNDERSCORE), T(TK.IDENT)),
        lambda underscore, ident_token: ("manifest", ident_token.lexeme),
    )

    # All ( Signature ) Type
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_ALL), T(TK.LPAREN), SIGNATURE, T(TK.RPAREN), TYPE),
        lambda all_token, left_paren, signatures, right_paren, result_type: ast.TypeAll(
            quantifiers=tuple(
                ast.Quantifier(
                    name=getattr(sig, "name", "_") or "_",
                    bound=(
                        getattr(sig, "bound", None)
                        or (
                            ast.KindPower(bound=sig.type_sig, offset=sig.offset)
                            if hasattr(sig, "type_sig")
                            else ast.KindType(offset=left_paren.offset)
                        )
                    ),
                    mode=getattr(sig, "mode", ast.ParamMode.VALUE),
                    offset=getattr(sig, "offset", left_paren.offset),
                )
                for sig in signatures
            ),
            result_type=result_type,
            offset=all_token.offset,
        ),
    )
    # Tuple Signature end
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_TUPLE_TYPE), SIGNATURE, T(TK.KW_END)),
        lambda tuple_token, signatures, end_token: ast.TypeTuple(fields=signatures, offset=tuple_token.offset),
    )
    # Option OptionSignature end
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_OPTION_TYPE), OPTION_SIGNATURE, T(TK.KW_END)),
        lambda option_token, option_signatures, end_token: ast.TypeOption(
            variants=option_signatures, offset=option_token.offset
        ),
    )
    # Record ValueSignature end
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_RECORD_TYPE), VALUE_SIGNATURE, T(TK.KW_END)),
        lambda record_token, signatures, end_token: ast.TypeRecord(fields=signatures, offset=record_token.offset),
    )
    # Variant ValueSignature end
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_VARIANT_TYPE), VALUE_SIGNATURE, T(TK.KW_END)),
        lambda variant_token, signatures, end_token: ast.TypeVariant(
            fields=tuple(
                ast.VariantFieldSig(
                    tag=sig.name,
                    type_sig=sig.type_sig,
                    is_var=sig.is_var,
                    offset=sig.offset,
                )
                for sig in signatures
            ),
            offset=variant_token.offset,
        ),
    )
    # Auto [ide] HasKind with Signature end
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_AUTO_TYPE), Opt(T(TK.IDENT)), HAS_KIND, T(TK.KW_WITH), SIGNATURE, T(TK.KW_END)),
        lambda auto_token, ident_token, kind_bound, with_token, signatures, end_token: ast.TypeAuto(
            type_param=ident_token.lexeme if ident_token else None,
            kind_bound=kind_bound,
            signature=signatures,
            offset=auto_token.offset,
        ),
    )
    # Fun ( Signature ) [HasKind] Type
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_FUN_TYPE), T(TK.LPAREN), SIGNATURE, T(TK.RPAREN), Opt(HAS_KIND), TYPE),
        lambda fun_token, left_paren, signatures, right_paren, kind_bound, body_type: ast.TypeFun(
            params=tuple(
                ast.TypeFormal(
                    name=getattr(sig, "name", "_"),
                    bound=getattr(sig, "bound", ast.KindType(offset=left_paren.offset)),
                    offset=getattr(sig, "offset", left_paren.offset),
                )
                for sig in signatures
            ),
            result_kind=kind_bound,
            body=body_type,
            offset=fun_token.offset,
        ),
    )
    # Rec ( ide HasKind ) Type
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_REC_TYPE), T(TK.LPAREN), T(TK.IDENT), HAS_KIND, T(TK.RPAREN), TYPE),
        lambda rec_token, left_paren, ident_token, kind_bound, right_paren, body_type: ast.TypeRec(
            var_name=ident_token.lexeme,
            bound=kind_bound,
            body=body_type,
            offset=rec_token.offset,
        ),
    )
    # Array ( Type )
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_ARRAY_TYPE), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda array_token, left_paren, element_type, right_paren: ast.TypeArray(
            element_type=element_type, offset=array_token.offset
        ),
    )
    # Var ( Type )
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_VAR_TYPE), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda var_token, left_paren, element_type, right_paren: ast.TypeVar(
            element_type=element_type, offset=var_token.offset
        ),
    )
    # Out ( Type )
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_OUT_TYPE), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda out_token, left_paren, element_type, right_paren: ast.TypeOut(
            element_type=element_type, offset=out_token.offset
        ),
    )
    # ide _ ide (Manifest type)
    PRIMARY_TYPE.add_rule(
        (T(TK.IDENT), T(TK.UNDERSCORE), T(TK.IDENT)),
        lambda module_ident, underscore, type_ident: ast.TypeManifest(
            module_name=module_ident.lexeme,
            type_name=type_ident.lexeme,
            offset=module_ident.offset,
        ),
    )
    # ide (Named type: Int, Real, Bool, String, Char, Ok, Exception, or User Type)
    PRIMARY_TYPE.add_rule(
        (T(TK.IDENT),),
        lambda ident_token: ast.TypePath(path=(ident_token.lexeme,), offset=ident_token.offset),
    )
    PRIMARY_TYPE.add_rule(
        (T(TK.KW_EXCEPTION_TYPE),),
        lambda exc_token: ast.TypePath(path=("Exception",), offset=exc_token.offset),
    )
    PRIMARY_TYPE.add_rule(
        (T(TK.LBRACE), T(TK.SYMBOLIC_INFIX), T(TK.RBRACE)),
        lambda left_brace, token, right_brace: ast.TypePath(
            path=(token.lexeme,), offset=token.offset
        ),
    )
    PRIMARY_TYPE.add_rule(
        (T(TK.SYMBOLIC_INFIX), T(TK.LPAREN), Opt(TYPE_BINDING), T(TK.RPAREN)),
        lambda token, left_paren, binding_payload, right_paren: ast.TypeApp(
            constructor=ast.TypePath(path=(token.lexeme,), offset=token.offset),
            arguments=(
                binding_payload
                if isinstance(binding_payload, tuple)
                else ((binding_payload,) if binding_payload else ())
            ),
            offset=token.offset,
        ),
    )
    # { Type }
    PRIMARY_TYPE.add_rule(
        (T(TK.LBRACE), TYPE, T(TK.RBRACE)),
        lambda left_brace, inner_type, right_brace: inner_type,
    )

    # ------------------------------------------------------------------------
    # Signatures
    # ------------------------------------------------------------------------
    SIGNATURE.add_rule(
        (Rep(TYPE_SIGNATURE),),
        lambda signatures: tuple(
            item for sig in signatures for item in (sig if isinstance(sig, tuple) else (sig,))
        ),
    )

    # DEF KindDecl
    TYPE_SIGNATURE.add_rule(
        (T(TK.KW_DEF_KIND), KIND_DECL),
        lambda def_token, kind_declaration: kind_declaration,
    )
    # Def [Rec] TypeDecl
    TYPE_SIGNATURE.add_rule(
        (T(TK.KW_DEF), Opt(T(TK.KW_REC_TYPE)), TYPE_DECL),
        lambda def_token, rec_token, type_declaration: type_declaration,
    )
    # [var | out] IdeList {"(" Signature ")"} : Type (ValueFormals)
    TYPE_SIGNATURE.add_rule(
        (
            Opt(T(TK.KW_VAR)),
            Opt(T(TK.KW_OUT)),
            IDE_LIST,
            Rep(T(TK.LPAREN), SIGNATURE, T(TK.RPAREN)),
            T(TK.COLON),
            TYPE,
        ),
        lambda var_token, out_token, identifiers, param_groups, colon_token, return_type: (
            _build_curried_field_sig(
                var_token, out_token, identifiers, param_groups, colon_token, return_type
            )
        ),
    )
    # [var | out] IdeList HasType
    TYPE_SIGNATURE.add_rule(
        (Opt(T(TK.KW_VAR)), Opt(T(TK.KW_OUT)), IDE_LIST, HAS_TYPE),
        lambda var_token, out_token, identifiers, field_type: tuple(
            ast.FieldSig(
                name=name,
                type_sig=field_type,
                mode=(
                    ast.ParamMode.VAR
                    if var_token
                    else (ast.ParamMode.OUT if out_token else ast.ParamMode.VALUE)
                ),
                offset=field_type.offset,
            )
            for name in identifiers
        ),
    )
    # [IdeList] HasKind
    TYPE_SIGNATURE.add_rule(
        (Opt(IDE_LIST), HAS_KIND),
        lambda identifiers, kind_bound: tuple(
            ast.TypeFormal(name=name, bound=kind_bound, offset=kind_bound.offset)
            for name in (identifiers or ("_",))
        ),
    )
    # HasMutType (Anonymous tuple/signature field :Int or :Var(Int) or :Out(Int))
    TYPE_SIGNATURE.add_rule(
        (HAS_MUT_TYPE,),
        lambda mut_field: (mut_field,),
    )

    # [var] IdeList HasType (Record/Variant type signatures)
    VALUE_SIGNATURE.add_rule(
        (Rep(Opt(T(TK.KW_VAR)), IDE_LIST, HAS_TYPE, Opt(T(TK.SEMICOLON))),),
        lambda fields: tuple(
            ast.RecordFieldSig(name=name, type_sig=field[2], is_var=bool(field[0]), offset=field[2].offset)
            for field in fields
            for name in field[1]
        ),
    )

    OPTION_SIGNATURE.add_rule(
        (Rep(IDE_LIST, Opt(T(TK.KW_WITH), SIGNATURE, T(TK.KW_END))),),
        lambda options: tuple(
            ast.OptionFieldSig(
                tag=tag,
                payload_sig=opt[1][1] if opt[1] else (),
                offset=0,
            )
            for opt in options
            for tag in opt[0]
        ),
    )

    # ------------------------------------------------------------------------
    # Values and Expressions (Level 0)
    # ------------------------------------------------------------------------
    INFIX_OP.add_rule((T(TK.SYMBOLIC_INFIX),), lambda token: token.lexeme)
    INFIX_OP.add_rule((T(TK.KW_IS),), lambda token: "is")
    INFIX_OP.add_rule((T(TK.KW_ISNOT),), lambda token: "isnot")
    INFIX_OP.add_rule((T(TK.KW_ANDIF),), lambda token: "andif")
    INFIX_OP.add_rule((T(TK.KW_ORIF),), lambda token: "orif")
    INFIX_OP.add_rule((T(TK.ASSIGN),), lambda token: ":=")

    # POSTFIX_VALUE [ InfixOp Value ]
    VALUE.add_rule(
        (POSTFIX_VALUE, Opt(INFIX_OP, VALUE)),
        lambda left, tail: (
            ast.ExprInfix(left=left, op=tail[0], right=tail[1], offset=left.offset)
            if tail
            else left
        ),
    )

    POSTFIX_VALUE.add_rule(
        (PRIMARY_VALUE, Rep(POSTFIX_OP)),
        lambda primary_expression, operations: fold_value_postfix(primary_expression, operations),
    )

    POSTFIX_OP.add_rule(
        (T(TK.DOT), T(TK.IDENT)),
        lambda dot_token, ident_token: ("dot", ident_token.lexeme),
    )
    POSTFIX_OP.add_rule(
        (T(TK.QUESTION), T(TK.IDENT)),
        lambda question_token, ident_token: ("question", ident_token.lexeme),
    )
    POSTFIX_OP.add_rule(
        (T(TK.BANG), T(TK.IDENT)),
        lambda bang_token, ident_token: ("bang", ident_token.lexeme),
    )
    POSTFIX_OP.add_rule(
        (T(TK.LPAREN), Opt(BINDING), T(TK.RPAREN)),
        lambda left_paren, binding_payload, right_paren: ("app", binding_payload),
    )
    POSTFIX_OP.add_rule(
        (T(TK.LBRACKET), VALUE, T(TK.RBRACKET)),
        lambda left_bracket, index_expr, right_bracket: ("index", index_expr),
    )
    # Listfix application: f of(count init) and f of ... end
    POSTFIX_OP.add_rule(
        (T(TK.KW_OF), T(TK.LPAREN), VALUE, VALUE, T(TK.RPAREN)),
        lambda of_token, lp, cnt, init, rp: (
            "listfix_rep",
            cnt,
            init,
            of_token.offset,
        ),
    )
    POSTFIX_OP.add_rule(
        (T(TK.KW_OF), Opt(BINDING), T(TK.KW_END)),
        lambda of_token, bindings, end_token: (
            "listfix_elements",
            bindings or (),
            of_token.offset,
        ),
    )

    # Literals
    PRIMARY_VALUE.add_rule(
        (T(TK.INT_LIT),),
        lambda token: ast.ExprInt(value=token.value, lexeme=token.lexeme, offset=token.offset),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.REAL_LIT),),
        lambda token: ast.ExprReal(value=token.value, lexeme=token.lexeme, offset=token.offset),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.CHAR_LIT),),
        lambda token: ast.ExprChar(value=token.value, lexeme=token.lexeme, offset=token.offset),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.STRING_LIT),),
        lambda token: ast.ExprString(value=token.value, lexeme=token.lexeme, offset=token.offset),
    )
    PRIMARY_VALUE.add_rule((T(TK.KW_TRUE),), lambda token: ast.ExprBool(value=True, offset=token.offset))
    PRIMARY_VALUE.add_rule((T(TK.KW_FALSE),), lambda token: ast.ExprBool(value=False, offset=token.offset))
    PRIMARY_VALUE.add_rule((T(TK.KW_OK),), lambda token: ast.ExprOk(offset=token.offset))
    PRIMARY_VALUE.add_rule((T(TK.KW_EXIT),), lambda token: ast.ExprExit(offset=token.offset))

    # if Binding [then Binding] {elsif Binding [then Binding]} [else Binding] end
    PRIMARY_VALUE.add_rule(
        (
            T(TK.KW_IF),
            VALUE,
            Opt(T(TK.KW_THEN)),
            BINDING,
            Rep(T(TK.KW_ELSIF), VALUE, Opt(T(TK.KW_THEN)), BINDING),
            Opt(T(TK.KW_ELSE), BINDING),
            T(TK.KW_END),
        ),
        lambda if_token, condition, then_token, then_branch, elsifs, else_branch, end_token: ast.ExprIf(
            cond=condition,
            then_branch=(
                then_branch
                if not isinstance(then_branch, tuple)
                else (
                    then_branch[0]
                    if len(then_branch) == 1
                    else ast.ExprBlock(bindings=then_branch, offset=if_token.offset)
                )
            ),
            elsifs=tuple(
                (
                    branch[1],
                    branch[3]
                    if not isinstance(branch[3], tuple)
                    else (
                        branch[3][0]
                        if len(branch[3]) == 1
                        else ast.ExprBlock(bindings=branch[3], offset=branch[0].offset)
                    ),
                )
                for branch in elsifs
            )
            if elsifs
            else (),
            else_branch=(
                else_branch[1]
                if (else_branch and not isinstance(else_branch[1], tuple))
                else (
                    else_branch[1][0]
                    if (else_branch and len(else_branch[1]) == 1)
                    else (
                        ast.ExprBlock(bindings=else_branch[1], offset=if_token.offset)
                        if else_branch
                        else None
                    )
                )
            ),
            offset=if_token.offset,
        ),
    )

    # begin Binding end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_BEGIN), BINDING, T(TK.KW_END)),
        lambda begin_token, bindings, end_token: ast.ExprBlock(
            bindings=bindings if isinstance(bindings, tuple) else (bindings,),
            offset=begin_token.offset,
        ),
    )

    # loop Binding end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_LOOP), BINDING, T(TK.KW_END)),
        lambda loop_token, bindings, end_token: ast.ExprLoop(
            body=(
                bindings[0]
                if isinstance(bindings, tuple) and len(bindings) == 1
                else ast.ExprBlock(
                    bindings=bindings if isinstance(bindings, tuple) else (bindings,),
                    offset=loop_token.offset,
                )
            ),
            offset=loop_token.offset,
        ),
    )

    # while Binding do Binding end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_WHILE), VALUE, T(TK.KW_DO), BINDING, T(TK.KW_END)),
        lambda while_token, condition, do_token, body_bindings, end_token: ast.ExprWhile(
            cond=condition,
            body=(
                body_bindings[0]
                if isinstance(body_bindings, tuple) and len(body_bindings) == 1
                else ast.ExprBlock(
                    bindings=body_bindings if isinstance(body_bindings, tuple) else (body_bindings,),
                    offset=while_token.offset,
                )
            ),
            offset=while_token.offset,
        ),
    )

    # for ide = Binding (upto | downto) Binding do Binding end
    PRIMARY_VALUE.add_rule(
        (
            T(TK.KW_FOR),
            T(TK.IDENT),
            T(TK.EQUAL),
            VALUE,
            Opt(T(TK.KW_UPTO)),
            Opt(T(TK.KW_DOWNTO)),
            VALUE,
            T(TK.KW_DO),
            BINDING,
            T(TK.KW_END),
        ),
        (
            lambda for_token, ident_token, equal_token, start_val, upto_token, downto_token,
            stop_val, do_token, body_bindings, end_token: (
                ast.ExprFor(
                    var_name=ident_token.lexeme,
                    start=start_val,
                    is_downto=bool(downto_token),
                    stop=stop_val,
                    body=(
                        body_bindings[0]
                        if isinstance(body_bindings, tuple) and len(body_bindings) == 1
                        else ast.ExprBlock(
                            bindings=body_bindings if isinstance(body_bindings, tuple) else (body_bindings,),
                            offset=for_token.offset,
                        )
                    ),
                    offset=for_token.offset,
                )
            )
        ),
    )

    # fun { ( Signature ) } [: Type] Value
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_FUN), Rep(T(TK.LPAREN), SIGNATURE, T(TK.RPAREN)), Opt(T(TK.COLON), TYPE), VALUE),
        lambda fun_token, param_groups, return_type, body_expr: _build_curried_fun_expr(
            param_groups, return_type, body_expr, fun_token.offset
        ),
    )

    # tuple Binding end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_TUPLE), BINDING, T(TK.KW_END)),
        lambda tuple_token, bindings, end_token: ast.ExprTuple(
            fields=_process_tuple_bindings(bindings),
            offset=tuple_token.offset,
        ),
    )

    # record ValueBinding end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_RECORD), VALUE_BINDING, T(TK.KW_END)),
        lambda record_token, bindings, end_token: ast.ExprRecord(
            fields=bindings if isinstance(bindings, tuple) else (bindings,),
            offset=record_token.offset,
        ),
    )

    # array of ( Binding end | ( Value Value ) )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_ARRAY), T(TK.KW_OF), T(TK.LPAREN), VALUE, VALUE, T(TK.RPAREN)),
        lambda array_token, of_token, left_paren, count_expr, init_expr, right_paren: ast.ExprArrayRep(
            count=count_expr,
            init_val=init_expr,
            offset=array_token.offset,
        ),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_ARRAY), T(TK.KW_OF), Opt(BINDING), T(TK.KW_END)),
        lambda array_token, of_token, bindings, end_token: (
            _build_array_expr(array_token.offset, bindings or ())
        ),
    )

    # option (ide | ordinal(Value)) of Type [with Binding] end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_OPTION), IDE, T(TK.KW_OF), TYPE, Opt(T(TK.KW_WITH), BINDING), T(TK.KW_END)),
        lambda option_token, ide, of_token, option_type, with_binding, end_token: ast.ExprOption(
            tag=ide.lexeme if hasattr(ide, "lexeme") else str(ide),
            option_type=option_type,
            payload=_build_option_payload(with_binding, option_token.offset),
            offset=option_token.offset,
        ),
    )
    PRIMARY_VALUE.add_rule(
        (
            T(TK.KW_OPTION),
            T(TK.KW_ORDINAL),
            T(TK.LPAREN),
            VALUE,
            T(TK.RPAREN),
            T(TK.KW_OF),
            TYPE,
            Opt(T(TK.KW_WITH), BINDING),
            T(TK.KW_END),
        ),
        lambda option_token, ord_token, lp, ord_val, rp, of_token, option_type, with_binding, end_token: ast.ExprOption(
            tag=None,
            option_type=option_type,
            payload=_build_option_payload(with_binding, option_token.offset),
            ordinal_expr=ord_val,
            offset=option_token.offset,
        ),
    )

    # variant [var] ide of Type [with Value] end
    PRIMARY_VALUE.add_rule(
        (
            T(TK.KW_VARIANT),
            Opt(T(TK.KW_VAR)),
            T(TK.IDENT),
            T(TK.KW_OF),
            TYPE,
            Opt(T(TK.KW_WITH), VALUE),
            T(TK.KW_END),
        ),
        lambda variant_token, var_token, ident_token, of_token, variant_type, with_val, end_token: ast.ExprVariant(
            tag=ident_token.lexeme,
            variant_type=variant_type,
            is_var=bool(var_token),
            payload=with_val[1] if with_val else None,
            offset=variant_token.offset,
        ),
    )

    # case Binding CaseBranches end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_CASE), VALUE, CASE_BRANCHES, T(TK.KW_END)),
        lambda case_token, target_expr, branches, end_token: ast.ExprCase(
            target=target_expr,
            branches=branches[0],
            else_branch=branches[1],
            offset=case_token.offset,
        ),
    )

    # inspect Binding InspectBranches end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_INSPECT), VALUE, INSPECT_BRANCHES, T(TK.KW_END)),
        lambda inspect_token, target_expr, branches, end_token: ast.ExprInspect(
            target=target_expr,
            branches=branches[0],
            else_branch=branches[1],
            offset=inspect_token.offset,
        ),
    )

    # exception ide [: Type] end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_EXCEPTION), T(TK.IDENT), Opt(T(TK.COLON), TYPE), T(TK.KW_END)),
        lambda exc_token, ident_token, type_annot, end_token: ast.ExprException(
            name=ident_token.lexeme,
            type_annot=type_annot[1] if type_annot else None,
            offset=exc_token.offset,
        ),
    )

    # raise Value [with Value] [as Type] end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_RAISE), VALUE, Opt(T(TK.KW_WITH), VALUE), Opt(T(TK.KW_AS), TYPE), T(TK.KW_END)),
        lambda raise_token, exc_expr, with_val, as_type, end_token: ast.ExprRaise(
            exc=exc_expr,
            payload=with_val[1] if with_val else None,
            as_type=as_type[1] if as_type else None,
            offset=raise_token.offset,
        ),
    )

    # try Binding TryBranches end
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_TRY), BINDING, TRY_BRANCHES, T(TK.KW_END)),
        lambda try_token, body_bindings, branches, end_token: ast.ExprTry(
            body=(
                body_bindings[0]
                if isinstance(body_bindings, tuple) and len(body_bindings) == 1
                else ast.ExprBlock(
                    bindings=body_bindings if isinstance(body_bindings, tuple) else (body_bindings,),
                    offset=try_token.offset,
                )
            ),
            branches=branches[0],
            else_branch=branches[1],
            offset=try_token.offset,
        ),
    )

    # var ( Value )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_VAR), T(TK.LPAREN), VALUE, T(TK.RPAREN)),
        lambda var_token, left_paren, cell_value, right_paren: ast.ExprVarCell(
            value=cell_value, offset=var_token.offset
        ),
    )

    # @ Value
    PRIMARY_VALUE.add_rule(
        (T(TK.AT), VALUE),
        lambda at_token, target_expr: ast.ExprDerefCell(target=target_expr, offset=at_token.offset),
    )

    # ide (Identifier)
    PRIMARY_VALUE.add_rule(
        (T(TK.IDENT),),
        lambda ident_token: ast.ExprId(name=ident_token.lexeme, offset=ident_token.offset),
    )
    # { infix } (Stand-alone infix identifier, e.g. {+})
    PRIMARY_VALUE.add_rule(
        (T(TK.LBRACE), T(TK.SYMBOLIC_INFIX), T(TK.RBRACE)),
        lambda left_brace, token, right_brace: ast.ExprId(
            name=token.lexeme, offset=token.offset
        ),
    )
    # prefix infix application: +(x y)
    PRIMARY_VALUE.add_rule(
        (T(TK.SYMBOLIC_INFIX), T(TK.LPAREN), Opt(BINDING), T(TK.RPAREN)),
        lambda token, left_paren, binding_payload, right_paren: ast.ExprApp(
            func=ast.ExprId(name=token.lexeme, offset=token.offset),
            args=tuple(
                argument.expr if isinstance(argument, ast.ExprStmt) else argument
                for argument in (
                    binding_payload
                    if isinstance(binding_payload, tuple)
                    else ((binding_payload,) if binding_payload else ())
                )
            ),
            offset=token.offset,
        ),
    )

    # { Value }
    PRIMARY_VALUE.add_rule(
        (T(TK.LBRACE), VALUE, T(TK.RBRACE)),
        lambda left_brace, inner_expr, right_brace: inner_expr,
    )

    # Monadic Operators: not, extent, ordinal (Cardelli §4.2, §4.3, §4.5)
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_NOT), POSTFIX_VALUE),
        lambda tok, val: ast.ExprApp(
            func=ast.ExprId(name="not", offset=tok.offset),
            args=(val,),
            offset=tok.offset,
        ),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_NOT),),
        lambda tok: ast.ExprId(name="not", offset=tok.offset),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_EXTENT), POSTFIX_VALUE),
        lambda tok, val: ast.ExprApp(
            func=ast.ExprId(name="extent", offset=tok.offset),
            args=(val,),
            offset=tok.offset,
        ),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_EXTENT),),
        lambda tok: ast.ExprId(name="extent", offset=tok.offset),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_ORDINAL), POSTFIX_VALUE),
        lambda tok, val: ast.ExprApp(
            func=ast.ExprId(name="ordinal", offset=tok.offset),
            args=(val,),
            offset=tok.offset,
        ),
    )
    PRIMARY_VALUE.add_rule(
        (T(TK.KW_ORDINAL),),
        lambda tok: ast.ExprId(name="ordinal", offset=tok.offset),
    )

    # ------------------------------------------------------------------------
    # Bindings (Inside Blocks, Tuples, Phrases)
    # ------------------------------------------------------------------------
    BINDING.add_rule(
        (Rep(PHRASE, Opt(T(TK.SEMICOLON))),),
        lambda phrases: tuple(phrase[0] for phrase in phrases) if phrases else (),
    )

    TYPE_BINDING.add_rule(
        (Rep(TYPE),),
        lambda types: types if isinstance(types, tuple) else (types,),
    )

    VALUE_BINDING.add_rule(
        (Rep(Opt(T(TK.KW_VAR)), T(TK.IDENT), T(TK.EQUAL), VALUE, Opt(T(TK.SEMICOLON))),),
        lambda items: tuple(
            ast.RecordBinding(
                name=item[1].lexeme,
                value=item[3],
                is_var=bool(item[0]),
                offset=item[1].offset,
            )
            for item in items
        ),
    )

    # ------------------------------------------------------------------------
    # Declarations
    # ------------------------------------------------------------------------
    KIND_DECL.add_rule(
        (IDE, T(TK.EQUAL), KIND),
        lambda ident_token, equal_token, kind_node: ast.DefKindBinding(
            name=ident_token.lexeme, kind_val=kind_node, offset=ident_token.offset
        ),
    )

    TYPE_DECL.add_rule(
        (IDE, Rep(T(TK.LPAREN), SIGNATURE, T(TK.RPAREN)), Opt(HAS_KIND), T(TK.EQUAL), TYPE),
        lambda ident_token, param_groups, kind_bound, equal_token, type_node: (
            _build_type_decl(ident_token, param_groups, kind_bound, type_node)
            if param_groups
            else ast.LetTypeBinding(
                name=ident_token.lexeme,
                type_val=type_node,
                bound=kind_bound,
                offset=ident_token.offset,
            )
        ),
    )

    VALUE_DECL.add_rule(
        (
            Opt(T(TK.KW_VAR)),
            IDE,
            Rep(T(TK.LPAREN), SIGNATURE, T(TK.RPAREN)),
            Opt(T(TK.COLON), TYPE),
            T(TK.EQUAL),
            VALUE,
        ),
        lambda var_token, ident_token, param_groups, ret_type, equal_token, val_expr: (
            _build_curried_value_decl(var_token, ident_token, param_groups, ret_type, val_expr)
        ),
    )

    # ------------------------------------------------------------------------
    # Case, Inspect, Try Branches
    # ------------------------------------------------------------------------
    CASE_BRANCHES.add_rule(
        (
            Rep(
                T(TK.KW_WHEN),
                IDE_LIST,
                Opt(T(TK.KW_WITH), T(TK.IDENT), Opt(T(TK.COLON), TYPE)),
                T(TK.KW_THEN),
                BINDING,
            ),
            Opt(T(TK.KW_ELSE), BINDING),
        ),
        lambda branches, else_branch: (
            tuple(
                ast.CaseBranch(
                    tags=branch[1],
                    binder=branch[2][1].lexeme if branch[2] else None,
                    binder_type=branch[2][2][1] if branch[2] and branch[2][2] else None,
                    body=(
                        branch[4][0]
                        if isinstance(branch[4], tuple) and len(branch[4]) == 1
                        else ast.ExprBlock(
                            bindings=branch[4] if isinstance(branch[4], tuple) else (branch[4],),
                            offset=branch[0].offset,
                        )
                    ),
                    offset=branch[0].offset,
                )
                for branch in branches
            ),
            (
                else_branch[1][0]
                if (else_branch and isinstance(else_branch[1], tuple) and len(else_branch[1]) == 1)
                else (
                    ast.ExprBlock(
                        bindings=else_branch[1] if isinstance(else_branch[1], tuple) else (else_branch[1],),
                        offset=0,
                    )
                    if else_branch
                    else None
                )
            ),
        ),
    )

    INSPECT_BRANCHES.add_rule(
        (
            Rep(
                T(TK.KW_WHEN),
                TYPE,
                Opt(T(TK.KW_WITH), IDE_LIST, Opt(T(TK.COLON), TYPE)),
                T(TK.KW_THEN),
                BINDING,
            ),
            Opt(T(TK.KW_ELSE), BINDING),
        ),
        lambda branches, else_branch: (
            tuple(
                ast.InspectBranch(
                    match_type=branch[1],
                    binders=(
                        tuple((name, branch[2][2][1] if branch[2][2] else None) for name in branch[2][1])
                        if branch[2]
                        else ()
                    ),
                    body=(
                        branch[4][0]
                        if isinstance(branch[4], tuple) and len(branch[4]) == 1
                        else ast.ExprBlock(
                            bindings=branch[4] if isinstance(branch[4], tuple) else (branch[4],),
                            offset=branch[0].offset,
                        )
                    ),
                    offset=branch[0].offset,
                )
                for branch in branches
            ),
            (
                else_branch[1][0]
                if (else_branch and isinstance(else_branch[1], tuple) and len(else_branch[1]) == 1)
                else (
                    ast.ExprBlock(
                        bindings=else_branch[1] if isinstance(else_branch[1], tuple) else (else_branch[1],),
                        offset=0,
                    )
                    if else_branch
                    else None
                )
            ),
        ),
    )

    TRY_BRANCHES.add_rule(
        (
            Rep(
                T(TK.KW_WHEN),
                VALUE,
                Opt(T(TK.KW_WITH), T(TK.IDENT), Opt(T(TK.COLON), TYPE)),
                T(TK.KW_THEN),
                BINDING,
            ),
            Opt(T(TK.KW_ELSE), BINDING),
        ),
        lambda branches, else_branch: (
            tuple(
                ast.TryBranch(
                    exc_pattern=branch[1],
                    binder=branch[2][1].lexeme if branch[2] else None,
                    binder_type=branch[2][2][1] if branch[2] and branch[2][2] else None,
                    body=(
                        branch[4][0]
                        if isinstance(branch[4], tuple) and len(branch[4]) == 1
                        else ast.ExprBlock(
                            bindings=branch[4] if isinstance(branch[4], tuple) else (branch[4],),
                            offset=branch[0].offset,
                        )
                    ),
                    offset=branch[0].offset,
                )
                for branch in branches
            ),
            (
                else_branch[1][0]
                if (else_branch and isinstance(else_branch[1], tuple) and len(else_branch[1]) == 1)
                else (
                    ast.ExprBlock(
                        bindings=else_branch[1] if isinstance(else_branch[1], tuple) else (else_branch[1],),
                        offset=0,
                    )
                    if else_branch
                    else None
                )
            ),
        ),
    )

    # ------------------------------------------------------------------------
    # HasType / HasMutType / HasKind
    # ------------------------------------------------------------------------
    HAS_TYPE.add_rule((T(TK.COLON), TYPE), lambda colon_token, type_node: type_node)

    # : Var ( Type )
    HAS_MUT_TYPE.add_rule(
        (T(TK.COLON), T(TK.KW_VAR_TYPE), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda colon, var_tok, lp, type_node, rp: ast.FieldSig(
            name=None,
            type_sig=type_node,
            mode=ast.ParamMode.VAR,
            offset=colon.offset,
        ),
    )
    # : Out ( Type )
    HAS_MUT_TYPE.add_rule(
        (T(TK.COLON), T(TK.KW_OUT_TYPE), T(TK.LPAREN), TYPE, T(TK.RPAREN)),
        lambda colon, out_tok, lp, type_node, rp: ast.FieldSig(
            name=None,
            type_sig=type_node,
            mode=ast.ParamMode.OUT,
            offset=colon.offset,
        ),
    )
    # var : Type
    HAS_MUT_TYPE.add_rule(
        (T(TK.KW_VAR), T(TK.COLON), TYPE),
        lambda var_tok, colon, type_node: ast.FieldSig(
            name=None,
            type_sig=type_node,
            mode=ast.ParamMode.VAR,
            offset=var_tok.offset,
        ),
    )
    # out : Type
    HAS_MUT_TYPE.add_rule(
        (T(TK.KW_OUT), T(TK.COLON), TYPE),
        lambda out_tok, colon, type_node: ast.FieldSig(
            name=None,
            type_sig=type_node,
            mode=ast.ParamMode.OUT,
            offset=out_tok.offset,
        ),
    )
    # : Type
    HAS_MUT_TYPE.add_rule(
        (T(TK.COLON), TYPE),
        lambda colon, type_node: ast.FieldSig(
            name=None,
            type_sig=type_node,
            mode=ast.ParamMode.VALUE,
            offset=colon.offset,
        ),
    )

    HAS_KIND.add_rule(
        (T(TK.SUBTYPE), TYPE),
        lambda subtype_token, bound_type: ast.KindPower(bound=bound_type, offset=subtype_token.offset),
    )
    HAS_KIND.add_rule((T(TK.COLON_COLON), KIND), lambda colon_colon, kind_node: kind_node)

    # ------------------------------------------------------------------------
    # Phrases & Program (Top Level)
    # ------------------------------------------------------------------------
    # Interface
    PHRASE.add_rule(
        (
            Opt(T(TK.KW_UNSOUND)),
            T(TK.KW_INTERFACE),
            T(TK.IDENT),
            Opt(T(TK.KW_IMPORT), IMPORT),
            T(TK.KW_EXPORT),
            SIGNATURE,
            T(TK.KW_END),
        ),
        lambda unsound, if_token, ident_token, imports_seq, export_token, signatures, end_token: ast.InterfaceDecl(
            name=ident_token.lexeme,
            signatures=signatures if isinstance(signatures, tuple) else (signatures,),
            imports=imports_seq[1] if imports_seq else (),
            is_unsound=bool(unsound),
            offset=if_token.offset,
        ),
    )
    # Module
    PHRASE.add_rule(
        (
            Opt(T(TK.KW_UNSOUND)),
            T(TK.KW_MODULE),
            T(TK.IDENT),
            T(TK.COLON),
            T(TK.IDENT),
            Opt(T(TK.KW_IMPORT), IMPORT),
            T(TK.KW_EXPORT),
            BINDING,
            T(TK.KW_END),
        ),
        (
            lambda unsound, module_token, ident_token, colon_token, interface_ident,
            imports_seq, export_token, bindings, end_token: (
                ast.ModuleDecl(
                    name=ident_token.lexeme,
                    interface_name=interface_ident.lexeme,
                    bindings=bindings if isinstance(bindings, tuple) else (bindings,),
                    imports=imports_seq[1] if imports_seq else (),
                    is_unsound=bool(unsound),
                    offset=module_token.offset,
                )
            )
        ),
    )
    # Let [Rec] TypeDecl
    PHRASE.add_rule(
        (T(TK.KW_LET_TYPE), Opt(T(TK.KW_REC_TYPE)), TYPE_DECL),
        lambda let_token, rec_token, type_declaration: ast.LetTypeBinding(
            name=type_declaration.name,
            type_val=type_declaration.type_val,
            params=type_declaration.params,
            bound=type_declaration.bound,
            is_rec=bool(rec_token),
            offset=let_token.offset,
        ),
    )
    # let [rec] ValueDecl
    PHRASE.add_rule(
        (T(TK.KW_LET), Opt(T(TK.KW_REC)), VALUE_DECL),
        lambda let_token, rec_token, val_declaration: ast.LetValueBinding(
            name=val_declaration.name,
            value=val_declaration.value,
            params=val_declaration.params,
            type_annot=val_declaration.type_annot,
            is_rec=bool(rec_token),
            is_var=val_declaration.is_var,
            offset=let_token.offset,
        ),
    )
    # DEF KindDecl
    PHRASE.add_rule(
        (T(TK.KW_DEF_KIND), KIND_DECL),
        lambda def_token, kind_declaration: kind_declaration,
    )
    # Def [Rec] TypeDecl
    PHRASE.add_rule(
        (T(TK.KW_DEF), Opt(T(TK.KW_REC_TYPE)), TYPE_DECL),
        lambda def_token, rec_token, type_declaration: ast.DefTypeBinding(
            name=type_declaration.name,
            type_val=type_declaration.type_val,
            params=type_declaration.params,
            bound=type_declaration.bound,
            is_rec=bool(rec_token),
            offset=def_token.offset,
        ),
    )
    # : Type (TypeArgument in call bindings / phrases)
    PHRASE.add_rule(
        (T(TK.COLON), TYPE),
        lambda colon_token, type_node: ast.TypeArgument(
            type_val=type_node, offset=colon_token.offset
        ),
    )
    # :: Kind (KindArgument in call bindings / phrases)
    PHRASE.add_rule(
        (T(TK.COLON_COLON), KIND),
        lambda colon_token, kind_node: ast.KindArgument(
            kind_val=kind_node, offset=colon_token.offset
        ),
    )
    # Top-level Value Expression
    PHRASE.add_rule(
        (VALUE,),
        lambda value_expr: (
            ast.ExprStmt(expr=value_expr, offset=value_expr.offset)
            if isinstance(value_expr, ast.Expr)
            else value_expr
        ),
    )

    # import ImportList
    LINKAGE.add_rule(
        (T(TK.KW_IMPORT), IMPORT),
        lambda import_token, items: ast.ImportPhrase(items=items, offset=import_token.offset),
    )
    PHRASE.add_rule((LINKAGE,), lambda linkage: linkage)

    IMPORT_ITEM.add_rule(
        (IDE_LIST, T(TK.COLON), T(TK.IDENT)),
        lambda names, colon_token, iface_token: ast.ImportItem(
            names=names,
            interface_name=iface_token.lexeme,
            offset=colon_token.offset,
        ),
    )
    IMPORT_ITEM.add_rule(
        (T(TK.COLON), T(TK.IDENT)),
        lambda colon_token, iface_token: ast.ImportItem(
            names=(),
            interface_name=iface_token.lexeme,
            offset=colon_token.offset,
        ),
    )

    IMPORT.add_rule(
        (Rep(IMPORT_ITEM, Opt(T(TK.SEMICOLON))),),
        lambda items: tuple(item[0] for item in items),
    )

    PROGRAM.add_rule(
        (Rep(PHRASE, Opt(T(TK.SEMICOLON))),),
        lambda phrases: ast.Program(
            phrases=tuple(phrase[0] for phrase in phrases),
            offset=phrases[0][0].offset if phrases else 0,
        ),
    )


# Initialize the Quest grammar rules at module load time
build_quest_grammar()


def resolve_syntax_target(target: SyntaxTarget | str | None) -> SyntaxTarget:
    """Resolves a start symbol string or SyntaxTarget to a grammar SyntaxTarget."""
    if target is None:
        return PROGRAM
    if isinstance(target, SyntaxTarget):
        return target
    if isinstance(target, str):
        mapping = {
            "program": PROGRAM,
            "phrase": PHRASE,
            "type": TYPE,
            "kind": KIND,
            "expr": VALUE,
            "value": VALUE,
            "signature": SIGNATURE,
        }
        resolved = mapping.get(target.lower())
        if resolved is not None:
            return resolved
        available = sorted(mapping.keys())
        raise ValueError(f"Unknown start target '{target}'. Available: {available}")
    raise TypeError(f"Expected str or SyntaxTarget, got {type(target).__name__}")


def parse_quest_program(
    tokens: list[Token],
    source_map: SourceMap,
    target: SyntaxTarget | str | None = None,
) -> Any:
    """Convenience helper to parse tokens using the standard Quest grammar starting at target."""
    syntax_target = resolve_syntax_target(target)
    parser = Parser(tokens, source_map)
    return parser.parse(syntax_target)
