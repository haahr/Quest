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
) -> tuple[int, str, str]:
    """Executes the compiler driver up to the specified phase."""
    driver_script = root_dir / "bootstrap" / "python" / "quest_driver.py"
    command = [
        python_executable,
        str(driver_script),
        "--stop-after",
        phase_name,
        str(source_file),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_dir / "bootstrap" / "python")

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return process.returncode, process.stdout, process.stderr


def run_error_test(
    source_file: Path,
    target_phase: str,
    precursor_phases: list[str],
    python_executable: str,
    root_dir: Path,
    phase_configs: Optional[dict] = None,
) -> tuple[bool, str]:
    """Runs an error test with precursor validation and bidirectional 1:1 diagnostic matching."""
    source_text = source_file.read_text(encoding="utf-8")
    expected = extract_expected_diagnostics(source_text)

    if not expected:
        return False, f"Test file {source_file.name} defines no (* SEVERITY: REGEXP *) expectations"

    # Step 1: Precursor Phase Validation
    for pre_phase in precursor_phases:
        rc, _, stderr = execute_phase(pre_phase, source_file, python_executable, root_dir)
        if rc != 0 or parse_actual_diagnostics(stderr):
            err_msg = stderr.strip() if stderr.strip() else f"exited with code {rc}"
            return False, (
                f"Precursor phase '{pre_phase}' failed unexpectedly before reaching target phase '{target_phase}':\n"
                f"{err_msg}"
            )

    # Step 2: Target Phase Execution
    rc, stdout, stderr = execute_phase(target_phase, source_file, python_executable, root_dir)
    actual = parse_actual_diagnostics(stderr)

    # Step 3: Bidirectional 1:1 Matching
    unmatched_expected = list(expected)
    unmatched_actual = list(actual)

    for exp in expected:
        for act in list(unmatched_actual):
            if act.line == exp.line and act.severity == exp.severity:
                # Check regex match against message or full diagnostic block
                if re.search(exp.pattern, act.message, re.IGNORECASE) or re.search(
                    exp.pattern, act.full_text, re.IGNORECASE
                ):
                    unmatched_expected.remove(exp)
                    unmatched_actual.remove(act)
                    break

    if not unmatched_expected and not unmatched_actual:
        return True, ""

    # Format detailed failure report
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
