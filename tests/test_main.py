import json
import os
import subprocess
from pathlib import Path

import pytest

import main


class DummyConsole:
    """Console stub used to suppress Rich output during tests."""

    def print(self, *args, **kwargs):  # noqa: D401 - simple stub
        pass


@pytest.fixture(autouse=True)
def suppress_console(monkeypatch):
    """Replace the Rich console with a quiet stub for deterministic tests."""
    monkeypatch.setattr(main, "console", DummyConsole())
    yield


def test_resolve_project_path_valid(tmp_path):
    result = main.resolve_project_path(str(tmp_path))
    assert result == tmp_path.resolve()


def test_resolve_project_path_missing(monkeypatch, tmp_path):
    missing_path = tmp_path / "nonexistent"
    with pytest.raises(SystemExit) as exc:
        main.resolve_project_path(str(missing_path))
    assert exc.value.code == 2


def test_parse_deptry_report_handles_missing_and_unused():
    report = {
        "missing": [{"module": "requests"}],
        "unused": [{"module": "boto3"}],
    }
    missing, unused = main.parse_deptry_report(json.dumps(report))
    assert missing == ["requests"]
    assert unused == ["boto3"]


def test_run_deptry_collects_findings(monkeypatch, tmp_path):
    payload = {
        "missing": [{"module": "requests"}],
        "unused": [{"module": "boto3"}],
    }

    def fake_run_command(command, cwd=None):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(main, "run_command", fake_run_command)
    missing, unused = main.run_deptry(tmp_path)
    assert missing == ["requests"]
    assert unused == ["boto3"]


def test_run_pip_check_reqs_collects_missing_and_unused(monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n", encoding="utf-8")

    outputs = {
        "pip-missing-reqs": "Missing requirements:\n- requests",
        "pip-extra-reqs": "Unused requirements:\n- boto3",
    }

    def fake_run_command(command, cwd=None):
        tool = Path(command[0]).name
        stdout = outputs[tool]
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(main, "run_command", fake_run_command)
    missing, unused, diagnostics = main.run_pip_check_reqs(tmp_path)
    assert missing == ["requests"]
    assert unused == ["boto3"]
    assert diagnostics == {}


def test_main_successful_run(monkeypatch, tmp_path, tmp_path_factory):
    monkeypatch.setenv("INPUT_PATH", str(tmp_path))
    monkeypatch.setenv("INPUT_MODE", "deptry")
    monkeypatch.delenv("INPUT_FAIL_ON_WARN", raising=False)
    monkeypatch.setenv("INPUT_FAIL-ON-WARN", "false")

    def fake_run_deptry(path):
        return [], []

    summary_file = tmp_path_factory.mktemp("summary") / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    monkeypatch.setattr(main, "run_deptry", fake_run_deptry)
    main.main()

    assert summary_file.read_text(encoding="utf-8").strip().endswith("All dependencies look good!")


def test_main_fails_on_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_PATH", str(tmp_path))
    monkeypatch.setenv("INPUT_MODE", "deptry")
    monkeypatch.setenv("INPUT_FAIL_ON_WARN", "false")

    def fake_run_deptry(path):
        return ["requests"], []

    monkeypatch.setattr(main, "run_deptry", fake_run_deptry)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1


def test_main_warns_on_unused_when_fail_on_warn_false(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_PATH", str(tmp_path))
    monkeypatch.setenv("INPUT_MODE", "deptry")
    monkeypatch.setenv("INPUT_FAIL_ON_WARN", "false")

    def fake_run_deptry(path):
        return [], ["requests"]

    monkeypatch.setattr(main, "run_deptry", fake_run_deptry)
    main.main()  # Should not raise


def test_main_fails_when_fail_on_warn_true(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_PATH", str(tmp_path))
    monkeypatch.setenv("INPUT_MODE", "deptry")
    monkeypatch.setenv("INPUT_FAIL_ON_WARN", "true")

    def fake_run_deptry(path):
        return [], ["requests"]

    monkeypatch.setattr(main, "run_deptry", fake_run_deptry)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1


def test_write_summary_handles_missing_file(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    main.write_summary(["requests"], ["boto3"], "deptry")
    contents = summary_path.read_text(encoding="utf-8")
    assert "Missing dependencies" in contents
    assert "Unused dependencies" in contents
