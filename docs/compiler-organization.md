# Organization of the Self-Hosted Quest Compiler and Interpreter

This document specifies the directory, module, and type architecture for the **self-hosted Quest compiler and
interpreter** (`questlang`). The self-hosted system replaces the Python bootstrap implementation
(`bootstrap/python/quest/`) with clean, modular Quest code organized as an acyclic directed graph of interfaces
(`.int.quest`) and module implementations (`.mod.quest`).

---

## 1. Design Principles

1. **Strictly Acyclic Dependencies:** Cardelli's module system forbids mutual/cyclic dependencies between interfaces.
   The subsystem hierarchy is strictly layered: lower layers never import from higher layers.
2. **Deep, Cohesive Module Hierarchy:** Rather than large monolithic files, functionality is divided into focused,
   single-responsibility modules across up to three directory levels.
3. **Algebraic Data Types via `Option`:** Every AST and semantic model variant is defined as an `Option` type with
   case tags and payload records/tuples.
4. **Valid Quest Identifier Syntax:** Quest type names cannot contain underscores (`_`). All type names use `CamelCase`
   (e.g., `Expr`, `TypeExpr`, `TokenKind`, `AstPrint`).
5. **Data-Driven PEG Parser:** The parser decouples grammar rules, PEG parsing engine, and AST construction actions.
6. **Uncurried Value Arguments by Default:** Standard operations take uncurried value argument lists (`f(a b c)`),
   reserving currying for type parameter groups (`f(A::TYPE)(...)`) and higher-order combinators.
7. **Strict Minimization of `dynamic.T`:** A primary architectural goal is to use `dynamic.T` only where strictly
   necessary, such as serializing data structures externally. Everywhere else within the compiler and interpreter,
   Quest-native algebraic data types (`Option`) and records must always be used.

---

## 2. Subsystem Layout and Directory Structure

All self-hosted compiler and interpreter source code lives under the `questlang/` directory with module path prefixes
starting with `questlang/`.

```
questlang/
├── common/                  # Cross-cutting foundational utilities
│   ├── location             # Source coordinates (Pos, Span)
│   ├── diagnostics          # Diagnostic messages, error severity
│   └── diagbag              # Diagnostic accumulator and reporter
│
├── syntax/                  # Concrete syntax and parsing
│   ├── tokens               # TokenKind and Token definitions
│   ├── tokenizer            # Lexical scanner
│   ├── ast/                 # Abstract syntax tree definitions (Option types)
│   │   ├── expr             # Expression AST nodes (Expr)
│   │   ├── type             # Syntactic type expressions (TypeExpr)
│   │   ├── decl             # Declarations (Decl)
│   │   ├── module           # Interfaces, modules, imports, exports (ModuleAst)
│   │   └── phrase           # Top-level phrases and REPL commands (Phrase)
│   ├── astprint/            # AST pretty-printers (debugging & diagnostics)
│   │   ├── expr             # Expression formatting
│   │   ├── type             # Type expression formatting
│   │   └── decl             # Declaration formatting
│   └── parser/              # Data-driven PEG / Packrat parser
│       ├── engine           # Generic PEG engine (Construct, SyntaxTarget, Rule, Memo)
│       ├── rules/           # Grammar rule definitions
│       │   ├── expr         # Expression and operator grammar rules
│       │   ├── type         # Type expression grammar rules
│       │   ├── decl         # Declaration grammar rules
│       │   └── module       # Interface and module grammar rules
│       └── actions/         # Semantic action callbacks constructing AST nodes
│           ├── expr         # Expression AST construction
│           ├── type         # Type AST construction
│           ├── decl         # Declaration AST construction
│           └── module       # Module AST construction
│
├── types/                   # Semantic type system model
│   ├── kind                 # Kind representations (Kind)
│   ├── model                # Semantic type representations (Type)
│   ├── env                  # Lexical scoping and type/term environments
│   ├── subtyping            # Cardelli subtyping judgments and bound checks
│   ├── normalize            # Type normalization and expansion
│   └── builtins             # Predefined basic types and root interface models
│
├── typecheck/               # Typechecker and semantic elaboration
│   ├── typedast             # Type-annotated AST nodes
│   ├── elaborate            # Syntactic TypeExpr -> semantic Type transformation
│   ├── checkexpr            # Expression typechecking and bidirectional inference
│   ├── checkdecl            # Declaration typechecking
│   └── pattern              # Pattern matching exhaustiveness and reachability
│
├── modules/                 # Module system, dependency DAG, and linking
│   ├── modid                # Hierarchical module paths and alias management
│   ├── loader               # Filesystem module discovery and reading (QUESTPATH)
│   ├── graph                # Dependency DAG construction, topological sort, cycle check
│   ├── interfacecheck       # Module-to-interface conformance verification
│   └── linker               # Compilation unit assembly and pre-linking
│
├── eval/                    # Tree-walking interpreter & runtime environment
│   ├── value                # Runtime value representations (Val)
│   ├── env                  # Runtime evaluation frames and closures
│   ├── eval                 # Tree-walking evaluator
│   ├── builtins             # Native execution hooks for stdlib interfaces
│   └── dynamic              # Dynamic type boxing and JSON serialization
│
├── codegen/                 # C code generator targeting C99
│   ├── cmodel               # C intermediate representation
│   ├── ctypes               # Quest-to-C type mapping and representation strategy
│   ├── cclosure             # Closure capture analysis and environment layout
│   ├── cdecl                # C typedefs, struct declarations, function prototypes
│   ├── cemit                # C99 code emission for statements and expressions
│   └── crunner              # C compiler invocation (clang/gcc) and linking
│
└── driver/                  # Compiler pipeline and CLI driver
    ├── options              # Command-line option parsing (using util/argparse)
    ├── pipeline             # Multi-phase execution orchestrator
    └── main                 # Top-level executable entry point
```

