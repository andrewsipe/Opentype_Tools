# OpenType Tools

OpenType feature audit, wrap, connect, aalt, verify, and coverage sorting.

**Daily driver:** `OpentypeFlow.py` (see also `QUICK_REFERENCE.md`).  
Declutter / product-pass notes: `PRODUCT_REFINEMENT_NOTES.md`.

## Scripts

| Script | Role |
|--------|------|
| **`OpentypeFlow.py`** | Unified CLI: `scan`, `wrap`, `connect`, `aalt`, `verify`, `sort`, `pipeline` |
| `opentype_coverage_sorter.py` | Sort GSUB/GPOS/GDEF Coverage by GlyphID |
| `opentype_wrapper.py` | OTL scaffolding + enrichment (also `OpentypeFlow wrap`) |
| `opentype_ss_repair.py` | Repair stylistic-set FeatureParams / UI names (metadata only) |
| `opentype_feature_audit.py` | Audit → `.fea` / JSON report |
| `opentype_feature_apply.py` | Apply a `.fea` file safely |

Shared logic lives under `lib/`; registries in `data/`.

## Quick start

```bash
cd Opentype_Tools
./OpentypeFlow.py scan ./MyFamily -r
./OpentypeFlow.py connect ./MyFamily -r --dry-run
./OpentypeFlow.py pipeline ./MyFamily -r --backup -y
```

More examples: **`QUICK_REFERENCE.md`**.

## Structure

```
OpentypeFlow.py          # main entry
opentype_*.py            # focused CLIs
lib/                     # library modules
data/                    # feature_registry.json, feature_conflicts.json
tests/                   # pytest suite
```

## Dependencies

See `requirements.txt` (`fonttools`, `rich`, optional `fontFeatures`, `lxml`). Shared helpers via `FontCore/`.

## Related

- [FontFileTools](../FontFileTools) — also has a simpler `CoverageSorter.py`; prefer this package’s sorter / `OpentypeFlow sort` for the full workflow
- GitHub remote historically named OpentypeFeaturesGenerator
