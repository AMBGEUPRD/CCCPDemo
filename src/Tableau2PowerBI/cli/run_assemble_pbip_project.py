import argparse

from Tableau2PowerBI.agents.assembler import (
    PBIPProjectAssemblerAgent,
)
from Tableau2PowerBI.core.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble final PBIP project.")
    parser.add_argument("workbook_name", help="Name of the Tableau workbook")
    args = parser.parse_args()

    setup_logging()
    agent = PBIPProjectAssemblerAgent()
    agent.assemble_pbip_project(args.workbook_name)


if __name__ == "__main__":
    main()
