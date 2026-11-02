"""Guard behavior in temporary ledgers only; never launch a command or touch the real halt flag."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepublication_run.py"


class ResourceGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("isolated_guard", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module.ROOT = Path(self.directory.name)
        self.module.LEDGER = self.module.ROOT / "artifacts/prepublication/results.json"
        self.module.LEDGER.parent.mkdir(parents=True)
        self.module.LEDGER.write_text(json.dumps({"cases": {}}))

    def args(self, profile):
        return [
            "guard",
            "--resource-profile",
            profile,
            "--log",
            "artifacts/prepublication/test.log",
            "--",
            "never-execute-this",
        ]

    def test_existing_external_or_quota_stop_never_launches(self):
        for flag in ["halt", "external_blocker"]:
            self.module.LEDGER.write_text(json.dumps({flag: "Synthetic stop"}))
            with (
                patch.object(sys, "argv", self.args("bounded")),
                patch.object(self.module.subprocess, "Popen") as launch,
            ):
                self.assertEqual(self.module.main(), 75)
                launch.assert_not_called()

    def test_profile_preflight_preserves_reserve_without_launching(self):
        for profile, free, reserve in [("bounded", 5.5, 6), ("heavy", 9, 10)]:
            with (
                patch.object(sys, "argv", self.args(profile)),
                patch.object(
                    self.module.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=int(free * self.module.GIB)),
                ),
                patch.object(self.module, "block_storage") as block,
                patch.object(self.module.subprocess, "Popen") as launch,
            ):
                self.assertEqual(self.module.main(), 78)
                block.assert_called_once_with(
                    int(free * self.module.GIB), reserve * self.module.GIB
                )
                launch.assert_not_called()

    def test_bounded_profile_can_run_with_seven_gib(self):
        child = SimpleNamespace(poll=lambda: 0, returncode=0)
        with (
            patch.object(sys, "argv", self.args("bounded")),
            patch.object(
                self.module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=7 * self.module.GIB),
            ),
            patch.object(self.module.subprocess, "Popen", return_value=child) as launch,
        ):
            self.assertEqual(self.module.main(), 0)
            launch.assert_called_once()

    def test_runtime_low_space_records_stop_and_kills_only_owned_child(self):
        child = SimpleNamespace(
            poll=lambda: None, pid=123456789, wait=MagicMock(), terminate=MagicMock()
        )

        def record(*args):
            self.module.LEDGER.write_text(
                json.dumps({"external_blocker": "Synthetic low-space stop"})
            )

        with (
            patch.object(sys, "argv", self.args("bounded")),
            patch.object(
                self.module.shutil,
                "disk_usage",
                side_effect=[
                    SimpleNamespace(free=7 * self.module.GIB),
                    SimpleNamespace(free=4 * self.module.GIB),
                ],
            ),
            patch.object(self.module, "block_storage", side_effect=record),
            patch.object(self.module.subprocess, "Popen", return_value=child),
            patch.object(self.module.subprocess, "run") as terminate,
        ):
            self.assertEqual(self.module.main(), 75)
            if self.module.os.name == "nt":
                self.assertEqual(
                    terminate.call_args.args[0], ["taskkill", "/PID", "123456789", "/T", "/F"]
                )
            else:
                child.terminate.assert_called_once()
            child.wait.assert_called_once_with(timeout=20)


if __name__ == "__main__":
    unittest.main()
