import argparse

from Tableau2PowerBI.core.source_detection import extract_metadata_with_dispatch
from Tableau2PowerBI.core.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract metadata from a supported source file.")
    parser.add_argument("source_path", help="Path to .twb, .twbx, or .zip (PBIP package) file")
    args = parser.parse_args()

    setup_logging()
    extract_metadata_with_dispatch(args.source_path)


if __name__ == "__main__":
    main()
