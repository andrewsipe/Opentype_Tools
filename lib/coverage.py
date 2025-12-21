"""
Coverage table sorting for OpenType fonts.

Sorts Coverage tables by GlyphID to match GlyphOrder, which is required
by some font processors and prevents validation warnings.
"""

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from io import StringIO
from typing import Dict, Tuple

from fontTools.ttLib import TTFont

# Add project root to path for FontCore imports
import sys
from pathlib import Path

_project_root = Path(__file__).parent
while (
    not (_project_root / "FontCore").exists() and _project_root.parent != _project_root
):
    _project_root = _project_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import FontCore.core_console_styles as cs  # noqa: E402


def extract_glyph_order_from_ttx(ttx_content: str) -> Dict[str, int]:
    """
    Extract the GlyphOrder from TTX XML content.
    Returns a dict mapping glyph names to their IDs.
    """
    try:
        root = ET.fromstring(ttx_content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid TTX XML: {e}")

    glyph_order = root.find("GlyphOrder")
    if glyph_order is None:
        raise ValueError("No GlyphOrder table found in TTX content")

    glyph_to_id = {}
    for glyph_id_elem in glyph_order.findall("GlyphID"):
        glyph_name = glyph_id_elem.get("name")
        glyph_id = int(glyph_id_elem.get("id"))
        if glyph_name:
            glyph_to_id[glyph_name] = glyph_id

    return glyph_to_id


def sort_coverage_tables_in_ttx_content(
    ttx_content: str, glyph_to_id: Dict[str, int], verbose: bool = False
) -> Tuple[int, int, str]:
    """
    Sort Coverage tables in TTX XML content by glyph ID.
    Returns (total_coverage, sorted_count, sorted_content)
    """
    total_coverage = 0
    sorted_coverage = 0

    # Pattern to match Coverage blocks with their Glyph entries
    def process_coverage_block(match):
        nonlocal total_coverage, sorted_coverage

        total_coverage += 1
        full_block = match.group(0)
        indent = match.group(1)
        coverage_attrs = match.group(2)
        inner_content = match.group(3)

        # Find all Glyph value lines
        glyph_pattern = re.compile(r'(\s*)<Glyph value="([^"]+)"/>')
        glyph_matches = list(glyph_pattern.finditer(inner_content))

        if len(glyph_matches) <= 1:
            return full_block

        # Extract glyph values
        glyph_values = [m.group(2) for m in glyph_matches]

        # Sort by glyph ID (position in GlyphOrder)
        # Glyphs not in GlyphOrder get a high number to sort last
        sorted_values = sorted(glyph_values, key=lambda g: glyph_to_id.get(g, 999999))

        # Check if sorting is needed
        if glyph_values == sorted_values:
            return full_block

        sorted_coverage += 1

        if verbose:
            # Show what changed
            unsorted_ids = [glyph_to_id.get(g, -1) for g in glyph_values[:5]]
            sorted_ids = [glyph_to_id.get(g, -1) for g in sorted_values[:5]]
            cs.StatusIndicator("info").add_message(
                f"Sorted Coverage (was IDs {unsorted_ids}, now {sorted_ids})"
            ).emit()

        # Rebuild the Coverage block with sorted glyphs
        # Detect the indentation of the first Glyph element
        first_glyph_indent = glyph_matches[0].group(1) if glyph_matches else "        "

        # Build sorted glyph lines
        sorted_glyph_lines = [
            f'{first_glyph_indent}<Glyph value="{value}"/>' for value in sorted_values
        ]

        # Reconstruct the Coverage block
        result = f"{indent}<Coverage{coverage_attrs}>\n"
        result += "\n".join(sorted_glyph_lines)
        result += f"\n{indent}</Coverage>"

        return result

    # Pattern to match Coverage blocks
    coverage_pattern = re.compile(
        r"(\s*)<Coverage([^>]*)>\s*\n((?:\s*<Glyph[^>]+/>\s*\n)+)\s*\1</Coverage>",
        re.MULTILINE,
    )

    # Replace all Coverage blocks with sorted versions
    sorted_content = coverage_pattern.sub(process_coverage_block, ttx_content)

    return total_coverage, sorted_coverage, sorted_content


def sort_coverage_tables_in_font(font: TTFont, verbose: bool = False) -> Tuple[int, int]:
    """
    Sort all Coverage tables in a font by glyph ID using TTX conversion.
    This ensures sorting matches the exact behavior of Tools_TTX_GSUB_GPOS_CoverageTableSorter.py
    by converting to TTX, sorting by GlyphOrder IDs, then converting back.

    The font object is modified in place by reloading from the sorted TTX.

    Args:
        font: TTFont object (will be reloaded from sorted TTX if sorting occurs)
        verbose: Whether to show verbose output

    Returns:
        (total_coverage, sorted_count) tuple
    """
    try:
        # Convert font to TTX XML string using fontTools
        ttx_buffer = StringIO()
        font.saveXML(ttx_buffer)
        ttx_content = ttx_buffer.getvalue()

        # Extract GlyphOrder to get glyph IDs (matching TTX sorter logic exactly)
        glyph_to_id = extract_glyph_order_from_ttx(ttx_content)

        if verbose:
            cs.StatusIndicator("info").add_message(
                f"Extracted {len(glyph_to_id)} glyphs from GlyphOrder"
            ).emit()

        # Sort Coverage tables in TTX content using exact TTX sorter logic
        total, sorted_count, sorted_ttx_content = sort_coverage_tables_in_ttx_content(
            ttx_content, glyph_to_id, verbose
        )

        # If sorting occurred, reload font from sorted TTX
        if sorted_count > 0:
            # Determine output extension based on font type (before closing font)
            font_ext = ".otf"  # Default to OTF
            if hasattr(font, "sfntVersion"):
                # Check if it's TTF or OTF
                # TTF: "\x00\x01\x00\x00", OTF: "OTTO"
                if font.sfntVersion == "\x00\x01\x00\x00":
                    font_ext = ".ttf"

            # Use temporary file for TTX
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ttx", delete=False, encoding="utf-8"
            ) as tmp_ttx:
                tmp_ttx.write(sorted_ttx_content)
                tmp_ttx_path = tmp_ttx.name

            # Create temp binary file path (same directory, different extension)
            tmp_bin_path = tmp_ttx_path.rsplit(".", 1)[0] + font_ext

            try:
                # Convert sorted TTX back to binary using ttx command-line tool
                # Use ttx to compile TTX back to binary
                # ttx -f -o output.otf input.ttx
                # -f forces overwrite, -o specifies output file
                result = subprocess.run(
                    ["ttx", "-f", "-o", tmp_bin_path, tmp_ttx_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    raise ValueError(f"ttx compilation failed: {error_msg}")

                # Verify the output file was created and has content
                if not os.path.exists(tmp_bin_path):
                    raise ValueError(
                        f"ttx compilation succeeded but output file not found: {tmp_bin_path}"
                    )

                if os.path.getsize(tmp_bin_path) == 0:
                    raise ValueError(
                        f"ttx compilation created empty file: {tmp_bin_path}"
                    )

                # Reload font from sorted binary file
                # Load new font first (before closing old one to preserve any file paths)
                try:
                    new_font = TTFont(tmp_bin_path, lazy=False)
                except Exception as load_error:
                    raise ValueError(
                        f"Failed to load compiled font from {tmp_bin_path}: {load_error}. "
                        f"TTX file: {tmp_ttx_path}, ttx output: {result.stdout}, errors: {result.stderr}"
                    )

                # Update the original font object by replacing its internal state
                # Get list of existing table tags before closing (for cleanup)
                old_tags = list(font.keys()) if hasattr(font, "keys") else []

                # Copy all tables from new font to old font BEFORE closing
                # This way the font object is still valid
                for tag in new_font.keys():
                    font[tag] = new_font[tag]

                # Remove old tables that won't be replaced
                for tag in old_tags:
                    if tag not in new_font:
                        try:
                            del font[tag]
                        except Exception:
                            pass

                # Copy font-level attributes
                if hasattr(new_font, "sfntVersion"):
                    font.sfntVersion = new_font.sfntVersion
                if hasattr(new_font, "flavor"):
                    font.flavor = new_font.flavor
                if hasattr(new_font, "lazy"):
                    font.lazy = new_font.lazy

                # Close both fonts
                new_font.close()
                # Note: We don't close the original font here as it's still in use
                # The caller will close it when done

                # Clean up temp files
                os.unlink(tmp_ttx_path)
                os.unlink(tmp_bin_path)

            except FileNotFoundError:
                # ttx command not found - fall back to binary sorting
                if verbose:
                    cs.StatusIndicator("warning").add_message(
                        "ttx command not found, falling back to binary sorting"
                    ).emit()
                os.unlink(tmp_ttx_path)
                # Fall through to binary sorting below
                raise ValueError("ttx command not available")
            except Exception as e:
                # Clean up temp files on error
                try:
                    os.unlink(tmp_ttx_path)
                    if "tmp_bin_path" in locals() and os.path.exists(tmp_bin_path):
                        os.unlink(tmp_bin_path)
                except Exception:
                    pass
                raise ValueError(f"Failed to reload font from sorted TTX: {e}")

        return total, sorted_count

    except Exception as e:
        if verbose:
            cs.StatusIndicator("warning").add_message(
                f"TTX-based sorting failed: {e}"
            ).with_explanation("Coverage tables may not be sorted correctly").emit()

        # Return zero counts on error
        return 0, 0

