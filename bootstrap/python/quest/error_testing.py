"""Quest Compiler Error and Diagnostic Test Runner Framework."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ExpectedDiagnostic:
    """An expected diagnostic declared via an inline comment (* SEVERITY: REGEXP *)."""
    line: int
    severity: str
    pattern: str


@dataclass(frozen=True)
class ActualDiagnostic:
    """A diagnostic emitted by a compiler phase, parsed from stderr."""
    file_name: str
    line: int
    column: int
    severity: str
    message: str
    full_text: str


# Matches (* ERROR: ... *), (* WARNING: ... *), (* INFO: ... *), (* FATAL: ... *)
EXPECTATION_PATTERN = re.compile(
    r"\(\*\s*(ERROR|WARNING|INFO|FATAL)\s*:\s*(.*?)\s*\*\)",
    re.IGNORECASE,
)

# Matches standard compiler diagnostic header: file:line:col: severity: message
# or file:line:col: severity[code]: message
DIAGNOSTIC_HEADER_PATTERN = re.compile(
    r"^(.*?):(\d+):(\d+):\s*(error|warning|info|fatal)(?:\[.*?\])?:\s*(.*)$",
    re.IGNORECASE,
)


def extract_expected_diagnostics(source_text: str) -> list[ExpectedDiagnostic]:
    """Scans Quest source text for inline diagnostic expectations on each line."""
    expectations: list[ExpectedDiagnostic] = []
    for line_idx, line in enumerate(source_text.splitlines(), start=1):
        for match in EXPECTATION_PATTERN.finditer(line):
            severity = match.group(1).lower()
            pattern = match.group(2).strip()
            expectations.append(ExpectedDiagnostic(line=line_idx, severity=severity, pattern=pattern))
    return expectations


def extract_expected_patterns(error_golden_text: str) -> list[str]:
    """Scans .error golden file text for expected regex/substring patterns."""
    patterns: list[str] = []
    for line in error_golden_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def match_error_patterns(stderr_text: str, patterns: list[str]) -> tuple[bool, list[str]]:
    """Checks whether all expected pattern lines are present in stderr_text (literal or regex)."""
    unmatched: list[str] = []
    stderr_lower = stderr_text.lower()
    for pat in patterns:
        matched = False
        if pat.lower() in stderr_lower:
            matched = True
        else:
            try:
                if re.search(pat, stderr_text, re.IGNORECASE | re.MULTILINE):
                    matched = True
            except re.error:
                pass
        if not matched:
            unmatched.append(pat)
    return len(unmatched) == 0, unmatched


def format_canonical_error_golden(stderr_text: str) -> str:
    """Generates canonical pattern lines from stderr_text for --update-golden."""
    diags = parse_actual_diagnostics(stderr_text)
    if diags:
        lines = [f"{d.severity.lower()}: {d.message}" for d in diags]
        return "\n".join(lines) + "\n"
    # Fallback to non-empty lines from stderr
    clean_lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
    return "\n".join(clean_lines) + "\n"


def parse_actual_diagnostics(stderr_text: str) -> list[ActualDiagnostic]:
    """Parses compiler stderr output into a list of ActualDiagnostic objects."""
    diagnostics: list[ActualDiagnostic] = []
    lines = stderr_text.splitlines()
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        match = DIAGNOSTIC_HEADER_PATTERN.match(line)
        if match:
            file_name = match.group(1).strip()
            line_num = int(match.group(2))
            col_num = int(match.group(3))
            severity = match.group(4).lower()
            message = match.group(5).strip()

            # Collect subsequent lines that belong to this diagnostic (carets, notes, help)
            block_lines = [line]
            idx += 1
            while idx < len(lines) and not DIAGNOSTIC_HEADER_PATTERN.match(lines[idx]):
                block_lines.append(lines[idx])
                idx += 1

            full_text = "\n".join(block_lines)
            diagnostics.append(
                ActualDiagnostic(
                    file_name=file_name,
                    line=line_num,
                    column=col_num,
                    severity=severity,
                    message=message,
                    full_text=full_text,
                )
            )
        else:
            idx += 1

    return diagnostics


def execute_phase(
    phase_name: str,
    source_file: Path,
    python_executable: str,
    root_dir: Path,
    extra_args: Optional[list[str]] = None,
    env_vars: Optional[dict[str, str]] = None,
    stdin_data: Optional[str] = None,
) -> tuple[int, str, str]:
    """Executes the compiler driver up to the specified phase."""
    driver_script = root_dir / "bootstrap" / "python" / "quest_driver.py"
    command = [
        python_executable,
        str(driver_script),
        "--stop-after",
        phase_name,
    ]
    if extra_args:
        command.extend(extra_args)
    command.append(str(source_file))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_dir / "bootstrap" / "python")
    if env_vars:
        env.update(env_vars)

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        input=stdin_data,
        env=env,
    )
    return process.returncode, process.stdout, process.stderr


def run_error_test(
    source_file: Path,
    target_phase: str,
    precursor_phases: list[str],
    python_executable: str,
    root_dir: Path,
    golden_error_file: Optional[Path] = None,
    update_golden: bool = False,
    extra_args: Optional[list[str]] = None,
    env_vars: Optional[dict[str, str]] = None,
    stdin_data: Optional[str] = None,
    phase_configs: Optional[dict] = None,
) -> tuple[bool, str]:
    """Runs an error test with precursor validation and pattern-based or diagnostic matching."""
    # Step 1: Precursor Phase Validation
    for pre_phase in precursor_phases:
        rc, _, stderr = execute_phase(
            pre_phase, source_file, python_executable, root_dir,
            extra_args=extra_args, env_vars=env_vars, stdin_data=stdin_data,
        )
        if rc != 0 or parse_actual_diagnostics(stderr):
            err_msg = stderr.strip() if stderr.strip() else f"exited with code {rc}"
            return False, (
                f"Precursor phase '{pre_phase}' failed unexpectedly before reaching target phase '{target_phase}':\n"
                f"{err_msg}"
            )

    # Step 2: Target Phase Execution
    rc, stdout, stderr = execute_phase(
        target_phase, source_file, python_executable, root_dir,
        extra_args=extra_args, env_vars=env_vars, stdin_data=stdin_data,
    )
    if rc == 0:
        return False, f"Expected error in phase '{target_phase}', but command succeeded with return code 0"

    # Step 3: Golden Pattern Matching (or update)
    if golden_error_file is not None:
        if update_golden:
            golden_content = format_canonical_error_golden(stderr)
            golden_error_file.parent.mkdir(parents=True, exist_ok=True)
            golden_error_file.write_text(golden_content, encoding="utf-8")
            return True, "[UPDATED]"

        if golden_error_file.exists():
            patterns = extract_expected_patterns(golden_error_file.read_text(encoding="utf-8"))
            ok, unmatched = match_error_patterns(stderr, patterns)
            if ok:
                return True, ""
            report_lines = [f"  Expected patterns NOT found in stderr ({golden_error_file.name}):"]
            for pat in unmatched:
                report_lines.append(f"    - /{pat}/")
            report_lines.append("  Actual stderr was:")
            for line in stderr.strip().splitlines():
                report_lines.append(f"    | {line}")
            return False, "\n".join(report_lines)

    # Step 4: Fallback to inline (* ERROR: ... *) comments if golden file not present
    source_text = source_file.read_text(encoding="utf-8")
    expected = extract_expected_diagnostics(source_text)
    if not expected:
        if golden_error_file is not None:
            return False, f"Missing golden error file: {golden_error_file}"
        return False, f"Test file {source_file.name} defines no (* SEVERITY: REGEXP *) expectations"

    actual = parse_actual_diagnostics(stderr)
    unmatched_expected = list(expected)
    unmatched_actual = list(actual)

    for exp in expected:
        for act in list(unmatched_actual):
            if act.line == exp.line and act.severity == exp.severity:
                if re.search(exp.pattern, act.message, re.IGNORECASE) or re.search(
                    exp.pattern, act.full_text, re.IGNORECASE
                ):
                    unmatched_expected.remove(exp)
                    unmatched_actual.remove(act)
                    break

    if not unmatched_expected and not unmatched_actual:
        return True, ""

    report_lines = []
    if unmatched_expected:
        report_lines.append("  Expected diagnostics NOT found:")
        for exp in unmatched_expected:
            report_lines.append(f"    - line {exp.line}: {exp.severity.upper()}: /{exp.pattern}/")
    if unmatched_actual:
        report_lines.append("  Unexpected actual diagnostics emitted:")
        for act in unmatched_actual:
            report_lines.append(f"    - line {act.line}:{act.column}: {act.severity.upper()}: {act.message}")

    return False, "\n".join(report_lines)
