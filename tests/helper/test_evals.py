import subprocess
import sys
from pathlib import Path


def test_fixture_evals_rank_every_expected_file_first():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "evals/run.py"), "--queries", str(root / "evals/fixture.json")],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "first-hit total 7/7 (100.0%)" in result.stdout
