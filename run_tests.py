"""Quest Bootstrap Compiler Test Runner."""

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).parent.resolve()
TESTS_SOURCE_DIR = ROOT_DIR / "tests" / "source"
TESTS_GOLDEN_DIR = ROOT_DIR / "tests" / "golden"

PHASES = {
    "tokenize": {
        "runner": ROOT_DIR / "bootstrap" / "python" / "quest_tokenize.py",
        "golden_subdir": "tokenize",
    },
    "parse": {
        "runner": ROOT_DIR / "bootstrap" / "python" / "quest_parse.py",
        "golden_subdir": "parse",
    },
    "typed_ast": {
        "runner": ROOT_DIR / "bootstrap" / "python" / "quest_typed_ast.py",
        "golden_subdir": "typed_ast",
    },
}


def run_single_test(
    source_file: Path,
    phase_name: str,
    phase_config: dict,
    update_golden: bool = False,
    python_executable: str = sys.executable,
) -> bool:
    runner_script = phase_config["runner"]
    golden_dir = TESTS_GOLDEN_DIR / phase_config["golden_subdir"]
    golden_dir.mkdir(parents=True, exist_ok=True)
    out_file = golden_dir / f"{source_file.stem}.out"
    error_file = golden_dir / f"{source_file.stem}.error"

    # Run the phase tool
    command = [python_executable, str(runner_script), str(source_file)]
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
                    fromfile=f"golden/{phase_config['golden_subdir']}/{out_file.name}",
                    tofile=f"actual/{phase_config['golden_subdir']}/{out_file.name}",
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
    else:
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
                    fromfile=f"golden/{phase_config['golden_subdir']}/{error_file.name}",
                    tofile=f"actual/{phase_config['golden_subdir']}/{error_file.name}",
                )
                print("".join(diff))
                return False
        elif out_file.exists():
            print(
                f"  [FAIL] {phase_name}:{source_file.stem} "
                f"(unexpected compiler error, returncode={process.returncode}):\n{process.stderr.strip()}"
            )
            return False
        else:
            print(
                f"  [MISSING GOLDEN] {phase_name}:{source_file.stem} "
                f"(expected {error_file.relative_to(ROOT_DIR)})"
            )
            return False


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Run Quest golden tests across compiler phases.")
    arg_parser.add_argument(
        "--phase", choices=list(PHASES.keys()) + ["all"], default="all", help="Compiler phase to test."
    )
    arg_parser.add_argument("--test", help="Specific test name to run (e.g. 01_lexer_basics).")
    arg_parser.add_argument(
        "--update-golden", action="store_true", help="Overwrite golden files with actual test output."
    )
    arg_parser.add_argument(
        "--python",
        default="/opt/homebrew/opt/python@3.11/libexec/bin/python",
        help="Python binary to use.",
    )

    args = arg_parser.parse_args()

    # Fallback to sys.executable if specified python does not exist
    python_executable = args.python if os.path.exists(args.python) else sys.executable

    phases_to_run = list(PHASES.keys()) if args.phase == "all" else [args.phase]

    # Find source files
    source_files = sorted(TESTS_SOURCE_DIR.glob("*.quest"))
    if args.test:
        source_files = [
            source_file
            for source_file in source_files
            if source_file.stem == args.test or source_file.name == args.test
        ]

    if not source_files:
        print(f"No test files found matching criteria in {TESTS_SOURCE_DIR.relative_to(ROOT_DIR)}")
        return 1

    total_tests = 0
    passed_tests = 0

    print(f"Running tests with Python: {python_executable}")
    print(f"Phases: {', '.join(phases_to_run)}")
    print(f"Found {len(source_files)} test source file(s).\n")

    for phase in phases_to_run:
        config = PHASES[phase]
        print(f"=== Phase: {phase} ===")
        for source_file in source_files:
            total_tests += 1
            if run_single_test(
                source_file,
                phase,
                config,
                update_golden=args.update_golden,
                python_executable=python_executable,
            ):
                passed_tests += 1

    print(f"\nSummary: {passed_tests}/{total_tests} tests passed.")
    return 0 if passed_tests == total_tests else 1


if __name__ == "__main__":
    sys.exit(main())
