from types import SimpleNamespace

import pytest

from thesis_trace.bootstrap.application import AiWorkerRuntime


@pytest.mark.parametrize("work", [False, True])
def test_each_iteration_offers_all_classes_without_short_circuit(work):
    calls = []

    def run(name):
        calls.append(name)
        return work

    runtime = AiWorkerRuntime(
        SimpleNamespace(run_once=lambda: run("anomaly")),
        recommendation=lambda: run("recommendation"),
        expiry=lambda: run("expiry"),
    )
    assert runtime.run_once() is work
    assert calls == ["expiry", "anomaly", "recommendation"]


@pytest.mark.parametrize("failed", ["expiry", "anomaly", "recommendation"])
def test_failure_does_not_starve_other_classes_or_log_sensitive_exception(
    failed, caplog
):
    calls = []

    def run(name):
        calls.append(name)
        if name == failed:
            raise RuntimeError("private source and provider token")
        return True

    runtime = AiWorkerRuntime(
        SimpleNamespace(run_once=lambda: run("anomaly")),
        recommendation=lambda: run("recommendation"),
        expiry=lambda: run("expiry"),
    )
    assert runtime.run_once() is True
    assert calls == ["expiry", "anomaly", "recommendation"]
    assert failed in caplog.text and "private source" not in caplog.text


def test_interrupt_is_not_swallowed():
    def interrupt():
        raise KeyboardInterrupt

    runtime = AiWorkerRuntime(SimpleNamespace(run_once=interrupt))
    with pytest.raises(KeyboardInterrupt):
        runtime.run_once()


def test_idle_iteration_retains_two_second_pause(monkeypatch):
    calls = []
    runtime = AiWorkerRuntime(SimpleNamespace(run_once=lambda: False))

    def sleep(duration):
        calls.append(duration)
        raise KeyboardInterrupt

    monkeypatch.setattr("thesis_trace.bootstrap.application.time.sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        runtime.run_forever()
    assert calls == [2]
