"""Quota log reader tests use only temporary simulated files, never the real watcher/ledger."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
read_fresh = runpy.run_path(str(ROOT / "scripts/prepublication_quota_watch.py"))["fresh_log_text"]


def test_separate_logs_ignore_old_content_and_detect_new_secondary_log(tmp_path):
    native, live = tmp_path / "native.log", tmp_path / "live.log"
    native.write_bytes(b"Historical simulated HTTP/1.1 429\n")
    positions = {native: native.stat().st_size, live: 0}
    assert not read_fresh(positions).strip()
    live.write_bytes(b"New simulated HTTP/1.1 429 RESOURCE_EXHAUSTED\n")
    assert "429 RESOURCE_EXHAUSTED" in read_fresh(positions)
    assert not read_fresh(positions).strip()


def test_native_log_restart_resets_offset_without_losing_live_log(tmp_path):
    native, live = tmp_path / "native.log", tmp_path / "live.log"
    native.write_bytes(b"old" * 100)
    live.write_bytes(b"previous live\n")
    positions = {native: native.stat().st_size, live: live.stat().st_size}
    native.write_bytes(b"new native\n")
    with live.open("ab") as stream:
        stream.write(b"new live\n")
    fresh = read_fresh(positions)
    assert "new native" in fresh and "new live" in fresh
    assert "previous live" not in fresh
