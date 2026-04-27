import argparse

from Tableau2PowerBI.agents.metadata_extractor import (
    TableauMetadataExtractorAgent,
)
from Tableau2PowerBI.core.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract metadata from a Tableau workbook.")
    parser.add_argument("twb_path", help="Path to .twb or .twbx file")
    args = parser.parse_args()

    setup_logging()
    agent = TableauMetadataExtractorAgent()
    agent.extract_tableau_metadata(args.twb_path)


if __name__ == "__main__":
    main()
