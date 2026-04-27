import argparse
import logging
from pathlib import Path

from Tableau2PowerBI.cli import pipeline as pipeline_module
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.run_history import STAGE_GRAPH, RunHistory
from Tableau2PowerBI.core.logging_setup import setup_logging

logger = logging.getLogger(__name__)

MigrationPipeline = pipeline_module.MigrationPipeline
run_pipeline = pipeline_module.run_pipeline
_MODEL_SHORT_NAMES = pipeline_module._MODEL_SHORT_NAMES
"""CLI entrypoint for the Tableau → Power BI migration pipeline."""


def _build_settings(models_json: str | None) -> AgentSettings:
    """Backward-compatible wrapper around cli.pipeline.build_settings."""
    return pipeline_module.build_settings(models_json)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full Tableau to Power BI migration pipeline.",
    )
    parser.add_argument("twb_path", help="Path to .twb or .twbx file")
    parser.add_argument(
        "--semantic-model-name",
        default=None,
        help="Override semantic model name (defaults to workbook file name)",
    )
    parser.add_argument(
        "--models",
        default=None,
        metavar="JSON",
        help=(
            "Per-agent model overrides as JSON, e.g. "
            '\'{{"dax_measures": "o3", "semantic_model": "gpt-5.4"}}\'. '
            "Valid keys: " + ", ".join(sorted(_MODEL_SHORT_NAMES))
        ),
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="__latest__",
        default=None,
        metavar="RUN_ID",
        help=(
            "Resume a previous run. Without a value, resumes the latest run. "
            "With a RUN_ID, resumes that specific run."
        ),
    )
    parser.add_argument(
        "--regenerate",
        nargs="+",
        default=None,
        metavar="STAGE",
        help=(
            "Force-regenerate named stages (plus their downstream). "
            "Valid stage names: " + ", ".join(sorted(STAGE_GRAPH.keys()))
        ),
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        default=False,
        help="Ignore cache — regenerate all stages (default for new runs).",
    )
    args = parser.parse_args()

    setup_logging()
    settings = pipeline_module.build_settings(args.models)

    # Resolve --resume to a concrete run_id
    resume_run_id = None
    if args.resume:
        if args.resume == "__latest__":
            history = RunHistory(
                runs_root=settings.runs_root,
                output_root=settings.output_root,
                max_runs_per_workbook=settings.max_runs_per_workbook,
            )
            workbook_name = Path(args.twb_path).stem
            latest = history.get_latest_run(workbook_name)
            if latest is None:
                logger.warning(
                    "No previous run for '%s' — starting fresh",
                    workbook_name,
                )
            else:
                resume_run_id = latest.run_id
                logger.info("Resuming latest run: %s", resume_run_id)
        else:
            resume_run_id = args.resume

    # Resolve force stages
    force_stages: set[str] | None = None
    if args.force_all:
        force_stages = set(STAGE_GRAPH.keys())
    elif args.regenerate:
        force_stages = set(args.regenerate)
        invalid = force_stages - set(STAGE_GRAPH.keys())
        if invalid:
            parser.error(
                f"Unknown stage(s): {', '.join(sorted(invalid))}. " f"Valid: {', '.join(sorted(STAGE_GRAPH.keys()))}"
            )

    run_pipeline(
        args.twb_path,
        semantic_model_name=args.semantic_model_name,
        settings=settings,
        resume_run_id=resume_run_id,
        force_stages=force_stages,
    )


if __name__ == "__main__":
    main()
