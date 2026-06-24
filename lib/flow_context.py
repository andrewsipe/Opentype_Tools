"""Shared context for OpentypeFlow commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class FlowContext:
    paths: List[str]
    recursive: bool = False
    dry_run: bool = False
    verbose: bool = False
    yes: bool = False
    output_dir: Optional[Path] = None
    backup: bool = False
    connect_include_low: bool = False
    connect_include_manual: bool = False
    aalt_force: bool = False
    font_files: Optional[List[Path]] = None
    scan_root: Optional[Path] = None

    def resolved_fonts(self) -> List[Path]:
        if self.font_files is None:
            raise RuntimeError("font_files not collected")
        return self.font_files
