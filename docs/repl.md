# Quest Interactive REPL

This document describes the Quest interactive Read-Eval-Print Loop (REPL), its execution modes, input buffering
rules, prompt formatting, terminal handling, and error recovery.

---

## 1. Overview

The Quest REPL provides an interactive top-level environment for evaluating Quest expressions, defining variables and
functions, importing modules, and experimenting with types.

Key features:
- **Persistent Lexical and Dynamic Environments:** Types, bindings, and modules defined in one phrase remain in scope
  for subsequent phrases.
- **Semicolon-Optional Multi-line Buffering:** Evaluates syntactically complete phrases immediately. If input is
  incomplete (e.g. open block, unclosed delimiter, or missing operand), the REPL automatically prompts for continuation
  lines until the phrase is closed. Semicolons are supported but optional.
- **Uniform 4-Column Alignment:** Clean visual structure using 4-character prompts and response prefixes.
- **Transactional Error Rollback:** If a phrase fails typechecking or raises an uncaught runtime exception, any partial
  environment bindings from that phrase are rolled back, preserving a consistent environment.
- **Terminal & History Safety:** Full GNU `readline` line editing and history saved to `~/.quest_history`, with
  automatic fallback/bypass for `dumb` and `emacs` terminals.

---

## 2. Invocation Modes

### 2.1. Direct REPL Launch
Running `quest` without arguments from an interactive terminal (TTY) enters the REPL directly:

```bash
$ quest
>>  let a = 10
==  let a:Int = 10
>>  a * 4
==  40 : Int
```

### 2.2. Interactive Mode with File (`-i` / `--interactive`)
The `-i` and `--interactive` flags execute a file through the compiler pipeline first, and if successful, drop into
the REPL with the file's bindings and types in scope:

```bash
$ quest -i tests/source/03_functions_closures.quest
>>  apply(add1 100)
==  101 : Int
>>  adder(5)(10)
==  15 : Int
```

If the loaded file contains a compile error (syntax, kind, or type error) or encounters an uncaught runtime exception,
the diagnostic is emitted to `stderr` and the process exits immediately with code `1` without launching the REPL.

---

## 3. Prompts & Visual Formatting

The REPL enforces strict 4-character columnar alignment:

| Element | String | Meaning |
| :--- | :--- | :--- |
| **Main Prompt** | `">>  "` | Ready for a new top-level phrase. |
| **Continuation Prompt** | `"    "` | 4 blank spaces; input is incomplete and waiting for closing syntax. |
| **Response Prefix** | `"==  "` | Prefixes the evaluated result of each non-`ok` phrase. |

### 3.1. Single-Line and Semicolon Behavior
Semicolons are optional at phrase boundaries. Both forms are valid:

```quest
>>  let x = 1
==  let x:Int = 1
>>  let y = 2;
==  let y:Int = 2
```

Multiple phrases separated by semicolons on a single line are evaluated sequentially, and each non-`ok` phrase outputs
its result on its own line prefixed with `"==  "`:

```quest
>>  let x = 1; let y = 2; x + y
==  let x:Int = 1
==  let y:Int = 2
==  3 : Int
```

### 3.2. Multi-line Input & Heuristics
When a line ends while a construct is open (such as a function body, `if...then`, `loop`, `try`, `record`, or open
parenthesis), the REPL presents the continuation prompt (`"    "`):

```quest
>>  let rec fib(n: Int): Int =
        if n <= 1 then
            n
        else
            fib(n - 1) + fib(n - 2)
        end
==  let fib:All(n:Int):Int = <fun>
>>  fib(10)
==  55 : Int
```

The continuation heuristic checks:
1. **Lexical scanning:** If the tokenizer encounters an unterminated string literal or unclosed comment at EOF, it
   continues prompting.
2. **Grammar parsing:** If the parser reaches `EOF` while expecting a closing token or operand, it continues prompting.
3. **Syntax errors:** If a syntax error occurs on a non-EOF token (e.g. `let 123 = 4`), the diagnostic is emitted
   immediately, the buffer is cleared, and the REPL resets to `">>  "`.

### 3.3. Silent `ok` Phrases
Statements and expressions that evaluate to `ok` (assignments, loops, imports, or explicit `ok;`) produce no output:

```quest
>>  let var total = 0
==  let var total:Int = 0
>>  total := 42
>>  total
==  42 : Int
```

### 3.4. Multi-Line Output Formatting
When an evaluated phrase produces a multi-line formatted string (e.g. tuples or records), the first line is prefixed
with `"==  "` and subsequent lines are indented with 4 spaces (`"    "`):

```quest
>>  (1, "abc", true)
==  ( 1,
      "abc",
      true ) : Tuple(Int, String, Bool)
```

---

## 4. Terminal Support & History

### 4.1. History Persistence
Interactive inputs are automatically recorded to `~/.quest_history`. Up to 1,000 commands are saved across sessions.
Arrow keys (`Up`/`Down`) navigate history, and standard Emacs line editing shortcuts (`Ctrl-A`, `Ctrl-E`, `Ctrl-K`) are
supported via Python's `readline` library.

### 4.2. Dumb & Emacs Terminal Detection
If the terminal is not a TTY or if the `TERM` environment variable is set to `"dumb"`, `"emacs"`, or is empty,
`readline` escape sequences are disabled to avoid escape code corruption.

---

## 5. Error Recovery & Transactional Rollback

If a phrase fails during parsing, typechecking, or runtime evaluation:
1. A structured diagnostic is rendered to `stderr` with line and column pointers.
2. The environment is restored to its exact state prior to that phrase.
3. The session remains active and prompts for the next command.

Example:
```quest
>>  let a = 10
==  let a:Int = 10
>>  let a = 99; let b: Int = "type error"
<repl>:1:26: error: Type mismatch: synthesized type 'String' is not a subtype of expected type 'Int'
    let a = 99; let b: Int = "type error"
                             ^
>>  a
==  10 : Int
```

Notice `a` remains `10` because the failed line was rolled back transactionally.

---

## 6. Signals & Exit

- **`Ctrl-D` (EOF):** On an empty input line, exits the REPL cleanly with exit code `0`.
- **`Ctrl-C` (Interrupt):** Cancels the current multi-line input buffer without terminating the session, returning to
  `">>  "`.