---

## 3. AST Representation and Design

In Quest, type names must be alphanumeric and cannot contain underscores (`_`). Furthermore, the term "Kind" has a
precise, formal meaning in Quest's type system (kinds are the "types of types", such as `TYPE`). To avoid semantic
confusion, syntactic AST variants are named **`Form`** (e.g. `ExprForm`, `TypeExprForm`). AST categories are modeled
as parameterized `Node` records wrapping distinct `Option` forms in sub-modules under `questlang/syntax/ast/`.

### 3.1. Parameterized Node Wrapper (`Node(Form)`)

To ensure uniform source location tracking without code duplication, every AST node is represented as a parameterized
record holding a common `span` and a category-specific syntactic form:

```quest
Let Node(Form::TYPE) = Record
    span: location.Span,
    form: Form
end;
```

#### Trade-off Analysis: Parameterized `Node(Form)` vs. Flat Variants

- **Pros:**
  1. *Uniform Span Access:* Operations like diagnostic reporting, error formatting, and source mapping access
     `node.span` directly in $O(1)$ without writing 20+ arm `case` expressions just to extract the location.
  2. *DRY Variant Definitions:* Variant payloads in `ExprForm`, `TypeExprForm`, etc., define only their syntactic
     payloads without repeating `span: location.Span` in 40+ variant records.
  3. *Shared Node Metadata:* Common metadata (node IDs, comments, docstrings, or type annotations) can be added once
     to `Node` without modifying every individual variant.
  4. *Generic Utilities:* Diagnostic and source map utilities can accept any `Node(F)` generically.
  5. *Zero Collision with Type Kinds:* Naming the variant `form` (`node.form`) cleanly decouples AST structure from
     Quest's semantic `Kind` system.
- **Cons:**
  1. *Two-level matching:* Matching requires `case node.form of ... end` rather than matching on `node`
     directly.
  2. *Constructor wrapping:* Creating a node requires wrapping the variant in the outer record (mitigated with helper
     functions like `makeExpr(span form)`).
  3. *C runtime indirection:* An outer record pointing to an inner variant introduces an extra pointer indirection in
     the C runtime compared to a flat variant.

**Decision:** The parameterized `Node(Form)` design is adopted for its decisive advantages in diagnostic precision,
simplicity of variant definitions, and elimination of boilerplate across the compiler.

