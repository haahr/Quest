"""Quest Abstract Syntax Tree (AST) definitions and S-Expression Pretty-Printer."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, KW_ONLY
from enum import Enum, auto
from typing import Any, Optional, Union


# ============================================================================
# 1. Base Node and Parameter Modes
# ============================================================================

@dataclass(frozen=True)
class ASTNode:
    """Root base class for all Quest AST nodes."""
    _: KW_ONLY
    offset: int = 0


class ParamMode(Enum):
    VALUE = auto()
    VAR = auto()
    OUT = auto()


@dataclass(frozen=True)
class FormalParam(ASTNode):
    """Value-level function parameter: [var | out] x : T"""
    name: str
    type_annot: Optional[Type] = None
    mode: ParamMode = ParamMode.VALUE


@dataclass(frozen=True)
class TypeFormal(ASTNode):
    """Type-level parameter: X <: B or X :: K"""
    name: str
    bound: Kind


@dataclass(frozen=True)
class Quantifier(ASTNode):
    """Universal/existential quantifier: X <: B or X :: K"""
    name: str
    bound: Kind


# ============================================================================
# 2. Level 2: Kinds
# ============================================================================

@dataclass(frozen=True)
class Kind(ASTNode):
    """Base class for Level 2 kind terms."""
    pass


@dataclass(frozen=True)
class KindType(Kind):
    """TYPE — the base kind of all ground types."""
    pass


@dataclass(frozen=True)
class KindPower(Kind):
    """POWER(T) — the kind of all subtypes of type T."""
    bound: Type


@dataclass(frozen=True)
class KindAll(Kind):
    """ALL(X::K) K' — operator kind universal quantifier."""
    param_name: str
    param_kind: Kind
    body_kind: Kind


@dataclass(frozen=True)
class KindId(Kind):
    """User-defined or aliased kind identifier."""
    name: str


@dataclass(frozen=True)
class KindManifest(Kind):
    """Interface manifest kind path, e.g. I_K."""
    interface_name: str
    kind_name: str


# ============================================================================
# 3. Level 1: Types and Type Operators
# ============================================================================

@dataclass(frozen=True)
class Type(ASTNode):
    """Base class for Level 1 type terms and type operators."""
    pass


@dataclass(frozen=True)
class TypePath(Type):
    """Named type or dot-projection path: e.g. 'Int', 'Point', 'Mod.T'."""
    path: tuple[str, ...]


@dataclass(frozen=True)
class TypeAll(Type):
    """All(X <: B, Y :: K) T — universal type quantifier."""
    quantifiers: tuple[Quantifier, ...]
    result_type: Type


@dataclass(frozen=True)
class FieldSig(ASTNode):
    """Field in a tuple or auto signature: [var | out] x : T"""
    name: str
    type_sig: Type
    mode: ParamMode = ParamMode.VALUE


@dataclass(frozen=True)
class TypeTuple(Type):
    """Tuple x:Int, y:Real end — ordered dependent tuple signature."""
    fields: tuple[FieldSig, ...]


@dataclass(frozen=True)
class RecordFieldSig(ASTNode):
    """Field in a record signature: [var] x : T"""
    name: str
    type_sig: Type
    is_var: bool = False


@dataclass(frozen=True)
class TypeRecord(Type):
    """Record x:Int, y:Real end — unordered record type."""
    fields: tuple[RecordFieldSig, ...]


@dataclass(frozen=True)
class OptionFieldSig(ASTNode):
    """Variant in an option signature: tag [with fields...]"""
    tag: str
    payload_sig: tuple[FieldSig, ...] = ()


@dataclass(frozen=True)
class TypeOption(Type):
    """Option red, green, blue with val:Int end — tagged union / option type."""
    variants: tuple[OptionFieldSig, ...]


@dataclass(frozen=True)
class VariantFieldSig(ASTNode):
    """Field in a variant signature: [var] tag : T"""
    tag: str
    type_sig: Type
    is_var: bool = False


@dataclass(frozen=True)
class TypeVariant(Type):
    """Variant ok:Int, err:String end — unordered variant type."""
    fields: tuple[VariantFieldSig, ...]


