"""Generate functional documentation for a Tableau workbook.

Reads the ``tableau_metadata.json`` produced by Stage 1 (metadata extraction)
and generates hierarchical functional documentation in Markdown and HTML.
The functional doc agent automatically switches to a slimmed metadata input
when the full metadata exceeds the configured size threshold.

Usage::

    t2pbi-funcdoc "Supermercato"
    t2pbi-funcdoc "Supermercato" --data-folder "data/golden/Supermercato"
"""

import argparse
import logging

from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate functional documentation for a Tableau workbook. "
            "Uses full metadata for small inputs and auto-switches to slim "
            "metadata when the full extraction is too large."
        ),
    )
    parser.add_argument(
        "workbook_name",
        help="Workbook stem name (e.g. 'Supermercato')",
    )
    parser.add_argument(
        "--data-folder",
        default=None,
        help=(
            "Path to folder containing tableau_metadata.json "
            "(and optionally functional_doc_input_slim.json). Defaults to the "
            "metadata extractor output directory."
        ),
    )
    args = parser.parse_args()

    setup_logging()

    agent = FunctionalDocAgent()
    with agent:
        agent.create()
        md_path, html_path = agent.generate_documentation(
            args.workbook_name,
            data_folder_path=args.data_folder,
        )
    logger.info("Documentation generated:")
    logger.info("  Markdown: %s", md_path)
    logger.info("  HTML:     %s", html_path)


if __name__ == "__main__":
    main()
