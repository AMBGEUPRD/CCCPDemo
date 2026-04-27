"""Tests for the repository's GitHub hook helper scripts."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_module(module_name: str, relative_path: str) -> ModuleType:
    """Load a hook script module from its filesystem path."""
    file_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BlockDangerousHookTests(unittest.TestCase):
    """Verify dangerous terminal commands are blocked with context."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module(
            "block_dangerous_hook",
            ".github/hooks/scripts/block-dangerous.py",
        )

    def test_blocks_git_clean_with_feedback(self) -> None:
        payload = {
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "git clean -fdx"},
        }

        with (
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            with self.assertRaises(SystemExit) as exc:
                self.module.main()

        self.assertEqual(exc.exception.code, 2)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("Blocked dangerous terminal command", output["hookSpecificOutput"]["additionalContext"])


class CheckFileLengthHookTests(unittest.TestCase):
    """Verify edited Python files are discovered and reported correctly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module(
            "check_file_length_hook",
            ".github/hooks/scripts/check-file-length.py",
        )

    def test_iter_python_paths_supports_apply_patch(self) -> None:
        payload = {
            "tool_name": "apply_patch",
            "tool_input": {
                "input": (
                    "*** Begin Patch\n"
                    "*** Update File: C:\\temp\\alpha.py\n"
                    "*** Add File: C:\\temp\\beta.txt\n"
                    "*** End Patch"
                )
            },
        }

        paths = self.module._iter_python_paths(payload)

        self.assertEqual(paths, [Path("C:/temp/alpha.py")])

    def test_main_reports_soft_limit_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "large_module.py"
            file_path.write_text("\n".join(f"line_{index}" for index in range(501)), encoding="utf-8")

            payload = {
                "tool_name": "edit_file",
                "tool_input": {"filePath": str(file_path)},
            }

            with (
                patch("sys.stdin", io.StringIO(json.dumps(payload))),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                with self.assertRaises(SystemExit) as exc:
                    self.module.main()

        self.assertEqual(exc.exception.code, 0)
        output = json.loads(stdout.getvalue())
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("soft limit", context)
        self.assertIn("large_module.py", context)


class InjectContextHookTests(unittest.TestCase):
    """Verify session context uses explicit unknown values when git metadata fails."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module(
            "inject_context_hook",
            ".github/hooks/scripts/inject-context.py",
        )

    def test_main_keeps_unknown_dirty_count(self) -> None:
        with (
            patch.object(self.module, "_run", side_effect=["main", "Python 3.14.3", "unknown"]),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            with self.assertRaises(SystemExit) as exc:
                self.module.main()

        self.assertEqual(exc.exception.code, 0)
        output = json.loads(stdout.getvalue())
        self.assertIn("Uncommitted files: unknown", output["hookSpecificOutput"]["additionalContext"])


class RunChecksHookTests(unittest.TestCase):
    """Verify stop-hook commands are read-only and run from the repo root."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module(
            "run_checks_hook",
            ".github/hooks/scripts/run-checks.py",
        )

    def test_commands_use_current_interpreter_and_read_only_flags(self) -> None:
        self.assertEqual(
            self.module.COMMANDS[0][:4],
            [self.module.sys.executable, "-m", "isort", "--check-only"],
        )
        self.assertEqual(self.module.COMMANDS[1][:4], [self.module.sys.executable, "-m", "black", "--check"])
        self.assertEqual(
            self.module.COMMANDS[-1],
            [self.module.sys.executable, "-m", "pytest", "tests/unit/", "-v", "--tb=short"],
        )

    def test_main_runs_checks_from_repo_root(self) -> None:
        completed = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(self.module.subprocess, "run", return_value=completed) as run_mock:
            with self.assertRaises(SystemExit) as exc:
                self.module.main()

        self.assertEqual(exc.exception.code, 0)
        first_call = run_mock.call_args_list[0]
        self.assertEqual(first_call.kwargs["cwd"], self.module.REPO_ROOT)
        self.assertEqual(first_call.kwargs["timeout"], 300)


if __name__ == "__main__":
    unittest.main()