### 3.2. Expression Nodes (`questlang/syntax/ast/expr`)
```quest
Let ExprForm = Option
    literal with val: Token end,
    var with name: String end,
    app with funExpr: Expr argExpr: Expr end,
    record with fields: vector.T(FieldBinding) end,
    tuple with elements: vector.T(Expr) end,
    select with target: Expr field: String end,
    subscript with target: Expr index: Expr end,
    ifExpr with cond: Expr thenBranch: Expr elseBranch: maybe.T(Expr) end,
    caseExpr with target: Expr arms: vector.T(CaseArm) elseArm: maybe.T(Expr) end,
    seq with statements: vector.T(Expr) end,
    assign with target: Expr val: Expr end
end;

Let Expr = Node(ExprForm);
```

### 3.3. Type Expression Nodes (`questlang/syntax/ast/type`)
```quest
Let TypeExprForm = Option
    ident with name: String end,
    funType with domain: vector.T(ParamSig) range: TypeExpr end,
    recordType with fields: vector.T(FieldSig) end,
    tupleType with elements: vector.T(TypeExpr) end,
    variantType with tags: vector.T(VariantSig) end,
    optionType with tags: vector.T(OptionSig) end,
    appType with target: TypeExpr arg: TypeExpr end
end;

Let TypeExpr = Node(TypeExprForm);
```

### 3.4. Declaration Nodes (`questlang/syntax/ast/decl`)
```quest
Let DeclForm = Option
    letVal with name: String typeAnn: maybe.T(TypeExpr) init: Expr end,
    letRec with bindings: vector.T(RecBinding) end,
    letType with name: String kindAnn: maybe.T(KindExpr) defType: TypeExpr end,
    valSig with name: String typeExpr: TypeExpr end,
    typeSig with name: String kindExpr: KindExpr end
end;

Let Decl = Node(DeclForm);
```

---

## 4. Parser Architecture: Decoupled Data-Driven PEG

The parser preserves the architecture of the Python implementation (`bootstrap/python/quest/parser.py` and
`grammar.py`), separating:
1. **Engine (`questlang/syntax/parser/engine`):** Generic PEG parser combinators (`MatchToken`, `SyntaxTarget`,
   `Optional`, `Repeated`, `Sequence`) and packrat memoization tables.
2. **Rules (`questlang/syntax/parser/rules/*`):** Declarative definitions of grammar non-terminals and production rules.
3. **Actions (`questlang/syntax/parser/actions/*`):** Semantic action callbacks that transform matched tokens and child
   nodes into concrete AST objects.

### 4.1. Intermediate Semantic Values (`SemanticVal`)
In accordance with Principle 7 (minimizing `dynamic.T`), intermediate values produced by PEG combinators use a
dedicated sum type (`Option`) rather than dynamic boxing:

```quest
Let SemanticVal = Option
    none,
    tok with val: tokens.Token end,
    expr with val: ast/expr.Expr end,
    typeExpr with val: ast/type.TypeExpr end,
    decl with val: ast/decl.Decl end,
    phrase with val: ast/phrase.Phrase end,
    list with val: vector.T(SemanticVal) end,
    opt with val: maybe.T(SemanticVal) end
end;
```
This provides complete static type safety, avoids runtime boxing/unboxing overhead, and allows clean pattern matching
in semantic actions.

### 4.2. Packrat Memoization & Syntax Target Identification
Syntax targets (`SyntaxTarget`) are identified by instance identity using machine addresses (`identityHash`),
matching Quest's `is` / `isnot` semantics. The packrat memoization table in `parser/engine` maps:
```quest
(target: SyntaxTarget, pos: Int) -> maybe.T(MemoEntry)
```
using `identityHash` and `is` for $O(1)$ lookup and linear-time parsing guarantees.

---

## 5. Topological Dependency Layers

Module imports strictly respect the following layered DAG:

