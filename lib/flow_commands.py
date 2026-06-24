"""Command implementations for OpentypeFlow."""

from __future__ import annotations

from typing import List

import FontCore.core_console_styles as cs
from fontTools.ttLib import TTFont

from .aalt_builder import apply_aalt_to_font, build_aalt_plan
from .analyze import analyze_font
from .connect import (
    build_connect_plan,
    confirm_connect_apply,
    emit_connect_preview,
    render_connect_fea,
)
from .coverage import sort_coverage_tables_in_font
from .family_rollup import write_family_artifacts
from .scan_render import render_family_scan
from .flow_context import FlowContext
from .io_paths import (
    aalt_fea_path,
    common_parent,
    connect_fea_path,
    group_fonts_by_parent,
)
from .verify import verify_font, verify_passes
from .verify_render import render_family_verify
from .models import BatchSummary, ConnectOptions, FontFeatureAudit
from .feature_apply import apply_features_to_font, detect_feature_conflicts
from .utils import atomic_ttfont_save, backup_font, collect_font_files_flow
from .validation import FontValidator
from .wrapper import WrapperExecutor, WrapperStrategyEngine


def _load_audits(ctx: FlowContext) -> List[FontFeatureAudit]:
    audits: List[FontFeatureAudit] = []
    for font_path in ctx.resolved_fonts():
        with TTFont(font_path, lazy=False) as font:
            audits.append(analyze_font(font, font_path))
    return audits


def _emit_family_rollups(ctx: FlowContext, audits: List[FontFeatureAudit]) -> None:
    by_parent = group_fonts_by_parent([a.path for a in audits])
    audit_by_path = {a.path: a for a in audits}
    for parent, font_paths in by_parent.items():
        group_audits = [audit_by_path[p] for p in font_paths if p in audit_by_path]
        write_family_artifacts(
            parent,
            group_audits,
            scan_root=ctx.scan_root,
            output_dir=ctx.output_dir,
        )


def _print_family_tables(ctx: FlowContext, audits: List[FontFeatureAudit]) -> None:
    by_parent = group_fonts_by_parent([a.path for a in audits])
    audit_by_path = {a.path: a for a in audits}
    for parent, font_paths in by_parent.items():
        group_audits = [audit_by_path[p] for p in font_paths if p in audit_by_path]
        cs.emit("")
        cs.emit(render_family_scan(group_audits, parent=parent))


def cmd_scan(ctx: FlowContext, *, write_report: bool = False) -> int:
    """Analyze fonts and print a family matrix to the terminal.

    With ``write_report=True``, also writes one family_summary.json and
    family_matrix.txt per font directory under otl_reports/ (no per-font files).
    """
    audits = _load_audits(ctx)
    _print_family_tables(ctx, audits)

    wrap_needed = [
        a for a in audits if a.wrap_status.needs_scaffolding and a.wrap_status.can_wrap
    ]
    if wrap_needed:
        cs.emit("")
        cs.StatusIndicator("info").add_message(
            f"{len(wrap_needed)} font(s) can be wrapped (run: wrap)"
        ).emit()

    wrap_flagged = [a for a in audits if a.wrap_status.flagged_unsupported]
    if wrap_flagged:
        cs.emit("")
        cs.StatusIndicator("warning").add_message(
            f"{len(wrap_flagged)} font(s) need scaffolding but wrap is unsupported"
        ).emit()

    stripped = [a for a in audits if a.otl_stripped_suspected]
    if stripped:
        cs.emit("")
        cs.StatusIndicator("warning").add_message(
            f"{len(stripped)} font(s) look stripped/omitted — wrap before connect"
        ).emit()

    trial_like = [
        a
        for a in audits
        if a.glyph_inventory.limited_glyph_set and not a.glyph_inventory.has_variant_glyphs
    ]
    if trial_like:
        cs.emit("")
        counts = sorted({a.glyph_inventory.glyph_count for a in trial_like})
        count_str = str(counts[0]) if len(counts) == 1 else f"{min(counts)}–{max(counts)}"
        cs.StatusIndicator("warning").add_message(
            f"{len(trial_like)} font(s) have small glyph sets ({count_str} glyphs, "
            "no variants) — limited reconnect scope"
        ).emit()

    if write_report:
        _emit_family_rollups(ctx, audits)
        cs.emit("")
        cs.StatusIndicator("info").add_message(
            "Wrote family_summary.json and family_matrix.txt under otl_reports/"
        ).emit()

    cs.emit("")
    cs.StatusIndicator("success").add_message(
        f"Scanned {len(audits)} font(s)"
    ).emit()
    return 0