@dataclass(frozen=True)
class TypeAuto(Type):
    """Auto X::K with x:T end — existential / automorphic dynamic type."""
    type_param: Optional[str]
    kind_bound: Kind
    signature: tuple[FieldSig, ...]


@dataclass(frozen=True)
class TypeFun(Type):
    """Fun(X::K, Y<:B) T — higher-order compile-time type operator."""
    params: tuple[TypeFormal, ...]
    result_kind: Optional[Kind]
    body: Type


@dataclass(frozen=True)
class TypeRec(Type):
    """Rec(X <: B) T — recursive type constructor."""
    var_name: str
    bound: Kind
    body: Type


@dataclass(frozen=True)
class TypeApp(Type):
    """T(A, B) — type operator application."""
    constructor: Type
    arguments: tuple[Type, ...]


@dataclass(frozen=True)
class TypeInfix(Type):
    """T -> U, T /\ U — infix type operator."""
    left: Type
    op: str
    right: Type


@dataclass(frozen=True)
class TypeArray(Type):
    """Array(T) — built-in array type."""
    element_type: Type


@dataclass(frozen=True)
class TypeVar(Type):
    """Var(T) — mutable reference cell type."""
    element_type: Type


@dataclass(frozen=True)
class TypeOut(Type):
    """Out(T) — contravariant output parameter mode."""
    element_type: Type


@dataclass(frozen=True)
class TypeManifest(Type):
    """M_T — manifest type extraction across interfaces."""
    module_name: str
    type_name: str


# ============================================================================
# 4. Level 0: Values and Expressions
# ============================================================================

@dataclass(frozen=True)
class Expr(ASTNode):
    """Base class for Level 0 value expressions."""
    pass


# --- Literals ---

@dataclass(frozen=True)
class ExprInt(Expr):
    value: int
    lexeme: str


@dataclass(frozen=True)
class ExprReal(Expr):
    value: float
    lexeme: str


@dataclass(frozen=True)
class ExprChar(Expr):
    value: str
    lexeme: str


@dataclass(frozen=True)
class ExprString(Expr):
    value: str
    lexeme: str


@dataclass(frozen=True)
class ExprBool(Expr):
    value: bool


@dataclass(frozen=True)
class ExprOk(Expr):
    pass


@dataclass(frozen=True)
class ExprId(Expr):
    name: str


# --- Blocks & Control Flow ---

@dataclass(frozen=True)
class ExprBlock(Expr):
    """begin ... end — sequence of bindings and statements."""
    bindings: tuple[BindingNode, ...]


@dataclass(frozen=True)
class ExprIf(Expr):
    """if cond then e1 elsif cond2 then e2 else e3 end"""
    cond: Expr
    then_branch: Expr
    elsifs: tuple[tuple[Expr, Expr], ...] = ()
    else_branch: Optional[Expr] = None


@dataclass(frozen=True)
class ExprWhile(Expr):
    cond: Expr
    body: Expr


@dataclass(frozen=True)
class ExprLoop(Expr):
    body: Expr


@dataclass(frozen=True)
class ExprExit(Expr):
    pass


@dataclass(frozen=True)
class ExprFor(Expr):
    var_name: str
    start: Expr
    is_downto: bool
    stop: Expr
    body: Expr


# --- Functions & Applications ---

@dataclass(frozen=True)
class ExprFun(Expr):
    """fun(x: Int): Int x + 1"""
    params: tuple[FormalParam, ...]
    return_type: Optional[Type]
    body: Expr


@dataclass(frozen=True)
class ExprApp(Expr):
    """f(a, b)"""
    func: Expr
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class ExprInfix(Expr):
    """a + b, a := b, a andif b, a orif b, a is b"""
    left: Expr
    op: str
    right: Expr


# --- Aggregates & Constructors ---

@dataclass(frozen=True)
class TupleBinding(ASTNode):
    name: Optional[str]
    value: Expr


@dataclass(frozen=True)
class ExprTuple(Expr):
    fields: tuple[TupleBinding, ...]


@dataclass(frozen=True)
class RecordBinding(ASTNode):
    name: str
    value: Expr
    is_var: bool = False


@dataclass(frozen=True)
class ExprRecord(Expr):
    fields: tuple[RecordBinding, ...]


