# Product refinement notes — Opentype_Tools

Captured during the 2026-08-21 declutter pass. Use for a later product/release pass. **Not** user-facing docs.

## What was archived (declutter)

| Archived path | Was | Why archived |
|---------------|-----|--------------|
| `_misc/_archive/Opentype_Tools/AUDIT_REPORT.md` | Dec 2024 refactor status report | Historical; superseded by current `lib/` + `QUICK_REFERENCE.md` |

## Declutter verdict for code

**No CLI/library modules archived.** Active surface:

| Entry | Role |
|-------|------|
| `OpentypeFlow.py` | Daily driver (`scan` / `wrap` / `connect` / `aalt` / `verify` / `sort` / `pipeline`) |
| `opentype_coverage_sorter.py` | Standalone Coverage sort (also `OpentypeFlow sort`) |
| `opentype_wrapper.py` | Standalone wrap (also `OpentypeFlow wrap`) |
| `opentype_ss_repair.py` | SS metadata repair — **not** a Flow subcommand |
| `opentype_feature_audit.py` | Full audit → `.fea`/JSON — related to but distinct from `scan` |
| `opentype_feature_apply.py` | Apply external `.fea` — used with connect output / hand-edited FEA |
| `lib/*` | Shared implementation (tests cover much of it) |
| `data/*.json` | Feature registry / conflicts |

### Doc fix in declutter

- Root **README** still described removed `Opentype_FeaturesGenerator.py` / `opentype_features/` package. Rewritten to match Flow + thin CLIs. **`QUICK_REFERENCE.md`** was already accurate — keep as primary operator doc.

## Product-pass refinements (deferred)

1. **Single public CLI** — Ship `opentypeflow` console script; demote or fold thin CLIs (`ss_repair`, `feature_audit`, `feature_apply`) into Flow subcommands.
2. **Coverage sorter duplication** — Prefer this package (or Flow `sort`) over `FontFileTools/CoverageSorter.py` after parity check; archive the FontFileTools copy when ready.
3. **Remote / package name** — GitHub still “OpentypeFeaturesGenerator”; align folder, PyPI, and product name.
4. **AUDIT_REPORT leftovers** — Some Dec 2024 items (class-based kern extraction stubs, GSUB lookup coverage) may still be real limitations; re-triage against current `lib/feature_extraction.py` before release.
5. **`raw_github_urls.txt`** — PushCore noise; exclude from release artifacts.

## Do not lose

- Flow pipeline order: scan → wrap → connect → aalt → verify → sort.
- Connect tier gating (HIGH/MED vs `--include-low` / `--include-manual`).
- SS repair = metadata only (no GSUB rewrite).
- `data/feature_registry.json` + conflicts policy.
- Pytest suite under `tests/`.
