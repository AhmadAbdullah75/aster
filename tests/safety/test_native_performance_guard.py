"""Disposable performance target checks; never create databases or processes."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepublication_native_load.py"


class NativePerformanceGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("isolated_performance_guard", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.dotenv = SimpleNamespace(
            dotenv_values=lambda _: {
                "DATABASE_URL": "postgresql+psycopg://synthetic:unused@127.0.0.1:5434/nexus",
                "GEMINI_API_KEY": "synthetic-private-value",
            }
        )

    def test_path_like_or_invalid_identifiers_never_reach_database_setup(self):
        with patch.dict(sys.modules, {"dotenv": self.dotenv}):
            for identity in ["", "../nexus", "a/b", "UPPER", "a" * 36, "nexus;DROP"]:
                with self.subTest(identity=identity), self.assertRaises(AssertionError):
                    self.module.configure(identity, 8012)

    def test_normal_service_ports_cannot_be_used(self):
        with patch.dict(sys.modules, {"dotenv": self.dotenv}):
            for port in [3000, 8000, 8001, 8100]:
                with self.subTest(port=port), self.assertRaises(AssertionError):
                    self.module.configure("safe_run", port)

    def test_valid_target_is_separate_and_all_provider_keys_are_blank(self):
        original_path = sys.path[:]
        try:
            with (
                patch.dict(sys.modules, {"dotenv": self.dotenv}),
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_API_KEY": "prior-synthetic-value",
                        "OPENAI_API_KEY": "prior-synthetic-value",
                    },
                ),
            ):
                admin, database = self.module.configure("safe_run", 8012)
                self.assertTrue(admin.endswith("/nexus"))
                self.assertEqual(database, "nexus_perf_safe_run")
                self.assertTrue(os.environ["DATABASE_URL"].endswith("/nexus_perf_safe_run"))
                self.assertEqual(os.environ["GEMINI_API_KEY"], "")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "")
                self.assertEqual(os.environ["FREE_ONLY"], "true")
        finally:
            sys.path[:] = original_path

    def test_quota_and_external_stops_are_respected(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.module.LEDGER = Path(temporary) / "ledger.json"
            for state in [{}, {"halt": "synthetic stop"}, {"external_blocker": "synthetic stop"}]:
                self.module.LEDGER.write_text(json.dumps(state))
                self.assertEqual(self.module.stopped(), bool(state))

    def test_suspended_or_missing_load_measurements_cannot_pass(self):
        for times, duration in [([], 3600), ([0, 60, 3540], 3600), ([0, 60], 3600)]:
            with self.subTest(times=times), self.assertRaises(AssertionError):
                self.module.validate_sample_coverage(
                    [{"elapsed_seconds": value} for value in times], duration
                )
        self.module.validate_sample_coverage(
            [{"elapsed_seconds": value} for value in range(0, 3600, 60)], 3601
        )


if __name__ == "__main__":
    unittest.main()
