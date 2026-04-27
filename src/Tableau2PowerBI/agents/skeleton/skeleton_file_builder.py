"""SkeletonFileBuilder — builds JSON content for PBIP project scaffold files."""

from __future__ import annotations

import json
import uuid

from Tableau2PowerBI.core.config import SCHEMA_PBIR, SCHEMA_PBISM, SCHEMA_PLATFORM


class SkeletonFileBuilder:
    """Builds the JSON content for each file in the PBIP project scaffold.

    This class encapsulates all the file-content generation logic as pure
    methods that return serialised JSON strings.  The agent class handles
    file I/O; this class handles only data construction.
    """

    @staticmethod
    def pbip_manifest(report_name: str) -> str:
        """Build the ``.pbip`` root manifest JSON."""
        manifest = {
            "version": "1.0",
            "artifacts": [
                {"report": {"path": f"{report_name}.Report"}},
            ],
            "settings": {},
        }
        return json.dumps(manifest, indent=2)

    @staticmethod
    def gitignore() -> str:
        """Build the ``.gitignore`` content for PBI cache exclusions."""
        return "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n"

    @staticmethod
    def platform(display_name: str, item_type: str) -> str:
        """Build a ``.platform`` metadata file for a report or semantic model."""
        platform = {
            "$schema": SCHEMA_PLATFORM,
            "metadata": {
                "type": item_type,
                "displayName": display_name,
            },
            "config": {
                "version": "2.0",
                "logicalId": str(uuid.uuid4()),
            },
        }
        return json.dumps(platform, indent=2)

    @staticmethod
    def report_definition_pbir(semantic_model_name: str) -> str:
        """Build ``definition.pbir`` linking the report to its semantic model."""
        definition = {
            "$schema": SCHEMA_PBIR,
            "version": "4.0",
            "datasetReference": {
                "byPath": {
                    "path": f"../{semantic_model_name}.SemanticModel",
                }
            },
        }
        return json.dumps(definition, indent=2)

    @staticmethod
    def semantic_model_definition_pbism() -> str:
        """Build ``definition.pbism`` for the semantic model artefact."""
        definition = {
            "$schema": SCHEMA_PBISM,
            "version": "4.2",
            "settings": {},
        }
        return json.dumps(definition, indent=2)

    @staticmethod
    def semantic_model_bim(semantic_model_name: str) -> str:
        """Build the placeholder ``model.bim`` with empty tables/relationships."""
        model = {
            "name": semantic_model_name,
            "compatibilityLevel": 1601,
            "model": {
                "name": semantic_model_name,
                "culture": "en-US",
                "defaultPowerBIDataSourceVersion": "powerBI_V3",
                "sourceQueryCulture": "en-US",
                "dataAccessOptions": {
                    "legacyRedirects": True,
                    "returnErrorValuesAsNull": True,
                },
                "tables": [],
                "relationships": [],
                "cultures": [{"name": "en-US"}],
                "annotations": [
                    {
                        "name": "__PBI_TimeIntelligenceEnabled",
                        "value": "1",
                    }
                ],
            },
        }
        return json.dumps(model, indent=2)
