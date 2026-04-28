"""Tests for Tableau2PowerBI.core.run_history.stage_cache."""

from __future__ import annotations

import unittest

from Tableau2PowerBI.core.run_history import (
    RunManifest,
    StageRecord,
    StageStatus,
    compute_input_hash,
    get_stale_downstream,
    resolve_stages_to_run,
    should_skip_stage,
)
from tests.support import managed_tempdir


def _completed_record(*, input_hash: str = "hash") -> StageRecord:
    return StageRecord(
        status=StageStatus.COMPLETED,
        deterministic=True,
        input_hash=input_hash,
    )


class ComputeInputHashTests(unittest.TestCase):
    """Verify file and directory hashing behavior."""

    def test_hash_is_stable_for_same_inputs(self) -> None:
        with managed_tempdir() as tmpdir:
            first = tmpdir / "a.txt"
            second = tmpdir / "nested" / "b.txt"
            second.parent.mkdir()
            first.write_text("alpha", encoding="utf-8")
            second.write_text("beta", encoding="utf-8")

            digest_one = compute_input_hash([second.parent, first])
            digest_two = compute_input_hash([first, second.parent])

            self.assertEqual(digest_one, digest_two)

    def test_hash_changes_when_file_contents_change(self) -> None:
        with managed_tempdir() as tmpdir:
            target = tmpdir / "input.txt"
            target.write_text("before", encoding="utf-8")
            before = compute_input_hash([target])

            target.write_text("after", encoding="utf-8")
            after = compute_input_hash([target])

            self.assertNotEqual(before, after)


class StageDecisionTests(unittest.TestCase):
    """Verify cache skip decisions for deterministic and LLM stages."""

    def test_deterministic_stage_skips_as_cached(self) -> None:
        manifest = RunManifest(
            run_id="r1",
            workbook_name="Workbook",
            workbook_file="Workbook.twb",
            created_at="t0",
            updated_at="t0",
            stages={"metadata_extractor": _completed_record(input_hash="abc")},
        )

        decision = should_skip_stage(manifest, "metadata_extractor", "abc")

        self.assertTrue(decision.skip)
        self.assertEqual(decision.reason, "cached")

    def test_llm_stage_skips_as_regenerable(self) -> None:
        manifest = RunManifest(
            run_id="r1",
            workbook_name="Workbook",
            workbook_file="Workbook.twb",
            created_at="t0",
            updated_at="t0",
            stages={"functional_doc": _completed_record(input_hash="abc")},
        )

        decision = should_skip_stage(manifest, "functional_doc", "abc")

        self.assertTrue(decision.skip)
        self.assertEqual(decision.reason, "re-generable")


class DownstreamResolutionTests(unittest.TestCase):
    """Verify stale-stage propagation and execution-set resolution."""

    def _completed_manifest(self) -> RunManifest:
        return RunManifest(
            run_id="r1",
            workbook_name="Workbook",
            workbook_file="Workbook.twb",
            created_at="t0",
            updated_at="t0",
            stages={
                "metadata_extractor": _completed_record(input_hash="extract-hash"),
                "functional_doc": _completed_record(input_hash="func-hash"),
                "target_technical_doc": _completed_record(input_hash="tdd-hash"),
            },
        )

    def test_get_stale_downstream_returns_transitive_dependents(self) -> None:
        stale = get_stale_downstream("metadata_extractor")

        self.assertEqual(stale, {"functional_doc", "target_technical_doc"})

    def test_resolve_stages_to_run_is_empty_when_everything_is_cached(self) -> None:
        manifest = self._completed_manifest()
        current_hashes = {
            "metadata_extractor": "extract-hash",
            "functional_doc": "func-hash",
            "target_technical_doc": "tdd-hash",
        }

        stages = resolve_stages_to_run(manifest, current_hashes=current_hashes)

        self.assertEqual(stages, set())

    def test_resolve_stages_to_run_propagates_changed_inputs(self) -> None:
        manifest = self._completed_manifest()
        current_hashes = {
            "metadata_extractor": "changed",
            "functional_doc": "func-hash",
            "target_technical_doc": "tdd-hash",
        }

        stages = resolve_stages_to_run(manifest, current_hashes=current_hashes)

        self.assertEqual(
            stages,
            {"metadata_extractor", "functional_doc", "target_technical_doc"},
        )

    def test_force_stages_runs_only_needed_downstream(self) -> None:
        manifest = self._completed_manifest()

        stages = resolve_stages_to_run(
            manifest,
            force_stages={"functional_doc"},
        )

        self.assertEqual(stages, {"functional_doc", "target_technical_doc"})
