"""Host-only tests of the bounded native-command seam; never launch perf."""

import sys

from native_extraction_probe import run_bounded


def test_command_output_and_cleanup_are_observable(tmp_path):
    result = run_bounded(
        [sys.executable, "-I", "-c", "print('fixture')"], tmp_path / "out", 1
    )
    assert result["exit_code"] == 0
    assert result["output"] == "fixture\n"
    assert result["cleanup_confirmed"] is True


def test_timeout_is_not_reported_as_a_success(tmp_path):
    result = run_bounded(
        [sys.executable, "-I", "-c", "import time; time.sleep(10)"],
        tmp_path / "out",
        0.1,
    )
    assert result["timed_out"] is True
    assert result["cleanup_confirmed"] is True
    assert result["exit_code"] != 0


def test_output_limit_and_create_only_evidence(tmp_path):
    import pytest

    command = [sys.executable, "-I", "-c", "print('x' * 70000)"]
    result = run_bounded(command, tmp_path / "out", 1)
    assert result["output_exceeded"] is True
    assert len(result["output"]) == 65536
    with pytest.raises(FileExistsError):
        run_bounded(command, tmp_path / "out", 1)
