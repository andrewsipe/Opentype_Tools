# OpenType Tools - Quick Reference Guide

## Tool Overview

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `opentype_coverage_sorter.py` | Sort Coverage tables by GlyphID | Font files | Modified fonts |
| `opentype_wrapper.py` | Add OpenType scaffolding + enrichment | TrueType fonts | OpenType fonts |
| `opentype_ss_repair.py` | Fix stylistic set metadata | Fonts with SS | Fixed fonts |
| `opentype_feature_audit.py` | Audit features → .fea file | Font files | .fea or .json |
| `opentype_feature_apply.py` | Apply .fea files to fonts | Font + .fea | Modified font |

---

## Common Workflows

### 1. Audit Features in a Font

```bash
# Generate .fea file with all features (active, inactive, suggested)
./opentype_feature_audit.py MyFont.otf --output audit.fea

# Generate JSON report instead
./opentype_feature_audit.py MyFont.otf --output audit.json --format json

# Audit without suggestions (only active/inactive)
./opentype_feature_audit.py MyFont.otf --output audit.fea --no-suggest
```

**Output:** Human-readable .fea file with commented sections

---

### 2. Apply Features to a Font

```bash
# Apply features (merge mode - default)
./opentype_feature_apply.py MyFont.otf --input features.fea

# Apply with backup
./opentype_feature_apply.py MyFont.otf --input features.fea --backup

# Replace all existing features
./opentype_feature_apply.py MyFont.otf --input features.fea --replace

# Dry run (show what would happen)
./opentype_feature_apply.py MyFont.otf --input features.fea --dry-run
```

**Result:** Font updated with new features, Coverage tables sorted

---

### 3. Complete Feature Workflow

```bash
# Step 1: Audit font to see what features exist/are possible
./opentype_feature_audit.py MyFont.otf --output features.fea

# Step 2: Edit features.fea (uncomment desired features)
# ... manual editing ...

# Step 3: Apply edited features back to font
./opentype_feature_apply.py MyFont.otf --input features.fea --backup

# Step 4: Verify by auditing again
./opentype_feature_audit.py MyFont.otf --output verify.fea
```

---

### 4. Wrap TrueType Font

```bash
# Add OpenType scaffolding with smart enrichment
./opentype_wrapper.py MyFont.ttf

# Show what would be done
./opentype_wrapper.py MyFont.ttf --dry-run

# Wrapper only (no enrichment)
./opentype_wrapper.py MyFont.ttf --no-enrich
```

**Result:** Font with GDEF, GSUB, GPOS tables, inferred features

---

### 5. Fix Stylistic Set Metadata

```bash
# Audit SS features (read-only)
./opentype_ss_repair.py MyFont.otf --audit

# Auto-fix high-confidence issues
./opentype_ss_repair.py MyFont.otf --auto-fix

# Export suggestions to JSON
./opentype_ss_repair.py MyFont.otf --export ss_suggestions.json
```

---

### 6. Sort Coverage Tables

```bash
# Sort Coverage tables in font
./opentype_coverage_sorter.py MyFont.otf

# Batch process multiple fonts
./opentype_coverage_sorter.py *.otf

# Dry run to see what would be sorted
./opentype_coverage_sorter.py MyFont.otf --dry-run
```

---

## Batch Processing

### Process Entire Directory

```bash
# Audit all fonts in directory
./opentype_feature_audit.py fonts/ --recursive --output audits/

# Apply same .fea to multiple fonts
./opentype_feature_apply.py fonts/*.otf --input features.fea --backup

# Wrap all TrueType fonts
./opentype_wrapper.py fonts/*.ttf --recursive
```

---

## Common Options

### All Tools Support

- `--recursive` / `-r` - Search directories recursively
- `--verbose` / `-v` - Show detailed output
- `--help` / `-h` - Show help message

### Safety Options

- `--dry-run` - Preview changes without applying (audit, apply, wrapper)
- `--backup` - Create backup before modifying (apply)

---

## Feature Audit Output Format

The audit tool generates a .fea file with three sections:

### Section 1: EXISTING ACTIVE FEATURES
Features currently in the font (extracted)

```fea
# ==================================================
# EXISTING ACTIVE FEATURES
# Extracted from font on 2024-12-21
# ==================================================

feature liga {
  sub f f i by f_f_i;
} liga;
```

