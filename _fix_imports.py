"""Temporary script: update core.utils → split module imports. Delete after running."""

import pathlib


def replace_in_file(path_str, old, new):
    f = pathlib.Path(path_str)
    if not f.exists():
        return "MISSING_FILE"
    c = f.read_text(encoding="utf-8")
    if old not in c:
        return "NO_MATCH"
    f.write_text(c.replace(old, new, 1), encoding="utf-8")
    return "OK"


changes = []

# CLI entrypoints: setup_logging -> logging_setup
for fpath in [
    "src/Tableau2PowerBI/cli/run_target_technical_doc.py",
    "src/Tableau2PowerBI/cli/run_skeleton.py",
    "src/Tableau2PowerBI/cli/run_semantic_model.py",
    "src/Tableau2PowerBI/cli/run_pipeline.py",
    "src/Tableau2PowerBI/cli/run_functional_doc.py",
    "src/Tableau2PowerBI/cli/run_extraction.py",
    "src/Tableau2PowerBI/cli/run_assemble_pbip_project.py",
]:
    r = replace_in_file(
        fpath,
        "from Tableau2PowerBI.core.utils import setup_logging",
        "from Tableau2PowerBI.core.logging_setup import setup_logging",
    )
    changes.append((fpath, r))

# webapp/runtime.py
r = replace_in_file(
    "src/Tableau2PowerBI/webapp/runtime.py",
    "from Tableau2PowerBI.core.utils import shorten_abs_paths",
    "from Tableau2PowerBI.core.logging_setup import shorten_abs_paths",
)
changes.append(("runtime.py shorten_abs_paths", r))

# core/json_response.py
r = replace_in_file(
    "src/Tableau2PowerBI/core/json_response.py",
    "from Tableau2PowerBI.core.utils import recover_malformed_json, strip_markdown_fences",
    "from Tableau2PowerBI.core.llm_output_parsing import recover_malformed_json, strip_markdown_fences",
)
changes.append(("core/json_response.py", r))

# agents/assembler
r = replace_in_file(
    "src/Tableau2PowerBI/agents/assembler/__init__.py",
    "from Tableau2PowerBI.core.utils import ensure_output_dir, get_output_dir, reset_output_dir, validate_name",
    "from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir, validate_name",
)
changes.append(("assembler/__init__", r))

# agents/warnings_reviewer
r = replace_in_file(
    "src/Tableau2PowerBI/agents/warnings_reviewer/__init__.py",
    "from Tableau2PowerBI.core.utils import get_output_dir, strip_markdown_fences",
    "from Tableau2PowerBI.core.output_dirs import get_output_dir\nfrom Tableau2PowerBI.core.llm_output_parsing import strip_markdown_fences",
)
changes.append(("warnings_reviewer", r))

# report_skeleton
r = replace_in_file(
    "src/Tableau2PowerBI/agents/report_skeleton/report_skeleton_agent.py",
    "from Tableau2PowerBI.core.utils import normalise_warnings",
    "from Tableau2PowerBI.core.llm_output_parsing import normalise_warnings",
)
changes.append(("report_skeleton_agent", r))

# report_visuals/postprocessing
r = replace_in_file(
    "src/Tableau2PowerBI/agents/report_visuals/postprocessing.py",
    "from Tableau2PowerBI.core.utils import recover_malformed_json",
    "from Tableau2PowerBI.core.llm_output_parsing import recover_malformed_json",
)
changes.append(("report_visuals/postprocessing", r))

# report_visuals/pipeline_inputs
r = replace_in_file(
    "src/Tableau2PowerBI/agents/report_visuals/pipeline_inputs.py",
    "from Tableau2PowerBI.core.utils import get_output_dir",
    "from Tableau2PowerBI.core.output_dirs import get_output_dir",
)
changes.append(("report_visuals/pipeline_inputs", r))

# cli/pipeline.py
r = replace_in_file(
    "src/Tableau2PowerBI/cli/pipeline.py",
    "from Tableau2PowerBI.core.utils import get_output_dir",
    "from Tableau2PowerBI.core.output_dirs import get_output_dir",
)
changes.append(("cli/pipeline.py", r))

# pbir_report_generator_agent
r = replace_in_file(
    "src/Tableau2PowerBI/agents/report_visuals/pbir_report_generator_agent.py",
    "from Tableau2PowerBI.core.utils import ensure_output_dir, get_output_dir, reset_output_dir",
    "from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir",
)
changes.append(("pbir_report_generator_agent", r))

for name, result in changes:
    print(f"  {result:20s} {name}")
