# Quest Compiler Testing Framework

This document describes the testing architecture for the Quest bootstrap compiler, including unit tests, golden-file
end-to-end tests for valid programs, and diagnostic inline-comment tests for invalid programs.

---

## 1. Overview of Test Suites

The compiler test suite is organized into three complementary testing tiers:

1. **Python Unit Tests (`tests/python/`):**
   - Fine-grained unit tests written in Python using `unittest`.
   - Verifies individual compiler modules, functions, algorithms, and data structures:
     - `test_types_and_env.py`: Scopes, symbol tables, kind well-formedness, subkinding.
     - `test_typechecker.py`: Term elaboration, bidirectional typing (`check_expr` / `synth_expr`), contractiveness.
     - `test_diagnostics.py`: Structured diagnostics, `DiagnosticSink`, severities, formatters.
     - `test_typed_ast.py`: Typed AST node constructors, S-expression serialization.
     - `test_phase3_functions.py` through `test_phase6_modules_interfaces.py`: High-level feature-specific tests.
   - Run via:
     ```bash
     PYTHONPATH=bootstrap/python python3 -m unittest discover -s tests/python
     ```

2. **Golden-File Compiler Tests (`tests/source/` and `tests/golden/`):**
   - End-to-end tests for valid Quest programs.
   - Executes the unified compiler driver (`quest_driver.py --stop-after <phase>`) against
     canonical `.quest` source files.
   - Validates stdout against exact expected outputs in `tests/golden/<phase>/<name>.out`.

3. **Diagnostic & Error Tests (`tests/errors/`):**
   - Negative tests for invalid programs containing deliberate syntax, lexical, or type errors.
   - Avoids fragile exact-match terminal formatting goldens by embedding inline expectation directives in comments
     within the source file.
   - Enforces precursor phase validity and strict bidirectional 1:1 matching between expected and actual diagnostics.

---

## 2. Golden-File Testing Framework

### 2.1. Directory Structure

```
tests/
  ├── source/
  │   ├── 01_lexer_basics.quest
  │   ├── 02_expressions_control_flow.quest
  │   ├── 03_functions_closures.quest
  │   ├── 04_records_variants_options.quest
  │   ├── 05_types_operators.quest
  │   ├── 06_interfaces_modules.quest
  │   └── 07_exceptions_dynamic.quest
  └── golden/
      ├── tokenize/
      │   └── 01_lexer_basics.out ... 07_exceptions_dynamic.out
      ├── parse/
      │   └── 01_lexer_basics.out ... 07_exceptions_dynamic.out
      └── typecheck/
          └── 01_lexer_basics.out ... 07_exceptions_dynamic.out
```

### 2.2. Standard Output and Exit Code Discipline
- **Valid Programs:** Must complete successfully with exit code 0. Standard output is captured and verified against
  the corresponding `<test>.out` file.
- **Output Streams:**
  - `stdout`: Used exclusively for valid phase artifacts (e.g. token tables, AST S-expressions, typed AST dumps).
  - `stderr`: Reserved exclusively for diagnostic error messages and warnings.

### 2.3. Test Runner (`run_tests.py`)
The test runner executes each test source file across all active compiler phases via `quest_driver.py`:
- `tokenize`: Runs `quest_driver.py --stop-after tokenize <source_file>`.
- `parse`: Runs `quest_driver.py --stop-after parse <source_file>`.
- `typecheck`: Runs `quest_driver.py --stop-after typecheck <source_file>`.

**Commands:**
```bash
# Run all golden tests across all phases
python3 run_tests.py

# Run only a specific phase
python3 run_tests.py --phase typecheck

# Run only matching tests
python3 run_tests.py -k 03_functions

# Update golden files after an intentional AST or grammar change
python3 run_tests.py --update-golden
```

If stdout does not match the golden file, `run_tests.py` prints a unified diff detailing the exact mismatch.

---

## 3. Diagnostic & Error Testing Framework (`tests/errors/`)

### 3.1. Design Motivation
Exact-match golden files for error reporting are fragile: cosmetic adjustments to terminal box-drawing characters,
line gutters, column pointers, color ANSI sequences, or minor wording changes in help text break all golden files,
even when compiler diagnostic semantics remain correct.

The diagnostic testing framework tests errors semantically using **inline expectation comments** directly inside the
failing test source files.

### 3.2. Directory Structure and Phase Scoping

Error tests are organized by the specific compiler phase responsible for detecting and reporting the error:

```
tests/errors/
  ├── tokenize/
  │   ├── invalid_character.quest
  │   └── unclosed_string.quest
  ├── parse/
  │   ├── missing_end.quest
  │   └── invalid_infix.quest
  └── typecheck/
      ├── non_contractive_rec.quest
      ├── record_field_mismatch.quest
      └── unhandled_exception.quest
```

### 3.3. Inline Expectation Syntax

Expected diagnostics are declared using standard Quest block comments (`(* ... *)`) placed directly on the line where
the diagnostic is expected:

```
(* <SEVERITY>: <REGEXP> *)
```

- `<SEVERITY>`: One of `ERROR`, `WARNING`, `INFO`, `FATAL` (case-insensitive).
- `<REGEXP>`: A regular expression pattern matched against the diagnostic's primary `message`, `notes`, or `help_text`.

#### Examples
```quest
(* tests/errors/typecheck/non_contractive_rec.quest *)
Let Rec Bad::TYPE = Bad; (* ERROR: not contractive *)

(* tests/errors/typecheck/type_mismatch.quest *)
let x: Int = "hello"; (* ERROR: type mismatch.*expected 'Int' *)

(* tests/errors/typecheck/warnings.quest *)
let unused = 42; (* WARNING: unused variable 'unused' *)
```

### 3.4. Precursor Phase Validation
A test in `tests/errors/<phase>/` must contain errors **only in `<phase>`**.

When running a test for `<phase>`:
1. The runner executes all precursor phases in order (e.g. for `typecheck`, it first runs `tokenize` and `parse`).
2. If any precursor phase produces an error, the test fails immediately:
   ```
   [FAIL] typecheck:tests/errors/typecheck/bad_syntax.quest
     Precursor phase 'parse' failed unexpectedly before reaching 'typecheck':
     test.quest:2:5: error: syntax error, expected 'end'
   ```
This enforces independence of concerns and ensures tests do not pass accidentally due to earlier unintended failures.

### 3.5. Bidirectional 1:1 Diagnostic Matching
To prevent silent regressions (such as cascading poison errors or unverified warnings), the runner enforces exact
bidirectional matching:

1. **Every Expected Diagnostic Must Be Found:** Every inline expectation `(* SEVERITY: REGEXP *)` on line $N$ must
   match an actual diagnostic emitted with that severity on line $N$.
2. **Every Actual Diagnostic Must Be Expected:** Every diagnostic emitted by the compiler in the tested phase must
   match one of the declared inline expectations.
3. If any expected diagnostic is missing, or any unexpected diagnostic is emitted, the test fails with a clear diff.

---

## 4. Summary of Test Commands

| Test Suite | Purpose | Execution Command |
| :--- | :--- | :--- |
| **Unit Tests** | Module & algorithm verification | `python3 -m unittest discover -s tests/python` |
| **Golden Tests** | Valid end-to-end outputs | `python3 run_tests.py` |
| **Error Tests** | Semantic diagnostic verification | `python3 run_tests.py --errors` |
| **Update Goldens** | Refresh golden output files | `python3 run_tests.py --update-golden` |