@dataclass(frozen=True)
class ExprOption(Expr):
    tag: str
    option_type: Type
    payload: Optional[Expr] = None


@dataclass(frozen=True)
class ExprVariant(Expr):
    tag: str
    variant_type: Type
    is_var: bool = False
    payload: Optional[Expr] = None


@dataclass(frozen=True)
class ExprArray(Expr):
    elements: tuple[Expr, ...]


@dataclass(frozen=True)
class ExprArrayRep(Expr):
    count: Expr
    init_val: Expr


@dataclass(frozen=True)
class ExprAuto(Expr):
    witness: Optional[tuple[str, Optional[Kind], Expr]]
    target_type: Type
    payload: Expr


# --- Selection, Indexing, and References ---

@dataclass(frozen=True)
class ExprSelect(Expr):
    target: Expr
    field: str


@dataclass(frozen=True)
class ExprIndex(Expr):
    target: Expr
    index: Expr


@dataclass(frozen=True)
class ExprIndexAssign(Expr):
    target: Expr
    index: Expr
    value: Expr


@dataclass(frozen=True)
class ExprVarCell(Expr):
    value: Expr


@dataclass(frozen=True)
class ExprDerefCell(Expr):
    target: Expr


@dataclass(frozen=True)
class ExprVariantCheck(Expr):
    target: Expr
    tag: str


@dataclass(frozen=True)
class ExprVariantAssert(Expr):
    target: Expr
    tag: str


# --- Pattern Matching & Discrimination ---

@dataclass(frozen=True)
class CaseBranch(ASTNode):
    tags: tuple[str, ...]
    binder: Optional[str] = None
    binder_type: Optional[Type] = None
    body: Expr = None  # type: ignore


@dataclass(frozen=True)
class ExprCase(Expr):
    target: Expr
    branches: tuple[CaseBranch, ...]
    else_branch: Optional[Expr] = None


@dataclass(frozen=True)
class InspectBranch(ASTNode):
    match_type: Type
    binders: tuple[tuple[str, Optional[Type]], ...]
    body: Expr


@dataclass(frozen=True)
class ExprInspect(Expr):
    target: Expr
    branches: tuple[InspectBranch, ...]
    else_branch: Optional[Expr] = None


# --- Exceptions ---

@dataclass(frozen=True)
class ExprRaise(Expr):
    exc: Expr
    payload: Optional[Expr] = None
    as_type: Optional[Type] = None


@dataclass(frozen=True)
class TryBranch(ASTNode):
    exc_pattern: Expr
    binder: Optional[str] = None
    binder_type: Optional[Type] = None
    body: Expr = None  # type: ignore


@dataclass(frozen=True)
class ExprTry(Expr):
    body: Expr
    branches: tuple[TryBranch, ...]
    else_branch: Optional[Expr] = None


# ============================================================================
# 5. Bindings, Declarations, and Program Structure
# ============================================================================

@dataclass(frozen=True)
class BindingNode(ASTNode):
    """Base class for declarations and statements inside blocks/phrases."""
    pass


@dataclass(frozen=True)
class LetValueBinding(BindingNode):
    """let [rec] [var] x (params...) : T = expr and y = ..."""
    name: str
    value: Expr
    params: tuple[FormalParam, ...] = ()
    type_annot: Optional[Type] = None
    is_rec: bool = False
    is_var: bool = False


@dataclass(frozen=True)
class LetTypeBinding(BindingNode):
    """Let [Rec] T(X::K)::K' = Type and U = ..."""
    name: str
    type_val: Type
    params: tuple[TypeFormal, ...] = ()
    bound: Optional[Kind] = None
    is_rec: bool = False


@dataclass(frozen=True)
class DefTypeBinding(BindingNode):
    """Def [Rec] T = Type (in interface signature)"""
    name: str
    type_val: Type
    params: tuple[TypeFormal, ...] = ()
    bound: Optional[Kind] = None
    is_rec: bool = False


@dataclass(frozen=True)
class DefKindBinding(BindingNode):
    """DEF K = Kind"""
    name: str
    kind_val: Kind


@dataclass(frozen=True)
class ExprStmt(BindingNode):
    """Standalone expression statement."""
    expr: Expr


