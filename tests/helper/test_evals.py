import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_repeated_fixture_queries_have_one_combined_total():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "evals/run.py"),
         "--queries", str(root / "evals/fixture.json"),
         "--queries", str(root / "evals/fixture.json")],
        capture_output=True, text=True, timeout=10, cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("first-hit total") == 1
    assert "first-hit total 14/14 (100.0%)" in result.stdout
    assert "first-hit md 2/2 (100.0%)" in result.stdout


@pytest.mark.parametrize("gate,status", [(0.9, 0), (0.91, 1)])
def test_combined_gate_preserves_each_query_files_base(tmp_path, monkeypatch, capsys,
                                                     gate, status):
    import asyncio

    from fakes.embedder import FakeEmbedder
    from omafindd.code import index_code

    root = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "retry.py").write_text("def retry_with_backoff(): pass")
    subprocess.run(["git", "-C", str(repo), "add", "retry.py"], check=True)
    asyncio.run(index_code([repo], tmp_path / "index", FakeEmbedder()))
    first, second = tmp_path / "personal.json", tmp_path / "media-code.json"
    first.write_text(json.dumps({"base": str(tmp_path), "queries": [
        {"q": "code: retry_with_backoff", "expect": ["repo/retry.py"], "tag": "lookup"}
    ] * 8}))
    second.write_text(json.dumps({"base": str(repo), "queries": [
        {"q": "code: retry_with_backoff", "expect": ["retry.py"], "tag": "lookup"},
        {"q": "code: missing_identifier", "expect": ["missing.py"], "tag": "meaning"},
    ]}))
    spec = importlib.util.spec_from_file_location("eval_run", root / "evals/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "Adapter", lambda runtime: FakeEmbedder())
    monkeypatch.setattr(sys, "argv", ["evals/run.py", "--index", str(tmp_path / "index"),
                                    "--queries", str(first), "--queries", str(second),
                                    "--gate", str(gate)])
    assert module.main() == status
    output = capsys.readouterr().out
    assert output.count("first-hit total") == 1
    assert "first-hit lookup 9/9 (100.0%)" in output
    assert "first-hit meaning 0/1 (0.0%)" in output
    assert "first-hit total 9/10 (90.0%)" in output
