"""
Wrapper strategy and execution for OpenType table scaffolding.

Provides validation-first approach to adding table scaffolding and enrichment.
"""

from dataclasses import dataclass, field
from typing import List, Set, Tuple

from fontTools.ttLib import TTFont

from .detection import UnifiedGlyphDetector
from .results import OperationResult
from .validation import FontValidator
from .wrapper_helpers import (
    create_cmap,
    create_dsig_stub,
    create_gdef,
    create_gpos,
    create_gsub,
    enrich_font,
)


@dataclass
class WrapperPlan:
    """Plan for what wrapper operations to perform."""

    needs_cmap: bool = False
    needs_gdef: bool = False
    needs_gsub: bool = False
    needs_gpos: bool = False
    needs_dsig: bool = False

    can_migrate_kern: bool = False
    kern_pair_count: int = 0

    can_infer_liga: bool = False
    liga_count: int = 0

    can_enrich_gdef: bool = False
    mark_count: int = 0
    ligature_caret_count: int = 0

    warnings: List[str] = field(default_factory=list)

    def has_work(self) -> bool:
        """Check if any work needs to be done."""
        return (
            self.needs_cmap
            or self.needs_gdef
            or self.needs_gsub
            or self.needs_gpos
            or self.can_migrate_kern
            or self.can_infer_liga
            or self.can_enrich_gdef
        )

    def summarize(self) -> str:
        """Human-readable summary of the plan."""
        actions = []

        if self.needs_cmap:
            actions.append("Create Unicode cmap from glyph names")
        if self.needs_gdef:
            actions.append("Create GDEF table")
        if self.needs_gsub:
            actions.append("Create GSUB table")
        if self.needs_gpos:
            actions.append("Create GPOS table")

        if self.can_migrate_kern:
            actions.append(f"Migrate {self.kern_pair_count} kern pairs → GPOS")
        if self.can_infer_liga:
            actions.append(f"Create liga feature with {self.liga_count} ligatures")
        if self.can_enrich_gdef:
            details = []
            if self.mark_count > 0:
                details.append(f"{self.mark_count} marks")
            if self.ligature_caret_count > 0:
                details.append(f"{self.ligature_caret_count} lig carets")
            if details:
                actions.append(f"Enrich GDEF ({', '.join(details)})")
            else:
                actions.append("Enrich GDEF")

        if not actions:
            return "No changes needed"

        return "\n".join(f"• {action}" for action in actions)


