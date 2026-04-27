"""ReportPageVisualsAgent — Pass 2 of the hybrid PBIR generation pipeline."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from Tableau2PowerBI.agents.report_page_visuals.page_visuals_output import PageVisualsOutput
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.json_response import parse_llm_json_object
from Tableau2PowerBI.core.llm_output_parsing import (
    normalise_warnings,
    recover_malformed_json,
    strip_markdown_fences,
)

logger = logging.getLogger(__name__)

# Keys in the LLM response that are metadata, not visual content.
_NON_VISUAL_KEYS = {"_warnings"}


class ReportPageVisualsAgent(Agent):
    """Pass 2 — generate visual.json content for a single report page.

    Receives the skeleton page context (visual types, positions) and
    filtered Tableau worksheet metadata. Returns visual.json content
    for each visual slot.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="report_page_visuals_agent",
            model=model,
            settings=settings,
        )
        self.prompt_template = (
            "Generate visual.json content for each visual on this page "
            "following the skill instructions.\n\n"
            "Return a JSON object where each key is a visual hex_id and "
            "each value is the COMPLETE visual.json content as a COMPACT "
            "JSON string (no indentation). Include a '_warnings' key.\n"
            "Do NOT wrap in markdown fences.\n\n"
            "Workbook name: {workbook_name}\n"
            "Page: {display_name} (hex_id: {page_hex_id})\n\n"
        )

    def generate_page_visuals(
        self,
        workbook_name: str,
        skeleton_page_json: str,
        page_worksheets_json: str,
        schema_text: str,
    ) -> PageVisualsOutput:
        """Generate visual.json content for all visuals on one page.

        Args:
            workbook_name: Name of the Tableau workbook.
            skeleton_page_json: JSON-serialised SkeletonPage with visual slots.
            page_worksheets_json: Filtered worksheets + datasource_index JSON.
            schema_text: Semantic model schema summary for the LLM.

        Returns:
            A validated PageVisualsOutput mapping visual hex_id → content.
        """
        # Extract page identifiers for the prompt template.
        skeleton_page = json.loads(skeleton_page_json)
        display_name = skeleton_page.get("display_name", "Unknown")
        page_hex_id = skeleton_page.get("hex_id", "")

        prompt = (
            self.prompt_template.replace("{workbook_name}", workbook_name)
            .replace("{display_name}", display_name)
            .replace("{page_hex_id}", page_hex_id)
        )
        prompt += f"Visual slots (from skeleton):\n{skeleton_page_json}\n\n"
        prompt += f"Semantic model schema:\n\n{schema_text}\n\n"
        prompt += (
            "Visual metadata for this page (use field_bindings " "to build queryState):\n\n" f"{page_worksheets_json}"
        )
        return self._run_with_validation(prompt)

    # ── LLM call with validation and retry ────────────────────────────────

    def _run_with_validation(self, prompt: str) -> PageVisualsOutput:
        """Call the LLM and validate, retrying with error feedback."""
        return self.run_with_validation(
            prompt,
            parse_page_visuals_response,
            label="Report page visuals response",
            parse_exceptions=(ValidationError, ValueError),
        )

    @staticmethod
    def _normalise_visual_content(content: object) -> str:
        """Coerce a visual.json value into a consistently formatted string.

        Handles cases where the LLM returns the content as a dict instead
        of a JSON string, double-encodes it, or contains invalid escape
        sequences (stray backslashes).
        """
        obj: dict | None = None
        if isinstance(content, dict):
            obj = content
        elif isinstance(content, list):
            return json.dumps(content, indent=2, ensure_ascii=False)
        elif not isinstance(content, str):
            return str(content)
        else:
            # If the string parses as JSON, re-serialise for consistency.
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    obj = parsed
                elif isinstance(parsed, list):
                    return json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                # Try recovering invalid escape sequences / control chars.
                recovered = recover_malformed_json(content)
                if recovered is not None:
                    logger.warning(
                        "Visual content recovered after fixing " "escape sequences (%d chars)",
                        len(content),
                    )
                    obj = recovered if isinstance(recovered, dict) else None
                    if obj is None:
                        return json.dumps(recovered, indent=2, ensure_ascii=False)
                else:
                    return content

        if obj is not None:
            obj = ReportPageVisualsAgent._fix_visual_structure(obj)
            return json.dumps(obj, indent=2, ensure_ascii=False)
        return str(content)

    @staticmethod
    def _fix_visual_structure(data: dict) -> dict:
        """Fix common LLM structural mistakes in a visual.json dict.

        Applies the same corrections as the monolithic report_visuals
        agent's ``_sanitize_visuals``:
        1. Strip ``visual.config`` (legacy PBIX property).
        2. Move ``drillFilterOtherVisuals`` from root or ``visual.query``
           into ``visual``.
        3. Move ``filterConfig`` from ``visual`` to root.
        4. Strip ``active`` from ``filterConfig.filters[].field``.
        5. Wrap bare arrays in ``queryState`` roles.
        """
        visual_obj = data.get("visual")
        if not isinstance(visual_obj, dict):
            return data

        # Strip visual.config (legacy PBIX property).
        if "config" in visual_obj:
            del visual_obj["config"]
            logger.debug("Stripped visual.config")

        query_obj = visual_obj.get("query", {})

        # Move drillFilterOtherVisuals from visual.query → visual.
        if isinstance(query_obj, dict) and "drillFilterOtherVisuals" in query_obj:
            visual_obj["drillFilterOtherVisuals"] = query_obj.pop("drillFilterOtherVisuals")
            logger.debug("Moved drillFilterOtherVisuals out of query")

        # Move drillFilterOtherVisuals from root → visual.
        if "drillFilterOtherVisuals" in data:
            visual_obj["drillFilterOtherVisuals"] = data.pop("drillFilterOtherVisuals")
            logger.debug("Moved drillFilterOtherVisuals from root to visual")

        # Move filterConfig from visual → root.
        if "filterConfig" in visual_obj:
            data["filterConfig"] = visual_obj.pop("filterConfig")
            logger.debug("Moved filterConfig from visual to root")

        # Strip 'active' from filterConfig field entries.
        for filt in data.get("filterConfig", {}).get("filters", []):
            filt_field = filt.get("field")
            if isinstance(filt_field, dict) and "active" in filt_field:
                del filt_field["active"]

        # Wrap bare arrays in queryState roles.
        if isinstance(query_obj, dict):
            query_state = query_obj.get("queryState", {})
            if isinstance(query_state, dict):
                for role_name, role_val in query_state.items():
                    if isinstance(role_val, list):
                        query_state[role_name] = {"projections": role_val}
                        logger.debug("Wrapped bare array in queryState '%s'", role_name)

        return data

    @staticmethod
    def _recover_truncated_json(text: str) -> dict | None:
        """Attempt to recover a truncated JSON object.

        Page-level responses are smaller than the monolithic output,
        so truncation is less likely. Still useful as a safety net.
        """
        text = text.rstrip()

        if text.endswith("}"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Find the last complete key-value pair.
        last_comma = text.rfind(',"')
        if last_comma > 0:
            candidate = text[:last_comma] + "}"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return None


def parse_page_visuals_response(response: str) -> PageVisualsOutput:
    """Parse and validate the raw LLM response for page visuals."""
    clean = strip_markdown_fences(response)
    try:
        raw = parse_llm_json_object(clean, logger=logger, enable_recovery=True)
    except ValueError as parse_exc:
        # Dense pages can still hit token limits and return truncated JSON.
        raw = ReportPageVisualsAgent._recover_truncated_json(clean)
        if raw is None:
            raise ValueError(
                f"Response is not valid JSON. {parse_exc}. First 300 chars: {clean[:300]!r}"
            ) from parse_exc

    # Separate visual keys from metadata keys, normalise content.
    visuals: dict[str, str] = {}
    for key, content in raw.items():
        if key in _NON_VISUAL_KEYS:
            continue
        visuals[key] = ReportPageVisualsAgent._normalise_visual_content(content)

    warnings = normalise_warnings(raw.get("_warnings", []))

    return PageVisualsOutput.model_validate({"visuals": visuals, "warnings": warnings})
