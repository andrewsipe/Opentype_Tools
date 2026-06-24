"""Output path resolution for OpentypeFlow reports."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

OTL_REPORTS_DIRNAME = "otl_reports"


def common_parent(paths: List[Path]) -> Path:
    """Find common parent directory for a list of font paths."""
    if not paths:
        return Path.cwd()
    resolved = [p.resolve() for p in paths]
    if len(resolved) == 1:
        return resolved[0].parent
    parts_list = [p.parts for p in resolved]
    common: List[str] = []
    for parts in zip(*parts_list):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break
    if common:
        return Path(*common)
    return resolved[0].parent


def group_fonts_by_parent(font_paths: List[Path]) -> Dict[Path, List[Path]]:
    """Group font paths by their parent directory."""
    groups: Dict[Path, List[Path]] = {}
    for fp in font_paths:
        groups.setdefault(fp.parent.resolve(), []).append(fp.resolve())
    for parent in groups:
        groups[parent] = sorted(groups[parent])
    return groups


def report_dir_for_font(
    font_path: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Resolve otl_reports directory for a font.

    Default: ``font_path.parent / otl_reports``
    With output_dir: ``output_dir / relative_parent / otl_reports``
    """
    font_path = font_path.resolve()
    if output_dir is None:
        return font_path.parent / OTL_REPORTS_DIRNAME

    root = (scan_root or font_path.parent).resolve()
    try:
        rel_parent = font_path.parent.relative_to(root)
    except ValueError:
        rel_parent = Path(font_path.parent.name)

    if str(rel_parent) == ".":
        return Path(output_dir).resolve() / OTL_REPORTS_DIRNAME
    return Path(output_dir).resolve() / rel_parent / OTL_REPORTS_DIRNAME


def audit_fea_path(
    font_path: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    return report_dir_for_font(
        font_path, scan_root=scan_root, output_dir=output_dir
    ) / f"{font_path.stem}_audit.fea"


def audit_json_path(
    font_path: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    return report_dir_for_font(
        font_path, scan_root=scan_root, output_dir=output_dir
    ) / f"{font_path.stem}_audit.json"


def connect_fea_path(
    font_path: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    return report_dir_for_font(
        font_path, scan_root=scan_root, output_dir=output_dir
    ) / f"{font_path.stem}_connect.fea"


def aalt_fea_path(
    font_path: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    return report_dir_for_font(
        font_path, scan_root=scan_root, output_dir=output_dir
    ) / f"{font_path.stem}_aalt.fea"


def family_summary_path(
    parent_dir: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Family rollup JSON for all fonts under parent_dir."""
    parent_dir = parent_dir.resolve()
    if output_dir is None:
        return parent_dir / OTL_REPORTS_DIRNAME / "family_summary.json"

    root = (scan_root or parent_dir).resolve()
    try:
        rel_parent = parent_dir.relative_to(root)
    except ValueError:
        rel_parent = Path(parent_dir.name)

    if str(rel_parent) == ".":
        return Path(output_dir).resolve() / OTL_REPORTS_DIRNAME / "family_summary.json"
    return (
        Path(output_dir).resolve()
        / rel_parent
        / OTL_REPORTS_DIRNAME
        / "family_summary.json"
    )


def family_matrix_path(
    parent_dir: Path,
    *,
    scan_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    return family_summary_path(
        parent_dir, scan_root=scan_root, output_dir=output_dir
    ).with_name("family_matrix.txt")
