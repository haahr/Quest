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
class ExprException(Expr):
    name: str
    type_annot: Optional[Type] = None


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

def _is_simple_leaf(value: Any) -> bool:
    """Checks if an AST value is a simple leaf that can be printed inline."""
    match value:
        case None | int() | float() | bool() | str() | Enum():
            return True
        case tuple() if all(isinstance(item, str) for item in value):
            return True
        case ASTNode() if len(fields(value)) == 0:
            return True
        case _:
            return False


def ast_dump(node: Any, indent: int = 0, show_offsets: bool = False) -> str:
    """Recursively formats an AST node into a canonical 2-space indented S-expression string."""
    padding = "  " * indent
    child_padding = "  " * (indent + 1)

    if not isinstance(node, ASTNode):
        match node:
            case tuple():
                if not node:
                    return "()"
                if all(_is_simple_leaf(item) for item in node):
                    return "(" + " ".join(repr(item) if isinstance(item, str) else str(item) for item in node) + ")"
                lines = ["("]
                for element in node:
                    lines.append(f"{child_padding}{ast_dump(element, indent + 1, show_offsets)}")
                lines.append(f"{padding})")
                return "\n".join(lines)
            case Enum(name=enum_name):
                return enum_name
            case str():
                return repr(node)
            case None:
                return "nil"
            case _:
                return str(node)

    class_name = node.__class__.__name__
    node_fields = fields(node)

    # Filter out offset field unless show_offsets is True
    active_fields = [field for field in node_fields if show_offsets or field.name != "offset"]

    if not active_fields:
        if show_offsets:
            return f"({class_name} :offset {node.offset})"
        return f"({class_name})"

    # Check if all fields are simple leaves
    all_simple = True
    field_values = []
    for field in active_fields:
        field_value = getattr(node, field.name)
        field_values.append((field.name, field_value))
        if not _is_simple_leaf(field_value):
            all_simple = False

    if all_simple:
        parts = [class_name]
        for name, field_value in field_values:
            match field_value:
                case Enum(name=enum_name):
                    parts.append(enum_name)
                case str():
                    parts.append(repr(field_value))
                case tuple():
                    parts.append("(" + " ".join(repr(item) for item in field_value) + ")")
                case None:
                    continue  # omit None in simple leaf inline
                case _:
                    parts.append(str(field_value))
        return f"({ ' '.join(parts) })"

    # Multi-line indented S-expression
    lines = [f"({class_name}"]
    for name, field_value in field_values:
        if field_value is None or field_value == () or field_value is False:
            # Skip empty optional values to keep trees compact
            continue
        if _is_simple_leaf(field_value):
            match field_value:
                case Enum(name=enum_name):
                    lines.append(f"{child_padding}:{name} {enum_name}")
                case str():
                    lines.append(f"{child_padding}:{name} {field_value!r}")
                case tuple():
                    lines.append(f"{child_padding}:{name} ({ ' '.join(repr(item) for item in field_value) })")
                case _:
                    lines.append(f"{child_padding}:{name} {field_value}")
        else:
            if isinstance(field_value, tuple):
                lines.append(f"{child_padding}:{name} (")
                for item in field_value:
                    lines.append(f"{child_padding}  {ast_dump(item, indent + 2, show_offsets)}")
                lines.append(f"{child_padding})")
            else:
                lines.append(f"{child_padding}:{name} {ast_dump(field_value, indent + 1, show_offsets)}")

    lines.append(f"{padding})")
    return "\n".join(lines)
