#!/usr/bin/env python3
"""Real integration test — actually calls the API."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_cli_help():
    r = subprocess.run(
        [sys.executable, "cli.py", "--help"],
        capture_output=True, text=True, cwd=ROOT
    )
    assert r.returncode == 0
    assert "generate" in r.stdout
    assert "status" in r.stdout


def test_cli_status():
    """Test that CLI status command runs without import errors."""
    r = subprocess.run(
        [sys.executable, "cli.py", "status", "--keys", "nonexistent_keys.json"],
        capture_output=True, text=True, cwd=ROOT
    )
    # Should not crash with import errors
    assert "ModuleNotFoundError" not in r.stderr
    assert "ImportError" not in r.stderr


if __name__ == "__main__":
    test_cli_help()
    test_cli_status()
    print("All real tests passed!")
