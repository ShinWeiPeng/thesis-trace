"""Host-only safety contracts; these tests never invoke sudo, perf or Docker."""

import hashlib
from pathlib import Path

import pytest

from container_native_capture import capture_argv, valid_enable_ack
from container_native_smoke import matches_response


def test_capture_command_is_pid_scoped_and_bounded():
    argv = capture_argv([220, 210], Path("/tmp/scoped-capture"))
    assert argv[:6] == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/timeout",
        "--signal=INT",
        "--kill-after=1s",
        "14s",
    ]
    assert "--fsize=4194304:4194304" in argv
    assert argv[argv.index("-p") + 1] == "210,220"
    assert argv[argv.index("-e") + 1] == "task-clock:u"
    assert argv[argv.index("-D") + 1] == "-1"
    assert "--control=fifo:/tmp/scoped-capture/ctl,/tmp/scoped-capture/ack" in argv
    assert argv[-2:] == ["-o", "-"]
    assert not {"-a", "--all-cpus", "--all-user", "--no-inherit"} & set(argv)
    assert "python" not in " ".join(argv)


@pytest.mark.parametrize("value", [b"ack\n", b"ack\n\x00"])
def test_documented_and_observed_native_enable_ack(value):
    # Actual perf 7.0.14 capture returned ack newline followed by one C NUL.
    assert valid_enable_ack(value)


@pytest.mark.parametrize(
    "value", [b"", b"ack", b"ack\x00", b"ack\nerror", b"ack\n\x00\x00"]
)
def test_incomplete_or_unexpected_ack_is_rejected(value):
    assert not valid_enable_ack(value)


@pytest.mark.parametrize(
    "pids", [[], [0], [1], [-1], [True], ["200"], list(range(2, 19))]
)
def test_reject_invalid_scope(pids):
    with pytest.raises(ValueError):
        capture_argv(pids, Path("/tmp/unused"))


def readable():
    return {
        "status": "readable",
        "client_isolation": {
            "status": "isolated",
            "uid": 65532,
            "docker_socket_absent": True,
            "secrets_absent": True,
            "interfaces": ["lo"],
        },
        "sha256": hashlib.sha256(b"input").hexdigest(),
        "result": {
            "document_verified": False,
            "fragments": [{"text": "Visible evidence"}],
        },
    }


def test_readable_requires_hash_text_and_unverified_state():
    value = readable()
    assert matches_response(value, "html", "readable", b"input")
    assert not matches_response(value, "html", "readable", b"other")
    value["result"]["document_verified"] = True
    assert not matches_response(value, "html", "readable", b"input")


def test_missing_or_wrong_response_is_not_coverage():
    assert not matches_response({}, "html", "readable", b"")
    value = readable()
    value["status"] = "unavailable"
    assert not matches_response(value, "html", "readable", b"input")


def test_pdf_requires_missing_page_warning():
    value = readable()
    value["result"]["fragments"][0]["text"] = "SYNTHETIC text page"
    assert not matches_response(value, "pdf-plain", "readable", b"input")
    value["result"].update(pages_without_text=[2], selection_incomplete=True)
    assert matches_response(value, "pdf-plain", "readable", b"input")
