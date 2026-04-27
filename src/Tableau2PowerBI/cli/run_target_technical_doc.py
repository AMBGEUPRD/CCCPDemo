"""Generate target technical documentation for a Tableau workbook.

Reads the ``semantic_model_input.json``, ``report_input.json``, and
``functional_documentation.json`` from upstream agent output and produces
the TDD — a structured technical blueprint for the Power BI migration.

Usage::

    t2pbi-tdd "Supermercato"
    t2pbi-tdd "Supermercato" --data-folder "data/golden/Supermercato"
"""

import argparse
import logging

from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate target technical documentation for a Tableau workbook.",
    )
    parser.add_argument(
        "workbook_name",
        help="Workbook stem name (e.g. 'Supermercato')",
    )
    parser.add_argument(
        "--data-folder",
        default=None,
        help="Path to folder containing input files " "(defaults to upstream agent output directories)",
    )
    args = parser.parse_args()

    setup_logging()

    agent = TargetTechnicalDocAgent()
    with agent:
        agent.create()
        tdd = agent.generate_tdd(
            args.workbook_name,
            data_folder_path=args.data_folder,
        )
    logger.info(
        "TDD generated: %d tables, %d measures, %d pages",
        len(tdd.semantic_model.tables),
        len(tdd.dax_measures.measures),
        len(tdd.report.pages),
    )


if __name__ == "__main__":
    main()
