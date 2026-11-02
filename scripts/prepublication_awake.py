"""Run one guarded test command with a temporary Windows idle-sleep request."""

import ctypes
import subprocess
import sys


def main():
    assert sys.platform == "win32" and len(sys.argv) > 1
    state = ctypes.windll.kernel32.SetThreadExecutionState
    state.argtypes = [ctypes.c_uint]
    state.restype = ctypes.c_uint
    assert state(0x80000001), "Windows rejected the temporary idle-sleep request"
    print("Temporary idle-sleep request active for this test; lid close/shutdown remain effective.", flush=True)
    try:
        return subprocess.call(sys.argv[1:])
    finally:
        state(0x80000000)


if __name__ == "__main__":
    raise SystemExit(main())
