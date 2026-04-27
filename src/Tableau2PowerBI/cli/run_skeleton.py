import argparse

from Tableau2PowerBI.agents.skeleton import (
    PBIPProjectSkeletonAgent,
)
from Tableau2PowerBI.core.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PBIP project skeleton.")
    parser.add_argument("workbook_name", help="Name of the Tableau workbook")
    parser.add_argument("--semantic-model-name", default=None, help="Override semantic model name")
    args = parser.parse_args()

    setup_logging()
    agent = PBIPProjectSkeletonAgent()

    workbook_name = args.workbook_name
    semantic_model_name = args.semantic_model_name or workbook_name
    agent.generate_pbip_project_skeleton(
        workbook_name,
        report_name=workbook_name,
        semantic_model_name=semantic_model_name,
    )


if __name__ == "__main__":
    main()
