import argparse

from Tableau2PowerBI.agents.semantic_model import (
    PBIPSemanticModelGeneratorAgent,
)
from Tableau2PowerBI.core.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PBIP semantic model via LLM.")
    parser.add_argument("workbook_name", help="Name of the Tableau workbook")
    parser.add_argument("--semantic-model-name", default=None, help="Override semantic model name")
    args = parser.parse_args()

    setup_logging()
    agent = PBIPSemanticModelGeneratorAgent().create()

    workbook_name = args.workbook_name
    semantic_model_name = args.semantic_model_name or workbook_name
    agent.generate_pbip_semantic_model(workbook_name, semantic_model_name=semantic_model_name)


if __name__ == "__main__":
    main()
