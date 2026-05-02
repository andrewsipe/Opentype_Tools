"""
Shared utilities for OpenType tools.

File handling, backup, and font collection utilities.
"""

import shutil
from pathlib import Path
from typing import List

from fontTools.ttLib import TTFont

from .fontcore_path import ensure_fontcore_on_path

ensure_fontcore_on_path(Path(__file__).resolve().parent.parent)

from FontCore.core_file_collector import collect_font_files as core_collect_font_files  # noqa: E402


# Subfolder beside the font; numbered copies stay out of the main folder.
_FONT_BACKUPS_DIRNAME = "backups"


def backup_font(font_path: Path) -> Path:
    """
    Copy the font into a ``backups`` directory next to the source file.

    Names use ``Stem_001.ext``, ``Stem_002.ext``, … so originals in the font folder stay clean.

    Args:
        font_path: Path to font file to backup

    Returns:
        Path to the copied backup file
    """
    font_path = Path(font_path)
    stem = font_path.stem
    suffix = font_path.suffix
    backup_root = font_path.parent / _FONT_BACKUPS_DIRNAME
    backup_root.mkdir(parents=True, exist_ok=True)

    counter = 1
    while True:
        backup_path = backup_root / f"{stem}_{counter:03d}{suffix}"
        if not backup_path.exists():
            break
        counter += 1

    shutil.copy2(font_path, backup_path)
    return backup_path


def atomic_ttfont_save(font: TTFont, font_path: Path) -> None:
    """
    Save font to ``font_path`` via a sibling ``*.tmp`` file and atomic replace.

    Avoids overwriting the destination with a truncated file if save is interrupted.
    """
    dest = Path(font_path)
    tmp_path = dest.parent / (dest.name + ".tmp")
    font.save(tmp_path)
    tmp_path.replace(dest)


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