def cmd_wrap(ctx: FlowContext) -> int:
    summary = BatchSummary()
    for font_path in ctx.resolved_fonts():
        cs.StatusIndicator("parsing").add_message(f"Processing: {font_path.name}").emit()
        try:
            with TTFont(font_path, lazy=False) as font:
                from .wrap_assess import assess_wrap_status

                wrap = assess_wrap_status(font)
                if wrap.flagged_unsupported:
                    summary.wrap_flagged.append(str(font_path))
                    cs.StatusIndicator("warning").add_message(
                        "Wrap not supported for this font format"
                    ).with_explanation(wrap.reason).emit()
                    summary.fonts_skipped += 1
                    cs.emit("")
                    continue

                if not wrap.needs_scaffolding:
                    cs.StatusIndicator("unchanged").add_message(
                        "No wrap needed"
                    ).emit()
                    summary.fonts_skipped += 1
                    cs.emit("")
                    continue

                if ctx.dry_run:
                    preview = cs.StatusIndicator("preview", dry_run=True).add_message(
                        "Would wrap font"
                    )
                    if wrap.outline_kind:
                        preview = preview.with_explanation(
                            f"Outline: {wrap.outline_kind}"
                        )
                    preview.emit()
                    if wrap.wrap_plan_summary:
                        for line in wrap.wrap_plan_summary.split("\n"):
                            cs.StatusIndicator("info").add_message(f"  {line}").emit()
                    summary.fonts_processed += 1
                    cs.emit("")
                    continue

                validator = FontValidator(font)
                engine = WrapperStrategyEngine(font, validator)
                plan, plan_result = engine.create_plan(
                    {"enrich": True, "skip_validation": False, "overwrite_cmap": False}
                )

                if not plan_result.success or not plan.has_work():
                    cs.StatusIndicator("unchanged").add_message(
                        "No wrap operations needed"
                    ).emit()
                    summary.fonts_skipped += 1
                    cs.emit("")
                    continue

                if not ctx.yes:
                    try:
                        answer = input(f"Wrap {font_path.name}? [y/N]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer not in ("y", "yes"):
                        cs.StatusIndicator("skipped").add_message("Cancelled").emit()
                        summary.fonts_skipped += 1
                        cs.emit("")
                        continue

                executor = WrapperExecutor(font, plan)
                exec_result, has_changes = executor.execute()

                if exec_result.success and has_changes:
                    if ctx.backup:
                        backup_font(font_path)
                    sort_coverage_tables_in_font(font, verbose=ctx.verbose)
                    atomic_ttfont_save(font, font_path)
                    cs.StatusIndicator("saved").add_message(f"Saved: {font_path.name}").emit()
                    summary.fonts_updated += 1
                else:
                    summary.fonts_skipped += 1

                summary.fonts_processed += 1
        except Exception as e:
            cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
            summary.fonts_errors += 1
        cs.emit("")

    cs.StatusIndicator("success").add_message("Wrap complete").with_summary_block(
        updated=summary.fonts_updated,
        unchanged=summary.fonts_skipped,
        errors=summary.fonts_errors,
    ).emit()
    return 0 if summary.fonts_errors == 0 else 1


def _connect_options(ctx: FlowContext) -> ConnectOptions:
    return ConnectOptions(
        include_low=ctx.connect_include_low,
        include_manual=ctx.connect_include_manual,
    )


def cmd_connect(ctx: FlowContext, *, apply: bool = False, replace: bool = False) -> int:
    options = _connect_options(ctx)
    plans_with_work = 0
    blocked = 0
    applied = 0
    errors = 0

    for font_path in ctx.resolved_fonts():
        cs.StatusIndicator("parsing").add_message(f"Processing: {font_path.name}").emit()
        try:
            with TTFont(font_path, lazy=False) as font:
                audit = analyze_font(font, font_path)
                plan = build_connect_plan(audit, options)
                emit_connect_preview(audit, plan, options=options)

                if plan.blocked:
                    blocked += 1
                    cs.emit("")
                    continue

                if not plan.has_work:
                    cs.emit("")
                    continue

                plans_with_work += 1
                fea_content = render_connect_fea(audit, plan, font)
                out_path = connect_fea_path(
                    font_path, scan_root=ctx.scan_root, output_dir=ctx.output_dir
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(fea_content, encoding="utf-8")
                cs.StatusIndicator("success").add_message(
                    f"Wrote {out_path.name}"
                ).emit()

                if not apply:
                    cs.emit("")
                    continue

                if ctx.dry_run:
                    cs.StatusIndicator("preview", dry_run=True).add_message(
                        "Would apply reconnections"
                    ).emit()
                    cs.emit("")
                    continue

        except Exception as e:
            cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
            errors += 1
            cs.emit("")
            continue

        cs.emit("")

    if apply and plans_with_work > 0 and not ctx.dry_run:
        if not confirm_connect_apply(plans_with_work, auto_yes=ctx.yes):
            cs.StatusIndicator("skipped").add_message("Apply cancelled").emit()
            return 0

        for font_path in ctx.resolved_fonts():
            fea_path = connect_fea_path(
                font_path, scan_root=ctx.scan_root, output_dir=ctx.output_dir
            )
            if not fea_path.exists():
                continue
            try:
                with TTFont(font_path, lazy=False) as font:
                    fea_content = fea_path.read_text(encoding="utf-8")
                    if not replace:
                        for msg in detect_feature_conflicts(font, fea_content):
                            cs.StatusIndicator("warning").add_message(msg).emit()
                    if ctx.backup:
                        backup_font(font_path)
                    ok, messages = apply_features_to_font(
                        font,
                        fea_content,
                        replace_mode=replace,
                        merge_mode=not replace,
                    )
                    if ok:
                        for msg in messages:
                            if "Skipped contextual" in msg:
                                cs.StatusIndicator("warning").add_message(msg).emit()
                            elif msg.startswith("Merged"):
                                cs.StatusIndicator("info").add_message(msg).emit()
                        sort_coverage_tables_in_font(font, verbose=ctx.verbose)
                        atomic_ttfont_save(font, font_path)
                        cs.StatusIndicator("saved").add_message(
                            f"Applied: {font_path.name}"
                        ).emit()
                        applied += 1
                    else:
                        for msg in messages:
                            cs.StatusIndicator("error").add_message(msg).emit()
                        errors += 1
            except Exception as e:
                cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
                errors += 1

    cs.emit("")
    summary = cs.StatusIndicator("success").add_message("Connect complete")
    if blocked:
        summary = summary.with_explanation(f"{blocked} font(s) blocked — run wrap or use full export")
    summary.with_summary_block(updated=applied, errors=errors).emit()
    return 0 if errors == 0 else 1


def cmd_sort(ctx: FlowContext) -> int:
    updated = 0
    errors = 0
    for font_path in ctx.resolved_fonts():
        cs.StatusIndicator("parsing").add_message(f"Processing: {font_path.name}").emit()
        try:
            with TTFont(font_path, lazy=False) as font:
                total, sorted_count = sort_coverage_tables_in_font(
                    font, verbose=ctx.verbose
                )
                if ctx.dry_run:
                    if sorted_count:
                        cs.StatusIndicator("preview", dry_run=True).add_message(
                            f"Would sort {sorted_count} of {total} Coverage table(s)"
                        ).emit()
                    else:
                        cs.StatusIndicator("unchanged").add_message(
                            "Already sorted"
                        ).emit()
                elif sorted_count > 0:
                    if ctx.backup:
                        backup_font(font_path)
                    atomic_ttfont_save(font, font_path)
                    cs.StatusIndicator("success").add_message(
                        f"Sorted {sorted_count} of {total} Coverage table(s)"
                    ).emit()
                    updated += 1
                else:
                    cs.StatusIndicator("unchanged").add_message(
                        "No sorting needed"
                    ).emit()
        except Exception as e:
            cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
            errors += 1
        cs.emit("")

    cs.StatusIndicator("success").add_message("Sort complete").with_summary_block(
        updated=updated, errors=errors
    ).emit()
    return 0 if errors == 0 else 1


def cmd_aalt(ctx: FlowContext, *, apply: bool = False) -> int:
    updated = 0
    skipped = 0
    blocked = 0
    errors = 0

    for font_path in ctx.resolved_fonts():
        cs.StatusIndicator("parsing").add_message(f"Processing: {font_path.name}").emit()
        try:
            with TTFont(font_path, lazy=False) as font:
                plan = build_aalt_plan(font, force=ctx.aalt_force)

                if plan.blocked:
                    blocked += 1
                    cs.StatusIndicator("warning").add_message(plan.block_reason).emit()
                    cs.emit("")
                    continue

                if not plan.needs_update:
                    cs.StatusIndicator("unchanged").add_message(
                        plan.skip_reason or "No aalt changes needed"
                    ).emit()
                    skipped += 1
                    cs.emit("")
                    continue

                out_path = aalt_fea_path(
                    font_path, scan_root=ctx.scan_root, output_dir=ctx.output_dir
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)
                header = (
                    f"# AALT plan for {font_path.name}\n"
                    f"# References: {', '.join(plan.source_tags)}\n\n"
                )
                out_path.write_text(header + plan.fea_content, encoding="utf-8")
                cs.StatusIndicator("success").add_message(
                    f"Wrote {out_path.name} ({len(plan.source_tags)} feature(s))"
                ).emit()
                for tag in plan.source_tags:
                    cs.StatusIndicator("info").add_message(f"  • {tag}").emit()

                if not apply:
                    cs.emit("")
                    continue

                if ctx.dry_run:
                    cs.StatusIndicator("preview", dry_run=True).add_message(
                        "Would apply aalt"
                    ).emit()
                    cs.emit("")
                    continue

                if not ctx.yes:
                    try:
                        answer = (
                            input(f"Apply aalt to {font_path.name}? [y/N]: ")
                            .strip()
                            .lower()
                        )
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer not in ("y", "yes"):
                        cs.StatusIndicator("skipped").add_message("Cancelled").emit()
                        skipped += 1
                        cs.emit("")
                        continue

                if ctx.backup:
                    backup_font(font_path)
                ok, messages = apply_aalt_to_font(font, force=ctx.aalt_force)
                if ok:
                    for msg in messages:
                        cs.StatusIndicator("info").add_message(msg).emit()
                    atomic_ttfont_save(font, font_path)
                    cs.StatusIndicator("saved").add_message(
                        f"Applied: {font_path.name}"
                    ).emit()
                    updated += 1
                else:
                    for msg in messages:
                        cs.StatusIndicator("error").add_message(msg).emit()
                    errors += 1
        except Exception as e:
            cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
            errors += 1
        cs.emit("")

    cs.StatusIndicator("success").add_message("AALT complete").with_summary_block(
        updated=updated, unchanged=skipped, errors=errors
    ).emit()
    if blocked:
        cs.StatusIndicator("warning").add_message(
            f"{blocked} font(s) blocked — see messages above"
        ).emit()
    return 0 if errors == 0 else 1


def cmd_verify(ctx: FlowContext, *, strict: bool = False) -> int:
    options = _connect_options(ctx)
    reports: List = []

    for font_path in ctx.resolved_fonts():
        try:
            with TTFont(font_path, lazy=False) as font:
                reports.append(verify_font(font, font_path, options=options))
        except Exception as e:
            cs.StatusIndicator("error").add_message(f"{font_path.name}: {e}").emit()
            return 1

    by_parent = group_fonts_by_parent([r.path for r in reports])
    report_by_path = {r.path: r for r in reports}
    failed = 0

    for parent, font_paths in by_parent.items():
        group_reports = [report_by_path[p] for p in font_paths if p in report_by_path]
        cs.emit("")
        cs.emit(render_family_verify(group_reports, parent=parent))

    for report in reports:
        if not verify_passes(report, strict=strict):
            failed += 1

    cs.emit("")
    if failed:
        label = "failed" if not strict else "failed (strict)"
        cs.StatusIndicator("error").add_message(
            f"Verify {label}: {failed} of {len(reports)} font(s)"
        ).emit()
        return 1

    cs.StatusIndicator("success").add_message(
        f"Verify passed: {len(reports)} font(s)"
    ).emit()
    return 0


def cmd_pipeline(
    ctx: FlowContext,
    *,
    no_wrap: bool = False,
    no_connect: bool = False,
    no_aalt: bool = False,
    no_verify: bool = False,
    no_sort: bool = False,
) -> int:
    rc = cmd_scan(ctx, write_report=False)
    if rc != 0:
        return rc

    if not no_wrap:
        rc = cmd_wrap(ctx)
        if rc != 0:
            return rc

    if not no_connect:
        rc = cmd_connect(ctx, apply=False)
        if rc != 0:
            return rc
        if not ctx.dry_run:
            apply_ctx = FlowContext(
                paths=ctx.paths,
                recursive=ctx.recursive,
                dry_run=False,
                verbose=ctx.verbose,
                yes=ctx.yes,
                output_dir=ctx.output_dir,
                backup=ctx.backup,
                connect_include_low=ctx.connect_include_low,
                connect_include_manual=ctx.connect_include_manual,
                font_files=ctx.font_files,
                scan_root=ctx.scan_root,
            )
            rc = cmd_connect(apply_ctx, apply=True)
            if rc != 0:
                return rc

    if not no_aalt:
        rc = cmd_aalt(ctx, apply=not ctx.dry_run)
        if rc != 0:
            return rc

    if not no_verify:
        rc = cmd_verify(ctx, strict=False)
        if rc != 0:
            return rc

    if not no_sort:
        rc = cmd_sort(ctx)
        if rc != 0:
            return rc

    cs.emit("")
    cs.StatusIndicator("success").add_message("Pipeline complete").emit()
    return 0


def prepare_context(ctx: FlowContext) -> int:
    font_files = collect_font_files_flow(ctx.paths, recursive=ctx.recursive)
    if not font_files:
        cs.StatusIndicator("error").add_message("No font files found").emit()
        return 1
    ctx.font_files = font_files
    ctx.scan_root = common_parent(font_files)
    cs.StatusIndicator("info").add_message(
        f"Found {len(font_files)} font file(s)"
    ).emit()
    cs.emit("")
    return 0
