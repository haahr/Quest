"""Quest Diagnostic, Error, and Warning Reporting Pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(Enum):
    """Operational severity of a diagnostic message."""
    FATAL = "fatal"      # Unrecoverable error / Internal Compiler Error (ICE)
    ERROR = "error"      # User code error; compilation continues if possible
    WARNING = "warning"  # Non-fatal warning; compilation proceeds
    INFO = "info"        # Informational message


@dataclass(frozen=True)
class DiagnosticLabel:
    """An annotated source position highlighting code context within a diagnostic."""
    offset: int
    length: int = 1
    message: Optional[str] = None
    is_primary: bool = True


@dataclass(frozen=True)
class CodeSuggestion:
    """An actionable fix that can be automatically applied by an IDE/LSP or displayed as a diff."""
    offset: int
    length: int
    replacement: str
    description: str


@dataclass
class Diagnostic:
    """A comprehensive compiler or runtime diagnostic message."""
    severity: Severity
    message: str
    primary_label: Optional[DiagnosticLabel] = None
    secondary_labels: list[DiagnosticLabel] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    help_text: Optional[str] = None
    suggestions: list[CodeSuggestion] = field(default_factory=list)
    error_code: Optional[str] = None

    @classmethod
    def make_error(
        cls,
        message: str,
        offset: int,
        length: int = 1,
        help_text: Optional[str] = None,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        """Convenience constructor for a primary error diagnostic."""
        return cls(
            severity=Severity.ERROR,
            message=message,
            primary_label=DiagnosticLabel(offset=offset, length=length, is_primary=True),
            notes=notes or [],
            help_text=help_text,
            error_code=error_code,
        )

    @classmethod
    def make_fatal(
        cls,
        message: str,
        offset: Optional[int] = None,
        length: int = 1,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        """Convenience constructor for a fatal compiler error."""
        label = DiagnosticLabel(offset=offset, length=length, is_primary=True) if offset is not None else None
        return cls(
            severity=Severity.FATAL,
            message=message,
            primary_label=label,
            notes=notes or [],
            error_code=error_code,
        )

    @classmethod
    def make_warning(
        cls,
        message: str,
        offset: int,
        length: int = 1,
        help_text: Optional[str] = None,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        """Convenience constructor for a compiler warning."""
        return cls(
            severity=Severity.WARNING,
            message=message,
            primary_label=DiagnosticLabel(offset=offset, length=length, is_primary=True),
            notes=notes or [],
            help_text=help_text,
            error_code=error_code,
        )


class QuestCompilerError(Exception):
    """Base class for all Quest compilation and evaluation errors."""

    def __init__(
        self,
        message: str,
        offset: Optional[int] = 0,
        length: int = 1,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.length = length

    def to_diagnostic(self, length: Optional[int] = None) -> Diagnostic:
        """Converts this error into a structured Diagnostic object."""
        len_val = length if length is not None else self.length
        label = (
            DiagnosticLabel(offset=self.offset, length=len_val, is_primary=True)
            if self.offset is not None
            else None
        )
        return Diagnostic(
            severity=Severity.ERROR,
            message=self.message,
            primary_label=label,
        )

    def format_with_source(self, source_map: Any, length: Optional[int] = None) -> str:
        """Renders this error as a formatted diagnostic message with source context."""
        return DiagnosticRenderer.render_diagnostic(self.to_diagnostic(length), source_map)


class FatalDiagnosticError(QuestCompilerError):
    """Raised immediately by DiagnosticSink when a FATAL diagnostic is emitted."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(
            message=diagnostic.message,
            offset=diagnostic.primary_label.offset if diagnostic.primary_label else None,
            length=diagnostic.primary_label.length if diagnostic.primary_label else 1,
        )
        self.diagnostic = diagnostic

    def to_diagnostic(self, length: Optional[int] = None) -> Diagnostic:
        return self.diagnostic


