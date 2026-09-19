"""Quest Bootstrap Compiler Test Runner."""

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path

# Ensure bootstrap/python is importable
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR / "bootstrap" / "python"))

from quest.error_testing import run_error_test
from quest.pipeline import PhasePipeline, default_pipeline, full_pipeline

TESTS_SOURCE_DIR = ROOT_DIR / "tests" / "source"
TESTS_GOLDEN_DIR = ROOT_DIR / "tests" / "golden"
TESTS_ERRORS_DIR = ROOT_DIR / "tests" / "errors"
DRIVER_SCRIPT = ROOT_DIR / "bootstrap" / "python" / "quest_driver.py"


def golden_dir_for_phase(phase_name: str) -> Path:
    if phase_name in ("interpret", "run_c_compiled"):
        return TESTS_GOLDEN_DIR / "run"
    return TESTS_GOLDEN_DIR / phase_name


def pipeline_for_phase(phase_name: str) -> PhasePipeline:
    if phase_name in ("codegen_c", "run_c_compiled"):
        return full_pipeline()
    return default_pipeline()


def run_single_golden_test(
    source_file: Path,
    phase_name: str,
    update_golden: bool = False,
    python_executable: str = sys.executable,
) -> bool:
    golden_dir = golden_dir_for_phase(phase_name)
    golden_dir.mkdir(parents=True, exist_ok=True)
    out_file = golden_dir / f"{source_file.stem}.out"
    error_file = golden_dir / f"{source_file.stem}.error"

    # Execute driver with --stop-after <phase_name>
    command = [
        python_executable,
        str(DRIVER_SCRIPT),
        "--stop-after",
        phase_name,
        str(source_file),
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT_DIR / "bootstrap" / "python")

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )

    if update_golden:
        if process.returncode == 0:
            out_file.write_text(process.stdout, encoding="utf-8")
            if error_file.exists():
                error_file.unlink()
            print(f"  [UPDATED] {phase_name}:{source_file.stem} (.out)")
        else:
            error_file.write_text(process.stderr, encoding="utf-8")
            if out_file.exists():
                out_file.unlink()
            print(f"  [UPDATED] {phase_name}:{source_file.stem} (.error)")
        return True

    # Case 1: Process succeeded (returncode == 0)
    if process.returncode == 0:
        if out_file.exists():
            expected_output = out_file.read_text(encoding="utf-8")
            if process.stdout == expected_output:
                print(f"  [PASS] {phase_name}:{source_file.stem}")
                return True
            else:
                print(f"  [FAIL] {phase_name}:{source_file.stem} (stdout mismatch)")
                diff = difflib.unified_diff(
                    expected_output.splitlines(keepends=True),
                    process.stdout.splitlines(keepends=True),
                    fromfile=f"golden/{golden_dir.name}/{out_file.name}",
                    tofile=f"actual/{golden_dir.name}/{out_file.name}",
                )
                print("".join(diff))
                return False
        elif error_file.exists():
            print(
                f"  [FAIL] {phase_name}:{source_file.stem} "
                f"(expected compiler error in {error_file.name}, but command succeeded)"
            )
            return False
        else:
            print(
                f"  [MISSING GOLDEN] {phase_name}:{source_file.stem} "
                f"(expected {out_file.relative_to(ROOT_DIR)})"
            )
            return False

    # Case 2: Process failed (returncode != 0)
    if error_file.exists():
        expected_error = error_file.read_text(encoding="utf-8")
        if process.stderr == expected_error:
            print(f"  [PASS] {phase_name}:{source_file.stem} (expected error)")
            return True
        else:
            print(f"  [FAIL] {phase_name}:{source_file.stem} (stderr mismatch)")
            diff = difflib.unified_diff(
                expected_error.splitlines(keepends=True),
                process.stderr.splitlines(keepends=True),
                fromfile=f"golden/{golden_dir.name}/{error_file.name}",
                tofile=f"actual/{golden_dir.name}/{error_file.name}",
            )
            print("".join(diff))
            return False
    elif out_file.exists():
        print(f"  [FAIL] {phase_name}:{source_file.stem} (failed with returncode {process.returncode})")
        print(process.stderr)
        return False
    else:
        print(
            f"  [MISSING GOLDEN] {phase_name}:{source_file.stem} "
            f"(expected error golden in {error_file.relative_to(ROOT_DIR)})"
        )
        return False



