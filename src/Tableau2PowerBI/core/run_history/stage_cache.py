"""Stage dependency graph and input-hash caching logic.

Defines the pipeline's data-flow dependencies and provides helpers
to decide which stages can be skipped (inputs unchanged) vs. which
must (re-)run.

Key types:

* :class:`StageInfo`    — static metadata for one stage (upstream deps,
  deterministic flag).
* :class:`SkipDecision` — the result of evaluating whether a stage can
  be skipped on the current run.

Public API:

* ``STAGE_GRAPH``            — the authoritative dependency graph.
* ``compute_input_hash()``   — SHA-256 of a stage's input files.
* ``should_skip_stage()``    — compare stored hash vs. current hash.
* ``get_stale_downstream()`` — transitive closure of downstream stages.
* ``resolve_stages_to_run()``— minimal execution set for a pipeline run.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from Tableau2PowerBI.core.run_history.run_manifest import RunManifest
from Tableau2PowerBI.core.run_history.stage_status import StageStatus

logger = logging.getLogger(__name__)


# ── Value objects ────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageInfo:
    """Static metadata about a single pipeline stage.

    Attributes:
        upstream: Names of stages that must complete before this one.
        deterministic: True if the stage always produces identical output
            for the same inputs (e.g. XML parsing, file assembly).
            False for LLM-backed stages whose output may vary.
    """

    upstream: tuple[str, ...]
    deterministic: bool


@dataclass(frozen=True)
class SkipDecision:
    """Result of evaluating whether a stage can be skipped.

    Attributes:
        skip: True if the stage does not need to re-run.
        reason: Human-readable label — one of ``"cached"``,
            ``"re-generable"``, ``"not completed"``, ``"no hash available"``,
            or ``"inputs changed"``.
    """

    skip: bool
    reason: str


# ── Stage dependency graph (authoritative) ───────────────────────────
STAGE_GRAPH: dict[str, StageInfo] = {
    "metadata_extractor": StageInfo(
        upstream=(),
        deterministic=True,
    ),
    "functional_doc": StageInfo(
        upstream=("metadata_extractor",),
        deterministic=False,
    ),
    "target_technical_doc": StageInfo(
        upstream=("metadata_extractor", "functional_doc"),
        deterministic=False,
    ),
}


# ── Input hashing ────────────────────────────────────────────────────


def compute_input_hash(input_paths: list[Path]) -> str:
    """Return a SHA-256 hex digest of the sorted file contents.

    Files are hashed directly. Directories are walked recursively and all
    contained files contribute to the digest in stable path order.
    Returns an empty string when no files are found.
    """
    h = hashlib.sha256()
    found = False
    for p in sorted(input_paths):
        if p.is_file():
            h.update(p.read_bytes())
            found = True
        elif p.is_dir():
            for child in sorted(c for c in p.rglob("*") if c.is_file()):
                h.update(str(child.relative_to(p)).encode("utf-8"))
                h.update(child.read_bytes())
                found = True
    return h.hexdigest() if found else ""


# ── Skip decision ────────────────────────────────────────────────────


def should_skip_stage(
    manifest: RunManifest,
    stage_name: str,
    current_hash: str,
) -> SkipDecision:
    """Decide whether *stage_name* can be safely skipped.

    Returns a :class:`SkipDecision` with a human-readable reason.
    Deterministic stages skip silently when the hash matches.
    LLM stages return a ``reason`` hinting that regeneration is
    available ("re-generable") so the UI can distinguish.
    """
    record = manifest.stages.get(stage_name)
    if record is None or record.status != StageStatus.COMPLETED:
        return SkipDecision(skip=False, reason="not completed")

    if not current_hash or not record.input_hash:
        return SkipDecision(skip=False, reason="no hash available")

    if current_hash != record.input_hash:
        return SkipDecision(skip=False, reason="inputs changed")

    info = STAGE_GRAPH.get(stage_name)
    if info and info.deterministic:
        return SkipDecision(skip=True, reason="cached")
    else:
        return SkipDecision(skip=True, reason="re-generable")


# ── Downstream propagation ───────────────────────────────────────────


def get_stale_downstream(stage_name: str) -> set[str]:
    """Return the transitive set of stages downstream of *stage_name*.

    Does **not** include *stage_name* itself.
    """
    result: set[str] = set()
    queue = [stage_name]
    while queue:
        current = queue.pop()
        for name, info in STAGE_GRAPH.items():
            if current in info.upstream and name not in result:
                result.add(name)
                queue.append(name)
    return result


# ── Resolve execution set ────────────────────────────────────────────


def resolve_stages_to_run(
    manifest: RunManifest,
    current_hashes: dict[str, str] | None = None,
    force_stages: set[str] | None = None,
    pipeline_stages: set[str] | None = None,
) -> set[str]:
    """Compute the minimal set of stages that must execute.

    Two modes:

    **Full pipeline** (no *force_stages*):
        1. Start with all incomplete or changed-input stages.
        2. Propagate each required stage to its transitive downstream.

    **Selective regen** (*force_stages* provided):
        1. Start with exactly the forced stages.
        2. Propagate downstream, but only add a downstream stage
           when **all** of its upstreams are satisfied (completed,
           forced, or already added).

    In both cases the result is constrained to *pipeline_stages*
    when provided.
    """
    all_stages = set(STAGE_GRAPH.keys())
    if pipeline_stages is not None:
        all_stages = all_stages & pipeline_stages

    must_run: set[str] = set()

    if force_stages:
        # ── Selective regen: start with only forced stages ──
        for name in force_stages:
            if name in all_stages:
                must_run.add(name)

        # Build "satisfied" set: completed stages + no-upstream stages
        # + forced stages — used to check if downstream can run.
        satisfied: set[str] = set(must_run)
        for name in STAGE_GRAPH:
            if not STAGE_GRAPH[name].upstream:
                satisfied.add(name)
            record = manifest.stages.get(name)
            if record and record.status == StageStatus.COMPLETED:
                satisfied.add(name)

        # Fixed-point: add downstream only if all upstreams met
        changed = True
        while changed:
            changed = False
            for name, info in STAGE_GRAPH.items():
                if name in must_run or name not in all_stages:
                    continue
                if not info.upstream:
                    continue
                all_met = all(u in satisfied for u in info.upstream)
                triggered = any(u in must_run for u in info.upstream)
                if all_met and triggered:
                    must_run.add(name)
                    satisfied.add(name)
                    changed = True
    else:
        # ── Full pipeline: run all incomplete/changed stages ──
        for name in all_stages:
            current_hash = (current_hashes or {}).get(name, "")
            decision = should_skip_stage(manifest, name, current_hash)
            record = manifest.stages.get(name)
            if record is None or record.status in (
                StageStatus.NOT_STARTED,
                StageStatus.FAILED,
                StageStatus.OVERWRITTEN,
            ):
                must_run.add(name)
            elif current_hash and not decision.skip:
                must_run.add(name)

        # Naive downstream propagation for full pipeline.
        queue = list(must_run)
        while queue:
            current = queue.pop()
            downstream = get_stale_downstream(current) & all_stages
            for name in downstream:
                if name not in must_run:
                    must_run.add(name)
                    queue.append(name)

    return must_run