class DiagnosticSink:
    """Collects diagnostics during compiler phases, supporting error accumulation and fatal aborts."""

    def __init__(self, fail_fast: bool = False, warnings_as_errors: bool = False) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.fail_fast = fail_fast
        self.warnings_as_errors = warnings_as_errors

    def emit(self, diag: Diagnostic) -> None:
        """Appends a diagnostic to the sink, aborting immediately if FATAL or fail_fast ERROR."""
        self.diagnostics.append(diag)
        if diag.severity == Severity.FATAL:
            raise FatalDiagnosticError(diag)
        if self.fail_fast and diag.severity == Severity.ERROR:
            raise FatalDiagnosticError(diag)

    def add_error(
        self,
        message: str,
        offset: int,
        length: int = 1,
        help_text: Optional[str] = None,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        diag = Diagnostic.make_error(message, offset, length, help_text, notes, error_code)
        self.emit(diag)
        return diag

    def add_fatal(
        self,
        message: str,
        offset: Optional[int] = None,
        length: int = 1,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        diag = Diagnostic.make_fatal(message, offset, length, notes, error_code)
        self.emit(diag)
        return diag

    def add_warning(
        self,
        message: str,
        offset: int,
        length: int = 1,
        help_text: Optional[str] = None,
        notes: Optional[list[str]] = None,
        error_code: Optional[str] = None,
    ) -> Diagnostic:
        diag = Diagnostic.make_warning(message, offset, length, help_text, notes, error_code)
        self.emit(diag)
        return diag

    @property
    def has_errors(self) -> bool:
        """Returns True if any FATAL or ERROR (or WARNING when warnings_as_errors is True) is present."""
        return any(
            d.severity in (Severity.FATAL, Severity.ERROR)
            or (self.warnings_as_errors and d.severity == Severity.WARNING)
            for d in self.diagnostics
        )

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity in (Severity.FATAL, Severity.ERROR))

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == Severity.INFO)


class DiagnosticRenderer:
    """Formats structured diagnostics into human-readable terminal output with source context."""

    @staticmethod
    def render_diagnostic(diag: Diagnostic, source_map: Optional[Any] = None, use_color: bool = False) -> str:
        """Renders a single Diagnostic with header, source line context, notes, and help."""
        code_str = f"[{diag.error_code}]" if diag.error_code else ""
        sev_str = f"{diag.severity.value}{code_str}"

        # If no source map or no primary label offset, emit plain message header
        if source_map is None or diag.primary_label is None:
            lines = [f"{sev_str}: {diag.message}"]
            for note in diag.notes:
                lines.append(f"  = note: {note}")
            if diag.help_text:
                lines.append(f"  = help: {diag.help_text}")
            for sugg in diag.suggestions:
                lines.append(f"  = suggestion: {sugg.description} -> '{sugg.replacement}'")
            return "\n".join(lines)

        # Primary location header
        loc = source_map.locate(diag.primary_label.offset)
        header = f"{loc.file_name}:{loc.line}:{loc.column}: {sev_str}: {diag.message}"
        lines = [header]

        # Primary source line and caret underline
        src_lines = source_map.source_text.splitlines()
        if 1 <= loc.line <= len(src_lines):
            src_line = src_lines[loc.line - 1]
            caret_pad = " " * (loc.column - 1)
            underline = "^" * max(1, diag.primary_label.length)
            lines.append(f"    {src_line}")
            label_msg = f" {diag.primary_label.message}" if diag.primary_label.message else ""
            lines.append(f"    {caret_pad}{underline}{label_msg}")

        # Secondary contextual labels
        for sec in diag.secondary_labels:
            sec_loc = source_map.locate(sec.offset)
            if 1 <= sec_loc.line <= len(src_lines):
                sec_src = src_lines[sec_loc.line - 1]
                sec_pad = " " * (sec_loc.column - 1)
                sec_dash = "-" * max(1, sec.length)
                sec_msg = f" note: {sec.message}" if sec.message else ""
                lines.append(f"  ::: {sec_loc.file_name}:{sec_loc.line}:{sec_loc.column}")
                lines.append(f"    {sec_src}")
                lines.append(f"    {sec_pad}{sec_dash}{sec_msg}")

        # Explanatory notes and actionable help
        for note in diag.notes:
            lines.append(f"  = note: {note}")
        if diag.help_text:
            lines.append(f"  = help: {diag.help_text}")
        for sugg in diag.suggestions:
            lines.append(f"  = suggestion: {sugg.description} -> '{sugg.replacement}'")

        return "\n".join(lines)

    @classmethod
    def render_all(cls, sink: DiagnosticSink, source_map: Optional[Any] = None, use_color: bool = False) -> str:
        """Renders all diagnostics collected in a DiagnosticSink."""
        return "\n\n".join(cls.render_diagnostic(d, source_map, use_color) for d in sink.diagnostics)