def main() -> int:
    available_phases = [
        "tokenize",
        "parse",
        "typecheck",
        "interpret",
        "run_c_compiled",
    ]

    arg_parser = argparse.ArgumentParser(description="Run Quest compiler tests (golden outputs and error suites).")
    arg_parser.add_argument(
        "--phase", choices=available_phases + ["all"], default="all", help="Compiler phase to test."
    )
    arg_parser.add_argument(
        "--suite",
        choices=["golden", "errors", "all"],
        default="all",
        help="Test suite to run (default: all).",
    )
    arg_parser.add_argument(
        "--errors",
        action="store_true",
        help="Shorthand for --suite errors.",
    )
    arg_parser.add_argument("--test", "-k", help="Filter test name substring or exact filename.")
    arg_parser.add_argument(
        "--update-golden", action="store_true", help="Overwrite golden files with actual test output."
    )
    arg_parser.add_argument(
        "--python",
        default="/opt/homebrew/opt/python@3.11/libexec/bin/python",
        help="Python binary to use.",
    )

    args = arg_parser.parse_args()

    # Determine suite mode
    suite_mode = "errors" if args.errors else args.suite

    # Fallback to sys.executable if specified python does not exist
    python_executable = args.python if os.path.exists(args.python) else sys.executable

    phases_to_run = available_phases if args.phase == "all" else [args.phase]

    total_golden = 0
    passed_golden = 0
    total_errors = 0
    passed_errors = 0

    print(f"Running tests with Python: {python_executable}")
    print(f"Suite: {suite_mode}, Phases: {', '.join(phases_to_run)}\n")

    # 1. Run Golden Tests (if suite is 'golden' or 'all')
    if suite_mode in ("golden", "all"):
        source_files = sorted(TESTS_SOURCE_DIR.glob("*.quest"))
        if args.test:
            source_files = [
                sf for sf in source_files
                if args.test in sf.stem or args.test in sf.name
            ]

        if source_files:
            print("=== Golden Tests ===")
            for phase in phases_to_run:
                golden_dir = golden_dir_for_phase(phase)
                if not golden_dir.exists():
                    continue
                print(f"--- Phase: {phase} ---")
                for source_file in source_files:
                    total_golden += 1
                    if run_single_golden_test(
                        source_file,
                        phase,
                        update_golden=args.update_golden,
                        python_executable=python_executable,
                    ):
                        passed_golden += 1
            print()

    # 2. Run Inline Diagnostic Error Tests (if suite is 'errors' or 'all')
    if suite_mode in ("errors", "all"):
        error_phases_found = False
        for phase in phases_to_run:
            phase_error_dir = TESTS_ERRORS_DIR / phase
            if not phase_error_dir.exists():
                continue
            error_files = sorted(phase_error_dir.glob("*.quest"))
            if args.test:
                error_files = [
                    ef for ef in error_files
                    if args.test in ef.stem or args.test in ef.name
                ]
            if not error_files:
                continue

            if not error_phases_found:
                print("=== Diagnostic Error Tests ===")
                error_phases_found = True

            print(f"--- Phase: {phase} ---")
            pipeline = pipeline_for_phase(phase)
            precursors = pipeline.precursors_of(phase)
            for error_file in error_files:
                total_errors += 1
                passed, report = run_error_test(
                    source_file=error_file,
                    target_phase=phase,
                    precursor_phases=precursors,
                    python_executable=python_executable,
                    root_dir=ROOT_DIR,
                )
                if passed:
                    passed_errors += 1
                    print(f"  [PASS] {phase}:{error_file.stem}")
                else:
                    print(f"  [FAIL] {phase}:{error_file.stem}")
                    print(report)

    # Summary report
    total_tests = total_golden + total_errors
    total_passed = passed_golden + passed_errors

    print(f"\nSummary: {total_passed}/{total_tests} tests passed.")
    if suite_mode == "all":
        print(f"  Golden tests: {passed_golden}/{total_golden} passed")
        print(f"  Error tests:  {passed_errors}/{total_errors} passed")

    return 0 if total_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(main())
