"""
Shared utilities for OpenType tools.

File handling, backup, and font collection utilities.
"""

import shutil
from pathlib import Path
from typing import List

# Add project root to path for FontCore imports
import sys

_project_root = Path(__file__).parent
while (
    not (_project_root / "FontCore").exists() and _project_root.parent != _project_root
):
    _project_root = _project_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from FontCore.core_file_collector import collect_font_files as core_collect_font_files  # noqa: E402


def backup_font(font_path: Path) -> Path:
    """
    Create backup of font file with tilde counter format.

    Uses format: FontName~001.ttf, FontName~002.ttf, etc.
    This makes duplicates easier to search for in macOS since hyphens
    are treated as NOT operators in search.

    Args:
        font_path: Path to font file to backup

    Returns:
        Path to backup file
    """
    stem = font_path.stem
    suffix = font_path.suffix
    parent = font_path.parent

    # Find next available counter
    counter = 1
    while True:
        backup_name = f"{stem}~{counter:03d}{suffix}"
        backup_path = parent / backup_name
        if not backup_path.exists():
            break
        counter += 1

    # Create backup
    shutil.copy2(font_path, backup_path)
    return backup_path


def collect_font_files(paths: List[str], recursive: bool = False) -> List[Path]:
    """
    Collect font files from paths.

    Wrapper around FontCore.core_file_collector.collect_font_files.

    Args:
        paths: List of file paths or directory paths
        recursive: If True, search directories recursively

    Returns:
        List of Path objects to font files
    """
    font_files = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_file():
            font_files.append(path)
        elif path.is_dir():
            if recursive:
                collected = core_collect_font_files([str(path)], recursive=True)
            else:
                collected = core_collect_font_files([str(path)], recursive=False)
            font_files.extend([Path(f) for f in collected])
    return font_files


def validate_font_file(path: Path) -> bool:
    """
    Basic font file validation.

    Checks if file exists and has a valid font extension.

    Args:
        path: Path to font file

    Returns:
        True if file appears to be a valid font file
    """
    if not path.exists():
        return False

    valid_extensions = {".ttf", ".otf", ".woff", ".woff2"}
    return path.suffix.lower() in valid_extensions
