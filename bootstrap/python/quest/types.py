"""Quest Semantic Types, Kinds, Substitution, and Subtyping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union


# ============================================================================
# 1. Kinds (Level 2)
# ============================================================================

class QKind:
    """Base class for all Quest kinds."""

    def evaluate_lazily(self, env: Optional[Any] = None) -> QKind:
        """Evaluates kind aliases lazily on demand."""
        return self

    def substitute_kinds(self, subst: dict[int, QKind]) -> QKind:
        """Substitutes kind variables keyed by symbol_id."""
        return self

    def substitute_types(self, subst: dict[int, QType]) -> QKind:
        """Substitutes type variables inside power kind bounds."""
        return self


@dataclass(frozen=True)
class QTypeKind(QKind):
    """The base kind TYPE (all proper types)."""

    def __str__(self) -> str:
        return "TYPE"


@dataclass(frozen=True)
class QPowerKind(QKind):
    """The power kind POWER(bound) / <: bound (all subtypes of bound)."""
    bound: QType

    def evaluate_lazily(self, env: Optional[Any] = None) -> QKind:
        return QPowerKind(self.bound.evaluate_lazily(env))

    def substitute_types(self, subst: dict[int, QType]) -> QKind:
        return QPowerKind(self.bound.substitute(subst))

    def __str__(self) -> str:
        return f"<: {self.bound}"


@dataclass(frozen=True)
class QAllKind(QKind):
    """Higher-order operator kind: ALL(param::param_kind) result_kind."""
    param_name: str
    param_id: int
    param_kind: QKind
    result_kind: QKind

    def evaluate_lazily(self, env: Optional[Any] = None) -> QKind:
        return QAllKind(
            param_name=self.param_name,
            param_id=self.param_id,
            param_kind=self.param_kind.evaluate_lazily(env),
            result_kind=self.result_kind.evaluate_lazily(env),
        )

    def substitute_kinds(self, subst: dict[int, QKind]) -> QKind:
        if self.param_id in subst:
            active_subst = {k: v for k, v in subst.items() if k != self.param_id}
        else:
            active_subst = subst
        return QAllKind(
            param_name=self.param_name,
            param_id=self.param_id,
            param_kind=self.param_kind.substitute_kinds(subst),
            result_kind=self.result_kind.substitute_kinds(active_subst),
        )

    def substitute_types(self, subst: dict[int, QType]) -> QKind:
        return QAllKind(
            param_name=self.param_name,
            param_id=self.param_id,
            param_kind=self.param_kind.substitute_types(subst),
            result_kind=self.result_kind.substitute_types(subst),
        )

    def __str__(self) -> str:
        return f"ALL({self.param_name} :: {self.param_kind}) {self.result_kind}"


@dataclass(frozen=True)
class QKindVar(QKind):
    """Kind variable reference."""
    name: str
    symbol_id: int

    def evaluate_lazily(self, env: Optional[Any] = None) -> QKind:
        if env is not None and hasattr(env, "lookup_kind_by_id"):
            sym = env.lookup_kind_by_id(self.symbol_id)
            if sym is not None:
                return sym.kind.evaluate_lazily(env)
        return self

    def substitute_kinds(self, subst: dict[int, QKind]) -> QKind:
        return subst.get(self.symbol_id, self)

    def __str__(self) -> str:
        return self.name


# Canonical singletons for kinds
TYPE_KIND = QTypeKind()


# ============================================================================
# 2. Base Semantic Type (Level 1)
# ============================================================================

class QType:
    """Base class for all semantic Quest types."""

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        """Evaluates type aliases and applications lazily to expose the outermost constructor."""
        return self

    def substitute(self, subst: dict[int, QType]) -> QType:
        """Performs capture-avoiding substitution using symbol_id keys."""
        return self

    def __str__(self) -> str:
        return self.__class__.__name__


# ============================================================================
# 3. Primitive Types
# ============================================================================

@dataclass(frozen=True)
class QIntType(QType):
    def __str__(self) -> str:
        return "Int"


@dataclass(frozen=True)
class QRealType(QType):
    def __str__(self) -> str:
        return "Real"


@dataclass(frozen=True)
class QBoolType(QType):
    def __str__(self) -> str:
        return "Bool"


@dataclass(frozen=True)
class QCharType(QType):
    def __str__(self) -> str:
        return "Char"


@dataclass(frozen=True)
class QStringType(QType):
    def __str__(self) -> str:
        return "String"


@dataclass(frozen=True)
class QOkType(QType):
    def __str__(self) -> str:
        return "Ok"


@dataclass(frozen=True)
class QDynamicType(QType):
    def __str__(self) -> str:
        return "Dynamic"


@dataclass(frozen=True)
class QExceptionType(QType):
    def __str__(self) -> str:
        return "Exception"


# Canonical singletons for primitive types
INT_TYPE = QIntType()
REAL_TYPE = QRealType()
BOOL_TYPE = QBoolType()
CHAR_TYPE = QCharType()
STRING_TYPE = QStringType()
OK_TYPE = QOkType()
DYNAMIC_TYPE = QDynamicType()
EXCEPTION_TYPE = QExceptionType()


# ============================================================================
# 4. Composite Types (Tuples, Records, Variants, Options)
# ============================================================================

@dataclass(frozen=True)
class QTupleType(QType):
    """Ordered tuple type: Tuple T1 ... Tn end."""
    elements: tuple[QType, ...]

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        return self

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QTupleType(tuple(t.substitute(subst) for t in self.elements))

    def __str__(self) -> str:
        elems = " ".join(str(t) for t in self.elements)
        return f"Tuple {elems} end" if elems else "Tuple end"


@dataclass(frozen=True)
class QRecordField:
    """A single field inside a record type."""
    name: str
    type_val: QType
    is_var: bool = False

    def substitute(self, subst: dict[int, QType]) -> QRecordField:
        return QRecordField(name=self.name, type_val=self.type_val.substitute(subst), is_var=self.is_var)

    def __str__(self) -> str:
        var_prefix = "var " if self.is_var else ""
        return f"{var_prefix}{self.name}: {self.type_val}"


@dataclass(frozen=True)
class QRecordType(QType):
    """Unordered record type with structural subtyping: Record [var] x: T ... end."""
    fields: tuple[QRecordField, ...]

    def get_field(self, name: str) -> Optional[QRecordField]:
        for field_entry in self.fields:
            if field_entry.name == name:
                return field_entry
        return None

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QRecordType(tuple(f.substitute(subst) for f in self.fields))

    def __str__(self) -> str:
        fields_str = " ".join(str(f) for f in self.fields)
        return f"Record {fields_str} end" if fields_str else "Record end"


@dataclass(frozen=True)
class QVariantField:
    """A tagged branch inside a variant type."""
    name: str
    type_val: Optional[QType] = None
    is_var: bool = False

    def substitute(self, subst: dict[int, QType]) -> QVariantField:
        return QVariantField(
            name=self.name,
            type_val=self.type_val.substitute(subst) if self.type_val else None,
            is_var=self.is_var,
        )

    def __str__(self) -> str:
        var_prefix = "var " if self.is_var else ""
        if self.type_val:
            return f"{var_prefix}{self.name}: {self.type_val}"
        return f"{var_prefix}{self.name}"


@dataclass(frozen=True)
class QVariantType(QType):
    """Variant type: Variant tag1: T1 ... end."""
    variants: tuple[QVariantField, ...]

    def get_variant(self, name: str) -> Optional[QVariantField]:
        for v in self.variants:
            if v.name == name:
                return v
        return None

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QVariantType(tuple(v.substitute(subst) for v in self.variants))

    def __str__(self) -> str:
        variants_str = " ".join(str(v) for v in self.variants)
        return f"Variant {variants_str} end" if variants_str else "Variant end"


@dataclass(frozen=True)
class QOptionField:
    """A tagged case inside an option type."""
    name: str
    payload_type: Optional[QType] = None

    def substitute(self, subst: dict[int, QType]) -> QOptionField:
        return QOptionField(
            name=self.name,
            payload_type=self.payload_type.substitute(subst) if self.payload_type else None,
        )

    def __str__(self) -> str:
        if self.payload_type:
            return f"{self.name} with {self.payload_type}"
        return self.name


@dataclass(frozen=True)
class QOptionType(QType):
    """Option type: Option tag1 tag2 with T end."""
    options: tuple[QOptionField, ...]

    def get_option(self, name: str) -> Optional[QOptionField]:
        for opt in self.options:
            if opt.name == name:
                return opt
        return None

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QOptionType(tuple(o.substitute(subst) for o in self.options))

    def __str__(self) -> str:
        options_str = " ".join(str(o) for o in self.options)
        return f"Option {options_str} end" if options_str else "Option end"


# ============================================================================
# 5. Functions, References, and Computation Types
# ============================================================================

@dataclass(frozen=True)
class QParam:
    """Formal parameter to a function."""
    name: str
    type_val: QType
    is_var: bool = False
    is_out: bool = False

    def substitute(self, subst: dict[int, QType]) -> QParam:
        return QParam(
            name=self.name,
            type_val=self.type_val.substitute(subst),
            is_var=self.is_var,
            is_out=self.is_out,
        )

    def __str__(self) -> str:
        prefix = "var " if self.is_var else ("out " if self.is_out else "")
        return f"{prefix}{self.name}: {self.type_val}"


@dataclass(frozen=True)
class QFunType(QType):
    """Function type: Fun(params) : result_type."""
    params: tuple[QParam, ...]
    result_type: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QFunType(
            params=tuple(p.substitute(subst) for p in self.params),
            result_type=self.result_type.substitute(subst),
        )

    def __str__(self) -> str:
        params_str = " ".join(str(p) for p in self.params)
        return f"Fun({params_str}): {self.result_type}"


@dataclass(frozen=True)
class QVarType(QType):
    """Mutable reference cell type: Var(T)."""
    element_type: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QVarType(self.element_type.substitute(subst))

    def __str__(self) -> str:
        return f"Var({self.element_type})"


@dataclass(frozen=True)
class QArrayType(QType):
    """Mutable array type: Array(T)."""
    element_type: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QArrayType(self.element_type.substitute(subst))

    def __str__(self) -> str:
        return f"Array({self.element_type})"


@dataclass(frozen=True)
class QOutType(QType):
    """Write-only output parameter type: Out(T)."""
    element_type: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QOutType(self.element_type.substitute(subst))

    def __str__(self) -> str:
        return f"Out({self.element_type})"


# ============================================================================
# 6. Polymorphic, Higher-Order, and Parameterized Types
# ============================================================================

@dataclass(frozen=True)
class QQuantifier:
    """Type quantifier in All(X::K) T or All(X <: Bound) T."""
    name: str
    symbol_id: int
    bound: QKind

    def substitute(self, subst: dict[int, QType]) -> QQuantifier:
        return QQuantifier(
            name=self.name,
            symbol_id=self.symbol_id,
            bound=self.bound.substitute_types(subst),
        )

    def __str__(self) -> str:
        if isinstance(self.bound, QPowerKind):
            return f"{self.name} <: {self.bound.bound}"
        return f"{self.name} :: {self.bound}"


@dataclass(frozen=True)
class QAllType(QType):
    """Universal quantification: All(X::K) T."""
    quantifiers: tuple[QQuantifier, ...]
    body: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        # Avoid capturing bound quantifiers
        bound_ids = {q.symbol_id for q in self.quantifiers}
        active_subst = {k: v for k, v in subst.items() if k not in bound_ids}
        return QAllType(
            quantifiers=tuple(q.substitute(subst) for q in self.quantifiers),
            body=self.body.substitute(active_subst),
        )

    def __str__(self) -> str:
        quants = " ".join(str(q) for q in self.quantifiers)
        return f"All({quants}) {self.body}"


@dataclass(frozen=True)
class QAutoType(QType):
    """Existential / automorphic type: Auto X::K with ... end."""
    type_param: str
    symbol_id: int
    kind_bound: QKind
    signature: tuple[QRecordField, ...]

    def substitute(self, subst: dict[int, QType]) -> QType:
        if self.symbol_id in subst:
            active_subst = {k: v for k, v in subst.items() if k != self.symbol_id}
        else:
            active_subst = subst
        return QAutoType(
            type_param=self.type_param,
            symbol_id=self.symbol_id,
            kind_bound=self.kind_bound,
            signature=tuple(f.substitute(active_subst) for f in self.signature),
        )

    def __str__(self) -> str:
        sig_str = " ".join(str(f) for f in self.signature)
        return f"Auto {self.type_param} :: {self.kind_bound} with {sig_str} end"


@dataclass(frozen=True)
class QTypeFormal:
    """Formal type parameter for a type-level function: Fun(X::K) T."""
    name: str
    symbol_id: int
    bound: QKind

    def __str__(self) -> str:
        return f"{self.name} :: {self.bound}"


@dataclass(frozen=True)
class QTypeFun(QType):
    """Type-level abstraction: Fun(X::K) BodyType."""
    params: tuple[QTypeFormal, ...]
    body: QType

    def substitute(self, subst: dict[int, QType]) -> QType:
        bound_ids = {p.symbol_id for p in self.params}
        active_subst = {k: v for k, v in subst.items() if k not in bound_ids}
        return QTypeFun(params=self.params, body=self.body.substitute(active_subst))

    def __str__(self) -> str:
        params_str = " ".join(str(p) for p in self.params)
        return f"Fun({params_str}) {self.body}"


@dataclass(frozen=True)
class QTypeApp(QType):
    """Type operator application: Constructor(Arg1, ..., ArgN)."""
    constructor: QType
    arguments: tuple[QType, ...]

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        ctor = self.constructor.evaluate_lazily(env)
        if isinstance(ctor, QTypeFun):
            subst = {
                formal.symbol_id: arg
                for formal, arg in zip(ctor.params, self.arguments)
            }
            return ctor.body.substitute(subst).evaluate_lazily(env)
        return QTypeApp(constructor=ctor, arguments=self.arguments)

    def substitute(self, subst: dict[int, QType]) -> QType:
        return QTypeApp(
            constructor=self.constructor.substitute(subst),
            arguments=tuple(arg.substitute(subst) for arg in self.arguments),
        )

    def __str__(self) -> str:
        args_str = " ".join(str(a) for a in self.arguments)
        return f"{self.constructor}({args_str})"


# ============================================================================
# 7. Recursive Types, Variables, and Abstract Types
# ============================================================================

@dataclass(frozen=True)
class QRecType(QType):
    """Single recursive type: Rec(X::K) T."""
    var_name: str
    symbol_id: int
    bound: QKind
    body: QType

    def unfold_lazily(self) -> QType:
        """Unfolds Rec(X) T lazily by substituting Rec(X) T for X in T."""
        return self.body.substitute({self.symbol_id: self})

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        return self.unfold_lazily().evaluate_lazily(env)

    def substitute(self, subst: dict[int, QType]) -> QType:
        if self.symbol_id in subst:
            active_subst = {k: v for k, v in subst.items() if k != self.symbol_id}
        else:
            active_subst = subst
        return QRecType(
            var_name=self.var_name,
            symbol_id=self.symbol_id,
            bound=self.bound,
            body=self.body.substitute(active_subst),
        )

    def __str__(self) -> str:
        return f"Rec({self.var_name} :: {self.bound}) {self.body}"


@dataclass(frozen=True)
class QRecGroupType(QType):
    """Mutually recursive type group: Let Rec T1 = ... and T2 = ..."""
    # Each entry: (name, symbol_id, bound_kind, body_type)
    bindings: tuple[tuple[str, int, QKind, QType], ...]
    active_index: int = 0

    @property
    def current_symbol_id(self) -> int:
        return self.bindings[self.active_index][1]

    @property
    def current_name(self) -> str:
        return self.bindings[self.active_index][0]

    def unfold_lazily(self) -> QType:
        """Unfolds the active mutually recursive binding lazily."""
        subst = {
            binding[1]: QRecGroupType(bindings=self.bindings, active_index=idx)
            for idx, binding in enumerate(self.bindings)
        }
        body = self.bindings[self.active_index][3]
        return body.substitute(subst)

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        return self.unfold_lazily().evaluate_lazily(env)

    def substitute(self, subst: dict[int, QType]) -> QType:
        bound_ids = {b[1] for b in self.bindings}
        active_subst = {k: v for k, v in subst.items() if k not in bound_ids}
        new_bindings = tuple(
            (b[0], b[1], b[2], b[3].substitute(active_subst))
            for b in self.bindings
        )
        return QRecGroupType(bindings=new_bindings, active_index=self.active_index)

    def __str__(self) -> str:
        return f"RecGroup({self.current_name})"


@dataclass(frozen=True)
class QTypeVar(QType):
    """Named type variable with unique symbol identity."""
    name: str
    symbol_id: int
    bound: Optional[QKind] = None

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        if env is not None:
            sym = env.lookup_type_by_id(self.symbol_id) if hasattr(env, "lookup_type_by_id") else None
            if sym is not None and sym.definition is not None:
                return sym.definition.evaluate_lazily(env)
        return self

    def substitute(self, subst: dict[int, QType]) -> QType:
        return subst.get(self.symbol_id, self)

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class QAbstractType(QType):
    """An abstract type bounded by a kind."""
    name: str
    symbol_id: int
    bound: QKind

    def substitute(self, subst: dict[int, QType]) -> QType:
        return subst.get(self.symbol_id, self)

    def __str__(self) -> str:
        return self.name


# ============================================================================
# 8. Type Inference Metavariable
# ============================================================================

class QTypeMeta(QType):
    """Mutable type metavariable (?T_1) for local bidirectional unification."""
    _counter: int = 0

    def __init__(self, bound: QKind = TYPE_KIND, name: Optional[str] = None):
        QTypeMeta._counter += 1
        self.symbol_id: int = -QTypeMeta._counter  # Negative IDs for inference metavars
        self.bound: QKind = bound
        self.name: str = name or f"?T{abs(self.symbol_id)}"
        self.instance: Optional[QType] = None

    @classmethod
    def reset_counter(cls) -> None:
        cls._counter = 0

    def is_solved(self) -> bool:
        return self.instance is not None

    def prune(self) -> QType:
        """Flattens chained metavariable instantiations."""
        if self.instance is not None:
            if isinstance(self.instance, QTypeMeta):
                self.instance = self.instance.prune()
            return self.instance
        return self

    def evaluate_lazily(self, env: Optional[Any] = None) -> QType:
        pruned = self.prune()
        if pruned is not self:
            return pruned.evaluate_lazily(env)
        return self

    def substitute(self, subst: dict[int, QType]) -> QType:
        pruned = self.prune()
        if pruned is not self:
            return pruned.substitute(subst)
        return subst.get(self.symbol_id, self)

    def __str__(self) -> str:
        pruned = self.prune()
        if pruned is not self:
            return str(pruned)
        return self.name

    def __repr__(self) -> str:
        pruned = self.prune()
        if pruned is not self:
            return f"QTypeMeta({self.name} => {pruned!r})"
        return f"QTypeMeta({self.name})"


# ============================================================================
# 9. Equi-Recursive Subtyping and Type Equivalence
# ============================================================================

def is_type_equal(t1: QType, t2: QType, env: Optional[Any] = None) -> bool:
    """Checks equi-recursive type equivalence (t1 <: t2 and t2 <: t1)."""
    return is_subtype(t1, t2, env) and is_subtype(t2, t1, env)


def is_subtype(
    sub: QType,
    sup: QType,
    env: Optional[Any] = None,
    trail: Optional[set[tuple[int, int]]] = None,
) -> bool:
    """Checks if sub is a subtype of sup (sub <: sup) with coinductive cycle detection."""
    if trail is None:
        trail = set()

    # 1. Evaluate both types lazily to expose outermost constructors
    sub_lazy = sub.evaluate_lazily(env)
    sup_lazy = sup.evaluate_lazily(env)

    # 2. Reflexivity & identical instances
    if sub_lazy == sup_lazy:
        return True

    # 3. Metavariable resolution & unification
    if isinstance(sub_lazy, QTypeMeta):
        pruned = sub_lazy.prune()
        if pruned is not sub_lazy:
            return is_subtype(pruned, sup_lazy, env, trail)
        sub_lazy.instance = sup_lazy
        return True
    if isinstance(sup_lazy, QTypeMeta):
        pruned = sup_lazy.prune()
        if pruned is not sup_lazy:
            return is_subtype(sub_lazy, pruned, env, trail)
        sup_lazy.instance = sub_lazy
        return True

    # 4. Top types: in Quest, any proper type is a subtype of itself or upper bounds
    # 5. Coinductive trail check
    sub_id = getattr(sub_lazy, "symbol_id", id(sub_lazy))
    sup_id = getattr(sup_lazy, "symbol_id", id(sup_lazy))
    pair = (sub_id, sup_id)
    if pair in trail:
        return True
    trail.add(pair)

    # 6. Type Variable bound checking
    if isinstance(sub_lazy, (QTypeVar, QAbstractType)):
        if sub_lazy.bound and isinstance(sub_lazy.bound, QPowerKind):
            if is_subtype(sub_lazy.bound.bound, sup_lazy, env, trail):
                return True

    # 7. Tuples: length match, covariant in all fields
    if isinstance(sub_lazy, QTupleType) and isinstance(sup_lazy, QTupleType):
        if len(sub_lazy.elements) != len(sup_lazy.elements):
            return False
        return all(
            is_subtype(s_elem, t_elem, env, trail)
            for s_elem, t_elem in zip(sub_lazy.elements, sup_lazy.elements)
        )

    # 8. Records: width, depth, and mutable invariance
    if isinstance(sub_lazy, QRecordType) and isinstance(sup_lazy, QRecordType):
        for sup_field in sup_lazy.fields:
            sub_field = sub_lazy.get_field(sup_field.name)
            if sub_field is None:
                return False
            if sup_field.is_var:
                # Mutable record fields must be invariant
                if not sub_field.is_var:
                    return False
                if not (is_subtype(sub_field.type_val, sup_field.type_val, env, trail)
                        and is_subtype(sup_field.type_val, sub_field.type_val, env, trail)):
                    return False
            else:
                # Immutable fields are covariant
                if not is_subtype(sub_field.type_val, sup_field.type_val, env, trail):
                    return False
        return True

    # 9. Variants: sup must contain all tags of sub (width), payload covariance
    if isinstance(sub_lazy, QVariantType) and isinstance(sup_lazy, QVariantType):
        for sub_var in sub_lazy.variants:
            sup_var = sup_lazy.get_variant(sub_var.name)
            if sup_var is None:
                return False
            if sub_var.type_val is not None:
                if sup_var.type_val is None:
                    return False
                if sub_var.is_var or sup_var.is_var:
                    if not (is_subtype(sub_var.type_val, sup_var.type_val, env, trail)
                            and is_subtype(sup_var.type_val, sub_var.type_val, env, trail)):
                        return False
                else:
                    if not is_subtype(sub_var.type_val, sup_var.type_val, env, trail):
                        return False
            elif sup_var.type_val is not None:
                return False
        return True

    # 10. Options: sup must contain all tags of sub, payload covariance
    if isinstance(sub_lazy, QOptionType) and isinstance(sup_lazy, QOptionType):
        for sub_opt in sub_lazy.options:
            sup_opt = sup_lazy.get_option(sub_opt.name)
            if sup_opt is None:
                return False
            if sub_opt.payload_type is not None:
                if sup_opt.payload_type is None:
                    return False
                if not is_subtype(sub_opt.payload_type, sup_opt.payload_type, env, trail):
                    return False
            elif sup_opt.payload_type is not None:
                return False
        return True

    # 11. Functions: contravariant params, covariant result
    if isinstance(sub_lazy, QFunType) and isinstance(sup_lazy, QFunType):
        if len(sub_lazy.params) != len(sup_lazy.params):
            return False
            if s_param.is_var or t_param.is_var:
                if s_param.is_var != t_param.is_var:
                    return False
                if not (is_subtype(t_param.type_val, s_param.type_val, env, trail)
                        and is_subtype(s_param.type_val, t_param.type_val, env, trail)):
                    return False
            elif s_param.is_out or t_param.is_out:
                if s_param.is_out != t_param.is_out:
                    return False
                # Covariant in output parameters: sub_param <: sup_param
                if not is_subtype(s_param.type_val, t_param.type_val, env, trail):
                    return False
            else:
                # Contravariant in value parameters: sup_param <: sub_param
                if not is_subtype(t_param.type_val, s_param.type_val, env, trail):
                    return False
        # Covariant in result type
        return is_subtype(sub_lazy.result_type, sup_lazy.result_type, env, trail)

    # 12. References (Var): invariant in element type
    if isinstance(sub_lazy, QVarType) and isinstance(sup_lazy, QVarType):
        return (is_subtype(sub_lazy.element_type, sup_lazy.element_type, env, trail)
                and is_subtype(sup_lazy.element_type, sub_lazy.element_type, env, trail))

    # 13. Arrays: invariant in element type
    if isinstance(sub_lazy, QArrayType) and isinstance(sup_lazy, QArrayType):
        return (is_subtype(sub_lazy.element_type, sup_lazy.element_type, env, trail)
                and is_subtype(sup_lazy.element_type, sub_lazy.element_type, env, trail))

    # 14. Out parameters: contravariant
    if isinstance(sub_lazy, QOutType) and isinstance(sup_lazy, QOutType):
        return is_subtype(sup_lazy.element_type, sub_lazy.element_type, env, trail)

    # 15. Universal Quantifiers (Kernel F<:): bounds must match, body covariant
    if isinstance(sub_lazy, QAllType) and isinstance(sup_lazy, QAllType):
        if len(sub_lazy.quantifiers) != len(sup_lazy.quantifiers):
            return False
        # Rename sup quantifiers to match sub quantifiers
        subst = {
            t_quant.symbol_id: QTypeVar(s_quant.name, s_quant.symbol_id, s_quant.bound)
            for s_quant, t_quant in zip(sub_lazy.quantifiers, sup_lazy.quantifiers)
        }
        for s_q, t_q in zip(sub_lazy.quantifiers, sup_lazy.quantifiers):
            t_bound_renamed = t_q.bound.substitute_types(subst)
            if not is_kind_equal(s_q.bound, t_bound_renamed, env):
                return False
        return is_subtype(sub_lazy.body, sup_lazy.body.substitute(subst), env, trail)

    return False


def is_kind_equal(k1: QKind, k2: QKind, env: Optional[Any] = None) -> bool:
    """Checks if two kinds are equivalent (k1 <= k2 and k2 <= k1)."""
    return is_subkind(k1, k2, env) and is_subkind(k2, k1, env)


def is_subkind(sub: QKind, sup: QKind, env: Optional[Any] = None) -> bool:
    """Checks if sub is a subkind of sup (sub <= sup) with Full Subkinding on Kinds."""
    sub_lazy = sub.evaluate_lazily(env)
    sup_lazy = sup.evaluate_lazily(env)

    # 1. Reflexivity
    if sub_lazy == sup_lazy:
        return True

    # 2. Power Kind to TYPE: POWER(T) <= TYPE (for any proper type T)
    if isinstance(sup_lazy, QTypeKind):
        if isinstance(sub_lazy, QPowerKind):
            return True

    # 3. Power to Power: POWER(S) <= POWER(T) iff S <: T
    if isinstance(sub_lazy, QPowerKind) and isinstance(sup_lazy, QPowerKind):
        return is_subtype(sub_lazy.bound, sup_lazy.bound, env)

    # 4. Higher-Order Operator Kinds (Full Subkinding on Kinds):
    # ALL(X :: K1) K2 <= ALL(Y :: K1') K2' iff K1' <= K1 and K2 <= K2'[Y -> X]
    if isinstance(sub_lazy, QAllKind) and isinstance(sup_lazy, QAllKind):
        # Contravariant in parameter kind
        if not is_subkind(sup_lazy.param_kind, sub_lazy.param_kind, env):
            return False
        # Rename Y to X in sup_lazy.result_kind
        renamed_sup_res = sup_lazy.result_kind.substitute_types({
            sup_lazy.param_id: QTypeVar(sub_lazy.param_name, sub_lazy.param_id)
        }).substitute_kinds({
            sup_lazy.param_id: QKindVar(sub_lazy.param_name, sub_lazy.param_id)
        })
        # Covariant in result kind
        return is_subkind(sub_lazy.result_kind, renamed_sup_res, env)

    return False


# ============================================================================
# 10. Kind Synthesis, Checking, and Well-Kindedness
# ============================================================================

class KindError(Exception):
    """Raised when kind synthesis, kind checking, or well-kindedness verification fails."""
    pass


def check_kind_well_formed(kind: QKind, env: Optional[Any] = None) -> None:
    """Verifies that a kind is well-formed according to Quest kind formation rules."""
    kind_lazy = kind.evaluate_lazily(env)
    if isinstance(kind_lazy, QTypeKind):
        return

    if isinstance(kind_lazy, QPowerKind):
        # Bound of a power kind MUST be a proper type of kind TYPE
        check_kind(kind_lazy.bound, TYPE_KIND, env)
        return

    if isinstance(kind_lazy, QAllKind):
        check_kind_well_formed(kind_lazy.param_kind, env)
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope(f"kind_param_{kind_lazy.param_name}")
            try:
                env.current_scope.declare_type(
                    TypeSymbol(
                        name=kind_lazy.param_name,
                        symbol_id=kind_lazy.param_id,
                        kind=kind_lazy.param_kind,
                    )
                )
                check_kind_well_formed(kind_lazy.result_kind, env)
            finally:
                env.pop_scope()
        else:
            check_kind_well_formed(kind_lazy.result_kind, env)
        return

    if isinstance(kind_lazy, QKindVar):
        if env is not None and hasattr(env, "lookup_kind_by_id"):
            sym = env.lookup_kind_by_id(kind_lazy.symbol_id)
            if sym is None:
                sym = env.lookup_kind(kind_lazy.name)
            if sym is None:
                raise KindError(f"Unbound kind variable '{kind_lazy.name}' (#{kind_lazy.symbol_id})")
        return


def check_kind(type_val: QType, expected_kind: QKind, env: Optional[Any] = None) -> None:
    """Checks that type_val has a kind that is a subkind of expected_kind."""
    synthesized = synth_kind(type_val, env)
    if not is_subkind(synthesized, expected_kind, env):
        raise KindError(
            f"Kind mismatch: type '{type_val}' has kind '{synthesized}', "
            f"which is not a subkind of expected kind '{expected_kind}'"
        )


def synth_kind(type_val: QType, env: Optional[Any] = None) -> QKind:
    """Synthesizes the most specific minimal kind K for type_val in the given environment."""
    # 1. Primitives
    if isinstance(type_val, (QIntType, QRealType, QBoolType, QCharType, QStringType,
                             QOkType, QDynamicType, QExceptionType)):
        return TYPE_KIND

    # 2. Tuples
    if isinstance(type_val, QTupleType):
        for elem in type_val.elements:
            check_kind(elem, TYPE_KIND, env)
        return TYPE_KIND

    # 3. Records
    if isinstance(type_val, QRecordType):
        for f in type_val.fields:
            check_kind(f.type_val, TYPE_KIND, env)
        return TYPE_KIND

    # 4. Variants
    if isinstance(type_val, QVariantType):
        for v in type_val.variants:
            if v.type_val is not None:
                check_kind(v.type_val, TYPE_KIND, env)
        return TYPE_KIND

    # 5. Options
    if isinstance(type_val, QOptionType):
        for opt in type_val.options:
            if opt.payload_type is not None:
                check_kind(opt.payload_type, TYPE_KIND, env)
        return TYPE_KIND

    # 6. Functions
    if isinstance(type_val, QFunType):
        for param in type_val.params:
            check_kind(param.type_val, TYPE_KIND, env)
        check_kind(type_val.result_type, TYPE_KIND, env)
        return TYPE_KIND

    # 7. References, Arrays, Out
    if isinstance(type_val, (QVarType, QArrayType, QOutType)):
        check_kind(type_val.element_type, TYPE_KIND, env)
        return TYPE_KIND

    # 8. Type Variables
    if isinstance(type_val, QTypeVar):
        if type_val.bound is not None:
            return type_val.bound
        if env is not None and hasattr(env, "lookup_type_by_id"):
            sym = env.lookup_type_by_id(type_val.symbol_id)
            if sym is None:
                sym = env.lookup_type(type_val.name)
            if sym is not None:
                return sym.kind
        raise KindError(f"Unbound type variable '{type_val.name}' (#{type_val.symbol_id})")

    # 9. Abstract Types
    if isinstance(type_val, QAbstractType):
        check_kind_well_formed(type_val.bound, env)
        return type_val.bound

    # 10. Metavariables
    if isinstance(type_val, QTypeMeta):
        pruned = type_val.prune()
        if pruned is not type_val:
            return synth_kind(pruned, env)
        return type_val.bound

    # 11. Polymorphic Types (All)
    if isinstance(type_val, QAllType):
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope("all_type")
            try:
                for q in type_val.quantifiers:
                    check_kind_well_formed(q.bound, env)
                    env.current_scope.declare_type(
                        TypeSymbol(name=q.name, symbol_id=q.symbol_id, kind=q.bound)
                    )
                check_kind(type_val.body, TYPE_KIND, env)
            finally:
                env.pop_scope()
        else:
            for q in type_val.quantifiers:
                check_kind_well_formed(q.bound, env)
            check_kind(type_val.body, TYPE_KIND, env)
        return TYPE_KIND

    # 12. Automorphic / Existential Types (Auto)
    if isinstance(type_val, QAutoType):
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope("auto_type")
            try:
                check_kind_well_formed(type_val.kind_bound, env)
                env.current_scope.declare_type(
                    TypeSymbol(
                        name=type_val.type_param,
                        symbol_id=type_val.symbol_id,
                        kind=type_val.kind_bound,
                    )
                )
                for f in type_val.signature:
                    check_kind(f.type_val, TYPE_KIND, env)
            finally:
                env.pop_scope()
        else:
            check_kind_well_formed(type_val.kind_bound, env)
            for f in type_val.signature:
                check_kind(f.type_val, TYPE_KIND, env)
        return TYPE_KIND

    # 13. Recursive Types (Rec) - non-unfolding
    if isinstance(type_val, QRecType):
        check_kind_well_formed(type_val.bound, env)
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope(f"rec_{type_val.var_name}")
            try:
                env.current_scope.declare_type(
                    TypeSymbol(
                        name=type_val.var_name,
                        symbol_id=type_val.symbol_id,
                        kind=type_val.bound,
                    )
                )
                check_kind(type_val.body, type_val.bound, env)
            finally:
                env.pop_scope()
        else:
            check_kind(type_val.body, type_val.bound, env)
        return type_val.bound

    # 14. Mutually Recursive Type Groups (QRecGroupType)
    if isinstance(type_val, QRecGroupType):
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope("rec_group")
            try:
                for b_name, b_id, b_kind, _ in type_val.bindings:
                    check_kind_well_formed(b_kind, env)
                    env.current_scope.declare_type(
                        TypeSymbol(name=b_name, symbol_id=b_id, kind=b_kind)
                    )
                for _, _, b_kind, b_body in type_val.bindings:
                    check_kind(b_body, b_kind, env)
            finally:
                env.pop_scope()
        return type_val.bindings[type_val.active_index][2]

    # 15. Type Operators (TypeFun)
    if isinstance(type_val, QTypeFun):
        if env is not None and hasattr(env, "push_scope"):
            from quest.env import TypeSymbol
            env.push_scope("type_fun")
            try:
                for formal in type_val.params:
                    check_kind_well_formed(formal.bound, env)
                    env.current_scope.declare_type(
                        TypeSymbol(name=formal.name, symbol_id=formal.symbol_id, kind=formal.bound)
                    )
                body_kind = synth_kind(type_val.body, env)
            finally:
                env.pop_scope()
        else:
            for formal in type_val.params:
                check_kind_well_formed(formal.bound, env)
            body_kind = synth_kind(type_val.body, env)

        result_kind = body_kind
        for formal in reversed(type_val.params):
            result_kind = QAllKind(
                param_name=formal.name,
                param_id=formal.symbol_id,
                param_kind=formal.bound,
                result_kind=result_kind,
            )
        return result_kind

    # 16. Type Application (TypeApp)
    if isinstance(type_val, QTypeApp):
        ctor_kind = synth_kind(type_val.constructor, env).evaluate_lazily(env)
        for arg in type_val.arguments:
            if not isinstance(ctor_kind, QAllKind):
                raise KindError(
                    f"Type application error: constructor '{type_val.constructor}' "
                    f"has non-operator kind '{ctor_kind}'"
                )
            check_kind(arg, ctor_kind.param_kind, env)
            # Substitute argument into remaining kind telescope
            ctor_kind = ctor_kind.result_kind.substitute_types({
                ctor_kind.param_id: arg
            }).evaluate_lazily(env)
        return ctor_kind

    raise KindError(f"Cannot synthesize kind for unknown type node '{type_val}'")


# ============================================================================
# 11. Canonical S-Expression Pretty Printer (qtype_dump)
# ============================================================================

def qtype_dump(item: Union[QType, QKind], indent: int = 0) -> str:
    """Formats a QType or QKind into a canonical 2-space indented S-expression string."""
    pad = "  " * indent
    if isinstance(item, (QIntType, QRealType, QBoolType, QCharType, QStringType,
                         QOkType, QDynamicType, QExceptionType, QTypeKind)):
        return f"({item.__class__.__name__})"

    if isinstance(item, QPowerKind):
        return f"({item.__class__.__name__}\n{pad}  :bound {qtype_dump(item.bound, indent + 1)})"

    if isinstance(item, QAllKind):
        return (
            f"({item.__class__.__name__}\n"
            f"{pad}  :param '{item.param_name}'\n"
            f"{pad}  :param_kind {qtype_dump(item.param_kind, indent + 1)}\n"
            f"{pad}  :result_kind {qtype_dump(item.result_kind, indent + 1)})"
        )

    if isinstance(item, (QTypeVar, QAbstractType, QKindVar)):
        return f"({item.__class__.__name__} '{item.name}' #{item.symbol_id})"

    if isinstance(item, QTupleType):
        elems = "\n".join(f"{pad}    {qtype_dump(elem, indent + 2)}" for elem in item.elements)
        return f"(QTupleType\n{pad}  :elements (\n{elems}\n{pad}  ))" if item.elements else "(QTupleType)"

    if isinstance(item, QRecordType):
        fields = "\n".join(
            f"{pad}    (QRecordField '{f.name}'{ ' :var' if f.is_var else '' } {qtype_dump(f.type_val, indent + 2)})"
            for f in item.fields
        )
        return f"(QRecordType\n{pad}  :fields (\n{fields}\n{pad}  ))" if item.fields else "(QRecordType)"

    if isinstance(item, QVariantType):
        variants = "\n".join(
            f"{pad}    (QVariantField '{v.name}'"
            + (f" {qtype_dump(v.type_val, indent + 2)}" if v.type_val else "")
            + ")"
            for v in item.variants
        )
        return f"(QVariantType\n{pad}  :variants (\n{variants}\n{pad}  ))" if item.variants else "(QVariantType)"

    if isinstance(item, QOptionType):
        options = "\n".join(
            f"{pad}    (QOptionField '{o.name}'"
            + (f" {qtype_dump(o.payload_type, indent + 2)}" if o.payload_type else "")
            + ")"
            for o in item.options
        )
        return f"(QOptionType\n{pad}  :options (\n{options}\n{pad}  ))" if item.options else "(QOptionType)"

    if isinstance(item, QFunType):
        params = "\n".join(
            f"{pad}    (QParam '{p.name}'{ ' :var' if p.is_var else '' }{ ' :out' if p.is_out else '' } "
            f"{qtype_dump(p.type_val, indent + 2)})"
            for p in item.params
        )
        return (
            f"(QFunType\n"
            f"{pad}  :params (\n{params}\n{pad}  )\n"
            f"{pad}  :result {qtype_dump(item.result_type, indent + 1)})"
        )

    if isinstance(item, (QVarType, QArrayType, QOutType)):
        return f"({item.__class__.__name__}\n{pad}  :element {qtype_dump(item.element_type, indent + 1)})"

    if isinstance(item, QAllType):
        quants = "\n".join(
            f"{pad}    (QQuantifier '{q.name}' #{q.symbol_id} {qtype_dump(q.bound, indent + 2)})"
            for q in item.quantifiers
        )
        return (
            f"(QAllType\n"
            f"{pad}  :quantifiers (\n{quants}\n{pad}  )\n"
            f"{pad}  :body {qtype_dump(item.body, indent + 1)})"
        )

    if isinstance(item, QTypeApp):
        args = "\n".join(f"{pad}    {qtype_dump(arg, indent + 2)}" for arg in item.arguments)
        return (
            f"(QTypeApp\n"
            f"{pad}  :constructor {qtype_dump(item.constructor, indent + 1)}\n"
            f"{pad}  :arguments (\n{args}\n{pad}  ))"
        )

    if isinstance(item, QRecType):
        return (
            f"(QRecType '{item.var_name}' #{item.symbol_id}\n"
            f"{pad}  :bound {qtype_dump(item.bound, indent + 1)}\n"
            f"{pad}  :body {qtype_dump(item.body, indent + 1)})"
        )

    if isinstance(item, QRecGroupType):
        bindings = "\n".join(
            f"{pad}    (Binding '{b[0]}' #{b[1]} {qtype_dump(b[2], indent + 2)} {qtype_dump(b[3], indent + 2)})"
            for b in item.bindings
        )
        return (
            f"(QRecGroupType :active '{item.current_name}'\n"
            f"{pad}  :bindings (\n{bindings}\n{pad}  ))"
        )

    if isinstance(item, QTypeMeta):
        pruned = item.prune()
        if pruned is not item:
            return f"(QTypeMeta {item.name} => {qtype_dump(pruned, indent)})"
        return f"(QTypeMeta {item.name})"

    return f"({item.__class__.__name__})"
