"""Build logging infrastructure for Quest compiler driver and build engine."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class BuildLogger:
    """Records timestamped build events to an audit log file and optionally streams to stderr."""

    def __init__(
        self,
        log_file: Optional[Path] = None,
        verbose: bool = False,
    ) -> None:
        self.log_file = log_file
        self.verbose = verbose
        if self.log_file is not None:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, tag: str, message: str) -> None:
        """Formats and logs a tagged build event."""
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        entry = f"[{timestamp}] {tag}: {message}"
        if self.log_file is not None:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        if self.verbose:
            sys.stderr.write(entry + "\n")
            sys.stderr.flush()

    def close(self) -> None:
        """Flushes any pending output."""
        pass