### Section 2: INACTIVE FEATURES
Glyphs exist but features not activated (commented)

```fea
# ==================================================
# INACTIVE FEATURES
# Glyphs exist but features are not activated
# Uncomment blocks below to enable
# ==================================================

# SS01: 15 glyphs
# Detected glyphs: A→A.ss01, B→B.ss01, C→C.ss01 (12 more)
#
# feature ss01 {
#   sub A by A.ss01;
#   sub B by B.ss01;
# } ss01;
```

### Section 3: SUGGESTED FEATURES
Based on glyph naming patterns (commented)

```fea
# ==================================================
# SUGGESTED FEATURES
# Based on glyph naming patterns
# Review carefully before uncommenting
# ==================================================

# Small Caps (26 glyphs)
# Detected glyphs: a→a.sc, b→b.sc, c→c.sc (23 more)
#
# feature smcp {
#   sub a by a.sc;
# } smcp;
```

---

## Supported Feature Types

### Substitution Features (GSUB)

- `liga` - Standard Ligatures
- `dlig` - Discretionary Ligatures
- `ss01-ss20` - Stylistic Sets
- `smcp` - Small Caps
- `c2sc` - Caps to Small Caps
- `onum` - Oldstyle Figures
- `lnum` - Lining Figures
- `tnum` - Tabular Figures
- `pnum` - Proportional Figures
- `swsh` - Swashes
- `calt` - Contextual Alternates
- `salt` - Stylistic Alternates
- `zero` - Slashed Zero
- `case` - Case-Sensitive Forms
- `titl` - Titling Alternates
- `frac` - Fractions
- `sups` - Superscripts
- `subs` - Subscripts
- `ordn` - Ordinals
- `numr` - Numerators
- `dnom` - Denominators
- `sinf` - Scientific Inferiors
- `hist` - Historical Forms

### Positioning Features (GPOS)

- `kern` - Kerning (extracted from existing fonts)

---

## Known Limitations

### Feature Extraction

- Only Type 1 (single) and Type 4 (ligature) GSUB lookups extracted
- Only Type 1 (single) and Type 2 (pair) GPOS lookups extracted
- Class-based kerning not fully extracted (stub only)
- Complex contextual features not extracted

**Impact:** Most common features work fine, advanced features may not extract correctly

### Feature Generation

- Fraction feature assumes specific slash glyph names
- Ordinal feature only applies contextual rules to specific letters
- Case-sensitive feature requires uppercase glyphs in font

**Impact:** Minor - fallbacks exist for most cases

---

## Troubleshooting

### "No font files found"
- Check file paths
- Use `--recursive` for directories
- Verify files are .ttf or .otf

### "Failed to compile features"
- Check .fea file syntax
- Look for missing glyphs referenced in .fea
- Try `--dry-run` to see what would happen

### "Coverage tables not sorted"
- Run `opentype_coverage_sorter.py` separately
- Check for malformed GSUB/GPOS tables

### Import errors
- Ensure all dependencies installed: `pip install -r requirements.txt`
- Check Python version (3.8+ required, 3.9+ recommended)

---

## Tips & Best Practices

1. **Always use `--dry-run` first** to preview changes
2. **Use `--backup` when applying features** to preserve originals
3. **Audit before and after** to verify changes
4. **Start with high-confidence features** (uncomment inactive features first)
5. **Test on a single font** before batch processing
6. **Use verbose mode** (`-v`) when debugging

---

## File Locations

### Scripts
- `/Users/skymacbook/Documents/Scripting/Good Font Scripts/OpentypeFeaturesGenerator/`

### Library Modules
- `/Users/skymacbook/Documents/Scripting/Good Font Scripts/OpentypeFeaturesGenerator/lib/`

### Documentation
- `README.md` - Project overview
- `AUDIT_REPORT.md` - Comprehensive audit
- `QUICK_REFERENCE.md` - This file

---

## Getting Help

```bash
# Show help for any tool
./opentype_feature_audit.py --help
./opentype_feature_apply.py --help
./opentype_wrapper.py --help
./opentype_ss_repair.py --help
./opentype_coverage_sorter.py --help
```

---

**Last Updated:** December 21, 2024

