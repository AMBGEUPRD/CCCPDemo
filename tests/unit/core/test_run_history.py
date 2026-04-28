"""Tests for pipeline run persistence and stage-cache skip logic.

The pipeline converts Tableau workbooks to Power BI through a sequence
of *stages* (metadata extraction → functional doc → target technical doc).
Two subsystems keep track of this:

* **RunHistory** — CRUD for run manifests on the local filesystem.
  Each run records which stages completed, their input hashes, and the
  stored artefact paths so a run can be resumed or replayed.

* **stage_cache** — uses the stage dependency graph and per-stage
  input hashes to decide which stages can be skipped on the next run.
  Deterministic stages (metadata extractor, skeleton, assembler) are
  skippable when their input hash hasn't changed.  LLM-backed stages
  are marked "re-generable" but still skippable when inputs match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Tableau2PowerBI.core.run_history import (
    STAGE_GRAPH,
    RunHistory,
    RunManifest,
    StageRecord,
    StageStatus,
    compute_input_hash,
    get_stale_downstream,
    resolve_stages_to_run,
    should_skip_stage,
)

# ═══════════════════════════════════════════════════════════════════
# Serialisation — StageRecord and RunManifest survive JSON round-trips
# ═══════════════════════════════════════════════════════════════════


class TestStageRecord:
    """Verify StageRecord converts to/from dict without data loss.

    StageRecord captures one stage's execution state: status, timing,
    token counts, and a hash of its inputs.  We need lossless
    serialisation because manifests are written to disk as JSON.
    """

    def test_round_trip(self) -> None:
        rec = StageRecord(
            status=StageStatus.COMPLETED,
            deterministic=False,
            started_at="2026-04-08T10:00:00+00:00",
            completed_at="2026-04-08T10:01:00+00:00",
            input_hash="abc123",
            duration_seconds=42.5,
            input_tokens=1000,
            output_tokens=200,
        )
        d = rec.to_dict()
        assert d["status"] == "completed"
        restored = StageRecord.from_dict(d)
        assert restored.status == StageStatus.COMPLETED
        assert restored.input_tokens == 1000
        assert restored.deterministic is False

    def test_defaults(self) -> None:
        rec = StageRecord()
        assert rec.status == StageStatus.NOT_STARTED
        assert rec.deterministic is True
        assert rec.input_tokens == 0

    def test_overwritten_status(self) -> None:
        rec = StageRecord(status=StageStatus.OVERWRITTEN)
        d = rec.to_dict()
        assert d["status"] == "overwritten"
        restored = StageRecord.from_dict(d)
        assert restored.status == StageStatus.OVERWRITTEN


class TestRunManifest:
    """Verify RunManifest (the top-level run envelope) round-trips through JSON.

    A manifest wraps metadata (run ID, workbook name, ADLS path) plus a
    dict of StageRecords, stored-artefact names, and aggregate token
    usage.  All fields must survive write → read without loss.
    """

    def test_round_trip(self) -> None:
        manifest = RunManifest(
            run_id="2026-04-08T10-00-00+00-00",
            workbook_name="Supermercato",
            workbook_file="Supermercato.twbx",
            created_at="2026-04-08T10:00:00+00:00",
            updated_at="2026-04-08T10:00:00+00:00",
            stages={
                "metadata_extractor": StageRecord(
                    status=StageStatus.COMPLETED,
                    input_hash="abc",
                ),
            },
            stored_artifacts=["tableau_metadata_extractor_agent"],
            token_usage={"total_in": 5000},
            adls_path="abfss://tableau@storage/Supermercato.twbx",
            result_id="result_1712614859123",
        )
        d = manifest.to_dict()
        restored = RunManifest.from_dict(d)
        assert restored.run_id == manifest.run_id
        assert restored.workbook_file == "Supermercato.twbx"
        assert restored.adls_path == manifest.adls_path
        assert restored.result_id == manifest.result_id
        assert restored.stages["metadata_extractor"].status == StageStatus.COMPLETED
        assert restored.stored_artifacts == ["tableau_metadata_extractor_agent"]

    def test_json_round_trip(self) -> None:
        manifest = RunManifest(
            run_id="test-run",
            workbook_name="Test",
            workbook_file="Test.twb",
            created_at="t0",
            updated_at="t0",
        )
        text = json.dumps(manifest.to_dict())
        restored = RunManifest.from_dict(json.loads(text))
        assert restored.run_id == "test-run"
        assert restored.stages == {}


# ═══════════════════════════════════════════════════════════════════
# RunHistory CRUD — create, list, update, and prune runs on disk
# ═══════════════════════════════════════════════════════════════════


class TestRunHistory:
    """Filesystem-backed run management: create, list, load, update, prune.

    Uses *tmp_path* so every test starts with a clean directory tree.
    max_runs_per_workbook is set to 3 to make the pruning test feasible.
    """

    @pytest.fixture()
    def history(self, tmp_path: Path) -> RunHistory:
        """One RunHistory scoped to a temp directory, capped at 3 runs."""
        return RunHistory(
            runs_root=tmp_path / "runs",
            output_root=tmp_path / "output",
            max_runs_per_workbook=3,
        )

    def test_create_and_load(self, history: RunHistory) -> None:
        m = history.create_run("WB", "WB.twb")
        assert m.workbook_name == "WB"
        loaded = history.load_run("WB", m.run_id)
        assert loaded.run_id == m.run_id
        assert loaded.workbook_file == "WB.twb"

    def test_list_runs_returns_newest_first(self, history: RunHistory) -> None:
        history.create_run("WB", "WB.twb")  # older
        m2 = history.create_run("WB", "WB.twb")  # newer
        runs = history.list_runs("WB")
        assert len(runs) == 2
        assert runs[0].run_id == m2.run_id  # newest first

    def test_list_workbooks(self, history: RunHistory) -> None:
        history.create_run("Alpha", "Alpha.twb")
        history.create_run("Beta", "Beta.twb")
        wbs = history.list_workbooks()
        assert "Alpha" in wbs
        assert "Beta" in wbs

    def test_get_latest_run(self, history: RunHistory) -> None:
        history.create_run("WB", "WB.twb")
        m2 = history.create_run("WB", "WB.twb")
        latest = history.get_latest_run("WB")
        assert latest is not None
        assert latest.run_id == m2.run_id

    def test_get_latest_run_empty(self, history: RunHistory) -> None:
        assert history.get_latest_run("NoSuch") is None

    def test_load_run_not_found(self, history: RunHistory) -> None:
        with pytest.raises(FileNotFoundError):
            history.load_run("WB", "nonexistent")

    def test_update_stage(self, history: RunHistory) -> None:
        m = history.create_run("WB", "WB.twb")
        history.update_stage(
            m,
            "metadata_extractor",
            status=StageStatus.COMPLETED,
            input_hash="hash1",
            duration_seconds=5.0,
            input_tokens=100,
            output_tokens=50,
            deterministic=True,
        )
        loaded = history.load_run("WB", m.run_id)
        rec = loaded.stages["metadata_extractor"]
        assert rec.status == StageStatus.COMPLETED
        assert rec.input_hash == "hash1"
        assert rec.input_tokens == 100

    def test_cleanup_old_runs_keeps_only_max(self, history: RunHistory) -> None:
        # Fixture caps max at 3 — create 5 so 2 must be pruned.
        for _ in range(5):
            history.create_run("WB", "WB.twb")
        history.cleanup_old_runs("WB")
        remaining = history.list_runs("WB")
        assert len(remaining) == 3  # oldest 2 pruned

    def test_mark_overwritten_flags_old_run_but_spares_current(self, history: RunHistory) -> None:
        # ── Setup: complete semantic_model in run 1 ──
        m1 = history.create_run("WB", "WB.twb")
        history.update_stage(
            m1,
            "semantic_model",
            status=StageStatus.COMPLETED,
            deterministic=False,
        )
        m1_loaded = history.load_run("WB", m1.run_id)
        assert m1_loaded.stages["semantic_model"].status == StageStatus.COMPLETED

        # ── Act: start a new run, mark semantic_model overwritten
        # in all OTHER runs (m1) but not m2 ──
        m2 = history.create_run("WB", "WB.twb")
        history.mark_overwritten("WB", {"semantic_model"}, exclude_run_id=m2.run_id)

        # ── Assert: m1's semantic_model is now OVERWRITTEN ──
        reloaded = history.load_run("WB", m1.run_id)
        assert reloaded.stages["semantic_model"].status == StageStatus.OVERWRITTEN


# ═══════════════════════════════════════════════════════════════════
# Artefact storage & restore — snapshot agent outputs into the run
# folder and later restore them back into the output tree
# ═══════════════════════════════════════════════════════════════════


class TestArtifactStorage:
    """Verify that store_artifacts copies agent outputs into the run folder
    and restore_run puts them back into the output tree.

    This is critical for resumability: if the pipeline is re-run, we can
    skip completed stages and restore their outputs from the archived
    run instead of regenerating them.
    """

    @pytest.fixture()
    def env(self, tmp_path: Path) -> tuple[RunHistory, Path, Path]:
        """Return (history, runs_root, output_root) in a clean temp dir."""
        runs_root = tmp_path / "runs"
        output_root = tmp_path / "output"
        history = RunHistory(runs_root, output_root, max_runs_per_workbook=5)
        return history, runs_root, output_root

    def test_store_and_restore(self, env: tuple[RunHistory, Path, Path]) -> None:
        history, _, output_root = env
        agent = "tableau_metadata_extractor_agent"
        wb = "TestWB"

        # ── 1. Populate the agent's output folder ──
        src = output_root / agent / wb
        src.mkdir(parents=True)
        (src / "semantic_model_input.json").write_text('{"tables": []}')
        (src / "report_input.json").write_text('{"pages": []}')
        # extracted_data/ is large & derived — should be excluded
        extracted = src / "extracted_data"
        extracted.mkdir()
        (extracted / "data.xlsx").write_bytes(b"fake")

        # ── 2. Archive the agent's output into the run folder ──
        m = history.create_run(wb, "TestWB.twbx")
        history.store_artifacts(m, agent)

        run_dir = history._run_dir(wb, m.run_id) / agent
        assert (run_dir / "semantic_model_input.json").exists()
        assert not (run_dir / "extracted_data").exists()  # excluded

        # ── 3. Wipe the live output, then restore from archive ──
        import shutil

        shutil.rmtree(output_root / agent / wb)
        assert not (output_root / agent / wb).exists()

        history.restore_run(m)
        assert (output_root / agent / wb / "semantic_model_input.json").exists()
        assert (output_root / agent / wb / "report_input.json").exists()

    def test_store_non_storable_agent_is_noop(self, env: tuple[RunHistory, Path, Path]) -> None:
        """Only agents in _STORABLE_AGENTS are archived — others are silently ignored."""
        history, _, _ = env
        m = history.create_run("WB", "WB.twb")
        history.store_artifacts(m, "warnings_reviewer_agent")
        assert "warnings_reviewer_agent" not in m.stored_artifacts

    def test_store_and_restore_preserves_sub_directories(self, env: tuple[RunHistory, Path, Path]) -> None:
        """The skeleton agent outputs a .Report/ folder — verify it survives archive + restore."""
        history, _, output_root = env
        wb = "ResumeWB"
        agent = "pbip_project_skeleton_agent"
        src = output_root / agent / wb
        src.mkdir(parents=True)
        (src / "ResumeWB.Report").mkdir()

        m = history.create_run(wb, "ResumeWB.twb")
        history.store_artifacts(m, agent)

        import shutil

        shutil.rmtree(src)
        history.restore_run(m)
        assert (output_root / agent / wb / "ResumeWB.Report").exists()


# ═══════════════════════════════════════════════════════════════════
# stage_cache — input hashing (SHA-256 of stage input files)
# ═══════════════════════════════════════════════════════════════════


class TestComputeInputHash:
    """Verify compute_input_hash produces a stable SHA-256 of file contents.

    The hash is the key to the skip decision: if inputs haven't changed
    since the last run, the stage can be skipped.
    """

    def test_same_content_produces_same_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "a.json"
        f.write_text('{"key": "value"}')
        h1 = compute_input_hash([f])
        h2 = compute_input_hash([f])
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex = 32 bytes = 64 hex chars

    def test_different_content_produces_different_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "a.json"
        f.write_text("v1")
        h1 = compute_input_hash([f])
        f.write_text("v2")
        h2 = compute_input_hash([f])
        assert h1 != h2

    def test_missing_files_return_empty_string(self) -> None:
        """Missing files yield empty-string hash (forces a re-run)."""
        assert compute_input_hash([Path("/nonexistent/file.json")]) == ""


# ═══════════════════════════════════════════════════════════════════
# stage_cache — per-stage skip decisions (cached / re-generable / run)
# ═══════════════════════════════════════════════════════════════════


class TestShouldSkipStage:
    """Verify the skip-decision logic that compares a stage's stored
    hash against the current input hash to decide run-vs-skip.

    Three possible outcomes:
    * skip=True  reason="cached"        — deterministic stage, hash match
    * skip=True  reason="re-generable"  — LLM stage, hash match
    * skip=False                        — status not COMPLETED or hash changed
    """

    def _manifest_with_stage(
        self,
        stage: str,
        status: StageStatus,
        input_hash: str | None = None,
    ) -> RunManifest:
        """Build a minimal manifest containing exactly one stage record."""
        return RunManifest(
            run_id="r1",
            workbook_name="WB",
            workbook_file="WB.twb",
            created_at="t0",
            updated_at="t0",
            stages={stage: StageRecord(status=status, input_hash=input_hash)},
        )

    def test_incomplete_stage_must_run(self) -> None:
        m = self._manifest_with_stage("metadata_extractor", StageStatus.NOT_STARTED)
        d = should_skip_stage(m, "metadata_extractor", "abc")
        assert d.skip is False

    def test_hash_mismatch_forces_rerun(self) -> None:
        """Inputs changed since last run → stage must re-execute."""
        m = self._manifest_with_stage("metadata_extractor", StageStatus.COMPLETED, "old")
        d = should_skip_stage(m, "metadata_extractor", "new")
        assert d.skip is False
        assert "changed" in d.reason

    def test_deterministic_stage_with_matching_hash_is_cached(self) -> None:
        """metadata_extractor is deterministic → skip reason is 'cached'."""
        m = self._manifest_with_stage("metadata_extractor", StageStatus.COMPLETED, "abc")
        d = should_skip_stage(m, "metadata_extractor", "abc")
        assert d.skip is True
        assert d.reason == "cached"

    def test_llm_stage_with_matching_hash_is_regenerable(self) -> None:
        """semantic_model is LLM-backed → skip reason is 're-generable'."""
        m = self._manifest_with_stage("semantic_model", StageStatus.COMPLETED, "abc")
        d = should_skip_stage(m, "semantic_model", "abc")
        assert d.skip is True
        assert d.reason == "re-generable"

    def test_null_stored_hash_forces_rerun(self) -> None:
        """Legacy manifests without input_hash must not be skipped."""
        m = self._manifest_with_stage("metadata_extractor", StageStatus.COMPLETED, None)
        d = should_skip_stage(m, "metadata_extractor", "")
        assert d.skip is False


# ═══════════════════════════════════════════════════════════════════
# stage_cache — STAGE_GRAPH structure and downstream propagation
#
# Pipeline flow:
#   metadata_extractor ──► functional_doc ──► target_technical_doc
# ═══════════════════════════════════════════════════════════════════


class TestStageGraph:
    """Verify the static STAGE_GRAPH declares correct upstream edges
    and deterministic flags.  These matter because:

    * *upstream* determines what must complete before a stage can start.
    * *deterministic* controls the skip-decision label (cached vs.
      re-generable) and whether outputs are byte-for-byte identical.
    """

    def test_metadata_extractor_has_no_upstream(self) -> None:
        assert STAGE_GRAPH["metadata_extractor"].upstream == ()

    def test_tdd_depends_on_extractor_and_fdd(self) -> None:
        deps = set(STAGE_GRAPH["target_technical_doc"].upstream)
        assert deps == {"metadata_extractor", "functional_doc"}

    def test_deterministic_flags(self) -> None:
        assert STAGE_GRAPH["metadata_extractor"].deterministic is True
        assert STAGE_GRAPH["functional_doc"].deterministic is False
        assert STAGE_GRAPH["target_technical_doc"].deterministic is False


class TestGetStaleDownstream:
    """Verify get_stale_downstream returns every stage reachable
    *downstream* of a given stage (transitive closure, excluding itself).

    Used to decide which stages must be invalidated when an upstream
    stage is re-run or its output changes.
    """

    def test_metadata_extractor_invalidates_chain(self) -> None:
        ds = get_stale_downstream("metadata_extractor")
        assert "functional_doc" in ds
        assert "target_technical_doc" in ds
        assert "metadata_extractor" not in ds

    def test_functional_doc_only_invalidates_tdd(self) -> None:
        ds = get_stale_downstream("functional_doc")
        assert ds == {"target_technical_doc"}

    def test_tdd_has_no_downstream(self) -> None:
        ds = get_stale_downstream("target_technical_doc")
        assert ds == set()


# ═══════════════════════════════════════════════════════════════════
# stage_cache — resolve_stages_to_run (the "what do I need to execute?" API)
# ═══════════════════════════════════════════════════════════════════


class TestResolveStages:
    """Verify resolve_stages_to_run returns the minimal set of stages
    that must execute, taking into account:

    * which stages are already completed (status + hash match),
    * which stages are force-requested by the caller,
    * downstream propagation (force one → its dependents must re-run), and
    * pipeline_stages constraint (webapp flow omits some stages).
    """

    def _empty_manifest(self) -> RunManifest:
        """Manifest with no stage records — simulates a fresh run."""
        return RunManifest(
            run_id="r1",
            workbook_name="WB",
            workbook_file="WB.twb",
            created_at="t0",
            updated_at="t0",
        )

    def _completed_manifest(self) -> RunManifest:
        """Manifest where every stage is COMPLETED with hash 'h' — fully cached."""
        stages = {name: StageRecord(status=StageStatus.COMPLETED, input_hash="h") for name in STAGE_GRAPH}
        return RunManifest(
            run_id="r1",
            workbook_name="WB",
            workbook_file="WB.twb",
            created_at="t0",
            updated_at="t0",
            stages=stages,
        )

    def test_empty_manifest_runs_all(self) -> None:
        m = self._empty_manifest()
        result = resolve_stages_to_run(m)
        assert result == set(STAGE_GRAPH.keys())

    def test_completed_manifest_runs_nothing(self) -> None:
        m = self._completed_manifest()
        result = resolve_stages_to_run(m)
        assert result == set()

    def test_force_one_stage_also_reruns_its_downstream(self) -> None:
        """Forcing functional_doc re-runs it + target_technical_doc (its only downstream)."""
        m = self._completed_manifest()
        result = resolve_stages_to_run(m, force_stages={"functional_doc"})
        assert "functional_doc" in result
        assert "target_technical_doc" in result
        assert "metadata_extractor" not in result

    def test_force_terminal_stage_runs_only_itself(self) -> None:
        """Forcing target_technical_doc (last stage) re-runs only itself — no downstream."""
        m = self._completed_manifest()
        result = resolve_stages_to_run(m, force_stages={"target_technical_doc"})
        assert result == {"target_technical_doc"}

    def test_pipeline_stages_constraint_limits_scope(self) -> None:
        """A pipeline_stages constraint limits which stages can be returned.

        When only the first two stages are allowed, target_technical_doc
        must never appear in the result."""
        m = self._empty_manifest()
        constrained_stages = {"metadata_extractor", "functional_doc"}
        result = resolve_stages_to_run(m, pipeline_stages=constrained_stages)
        assert "target_technical_doc" not in result
        assert result == constrained_stages

    def test_failed_stage_is_retried(self) -> None:
        """A FAILED stage from a previous run must be re-executed."""
        m = self._completed_manifest()
        m.stages["functional_doc"].status = StageStatus.FAILED
        result = resolve_stages_to_run(m)
        assert "functional_doc" in result

    def test_changed_hash_invalidates_stage_and_all_downstream(self) -> None:
        """If functional_doc's input hash changed, it and target_technical_doc re-run."""
        m = self._completed_manifest()
        current_hashes = dict.fromkeys(STAGE_GRAPH, "h")  # all match…
        current_hashes["functional_doc"] = "changed"  # …except functional_doc
        result = resolve_stages_to_run(m, current_hashes=current_hashes)
        assert result == {
            "functional_doc",
            "target_technical_doc",
        }

    def test_force_on_partial_manifest_only_runs_forced(self) -> None:
        """Force TDD on a manifest with only metadata_extractor completed.

        Should run ONLY target_technical_doc — not all incomplete stages.
        """
        m = self._empty_manifest()
        m.stages["metadata_extractor"] = StageRecord(status=StageStatus.COMPLETED, input_hash="h")
        result = resolve_stages_to_run(m, force_stages={"target_technical_doc"})
        assert result == {"target_technical_doc"}

    def test_force_upstream_triggers_qualifying_downstream(self) -> None:
        """Forcing functional_doc with metadata completed also triggers target_technical_doc.

        All of TDD's upstreams (metadata ✓, functional_doc forced) are satisfied,
        so TDD is automatically added to the run set.
        """
        m = self._empty_manifest()
        m.stages["metadata_extractor"] = StageRecord(status=StageStatus.COMPLETED, input_hash="h")
        result = resolve_stages_to_run(m, force_stages={"functional_doc"})
        assert result == {
            "functional_doc",
            "target_technical_doc",
        }