class WrapperStrategyEngine:
    """Determines optimal wrapper strategy for a font."""

    def __init__(self, font: TTFont, validator: FontValidator):
        self.font = font
        self.validator = validator
        self.state = validator.state

    def create_plan(
        self, user_preferences: dict
    ) -> Tuple[WrapperPlan, OperationResult]:
        """
        Create a wrapper plan based on font state and user preferences.

        Args:
            user_preferences: Dict with keys like 'overwrite_cmap', 'enrich', etc.

        Returns:
            (plan, validation_result)
        """
        plan = WrapperPlan()
        result = OperationResult(success=True)

        # Always validate first
        result.add_info("Analyzing font state...")

        # Determine what scaffolding is needed
        if not self.state.has_unicode_cmap:
            plan.needs_cmap = True
            result.add_info("Unicode cmap missing or incomplete")

        if not self.state.has_gdef:
            plan.needs_gdef = True
            result.add_info("GDEF table missing")

        if not self.state.has_gsub:
            plan.needs_gsub = True
            result.add_info("GSUB table missing")

        if not self.state.has_gpos:
            plan.needs_gpos = True
            result.add_info("GPOS table missing")

        # Check enrichment opportunities (default to True)
        enrich = user_preferences.get("enrich", True)

        if enrich:
            if not self.state.can_enrich():
                result.add_warning(
                    "Cannot enrich font: no usable Unicode cmap",
                    "Will only add table scaffolding",
                )
            else:
                # Check kern migration
                if self.state.has_kern and self.state.kern_pair_count > 0:
                    if "kern" not in self.state.gpos_features:
                        plan.can_migrate_kern = True
                        plan.kern_pair_count = self.state.kern_pair_count
                        result.add_info(
                            f"Can migrate {plan.kern_pair_count} kern pairs to GPOS"
                        )
                    else:
                        result.add_info("Kern already in GPOS, skipping migration")

                # Check ligature inference
                ligatures = self._detect_ligatures()
                existing_liga_components = self._get_existing_liga_components()
                new_ligatures = [
                    lig
                    for lig in ligatures
                    if tuple(lig[0]) not in existing_liga_components
                ]

                if new_ligatures:
                    plan.can_infer_liga = True
                    plan.liga_count = len(new_ligatures)
                    if len(new_ligatures) < len(ligatures):
                        result.add_info(
                            f"Can add {len(new_ligatures)} ligatures "
                            f"({len(ligatures) - len(new_ligatures)} already exist)"
                        )
                    else:
                        result.add_info(
                            f"Can infer {len(new_ligatures)} ligatures from glyph names"
                        )

                # Check GDEF enrichment
                if not self.state.gdef_has_classes or not self.state.gdef_has_carets:
                    plan.can_enrich_gdef = True

                    if not self.state.gdef_has_classes:
                        marks = self._detect_marks()
                        plan.mark_count = len(marks)
                        if marks:
                            result.add_info(f"Can classify {len(marks)} mark glyphs")

                    if not self.state.gdef_has_carets and ligatures:
                        plan.ligature_caret_count = len(ligatures)
                        result.add_info(
                            f"Can add carets for {len(ligatures)} ligatures",
                            "Note: Caret positions will be evenly spaced (may need manual adjustment)",
                        )

        # Validate any destructive operations
        if user_preferences.get("overwrite_cmap") and self.state.has_unicode_cmap:
            cmap_result = self.validator.validate_cmap_operation(overwrite=True)
            result.messages.extend(cmap_result.messages)
            if cmap_result.has_errors():
                result.success = False

        # Check for problematic overwrites
        for table in ["gdef", "gsub", "gpos"]:
            if user_preferences.get(f"overwrite_{table}"):
                table_result = self.validator.validate_otl_operation(
                    table.upper(), overwrite=True
                )
                result.messages.extend(table_result.messages)
                if table_result.has_errors():
                    result.success = False

        # Final summary
        if plan.has_work():
            result.add_info("Wrapper plan created", plan.summarize())
        else:
            result.add_info(
                "Font already has complete OpenType tables",
                "No wrapper operations needed",
            )

        return plan, result

    def _detect_ligatures(self) -> List[tuple]:
        """Detect ligature opportunities."""
        detector = UnifiedGlyphDetector(self.font)
        features = detector.get_features()
        return features["liga"]

    def _get_existing_liga_components(self) -> Set[tuple]:
        """Get component sequences of existing ligatures."""
        components = set()
        if "GSUB" in self.font:
            gsub = self.font["GSUB"].table
            if hasattr(gsub, "LookupList") and gsub.LookupList:
                for lookup in gsub.LookupList.Lookup:
                    if lookup.LookupType == 4:  # Ligature
                        for subtable in lookup.SubTable:
                            if hasattr(subtable, "ligatures"):
                                for first_glyph, lig_list in subtable.ligatures.items():
                                    for lig in lig_list:
                                        comp_tuple = tuple(
                                            [first_glyph] + lig.Component
                                        )
                                        components.add(comp_tuple)
        return components

    def _detect_marks(self) -> Set[str]:
        """Detect mark glyphs."""
        return self.validator._detect_marks()


class WrapperExecutor:
    """Executes wrapper plan operations."""

    def __init__(self, font: TTFont, plan: WrapperPlan):
        self.font = font
        self.plan = plan

    def execute(self) -> Tuple[OperationResult, bool]:
        """
        Execute all operations in plan.

        Returns:
            (result, has_changes) - result with messages, and boolean indicating if any changes were made
        """
        result = OperationResult(success=True)
        has_changes = False

        # Execute scaffolding operations
        if self.plan.needs_cmap:
            changed, msgs = create_cmap(self.font, overwrite_unicode=False)
            if changed:
                has_changes = True
                result.add_info("Created Unicode cmap")
            for msg in msgs:
                result.add_info(msg)

        if self.plan.needs_gdef:
            changed, msg = create_gdef(self.font, overwrite=False)
            if changed:
                has_changes = True
                result.add_info(msg)
            else:
                result.add_info(msg)

        if self.plan.needs_gpos:
            changed, msg = create_gpos(self.font, overwrite=False)
            if changed:
                has_changes = True
                result.add_info(msg)
            else:
                result.add_info(msg)

        if self.plan.needs_gsub:
            changed, msg = create_gsub(self.font, overwrite=False)
            if changed:
                has_changes = True
                result.add_info(msg)
            else:
                result.add_info(msg)

        # DSIG is handled separately in user_prefs
        if self.plan.needs_dsig:
            changed, msg = create_dsig_stub(self.font, enable=True)
            if changed:
                has_changes = True
                result.add_info(msg)
            else:
                result.add_info(msg)

        # Execute enrichment operations
        if (
            self.plan.can_migrate_kern
            or self.plan.can_infer_liga
            or self.plan.can_enrich_gdef
        ):
            e_changed, e_msgs = enrich_font(
                self.font,
                do_kern_migration=self.plan.can_migrate_kern,
                do_liga=self.plan.can_infer_liga,
                do_gdef_classes=self.plan.mark_count > 0,
                do_lig_carets=self.plan.ligature_caret_count > 0,
                drop_kern_after=False,  # Controlled by user preference
            )
            if e_changed:
                has_changes = True
                result.add_info("Enrichment completed")
            for msg in e_msgs:
                result.add_info(msg)

        return result, has_changes

