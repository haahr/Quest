"""Quest Typed Core Abstract Syntax Tree (Typed AST) Definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from quest.types import (
    BOOL_TYPE,
    CHAR_TYPE,
    EXCEPTION_TYPE,
    INT_TYPE,
    OK_TYPE,
    QArrayType,
    QFunType,
    QKind,
    QOptionType,
    QRecordType,
    QTupleType,
    QType,
    QVarType,
    QVariantType,
    REAL_TYPE,
    STRING_TYPE,
    TYPE_KIND,
    qtype_dump,
)
from quest.env import (
    KindSymbol,
    Scope,
    Symbol,
    TypeSymbol,
    ValueSymbol,
)


# ============================================================================
# 1. Base Typed Nodes
# ============================================================================

@dataclass(frozen=True)
class TypedNode:
    """Base class for all typed Quest AST nodes with unified S-expression formatting."""
    offset: int = field(default=0, kw_only=True)

    def dump_header(self) -> str:
        """Returns inline summary tokens (e.g. literal values, names)."""
        return ""

    def dump_children(self) -> list[tuple[str, Any]]:
        """Returns structured children as [(':label', child_or_sequence), ...]."""
        return []

    def dump_show_type(self) -> bool:
        """Controls whether :type <type_val> is automatically appended to the header."""
        return hasattr(self, "type_val")

    def dump(self, indent: int = 0) -> str:
        """Recursively formats this node into a canonical 2-space indented S-expression."""
        child_pad = "  " * (indent + 1)

        # 1. Construct header parts
        parts = [self.__class__.__name__]
        extra = self.dump_header()
        if extra:
            parts.append(extra)

        if self.dump_show_type():
            parts.append(f":type {getattr(self, 'type_val')}")

        header_str = " ".join(parts)
        children = self.dump_children()

        # 2. Leaf node: render compact single-line
        if not children:
            return f"({header_str})"

        # 3. Non-leaf node: format labeled children consistently
        lines = [f"({header_str}"]
        for label, child in children:
            if isinstance(child, TypedNode):
                lines.append(f"{child_pad}{label} {child.dump(indent + 1)}")
            elif isinstance(child, (tuple, list)):
                if not child:
                    lines.append(f"{child_pad}{label} ()")
                else:
                    lines.append(f"{child_pad}{label} (")
                    for elem in child:
                        if isinstance(elem, TypedNode):
                            lines.append(f"{child_pad}  {elem.dump(indent + 2)}")
                        else:
                            lines.append(f"{child_pad}  {elem}")
                    lines.append(f"{child_pad})")
            elif child is not None:
                lines.append(f"{child_pad}{label} {child}")

        lines[-1] = lines[-1] + ")"
        return "\n".join(lines)


@dataclass(frozen=True)
class TypedExpr(TypedNode):
    """Base class for all typed value expressions."""
    pass


@dataclass(frozen=True)
class TypedBinding(TypedNode):
    """Base class for declarations and statements inside blocks and programs."""
    def dump_show_type(self) -> bool:
        return False


# ============================================================================
# 2. Literals and Variables
# ============================================================================

@dataclass(frozen=True)
class TypedInt(TypedExpr):
    value: int
    type_val: QType = INT_TYPE

    def dump_header(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class TypedReal(TypedExpr):
    value: float
    type_val: QType = REAL_TYPE

    def dump_header(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class TypedBool(TypedExpr):
    value: bool
    type_val: QType = BOOL_TYPE

    def dump_header(self) -> str:
        return "true" if self.value else "false"

    def dump_show_type(self) -> bool:
        return False


@dataclass(frozen=True)
class TypedChar(TypedExpr):
    value: str
    type_val: QType = CHAR_TYPE

    def dump_header(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class TypedString(TypedExpr):
    value: str
    type_val: QType = STRING_TYPE

    def dump_header(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class TypedOk(TypedExpr):
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False


@dataclass(frozen=True)
class TypedVar(TypedExpr):
    """Reference to a resolved value symbol."""
    name: str
    symbol: ValueSymbol
    type_val: QType

    def dump_header(self) -> str:
        return f"'{self.name}'"


# ============================================================================
# 3. Functions, Parameters, and Applications
# ============================================================================

@dataclass(frozen=True)
class TypedParam(TypedNode):
    """Resolved formal parameter to a function."""
    name: str
    symbol: ValueSymbol
    type_val: QType
    is_var: bool = False
    is_out: bool = False

    def dump_header(self) -> str:
        var_tag = " :var" if self.is_var else (" :out" if self.is_out else "")
        return f"'{self.name}'{var_tag}"


@dataclass(frozen=True)
class TypedFun(TypedExpr):
    """Function abstraction: fun(params): RetType Body."""
    params: tuple[TypedParam, ...]
    body: TypedExpr
    type_val: QFunType

    def dump_header(self) -> str:
        params_str = " ".join(f"('{p.name}' : {p.type_val})" for p in self.params)
        return f":params ({params_str})"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":body", self.body)]


@dataclass(frozen=True)
class TypedApp(TypedExpr):
    """Function application: func(arg1, ..., argN)."""
    func: TypedExpr
    args: tuple[TypedExpr, ...]
    type_val: QType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":func", self.func), (":args", self.args)]


@dataclass(frozen=True)
class TypedTypeApp(TypedExpr):
    """Explicit polymorphic type instantiation: func[T1, ..., Tn]."""
    func: TypedExpr
    type_args: tuple[QType, ...]
    type_val: QType

    def dump_header(self) -> str:
        targs_str = " ".join(str(t) for t in self.type_args)
        return f"[{targs_str}]"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":func", self.func)]


@dataclass(frozen=True)
class TypedInfix(TypedExpr):
    """Binary infix operation: left op right."""
    left: TypedExpr
    op: str
    right: TypedExpr
    type_val: QType

    def dump_header(self) -> str:
        return repr(self.op)

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":left", self.left), (":right", self.right)]


# ============================================================================
# 4. Aggregates and Projections
# ============================================================================

@dataclass(frozen=True)
class TypedRecordField(TypedNode):
    """A single evaluated field in a record value."""
    name: str
    value: TypedExpr
    is_var: bool = False

    def dump_header(self) -> str:
        var_tag = " :var" if self.is_var else ""
        return f"'{self.name}'{var_tag}"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":value", self.value)]


@dataclass(frozen=True)
class TypedRecord(TypedExpr):
    """Record value construction: record x = e1, y = e2 end."""
    fields: tuple[TypedRecordField, ...]
    type_val: QRecordType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":fields", self.fields)]


@dataclass(frozen=True)
class TypedTypeWitness(TypedExpr):
    """Witness type element in an existential tuple: Let A::K = T."""
    name: str
    witness_type: QType
    bound: Optional[Any] = None
    type_val: QType = field(default_factory=lambda: TYPE_KIND)

    def dump_header(self) -> str:
        return f"'{self.name}' = {self.witness_type}"

    def dump_show_type(self) -> bool:
        return False


@dataclass(frozen=True)
class TypedTuple(TypedExpr):
    """Tuple value construction: tuple e1, e2 end."""
    elements: tuple[TypedExpr, ...]
    type_val: QTupleType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":elements", self.elements)]


@dataclass(frozen=True)
class TypedSelect(TypedExpr):
    """Field selection: target.field."""
    target: TypedExpr
    field: str
    type_val: QType

    def dump_header(self) -> str:
        return f"'{self.field}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target)]


@dataclass(frozen=True)
class TypedIndex(TypedExpr):
    """Array indexing: target[index]."""
    target: TypedExpr
    index: TypedExpr
    type_val: QType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target), (":index", self.index)]


@dataclass(frozen=True)
class TypedIndexAssign(TypedExpr):
    """Array element assignment: target[index] := value."""
    target: TypedExpr
    index: TypedExpr
    value: TypedExpr
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target), (":index", self.index), (":value", self.value)]


@dataclass(frozen=True)
class TypedArray(TypedExpr):
    """Explicit array construction: array [e1, e2, ...]."""
    elements: tuple[TypedExpr, ...]
    type_val: QArrayType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":elements", self.elements)]


@dataclass(frozen=True)
class TypedArrayRep(TypedExpr):
    """Array repetition: array of count elements init_val."""
    count: TypedExpr
    init_val: TypedExpr
    type_val: QArrayType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":count", self.count), (":init", self.init_val)]


# ============================================================================
# 5. Mutable References and Assignment
# ============================================================================

@dataclass(frozen=True)
class TypedVarCell(TypedExpr):
    """Reference cell allocation: var(initial_value)."""
    value: TypedExpr
    type_val: QVarType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":value", self.value)]


@dataclass(frozen=True)
class TypedDerefCell(TypedExpr):
    """Explicit or implicit reference dereference."""
    target: TypedExpr
    type_val: QType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target)]


@dataclass(frozen=True)
class TypedAssign(TypedExpr):
    """Assignment to mutable reference or record field: target := value."""
    target: TypedExpr
    value: TypedExpr
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target), (":value", self.value)]


# ============================================================================
# 6. Variants, Options, and Pattern Matching
# ============================================================================

@dataclass(frozen=True)
class TypedVariant(TypedExpr):
    """Variant injection: variant tag = value end."""
    tag: str
    type_val: QVariantType
    payload: Optional[TypedExpr] = None

    def dump_header(self) -> str:
        return f"'{self.tag}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":payload", self.payload)] if self.payload else []


@dataclass(frozen=True)
class TypedOption(TypedExpr):
    """Option injection: option tag with value end."""
    tag: str
    type_val: QOptionType
    payload: Optional[TypedExpr] = None

    def dump_header(self) -> str:
        return f"'{self.tag}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":payload", self.payload)] if self.payload else []


@dataclass(frozen=True)
class TypedVariantCheck(TypedExpr):
    """Variant/Option tag check: target?tag."""
    target: TypedExpr
    tag: str
    type_val: QType

    def dump_header(self) -> str:
        return f"'{self.tag}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target)]


@dataclass(frozen=True)
class TypedVariantAssert(TypedExpr):
    """Variant/Option tag assertion/extraction: target!tag."""
    target: TypedExpr
    tag: str
    type_val: QType

    def dump_header(self) -> str:
        return f"'{self.tag}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":target", self.target)]


@dataclass(frozen=True)
class TypedCaseBranch(TypedNode):
    """A branch in a case discrimination: when tag1, tag2 => body."""
    tags: tuple[str, ...]
    body: TypedExpr
    binder: Optional[ValueSymbol] = None

    def dump_header(self) -> str:
        binder_str = f" :binder '{self.binder.name}'" if self.binder else ""
        return f"tags=({', '.join(self.tags)}){binder_str}"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":body", self.body)]


@dataclass(frozen=True)
class TypedCase(TypedExpr):
    """Case discrimination on variants or options."""
    target: TypedExpr
    branches: tuple[TypedCaseBranch, ...]
    type_val: QType
    else_branch: Optional[TypedExpr] = None

    def dump_children(self) -> list[tuple[str, Any]]:
        children: list[tuple[str, Any]] = [(":target", self.target), (":branches", self.branches)]
        if self.else_branch:
            children.append((":else", self.else_branch))
        return children


@dataclass(frozen=True)
class TypedInspectBranch(TypedNode):
    """A branch in a dynamic type inspection: when Type => body."""
    match_type: QType
    binders: tuple[ValueSymbol, ...]
    body: TypedExpr

    def dump_header(self) -> str:
        return f"match={self.match_type}"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":body", self.body)]


@dataclass(frozen=True)
class TypedInspect(TypedExpr):
    """Dynamic type inspection (inspect target ...)."""
    target: TypedExpr
    branches: tuple[TypedInspectBranch, ...]
    type_val: QType
    else_branch: Optional[TypedExpr] = None

    def dump_children(self) -> list[tuple[str, Any]]:
        children: list[tuple[str, Any]] = [(":target", self.target), (":branches", self.branches)]
        if self.else_branch:
            children.append((":else", self.else_branch))
        return children


# ============================================================================
# 7. Control Flow and Blocks
# ============================================================================

@dataclass(frozen=True)
class TypedBlock(TypedExpr):
    """Block expression: begin bindings... result end."""
    bindings: tuple[TypedBinding, ...]
    result: TypedExpr
    type_val: QType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":bindings", self.bindings), (":result", self.result)]


@dataclass(frozen=True)
class TypedIf(TypedExpr):
    """Conditional expression: if cond then e1 else e2 end."""
    cond: TypedExpr
    then_branch: TypedExpr
    else_branch: TypedExpr
    type_val: QType

    def dump_children(self) -> list[tuple[str, Any]]:
        return [
            (":cond", self.cond),
            (":then", self.then_branch),
            (":else", self.else_branch),
        ]


@dataclass(frozen=True)
class TypedWhile(TypedExpr):
    """While loop: while cond do body end."""
    cond: TypedExpr
    body: TypedExpr
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":cond", self.cond), (":body", self.body)]


@dataclass(frozen=True)
class TypedLoop(TypedExpr):
    """Infinite loop: loop body end."""
    body: TypedExpr
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":body", self.body)]


@dataclass(frozen=True)
class TypedFor(TypedExpr):
    """For loop: for var_name = start [downto] stop do body end."""
    var_name: str
    symbol: ValueSymbol
    start: TypedExpr
    is_downto: bool
    stop: TypedExpr
    body: TypedExpr
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False

    def dump_header(self) -> str:
        dir_tag = " :downto" if self.is_downto else " :upto"
        return f"'{self.var_name}'{dir_tag}"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":start", self.start), (":stop", self.stop), (":body", self.body)]


@dataclass(frozen=True)
class TypedExit(TypedExpr):
    """Exit statement exiting the innermost loop."""
    type_val: QType = OK_TYPE

    def dump_show_type(self) -> bool:
        return False


# ============================================================================
# 8. Exceptions
# ============================================================================

@dataclass(frozen=True)
class TypedException(TypedExpr):
    """Exception value constructor: exception name [: Type] end."""
    name: str
    payload_type: Optional[QType] = None
    type_val: QType = EXCEPTION_TYPE

    def dump_header(self) -> str:
        return f"'{self.name}'"


@dataclass(frozen=True)
class TypedRaise(TypedExpr):
    """Raise statement: raise exc [with payload]."""
    exc: TypedExpr
    type_val: QType
    payload: Optional[TypedExpr] = None

    def dump_children(self) -> list[tuple[str, Any]]:
        children: list[tuple[str, Any]] = [(":exc", self.exc)]
        if self.payload:
            children.append((":payload", self.payload))
        return children


@dataclass(frozen=True)
class TypedTryBranch(TypedNode):
    """Catch branch in a try block."""
    exc_pattern: TypedExpr
    body: TypedExpr
    binder: Optional[ValueSymbol] = None

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":exc_pattern", self.exc_pattern), (":body", self.body)]


@dataclass(frozen=True)
class TypedTry(TypedExpr):
    """Try-with exception handler."""
    body: TypedExpr
    branches: tuple[TypedTryBranch, ...]
    type_val: QType
    else_branch: Optional[TypedExpr] = None

    def dump_children(self) -> list[tuple[str, Any]]:
        children: list[tuple[str, Any]] = [(":body", self.body), (":branches", self.branches)]
        if self.else_branch:
            children.append((":else", self.else_branch))
        return children


# ============================================================================
# 9. Declarations and Program Structure
# ============================================================================

@dataclass(frozen=True)
class TypedLetValue(TypedBinding):
    """Value let declaration: let [rec] [var] x = expr."""
    name: str
    value: TypedExpr
    symbol: ValueSymbol
    is_rec: bool = False

    def dump_header(self) -> str:
        rec_tag = " :rec" if self.is_rec else ""
        return f"'{self.name}'{rec_tag} :type {self.symbol.type_val}"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":value", self.value)]


@dataclass(frozen=True)
class TypedLetType(TypedBinding):
    """Type let declaration: Let T = Type."""
    name: str
    symbol: TypeSymbol

    def dump_header(self) -> str:
        return f"'{self.name}' :kind {self.symbol.kind}"


@dataclass(frozen=True)
class TypedDefKind(TypedBinding):
    """Kind definition: DEF K = Kind."""
    name: str
    symbol: KindSymbol

    def dump_header(self) -> str:
        return f"'{self.name}' :kind {self.symbol.kind}"


@dataclass(frozen=True)
class TypedExprStmt(TypedBinding):
    """Standalone expression statement."""
    expr: TypedExpr

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":expr", self.expr)]


@dataclass(frozen=True)
class TypedInterface(TypedBinding):
    """Interface declaration."""
    name: str
    signatures: tuple[TypedBinding, ...]
    scope: Scope

    def dump_header(self) -> str:
        return f"'{self.name}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":signatures", self.signatures)]


@dataclass(frozen=True)
class TypedModule(TypedBinding):
    """Module implementation conforming to an interface."""
    name: str
    interface_name: str
    bindings: tuple[TypedBinding, ...]
    scope: Scope

    def dump_header(self) -> str:
        return f"'{self.name}' implements '{self.interface_name}'"

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":bindings", self.bindings)]


@dataclass(frozen=True)
class TypedImportItem(TypedNode):
    names: tuple[str, ...]
    interface_name: str

    def dump_header(self) -> str:
        if self.names:
            return f"({' '.join(repr(n) for n in self.names)}) : '{self.interface_name}'"
        return f": '{self.interface_name}'"


@dataclass(frozen=True)
class TypedImport(TypedBinding):
    """Import statement importing interfaces and modules."""
    items: tuple[TypedImportItem, ...]

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":items", self.items)]


@dataclass(frozen=True)
class TypedProgram(TypedNode):
    """Top-level typed program AST."""
    phrases: tuple[Union[TypedBinding, TypedExpr], ...]

    def dump_children(self) -> list[tuple[str, Any]]:
        return [(":phrases", self.phrases)]


# ============================================================================
# 10. Canonical S-Expression Pretty Printer (typed_ast_dump)
# ============================================================================

def typed_ast_dump(node: TypedNode, indent: int = 0) -> str:
    """Formats a TypedNode into a canonical 2-space indented S-expression string."""
    return node.dump(indent)