@dataclass(frozen=True)
class ImportItem(ASTNode):
    names: tuple[str, ...]
    interface_name: str


@dataclass(frozen=True)
class InterfaceDecl(ASTNode):
    name: str
    signatures: tuple[BindingNode, ...]
    imports: tuple[ImportItem, ...] = ()
    is_unsound: bool = False


@dataclass(frozen=True)
class ModuleDecl(ASTNode):
    name: str
    interface_name: str
    bindings: tuple[BindingNode, ...]
    imports: tuple[ImportItem, ...] = ()
    is_unsound: bool = False


@dataclass(frozen=True)
class Program(ASTNode):
    """A complete .quest compilation unit: top-level declarations, expressions, interfaces, modules."""
    phrases: tuple[ASTNode, ...]


# ============================================================================
# 6. Canonical S-Expression Pretty-Printer
# ============================================================================

def _is_simple_leaf(val: Any) -> bool:
    """Checks if a value can be rendered compactly inline."""
    if isinstance(val, (int, float, str, bool)) or val is None:
        return True
    if isinstance(val, Enum):
        return True
    if isinstance(val, tuple) and all(isinstance(x, str) for x in val):
        return True
    if isinstance(val, ASTNode) and len(fields(val)) == 0:
        return True
    return False


def ast_dump(node: Any, indent: int = 0, show_offsets: bool = False) -> str:
    """Recursively formats an AST node into a canonical 2-space indented S-expression string."""
    pad = "  " * indent
    child_pad = "  " * (indent + 1)

    if not isinstance(node, ASTNode):
        if isinstance(node, tuple):
            if not node:
                return "()"
            if all(_is_simple_leaf(x) for x in node):
                return "(" + " ".join(repr(x) if isinstance(x, str) else str(x) for x in node) + ")"
            lines = ["("]
            for elem in node:
                lines.append(f"{child_pad}{ast_dump(elem, indent + 1, show_offsets)}")
            lines.append(f"{pad})")
            return "\n".join(lines)
        elif isinstance(node, Enum):
            return node.name
        elif isinstance(node, str):
            return repr(node)
        elif node is None:
            return "nil"
        return str(node)

    class_name = node.__class__.__name__
    node_fields = fields(node)

    # Filter out offset field unless show_offsets is True
    active_fields = [f for f in node_fields if show_offsets or f.name != "offset"]

    if not active_fields:
        if show_offsets:
            return f"({class_name} :offset {node.offset})"
        return f"({class_name})"

    # Check if all fields are simple leaves
    all_simple = True
    field_values = []
    for f in active_fields:
        val = getattr(node, f.name)
        field_values.append((f.name, val))
        if not _is_simple_leaf(val):
            all_simple = False

    if all_simple:
        parts = [class_name]
        for name, val in field_values:
            if isinstance(val, Enum):
                parts.append(val.name)
            elif isinstance(val, str):
                parts.append(repr(val))
            elif isinstance(val, tuple):
                parts.append("(" + " ".join(repr(x) for x in val) + ")")
            elif val is None:
                continue  # omit None in simple leaf inline
            else:
                parts.append(str(val))
        return f"({ ' '.join(parts) })"

    # Multi-line indented S-expression
    lines = [f"({class_name}"]
    for name, val in field_values:
        if val is None or val == () or val == False:
            # Skip empty optional values to keep trees compact
            continue
        if _is_simple_leaf(val):
            if isinstance(val, Enum):
                lines.append(f"{child_pad}:{name} {val.name}")
            elif isinstance(val, str):
                lines.append(f"{child_pad}:{name} {val!r}")
            elif isinstance(val, tuple):
                lines.append(f"{child_pad}:{name} ({ ' '.join(repr(x) for x in val) })")
            else:
                lines.append(f"{child_pad}:{name} {val}")
        else:
            if isinstance(val, tuple):
                lines.append(f"{child_pad}:{name} (")
                for item in val:
                    lines.append(f"{child_pad}  {ast_dump(item, indent + 2, show_offsets)}")
                lines.append(f"{child_pad})")
            else:
                lines.append(f"{child_pad}:{name} {ast_dump(val, indent + 1, show_offsets)}")

    lines.append(f"{pad})")
    return "\n".join(lines)
