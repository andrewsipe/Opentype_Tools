"""
Result handling for OpenType feature operations.

Provides structured result objects with consistent message formatting.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fontcore_path import ensure_fontcore_on_path

ensure_fontcore_on_path(Path(__file__).resolve().parent.parent)

import FontCore.core_console_styles as cs  # noqa: E402


class ResultLevel(Enum):
    """Result severity levels."""

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ResultMessage:
    """Single result message."""

    level: ResultLevel
    message: str
    details: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        base = f"[{self.level.value.upper()}] {self.message}"
        if self.details:
            base += f"\n  → {self.details}"
        return base


@dataclass
class OperationResult:
    """Result of an operation with multiple messages."""

    success: bool = True
    messages: List[ResultMessage] = field(default_factory=list)
    data: Optional[Any] = None
    #: Stable, user-facing summaries of applied changes (for CLI aggregation; avoids parsing message strings).
    changelog: List[str] = field(default_factory=list)

    def add_message(
        self,
        level: ResultLevel,
        message: str,
        details: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Add a message to the result."""
        self.messages.append(ResultMessage(level, message, details, context))

    def add_success(self, message: str, details: Optional[str] = None):
        """Add a success message."""
        self.add_message(ResultLevel.SUCCESS, message, details)

    def add_info(self, message: str, details: Optional[str] = None):
        """Add an info message."""
        self.add_message(ResultLevel.INFO, message, details)

    def add_warning(self, message: str, details: Optional[str] = None):
        """Add a warning message."""
        self.add_message(ResultLevel.WARNING, message, details)

    def add_error(self, message: str, details: Optional[str] = None):
        """Add an error message."""
        self.add_message(ResultLevel.ERROR, message, details)
        self.success = False

    def add_critical(self, message: str, details: Optional[str] = None):
        """Add a critical error message."""
        self.add_message(ResultLevel.CRITICAL, message, details)
        self.success = False

    def record_change(self, line: str):
        """Record a substantive change summary for display."""
        stripped = line.strip()
        if stripped and stripped not in self.changelog:
            self.changelog.append(stripped)

    def has_errors(self) -> bool:
        """Check if result has any errors."""
        return any(
            m.level == ResultLevel.ERROR or m.level == ResultLevel.CRITICAL
            for m in self.messages
        )

    def has_warnings(self) -> bool:
        """Check if result has any warnings."""
        return any(m.level == ResultLevel.WARNING for m in self.messages)

    def emit_all(self):
        """Emit all messages using StatusIndicator."""
        for msg in self.messages:
            # Map result levels to status indicator types
            # Use "info" for operational messages, not "success"
            indicator_map = {
                ResultLevel.SUCCESS: "info",  # Operational success -> info
                ResultLevel.INFO: "info",
                ResultLevel.WARNING: "warning",
                ResultLevel.ERROR: "error",
                ResultLevel.CRITICAL: "error",
            }
            indicator = cs.StatusIndicator(indicator_map[msg.level])
            indicator.add_message(msg.message)
            if msg.details:
                indicator.with_explanation(msg.details)
            indicator.emit()