```
Layer 0: [questlang/common]
             ↓
Layer 1: [questlang/syntax/tokens] → [questlang/syntax/tokenizer]
             ↓
Layer 2: [questlang/syntax/ast/*]
             ↓
Layer 3: [questlang/syntax/astprint/*] ← [questlang/syntax/parser/*]
             ↓
Layer 4: [questlang/types/*] (kind, model, env, builtins, subtyping)
             ↓
Layer 5: [questlang/typecheck/*] (elaborate, checkexpr, checkdecl, pattern)
             ↓
Layer 6: [questlang/modules/*] (modid, loader, graph, interfacecheck, linker)
             ↓
┌────────────────────────────┴────────────────────────────┐
↓                                                         ↓
Layer 7a: [questlang/eval/*] (interpreter)    Layer 7b: [questlang/codegen/*] (C emitter)
└────────────────────────────┬────────────────────────────┘
                             ↓
Layer 8:  [questlang/driver/*] (options, pipeline, main)
```

---

## 6. Phased Implementation Milestones

Porting will proceed through four self-contained milestones. Each milestone will be broken into multiple incremental,
testable steps:

### Milestone 1: Frontend & Syntax (`common` and `syntax`)
- **Step 1.1:** `questlang/common/location`, `diagnostics`, `diagbag`.
- **Step 1.2:** `questlang/syntax/tokens` and `questlang/syntax/tokenizer`
  (verified against existing `tokenize` goldens).
- **Step 1.3:** `questlang/syntax/ast/*` and `questlang/syntax/astprint/*`.
- **Step 1.4:** `questlang/syntax/parser/engine` (generic PEG engine with memoization).
- **Step 1.5:** Grammar rules and actions for types and declarations.
- **Step 1.6:** Grammar rules and actions for expressions, operators, and full modules
  (verified against `parse` goldens).

### Milestone 2: Types & Typechecking (`types` and `typecheck`)
- **Step 2.1:** Semantic `kind`, `model` (Cardelli types), and lexical `env`.
- **Step 2.2:** `subtyping` rules (Cardelli subtyping judgments, bound checking, and recursion contractiveness).
- **Step 2.3:** `elaborate` (syntactic `TypeExpr` $\to$ semantic `Type`).
- **Step 2.4:** `builtins` (initial typing environment and root interface signatures).
- **Step 2.5:** `checkexpr` and `checkdecl` bidirectional typechecker.
- **Step 2.6:** `pattern` exhaustiveness analysis for `case` expressions (verified against `typecheck` goldens).

### Milestone 3: Modules & Interpreter (`modules` and `eval`)
- **Step 3.1:** `modules/modid`, `loader`, and `graph` (dependency DAG and cycle validation).
- **Step 3.2:** `modules/interfacecheck` and `linker`.
- **Step 3.3:** `eval/value`, `env`, and `eval_builtins`.
- **Step 3.4:** `eval/eval` tree-walking evaluator (verified against `interpret` goldens).
- **Step 3.5:** `eval/dynamic` serialization and interactive REPL.

### Milestone 4: C Code Generation & Self-Hosting (`codegen` and `driver`)
- **Step 4.1:** `codegen/cmodel` and `codegen/ctypes` (boxing, unboxing, struct layouts).
- **Step 4.2:** `codegen/cclosure` (capture analysis and closure record generation).
- **Step 4.3:** `codegen/cdecl` and `codegen/cemit` (emitting clean C99).
- **Step 4.4:** `codegen/crunner` (compiler driver and runtime linking).
- **Step 4.5:** `driver/options`, `pipeline`, and `main` entrypoint.
- **Step 4.6:** Complete self-hosting verification (`questc` compiling `questc`).

---

### 6.1. Milestone 1 Verification Strategy

Rather than building a full test runner in Quest immediately, Milestone 1 will be validated directly using the existing
Python test runner (`run_tests.py`) via focused Quest CLI driver harnesses:
- `tests/questlang_tokenize.quest`: A small driver that invokes `questlang/syntax/tokenizer` and emits token outputs
  matching the exact format of `tests/golden/tokenize/*.out`.
- `tests/questlang_parse.quest`: A small driver that invokes `questlang/syntax/parser` and formats AST outputs matching
  `tests/golden/parse/*.out`.

This allows `run_tests.py --phase tokenize` and `run_tests.py --phase parse` to verify the self-hosted frontend
against all existing language tests before moving to Milestone 2.