# ═══════════════════════════════════════════════════════════════════
# Atomic save — manifest.json must never be left half-written
# ═══════════════════════════════════════════════════════════════════


class TestAtomicSave:
    """Verify that repeated save_run calls produce a valid manifest.

    RunHistory.save_run writes to a temp file then does an atomic
    os.replace, so a crash mid-write cannot corrupt the manifest.
    """

    def test_manifest_not_corrupt_after_save(self, tmp_path: Path) -> None:
        history = RunHistory(
            tmp_path / "runs",
            tmp_path / "output",
        )
        m = history.create_run("WB", "WB.twb")
        # Update and save multiple times
        for i in range(5):
            history.update_stage(
                m,
                "metadata_extractor",
                status=StageStatus.COMPLETED,
                input_hash=f"hash_{i}",
            )
        # Reload and verify
        loaded = history.load_run("WB", m.run_id)
        assert loaded.stages["metadata_extractor"].input_hash == "hash_4"


# ═══════════════════════════════════════════════════════════════════
# Additional RunHistory edge case tests for uncovered lines
# ═══════════════════════════════════════════════════════════════════


class TestRunHistoryEdgeCases:
    """Cover error paths and edge cases in RunHistory."""

    @pytest.fixture()
    def history(self, tmp_path: Path) -> RunHistory:
        return RunHistory(
            runs_root=tmp_path / "runs",
            output_root=tmp_path / "output",
            max_runs_per_workbook=3,
        )

    def test_list_runs_skips_corrupt_manifest(self, history: RunHistory, tmp_path: Path) -> None:
        """Corrupt manifest.json files are skipped with a warning."""
        m = history.create_run("WB", "WB.twb")
        # Corrupt the manifest
        run_dir = history._run_dir("WB", m.run_id)
        (run_dir / "manifest.json").write_text("not valid json", encoding="utf-8")
        runs = history.list_runs("WB")
        assert len(runs) == 0

    def test_update_stage_failed_status(self, history: RunHistory) -> None:
        """Updating a stage to FAILED sets completed_at and duration."""
        m = history.create_run("WB", "WB.twb")
        history.update_stage(
            m,
            "semantic_model",
            status=StageStatus.FAILED,
            duration_seconds=10.0,
            deterministic=False,
        )
        loaded = history.load_run("WB", m.run_id)
        rec = loaded.stages["semantic_model"]
        assert rec.status == StageStatus.FAILED
        assert rec.completed_at is not None
        assert rec.duration_seconds == 10.0

    def test_update_stage_not_started_status(self, history: RunHistory) -> None:
        """Updating a stage to NOT_STARTED sets started_at."""
        m = history.create_run("WB", "WB.twb")
        history.update_stage(
            m,
            "metadata_extractor",
            status=StageStatus.NOT_STARTED,
            deterministic=True,
        )
        loaded = history.load_run("WB", m.run_id)
        rec = loaded.stages["metadata_extractor"]
        assert rec.status == StageStatus.NOT_STARTED
        assert rec.started_at is not None

    def test_store_artifacts_missing_source_dir(self, history: RunHistory) -> None:
        """store_artifacts with non-existent source directory is handled gracefully."""
        m = history.create_run("WB", "WB.twb")
        # Don't create the source dir — store_artifacts should handle it
        history.store_artifacts(m, "tableau_metadata_extractor_agent")
        assert "tableau_metadata_extractor_agent" not in m.stored_artifacts

    def test_restore_run_missing_artefact_dir(self, history: RunHistory, tmp_path: Path) -> None:
        """restore_run with a missing stored artefact directory logs warning."""
        m = history.create_run("WB", "WB.twb")
        m.stored_artifacts.append("fake_agent")
        history.save_run(m)
        # restore_run should not crash when the stored dir doesn't exist
        history.restore_run(m)

    def test_list_workbooks_on_empty_dir(self, history: RunHistory) -> None:
        """list_workbooks returns empty list when runs_root doesn't exist."""
        result = history.list_workbooks()
        assert result == []
