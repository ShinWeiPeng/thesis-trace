from decimal import Decimal
from pathlib import Path

import pytest

from thesis_trace.platform.runtime import minimum_return_configuration


def test_configured_local_acceptance_minimum_return_is_five_percent(monkeypatch):
    monkeypatch.delenv("THESIS_TRACE_MINIMUM_ANNUALIZED_RETURN_FILE", raising=False)
    monkeypatch.delenv("THESIS_TRACE_MINIMUM_RETURN_POLICY_VERSION_FILE", raising=False)
    monkeypatch.setenv("THESIS_TRACE_MINIMUM_ANNUALIZED_RETURN", "0.05")
    monkeypatch.setenv(
        "THESIS_TRACE_MINIMUM_RETURN_POLICY_VERSION",
        "local-acceptance-minimum-return-v1",
    )
    assert minimum_return_configuration() == (
        Decimal("0.05"),
        "local-acceptance-minimum-return-v1",
    )


@pytest.mark.parametrize(
    "value,version",
    [
        (None, None),
        ("0.05", None),
        (None, "v1"),
        ("", "v1"),
        ("5%", "v1"),
        ("NaN", "v1"),
        ("Infinity", "v1"),
    ],
)
def test_absent_or_invalid_configuration_never_supplies_a_default(
    monkeypatch, value, version
):
    for name, supplied in (
        ("THESIS_TRACE_MINIMUM_ANNUALIZED_RETURN", value),
        ("THESIS_TRACE_MINIMUM_RETURN_POLICY_VERSION", version),
    ):
        monkeypatch.delenv(f"{name}_FILE", raising=False)
        monkeypatch.delenv(name, raising=False)
        if supplied is not None:
            monkeypatch.setenv(name, supplied)
    assert minimum_return_configuration()[0] is None


def test_local_acceptance_fixture_explicitly_sets_approved_value(monkeypatch):
    path = Path(__file__).parent / "fixtures" / "wave7-settings.env"
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, value = line.split("=", 1)
        monkeypatch.delenv(f"{name}_FILE", raising=False)
        monkeypatch.setenv(name, value)
    assert minimum_return_configuration() == (
        Decimal("0.05"),
        "local-acceptance-minimum-return-v1",
    )
